"""Sharing service: snapshots, link/code credentials, preview, import,
revocation (L7 — specificații §8, GHID §8.2/8.3).

Contract (§8.1): the snapshot transfers ONLY the approved materials — no
chat, notes, insights, memory, or secrets. The allowlist is explicit
(selected ready sources of the author's notebook), never a generic
serialization.

Ordering (A19): the import re-checks the snapshot status at the end of its
transaction — a revocation committed before that check wins and the import
aborts; an import committed first leaves a valid copy.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import InvalidInputError, NotFoundError, OpenNotebookError


class ShareNotFound(NotFoundError):
    pass


class ShareValidation(OpenNotebookError):
    pass


class ShareRevoked(OpenNotebookError):
    """The package was revoked; new imports are refused (maps to 410/409)."""


class QuotaExceeded(OpenNotebookError):
    pass


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _generate_link_token() -> str:
    return secrets.token_urlsafe(18)


def _generate_code() -> str:
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no ambiguous chars
    return "".join(secrets.choice(alphabet) for _ in range(8))


class SharingService:
    def __init__(self, engine: AsyncEngine, *, quota_mib_per_user: int = 1024) -> None:
        self._engine = engine
        self._quota_mib_per_user = quota_mib_per_user

    # -- creation (author) ----------------------------------------------------

    async def create_share(
        self, actor: ActorContext, notebook_id: uuid.UUID, *,
        source_ids: list[uuid.UUID], title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> dict[str, Any]:
        """Snapshot only the selected, READY materials of the author's notebook."""
        if not source_ids:
            raise ShareValidation("Selectează cel puțin un material.")
        snapshot_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            nb = (
                await conn.execute(
                    text(
                        "SELECT id, title FROM digital_notebooks WHERE id = :id"
                    ),
                    {"id": notebook_id},
                )
            ).mappings().first()
            if nb is None:
                raise ShareNotFound()
            items: list[dict[str, Any]] = []
            for position, sid in enumerate(source_ids, start=1):
                row = (
                    await conn.execute(
                        text(
                            "SELECT ns.id, ns.local_name, mv.id AS mv_id, mv.version"
                            " FROM notebook_sources ns"
                            " JOIN material_versions mv ON mv.id = ns.material_version_id"
                            " WHERE ns.id = :sid AND ns.notebook_id = :nb"
                            "   AND ns.status = 'ready'"
                        ),
                        {"sid": sid, "nb": notebook_id},
                    )
                ).mappings().first()
                if row is None:
                    raise ShareValidation(
                        f"Materialul {sid} nu există în carnet sau nu este gata."
                    )
                items.append(
                    {"material_version_id": str(row["mv_id"]),
                     "display_name": row["local_name"], "position": position}
                )
            manifest = {
                "schema_version": 1,
                "title": (title or nb["title"]).strip()[:500],
                "description": description,
                "items": items,
            }
            await conn.execute(
                text(
                    "INSERT INTO share_snapshots (id, author_id, notebook_id,"
                    " schema_version, title, description, status, manifest)"
                    " VALUES (:id, :a, :nb, 1, :t, :d, 'active', CAST(:m AS jsonb))"
                ),
                {"id": snapshot_id, "a": actor.actor_id, "nb": notebook_id,
                 "t": manifest["title"], "d": description, "m": _json(manifest)},
            )
            for item in items:
                await conn.execute(
                    text(
                        "INSERT INTO share_materials (id, snapshot_id,"
                        " material_version_id, display_name, position)"
                        " VALUES (:id, :s, :mv, :name, :pos)"
                    ),
                    {"id": uuid.uuid4(), "s": snapshot_id,
                     "mv": uuid.UUID(item["material_version_id"]),
                     "name": item["display_name"], "pos": item["position"]},
                )
            link_token = _generate_link_token()
            code = _generate_code()
            for kind, secret in (("link", link_token), ("code", code)):
                await conn.execute(
                    text(
                        "INSERT INTO share_credentials (id, snapshot_id, kind,"
                        " token_hash) VALUES (:id, :s, :k, :h)"
                    ),
                    {"id": uuid.uuid4(), "s": snapshot_id, "k": kind,
                     "h": _sha256(secret)},
                )
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM share_materials WHERE snapshot_id = :s"),
                    {"s": snapshot_id},
                )
            ).scalar_one()
        return {
            "share_id": str(snapshot_id),
            "link": f"/import#token={link_token}",
            "token": link_token,  # shown once; only the hash is stored
            "code": code,
            "material_count": int(count),
            "manifest": manifest,
        }

    async def list_shares_for_notebook(
        self, actor: ActorContext, notebook_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            nb = (
                await conn.execute(
                    text("SELECT id FROM digital_notebooks WHERE id = :id"),
                    {"id": notebook_id},
                )
            ).first()
            if nb is None:
                raise ShareNotFound()
            rows = (
                await conn.execute(
                    text(
                        "SELECT s.id, s.title, s.status, s.created_at, s.revoked_at,"
                        " (SELECT count(*) FROM share_materials sm"
                        "  WHERE sm.snapshot_id = s.id) AS material_count"
                        " FROM share_snapshots s WHERE s.notebook_id = :nb"
                        " ORDER BY s.created_at DESC"
                    ),
                    {"nb": notebook_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def revoke_share(
        self, actor: ActorContext, notebook_id: uuid.UUID, share_id: uuid.UUID
    ) -> dict[str, Any]:
        """Revoke link AND code together; existing copies are untouched.
        F12: the snapshot row is locked via the definer function for the whole
        transaction, serializing against in-flight imports (A19)."""
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, status FROM share_snapshots"
                        " WHERE id = :id AND notebook_id = :nb"
                    ),
                    {"id": share_id, "nb": notebook_id},
                )
            ).first()
            if row is None:
                raise ShareNotFound()
            # F12 lock held until commit; concurrent imports block here
            locked = (
                await conn.execute(
                    text("SELECT guguta_share_lock(:id)"), {"id": share_id}
                )
            ).scalar_one()
            if locked == "revoked":
                return {"revoked": True, "already_revoked": True}
            await conn.execute(
                text(
                    "UPDATE share_snapshots SET status = 'revoked', revoked_at = now()"
                    " WHERE id = :id"
                ),
                {"id": share_id},
            )
            await conn.execute(
                text(
                    "UPDATE share_credentials SET revoked_at = now()"
                    " WHERE snapshot_id = :id AND revoked_at IS NULL"
                ),
                {"id": share_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO audit_events (id, actor_id, action, target_type,"
                    " target_id, result) VALUES (:id, :a, 'share_revoke',"
                    " 'share_snapshot', :sid, 'allowed')"
                ),
                {"id": uuid.uuid4(), "a": actor.actor_id, "sid": share_id},
            )
        return {"revoked": True, "already_revoked": False}

    async def revoke_all_for_author(self, actor: ActorContext) -> int:
        """Account/notebook-author deletion flow (A28): revoke every active
        package of the author; recipient copies stay independent."""
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE share_snapshots SET status = 'revoked',"
                        " revoked_at = now()"
                        " WHERE author_id = :a AND status = 'active' RETURNING id"
                    ),
                    {"a": actor.actor_id},
                )
            ).all()
            ids = [r[0] for r in row]
            for sid in ids:
                await conn.execute(
                    text(
                        "UPDATE share_credentials SET revoked_at = now()"
                        " WHERE snapshot_id = :sid AND revoked_at IS NULL"
                    ),
                    {"sid": sid},
                )
        return len(ids)

    # -- recipient flow ---------------------------------------------------------

    async def _resolve_snapshot(
        self, actor: ActorContext, token_or_code: str
    ) -> tuple[uuid.UUID, str]:
        """Tolerant lookup: returns (snapshot_id, status) — the status check
        happens later, AFTER the idempotent replay (R36)."""
        token_or_code = token_or_code.strip()
        if not token_or_code:
            raise ShareValidation("Introdu linkul sau codul.")
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT snapshot_id, snapshot_status FROM guguta_share_lookup(:h)"
                    ),
                    {"h": _sha256(token_or_code)},
                )
            ).mappings().first()
        if row is None:
            raise ShareNotFound("Linkul sau codul nu este valid.")
        return row["snapshot_id"], row["snapshot_status"]

    async def preview_import(
        self, actor: ActorContext, token_or_code: str
    ) -> dict[str, Any]:
        """Recipient preview: only the approved manifest metadata."""
        snapshot_id, status = await self._resolve_snapshot(actor, token_or_code)
        if status != "active":
            raise ShareNotFound("Linkul sau codul nu mai este valid.")
        async with actor_connection(
            self._engine, actor.actor_id, share_context=snapshot_id
        ) as conn:
            snap = (
                await conn.execute(
                    text(
                        "SELECT id, title, description, schema_version FROM"
                        " share_snapshots WHERE id = :id AND status = 'active'"
                    ),
                    {"id": snapshot_id},
                )
            ).mappings().first()
            if snap is None:
                raise ShareNotFound("Linkul sau codul nu mai este valid.")
            materials = (
                await conn.execute(
                    text(
                        "SELECT sm.display_name, sm.position FROM share_materials sm"
                        " WHERE sm.snapshot_id = :id ORDER BY sm.position"
                    ),
                    {"id": snapshot_id},
                )
            ).all()
        return {
            "snapshot_id": str(snap["id"]),
            "title": snap["title"],
            "description": snap["description"],
            "schema_version": snap["schema_version"],
            "materials": [m[0] for m in materials],
            "material_count": len(materials),
        }

    async def import_snapshot(
        self, actor: ActorContext, token_or_code: str, *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create the recipient's independent copy in ONE transaction.

        A19 ordering: the snapshot status is re-checked at the end of the
        transaction — a revocation committed first wins; an import committed
        first leaves a valid copy. A20: the recipient row is locked before the
        quota check, so concurrent imports cannot bypass the limit.
        """
        if not idempotency_key or not idempotency_key.strip():
            raise ShareValidation("Cheia de idempotency este obligatorie.")
        idempotency_key = idempotency_key.strip()

        # tolerant resolve: the replay after a revocation still reaches the
        # stored copy (R36); the status check happens right after the replay.
        snapshot_id, snapshot_status = await self._resolve_snapshot(
            actor, token_or_code
        )
        payload_hash = _sha256(f"import:{snapshot_id}")

        replay = await self._idempotent_lookup(actor, "import", idempotency_key)
        if replay is not None:
            if replay["payload_hash"] != payload_hash:
                raise InvalidInputError(
                    "Aceeași cheie de idempotency pentru alt pachet."
                )
            return {"replayed": True, "notebook_id": replay["result_id"]}

        if snapshot_status != "active":
            raise ShareRevoked(
                "Pachetul nu mai este disponibil pentru import (revocat)."
            )

        async with actor_connection(
            self._engine, actor.actor_id, share_context=snapshot_id
        ) as conn:
            # F12: serialize with revocation via a definer row-lock on the
            # snapshot — held until this transaction commits. A concurrent
            # revoke blocks here instead of racing the final check.
            locked_status = (
                await conn.execute(
                    text("SELECT guguta_share_lock(:id)"),
                    {"id": snapshot_id},
                )
            ).scalar_one()
            # serialize the recipient's own concurrent imports (quota, A20)
            await conn.execute(
                text("SELECT id FROM users WHERE id = :a FOR UPDATE"),
                {"a": actor.actor_id},
            )
            snap = (
                await conn.execute(
                    text(
                        "SELECT id, title, status FROM share_snapshots"
                        " WHERE id = :id"
                    ),
                    {"id": snapshot_id},
                )
            ).mappings().first()
            if snap is None or snap["status"] != "active" or locked_status != "active":
                raise ShareRevoked(
                    "Pachetul nu mai este disponibil pentru import (revocat)."
                )
            used = (
                await conn.execute(
                    text(
                        "SELECT coalesce(sum(sa.byte_size), 0)"
                        " FROM source_assets sa"
                        " JOIN material_versions mv ON mv.source_asset_id = sa.id"
                        " JOIN notebook_sources ns ON ns.material_version_id = mv.id"
                        " JOIN digital_notebooks dn ON dn.id = ns.notebook_id"
                        " WHERE dn.owner_id = :a"
                    ),
                    {"a": actor.actor_id},
                )
            ).scalar_one()
            incoming = (
                await conn.execute(
                    text(
                        "SELECT coalesce(sum(sa.byte_size), 0) FROM share_materials sm"
                        " JOIN material_versions mv ON mv.id = sm.material_version_id"
                        " JOIN source_assets sa ON sa.id = mv.source_asset_id"
                        " WHERE sm.snapshot_id = :s"
                    ),
                    {"s": snapshot_id},
                )
            ).scalar_one()
            quota_bytes = self._quota_mib_per_user * 1024 * 1024
            if int(used) + int(incoming) > quota_bytes:
                raise QuotaExceeded(
                    "Importul ar depăși cota de stocare; import refuzat."
                )
            nb_id = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO digital_notebooks (id, owner_id, title, origin,"
                    " origin_snapshot_id) VALUES (:id, :o, :t, 'import', :s)"
                ),
                {"id": nb_id, "o": actor.actor_id, "t": snap["title"],
                 "s": snapshot_id},
            )
            materials = (
                await conn.execute(
                    text(
                        "SELECT sm.material_version_id, sm.display_name, sm.position"
                        " FROM share_materials sm WHERE sm.snapshot_id = :s"
                        " ORDER BY sm.position"
                    ),
                    {"s": snapshot_id},
                )
            ).all()
            # 1) create all local associations first (needed for the RLS
            #    artifact-visibility path), 2) then flip to ready / enqueue.
            for mv_id, display_name, position in materials:
                await conn.execute(
                    text(
                        "INSERT INTO notebook_sources (id, notebook_id,"
                        " material_version_id, local_name, position,"
                        " selected_for_chat, status, added_by)"
                        " VALUES (:id, :nb, :mv, :name, :pos, true, 'processing', :by)"
                    ),
                    {"id": uuid.uuid4(), "nb": nb_id, "mv": mv_id,
                     "name": display_name, "pos": position, "by": actor.actor_id},
                )
            for mv_id, display_name, position in materials:
                artifact = (
                    await conn.execute(
                        text(
                            "SELECT ns.id FROM notebook_sources ns"
                            " JOIN material_versions mv ON mv.id = ns.material_version_id"
                            " WHERE ns.notebook_id = :nb AND mv.id = :mv"
                            "   AND EXISTS (SELECT 1 FROM processing_artifacts pa"
                            "               WHERE pa.material_version_id = mv.id"
                            "               AND pa.status = 'complete')"
                        ),
                        {"nb": nb_id, "mv": mv_id},
                    )
                ).first()
                if artifact is not None:
                    continue  # stays 'ready' via the bulk update below
                from open_notebook.jobs.guguta.queue import enqueue

                await enqueue(
                    self._engine, conn,
                    job_type="process_material_version",
                    target_type="material_version",
                    target_id=mv_id,
                    actor_id=actor.actor_id,
                    payload={"local_name": display_name},
                )
            await conn.execute(
                text(
                    "UPDATE notebook_sources ns SET status = 'ready'"
                    " WHERE ns.notebook_id = :nb"
                    "   AND EXISTS (SELECT 1 FROM processing_artifacts pa"
                    "               WHERE pa.material_version_id = ns.material_version_id"
                    "               AND pa.status = 'complete')"
                ),
                {"nb": nb_id},
            )
            await conn.execute(
                text(
                    "INSERT INTO share_imports (id, snapshot_id, recipient_id,"
                    " notebook_id, idempotency_key)"
                    " VALUES (:id, :s, :a, :nb, :k)"
                ),
                {"id": uuid.uuid4(), "s": snapshot_id, "a": actor.actor_id,
                 "nb": nb_id, "k": idempotency_key},
            )
            await conn.execute(
                text(
                    "INSERT INTO idempotency_records (id, actor_id, operation_type,"
                    " idempotency_key, payload_hash, result_type, result_id)"
                    " VALUES (:id, :a, 'import', :k, :ph, 'notebook', :nb)"
                ),
                {"id": uuid.uuid4(), "a": actor.actor_id, "k": idempotency_key,
                 "ph": payload_hash, "nb": nb_id},
            )
            # A19: final re-check — a revocation committed before this point
            # aborts the import; a committed import keeps its copy.
            final_status = (
                await conn.execute(
                    text("SELECT status FROM share_snapshots WHERE id = :id"),
                    {"id": snapshot_id},
                )
            ).scalar_one()
            if final_status != "active":
                raise ShareRevoked(
                    "Pachetul a fost revocat în timpul importului; copia a fost anulată."
                )
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM notebook_sources WHERE notebook_id = :nb"),
                    {"nb": nb_id},
                )
            ).scalar_one()
        return {
            "notebook_id": str(nb_id),
            "material_count": int(count),
        }

    async def _idempotent_lookup(
        self, actor: ActorContext, op: str, key: str
    ) -> Optional[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT payload_hash, result_id FROM idempotency_records"
                        " WHERE actor_id = :a AND operation_type = :op"
                        " AND idempotency_key = :k"
                    ),
                    {"a": actor.actor_id, "op": op, "k": key},
                )
            ).first()
        if row is None:
            return None
        return {"payload_hash": row[0], "result_id": str(row[1])}
