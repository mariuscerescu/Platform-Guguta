"""Catalog service: templates, immutable published versions, instantiation
(L6, GHID §8.1, specificații §7).

- Draft → publish → retire lifecycle; published manifests are immutable
  (DB trigger, ADR-0006) and corrections create a NEW version (A14).
- Publish requires every material to have a complete processing artifact —
  no unverified material enters a published edition (A24/R42).
- Instantiation pins the CURRENT published version, creates the personal
  copy with NEW local IDs, zero personal activity, and reuses the shared
  processing artifacts (no re-extraction, no LLM call).
- „Începe din nou" = instantiate again; the old notebook stays untouched.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import (
    actor_connection,
    system_connection,
)
from open_notebook.exceptions import InvalidInputError, NotFoundError, OpenNotebookError


class TemplateNotFound(NotFoundError):
    pass


class CatalogValidation(OpenNotebookError):
    pass


class RetiredTemplate(OpenNotebookError):
    """The current edition is retired; new instantiations are blocked."""


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def hashlib_sha256(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CatalogService:
    def __init__(self, engine: AsyncEngine, *, quota_mib_per_user: int = 1024) -> None:
        self._engine = engine
        self._quota_mib_per_user = quota_mib_per_user

    def _require_editor(self, actor: ActorContext) -> None:
        actor.require_any_role("catalog_editor", "admin")

    # -- template lifecycle ---------------------------------------------------

    async def create_template(self, actor: ActorContext, **meta: Any) -> dict[str, Any]:
        self._require_editor(actor)
        slug = (meta.get("slug") or "").strip().lower()
        title = (meta.get("title") or "").strip()
        if not slug or not title:
            raise CatalogValidation("Slug-ul și titlul sunt obligatorii.")
        template_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            dup = (
                await conn.execute(
                    text("SELECT id FROM templates WHERE slug = :slug"),
                    {"slug": slug},
                )
            ).first()
            if dup:
                raise CatalogValidation("Slug-ul există deja.")
            await conn.execute(
                text(
                    "INSERT INTO templates (id, slug, title, description, class_level,"
                    " discipline, language, edition, rights_note, status, created_by)"
                    " VALUES (:id, :slug, :title, :description, :class_level,"
                    " :discipline, :language, :edition, :rights_note, 'draft', :by)"
                ),
                {"id": template_id, "slug": slug, "title": title,
                 "description": meta.get("description"),
                 "class_level": meta.get("class_level"),
                 "discipline": meta.get("discipline"),
                 "language": meta.get("language") or "ro",
                 "edition": meta.get("edition"),
                 "rights_note": meta.get("rights_note"), "by": actor.actor_id},
            )
            row = (
                await conn.execute(
                    text("SELECT * FROM templates WHERE id = :id"), {"id": template_id}
                )
            ).mappings().one()
        return dict(row)

    async def get_template(
        self, actor: ActorContext, template_id: uuid.UUID
    ) -> dict[str, Any]:
        """Public detail: published template + current published edition."""
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT t.id, t.slug, t.title, t.description, t.class_level,"
                        " t.discipline, t.language, t.edition, t.rights_note, t.status,"
                        " v.id AS current_version_id, v.version AS current_version"
                        " FROM templates t"
                        " LEFT JOIN LATERAL ("
                        "   SELECT id, version FROM template_versions tv"
                        "   WHERE tv.template_id = t.id AND tv.status = 'published'"
                        "   ORDER BY tv.version DESC LIMIT 1"
                        " ) v ON true"
                        " WHERE t.id = :id AND (t.status = 'published' OR t.created_by = :a)"
                    ),
                    {"id": template_id, "a": actor.actor_id},
                )
            ).mappings().first()
        if row is None:
            raise TemplateNotFound()
        material_count = 0
        if row["current_version_id"]:
            async with actor_connection(self._engine, actor.actor_id) as conn:
                material_count = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM template_materials"
                            " WHERE template_version_id = :vid"
                        ),
                        {"vid": row["current_version_id"]},
                    )
                ).scalar_one()
        return {**dict(row), "material_count": material_count}

    async def list_public_templates_visitor(self) -> list[dict[str, Any]]:
        """Visitor (unauthenticated) view: only published templates, no drafts,
        no personal data — the RLS published-path stays the gate (A01)."""
        async with system_connection(self._engine) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.id, t.slug, t.title, t.description, t.class_level,"
                        " t.discipline, t.language, t.edition,"
                        " v.id AS current_version_id, v.version AS current_version,"
                        " (SELECT count(*) FROM template_materials tm"
                        "  WHERE tm.template_version_id = v.id) AS material_count"
                        " FROM templates t"
                        " LEFT JOIN LATERAL ("
                        "   SELECT id, version FROM template_versions tv"
                        "   WHERE tv.template_id = t.id AND tv.status = 'published'"
                        "   ORDER BY tv.version DESC LIMIT 1"
                        " ) v ON true"
                        " WHERE t.status = 'published'"
                        " ORDER BY t.class_level, t.discipline, t.title"
                    )
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def list_public_templates(self, actor: ActorContext) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT t.id, t.slug, t.title, t.description, t.class_level,"
                        " t.discipline, t.language, t.edition,"
                        " v.id AS current_version_id, v.version AS current_version,"
                        " (SELECT count(*) FROM template_materials tm"
                        "  WHERE tm.template_version_id = v.id) AS material_count"
                        " FROM templates t"
                        " LEFT JOIN LATERAL ("
                        "   SELECT id, version FROM template_versions tv"
                        "   WHERE tv.template_id = t.id AND tv.status = 'published'"
                        "   ORDER BY tv.version DESC LIMIT 1"
                        " ) v ON true"
                        " WHERE t.status = 'published'"
                        " ORDER BY t.class_level, t.discipline, t.title"
                    )
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def create_version(
        self, actor: ActorContext, template_id: uuid.UUID, *,
        items: list[Any],
    ) -> dict[str, Any]:
        """Create a draft version from the editor's own processed materials."""
        self._require_editor(actor)
        if not items:
            raise CatalogValidation("Versiunea are nevoie de cel puțin un material.")
        version_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            tpl = (
                await conn.execute(
                    text(
                        "SELECT id FROM templates WHERE id = :id AND created_by = :a"
                    ),
                    {"id": template_id, "a": actor.actor_id},
                )
            ).first()
            if tpl is None:
                raise TemplateNotFound()
            next_version = (
                await conn.execute(
                    text(
                        "SELECT coalesce(max(version), 0) + 1 FROM template_versions"
                        " WHERE template_id = :tid"
                    ),
                    {"tid": template_id},
                )
            ).scalar_one()
            # the draft version row must exist before its materials (WITH CHECK)
            await conn.execute(
                text(
                    "INSERT INTO template_versions (id, template_id, version, manifest,"
                    " status, created_by) VALUES (:id, :tid, :v, CAST(:m AS jsonb),"
                    " 'draft', :by)"
                ),
                {"id": version_id, "tid": template_id, "v": next_version,
                 "m": _json({"items": [], "schema": 1}), "by": actor.actor_id},
            )
            manifest_items = []
            for position, item in enumerate(items, start=1):
                mv_id = item.material_version_id
                display_name = (item.display_name or "").strip() or "Material"
                try:
                    mv_uuid = uuid.UUID(str(mv_id))
                except ValueError as exc:
                    raise CatalogValidation("material_version_id invalid.") from exc
                owned = (
                    await conn.execute(
                        text(
                            "SELECT mv.id, mv.title, mv.page_count FROM material_versions mv"
                            " WHERE mv.id = :mv AND mv.created_by = :a"
                            "   AND EXISTS (SELECT 1 FROM processing_artifacts pa"
                            "               WHERE pa.material_version_id = mv.id"
                            "               AND pa.status = 'complete')"
                        ),
                        {"mv": mv_uuid, "a": actor.actor_id},
                    )
                ).first()
                if owned is None:
                    raise CatalogValidation(
                        f"Materialul {mv_uuid} nu există, nu vă aparține sau nu este "
                        "procesat complet (fără artefact complet)."
                    )
                manifest_items.append(
                    {"material_version_id": str(mv_uuid),
                     "display_name": display_name, "position": position}
                )
                await conn.execute(
                    text(
                        "INSERT INTO template_materials (id, template_version_id,"
                        " material_version_id, display_name, position)"
                        " VALUES (:id, :tv, :mv, :name, :pos)"
                    ),
                    {"id": uuid.uuid4(), "tv": version_id, "mv": mv_uuid,
                     "name": display_name[:500], "pos": position},
                )
            manifest = {"items": manifest_items, "schema": 1}
            await conn.execute(
                text(
                    "UPDATE template_versions SET manifest = CAST(:m AS jsonb)"
                    " WHERE id = :id"
                ),
                {"m": _json(manifest), "id": version_id},
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT id, template_id, version, status, created_at"
                        " FROM template_versions WHERE id = :id"
                    ),
                    {"id": version_id},
                )
            ).mappings().one()
        return dict(row)

    async def publish_version(
        self, actor: ActorContext, template_id: uuid.UUID, version_id: uuid.UUID
    ) -> dict[str, Any]:
        self._require_editor(actor)
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT tv.id, tv.version, tv.status FROM template_versions tv"
                        " JOIN templates t ON t.id = tv.template_id"
                        " WHERE tv.id = :vid AND t.id = :tid AND t.created_by = :a"
                        " FOR UPDATE"
                    ),
                    {"vid": version_id, "tid": template_id, "a": actor.actor_id},
                )
            ).first()
            if row is None:
                raise TemplateNotFound()
            if row[2] != "draft":
                raise CatalogValidation(
                    "Doar versiunile draft pot fi publicate."
                )
            unverified = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM template_materials tm"
                        " WHERE tm.template_version_id = :vid"
                        "   AND NOT EXISTS ("
                        "     SELECT 1 FROM processing_artifacts pa"
                        "     WHERE pa.material_version_id = tm.material_version_id"
                        "       AND pa.status = 'complete')"
                    ),
                    {"vid": version_id},
                )
            ).scalar_one()
            if int(unverified) > 0:
                raise CatalogValidation(
                    "Publicarea blocată: există materiale fără extracție completă."
                )
            await conn.execute(
                text(
                    "UPDATE template_versions SET status = 'published',"
                    " published_at = now() WHERE id = :vid"
                ),
                {"vid": version_id},
            )
            await conn.execute(
                text("UPDATE templates SET status = 'published' WHERE id = :tid"),
                {"tid": template_id},
            )
        return {"published": True, "version_id": str(version_id)}

    async def retire_version(
        self, actor: ActorContext, template_id: uuid.UUID, version_id: uuid.UUID
    ) -> dict[str, Any]:
        """Retire a published edition: blocks future instantiations; existing
        copies keep working (specificații §7)."""
        self._require_editor(actor)
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT tv.id, tv.status FROM template_versions tv"
                        " JOIN templates t ON t.id = tv.template_id"
                        " WHERE tv.id = :vid AND t.id = :tid AND t.created_by = :a"
                        " FOR UPDATE"
                    ),
                    {"vid": version_id, "tid": template_id, "a": actor.actor_id},
                )
            ).first()
            if row is None:
                raise TemplateNotFound()
            if row[1] != "published":
                raise CatalogValidation("Doar versiunile publicate pot fi retrase.")
            await conn.execute(
                text(
                    "UPDATE template_versions SET status = 'retired' WHERE id = :vid"
                ),
                {"vid": version_id},
            )
        return {"retired": True, "version_id": str(version_id)}

    # -- instantiation ----------------------------------------------------------

    async def instantiate(
        self, actor: ActorContext, template_id: uuid.UUID, *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create the personal copy from the CURRENT published edition.

        One transaction pins the version, creates the notebook and the local
        associations (new IDs, ready when artifacts exist), and records the
        idempotency row — double clicks and retries return the same copy (A15).
        """
        if not idempotency_key or not idempotency_key.strip():
            raise CatalogValidation("Cheia de idempotency este obligatorie.")
        idempotency_key = idempotency_key.strip()
        payload_hash = hashlib_sha256(f"instantiate:{template_id}")

        replay = await self._idempotent_lookup(actor, "instantiate", idempotency_key)
        if replay is not None:
            if replay["payload_hash"] != payload_hash:
                raise InvalidInputError(
                    "Aceeași cheie de idempotency pentru alt șablon."
                )
            return {"replayed": True, "notebook_id": replay["result_id"],
                    "template_version_id": replay["version_id"]}

        async with actor_connection(self._engine, actor.actor_id) as conn:
            # F12: lock the template row via the definer function for the whole
            # transaction — serializes instantiate against retire/publish.
            locked_status = (
                await conn.execute(
                    text("SELECT guguta_template_lock(:id)"),
                    {"id": template_id},
                )
            ).scalar_one()
            # F13: lock the recipient row so concurrent instantiations cannot
            # bypass the logical storage quota.
            await conn.execute(
                text("SELECT id FROM users WHERE id = :a FOR UPDATE"),
                {"a": actor.actor_id},
            )
            tpl = (
                await conn.execute(
                    text(
                        "SELECT id, title, status FROM templates WHERE id = :id"
                        " AND status = 'published'"
                    ),
                    {"id": template_id},
                )
            ).mappings().first()
            if tpl is None or locked_status != "published":
                raise TemplateNotFound()
            version = (
                await conn.execute(
                    text(
                        "SELECT id, version, status FROM template_versions"
                        " WHERE template_id = :tid AND status = 'published'"
                        " ORDER BY version DESC LIMIT 1"
                    ),
                    {"tid": template_id},
                )
            ).mappings().first()
            if version is None:
                raise RetiredTemplate(
                    "Șablonul nu are o ediție publicată activă."
                )
            # F13: quota check under the user lock (logical bytes)
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
                        "SELECT coalesce(sum(sa.byte_size), 0)"
                        " FROM template_materials tm"
                        " JOIN material_versions mv ON mv.id = tm.material_version_id"
                        " JOIN source_assets sa ON sa.id = mv.source_asset_id"
                        " WHERE tm.template_version_id = :vid"
                    ),
                    {"vid": version["id"]},
                )
            ).scalar_one()
            quota_bytes = self._quota_mib_per_user * 1024 * 1024
            if int(used) + int(incoming) > quota_bytes:
                raise InvalidInputError(
                    "Instanțierea ar depăși cota de stocare; operațiune refuzată."
                )
            nb_id = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO digital_notebooks (id, owner_id, title, origin,"
                    " current_template_version_id)"
                    " VALUES (:id, :o, :title, 'template', :vid)"
                ),
                {"id": nb_id, "o": actor.actor_id, "title": tpl["title"],
                 "vid": version["id"]},
            )
            materials = (
                await conn.execute(
                    text(
                        "SELECT tm.material_version_id, tm.display_name, tm.position"
                        " FROM template_materials tm"
                        " WHERE tm.template_version_id = :vid ORDER BY tm.position"
                    ),
                    {"vid": version["id"]},
                )
            ).all()
            # associations first (RLS artifact-visibility path), then status flip
            for mv_id, display_name, position in materials:
                await conn.execute(
                    text(
                        "INSERT INTO notebook_sources (id, notebook_id,"
                        " material_version_id, local_name, position, selected_for_chat,"
                        " status, added_by)"
                        " VALUES (:id, :nb, :mv, :name, :pos, true, 'processing', :by)"
                    ),
                    {"id": uuid.uuid4(), "nb": nb_id, "mv": mv_id,
                     "name": display_name, "pos": position, "by": actor.actor_id},
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
            unready = (
                await conn.execute(
                    text(
                        "SELECT ns.material_version_id, ns.local_name"
                        " FROM notebook_sources ns WHERE ns.notebook_id = :nb"
                        "   AND ns.status = 'processing'"
                    ),
                    {"nb": nb_id},
                )
            ).all()
            for mv_id, display_name in unready:
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
                    "INSERT INTO idempotency_records (id, actor_id, operation_type,"
                    " idempotency_key, payload_hash, result_type, result_id)"
                    " VALUES (:id, :a, 'instantiate', :k, :ph, 'notebook', :nb)"
                ),
                {"id": uuid.uuid4(), "a": actor.actor_id, "k": idempotency_key,
                 "ph": payload_hash, "nb": nb_id},
            )
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM notebook_sources WHERE notebook_id = :nb"),
                    {"nb": nb_id},
                )
            ).scalar_one()
            # final re-check: the edition must STILL be published at commit
            # time (serializes against a concurrent retire — A19-style order)
            final_status = (
                await conn.execute(
                    text(
                        "SELECT status FROM template_versions WHERE id = :vid"
                    ),
                    {"vid": version["id"]},
                )
            ).scalar_one()
            if final_status != "published":
                raise RetiredTemplate(
                    "Șablonul a fost retras în timpul instanțierii; copia a fost anulată."
                )
        return {
            "notebook_id": str(nb_id),
            "template_version_id": str(version["id"]),
            "version": version["version"],
            "material_count": int(count),
        }

    async def _idempotent_lookup(
        self, actor: ActorContext, op: str, key: str
    ) -> Optional[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT payload_hash, result_type, result_id"
                        " FROM idempotency_records"
                        " WHERE actor_id = :a AND operation_type = :op"
                        " AND idempotency_key = :k"
                    ),
                    {"a": actor.actor_id, "op": op, "k": key},
                )
            ).first()
        if row is None:
            return None
        return {
            "payload_hash": row[0],
            "result_type": row[1],
            "result_id": str(row[2]),
            "version_id": None,
        }
