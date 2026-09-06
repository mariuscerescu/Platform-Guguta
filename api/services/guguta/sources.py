"""Sources service: upload, list, detail, rename/selection, remove, retry.

Upload pipeline (GHID §6.2, steps 1–4): authorize notebook → validate (real
type by magic bytes, size, page count) → write to private storage (server
key) → create SourceAsset + MaterialVersion + NotebookSource + ProcessingJob
in ONE transaction → on failure, compensating cleanup of stored bytes.

Quota counts logical material bytes of the user (invariant 7).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Any, BinaryIO, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import NotFoundError, OpenNotebookError
from open_notebook.jobs.guguta import parsing
from open_notebook.jobs.guguta.queue import enqueue
from open_notebook.storage.guguta.base import StorageBackend

logger = logging.getLogger("guguta.sources")

SOURCE_JOB_TYPE = "process_material_version"


class SourceNotFound(NotFoundError):
    pass


class SourceValidation(OpenNotebookError):
    pass


class QuotaExceeded(OpenNotebookError):
    pass


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _default_mimes() -> dict[str, str]:
    return {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", "text": "text/plain"}


class SourcesService:
    def __init__(
        self, engine: AsyncEngine, storage: StorageBackend, *,
        max_upload_mib: int = 25, max_pdf_pages: int = 300,
        max_sources_per_notebook: int = 20, quota_mib_per_user: int = 1024,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._max_bytes = max_upload_mib * 1024 * 1024
        self._max_pdf_pages = max_pdf_pages
        self._max_sources = max_sources_per_notebook
        self._quota_bytes = quota_mib_per_user * 1024 * 1024

    # -- helpers ------------------------------------------------------------

    def _read_upload(self, stream: BinaryIO) -> bytes:
        """Read up to max+1 bytes — an oversized stream is rejected, not truncated."""
        data = stream.read(self._max_bytes + 1)
        if len(data) > self._max_bytes:
            raise SourceValidation(
                f"Fișierul depășește limita de {self._max_bytes // (1024 * 1024)} MiB."
            )
        return data

    async def _check_notebook(self, conn: Any, notebook_id: uuid.UUID) -> None:
        row = (
            await conn.execute(
                text("SELECT id FROM digital_notebooks WHERE id = :id"),
                {"id": notebook_id},
            )
        ).first()
        if row is None:
            raise SourceNotFound()

    async def _check_quota(self, conn: Any, actor_id: uuid.UUID, extra: int) -> None:
        used = (
            await conn.execute(
                text(
                    "SELECT coalesce(sum(sa.byte_size), 0)"
                    " FROM source_assets sa"
                    " JOIN material_versions mv ON mv.source_asset_id = sa.id"
                    " JOIN notebook_sources ns ON ns.material_version_id = mv.id"
                    " JOIN digital_notebooks dn ON dn.id = ns.notebook_id"
                    " WHERE dn.owner_id = :owner"
                ),
                {"owner": actor_id},
            )
        ).scalar_one()
        if int(used) + extra > self._quota_bytes:
            raise QuotaExceeded(
                f"Cota de stocare este depășită "
                f"({int(used) // (1024 * 1024)} MiB folosiți din "
                f"{self._quota_bytes // (1024 * 1024)} MiB)."
            )

    # -- operations ----------------------------------------------------------

    async def upload_file(
        self, actor: ActorContext, notebook_id: uuid.UUID, *,
        stream: BinaryIO, original_name: Optional[str] = None,
        local_name: Optional[str] = None,
    ) -> dict[str, Any]:
        data = self._read_upload(stream)
        return await self._create_source(
            actor, notebook_id, data=data,
            original_name=original_name, local_name=local_name,
        )

    async def add_text(
        self, actor: ActorContext, notebook_id: uuid.UUID, *,
        text_content: str, title: Optional[str] = None,
    ) -> dict[str, Any]:
        if not text_content or not text_content.strip():
            raise SourceValidation("Textul introdus este vid.")
        return await self._create_source(
            actor, notebook_id, data=text_content.encode("utf-8"),
            original_name=None, local_name=title or "Text introdus",
        )

    async def _create_source(
        self, actor: ActorContext, notebook_id: uuid.UUID, *,
        data: bytes, original_name: Optional[str], local_name: Optional[str],
    ) -> dict[str, Any]:
        if len(data) == 0:
            raise SourceValidation("Fișierul este vid.")
        kind = parsing.detect_kind(data, None)
        if kind == "pdf":
            # validate page budget before storing anything heavy (GHID §6.1)
            import io

            from pypdf import PdfReader

            try:
                page_count = len(PdfReader(io.BytesIO(data)).pages)
            except Exception:
                raise SourceValidation("PDF-ul este invalid.")
            if page_count > self._max_pdf_pages:
                raise SourceValidation(
                    f"PDF-ul are {page_count} pagini, peste limita de "
                    f"{self._max_pdf_pages}."
                )
        else:
            page_count = None
        display_name = (local_name or original_name or "Material").strip()[:500]
        if not display_name:
            raise SourceValidation("Numele materialului nu poate fi vid.")

        sha = hashlib.sha256(data).hexdigest()
        storage_key: Optional[str] = None
        if kind != "text":
            storage_key = self._storage.save_bytes(data)

        try:
            async with actor_connection(self._engine, actor.actor_id) as conn:
                await self._check_notebook(conn, notebook_id)
                await self._check_quota(conn, actor.actor_id, len(data))
                count = (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM notebook_sources WHERE notebook_id = :n"
                        ),
                        {"n": notebook_id},
                    )
                ).scalar_one()
                if int(count) >= self._max_sources:
                    raise SourceValidation(
                        f"Carnetul are deja {self._max_sources} materiale (limita MVP)."
                    )
                asset_id = uuid.uuid4()
                mv_id = uuid.uuid4()
                ns_id = uuid.uuid4()
                # MAX(position)+1 — count(*) would collide after deletions
                position = (
                    await conn.execute(
                        text(
                            "SELECT coalesce(max(position), -1) + 1"
                            " FROM notebook_sources WHERE notebook_id = :n"
                        ),
                        {"n": notebook_id},
                    )
                ).scalar_one()
                await conn.execute(
                    text(
                        "INSERT INTO source_assets (id, kind, mime_type, byte_size,"
                        " sha256, storage_key, text_content, original_name, created_by)"
                        " VALUES (:id, :kind, :mime, :size, :sha, :key, :text, :oname, :by)"
                    ),
                    {"id": asset_id, "kind": "file" if kind != "text" else "text",
                     "mime": _default_mimes()[kind], "size": len(data), "sha": sha,
                     "key": storage_key,
                     "text": data.decode("utf-8") if kind == "text" else None,
                     "oname": original_name, "by": actor.actor_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO material_versions (id, source_asset_id, version,"
                        " title, provenance, page_count, created_by)"
                        " VALUES (:id, :asset, 1, :title, CAST(:prov AS jsonb),"
                        " :pages, :by)"
                    ),
                    {"id": mv_id, "asset": asset_id, "title": display_name,
                     "prov": _json({"kind": kind}), "pages": page_count,
                     "by": actor.actor_id},
                )
                await conn.execute(
                    text(
                        "INSERT INTO notebook_sources (id, notebook_id,"
                        " material_version_id, local_name, position, selected_for_chat,"
                        " status, added_by) VALUES (:id, :n, :mv, :name, :pos, true,"
                        " 'processing', :by)"
                    ),
                    {"id": ns_id, "n": notebook_id, "mv": mv_id,
                     "name": display_name, "pos": position, "by": actor.actor_id},
                )
                job_id = await enqueue(
                    self._engine, conn,
                    job_type=SOURCE_JOB_TYPE,
                    target_type="material_version",
                    target_id=mv_id,
                    actor_id=actor.actor_id,
                    payload={"local_name": display_name, "kind": kind},
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT id, local_name, status, position, created_at"
                            " FROM notebook_sources WHERE id = :id"
                        ),
                        {"id": ns_id},
                    )
                ).mappings().one()
            return {"source": dict(row), "job_id": str(job_id), "kind": kind}
        except Exception:
            # Compensating cleanup: bytes stored outside the DB die with the
            # failed transaction (GHID §6.2 step 4).
            if storage_key is not None:
                try:
                    self._storage.delete(storage_key)
                except Exception:  # pragma: no cover
                    logger.warning("curățarea compensatorie a eșuat pentru %s", storage_key)
            raise

    async def list_for_notebook(
        self, actor: ActorContext, notebook_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await self._check_notebook(conn, notebook_id)
            rows = (
                await conn.execute(
                    text(
                        "SELECT ns.id, ns.local_name, ns.position, ns.status,"
                        " ns.status_detail, ns.selected_for_chat, ns.created_at,"
                        " mv.page_count, sa.byte_size, sa.sha256, mv.id AS material_version_id"
                        " FROM notebook_sources ns"
                        " JOIN material_versions mv ON mv.id = ns.material_version_id"
                        " JOIN source_assets sa ON sa.id = mv.source_asset_id"
                        " WHERE ns.notebook_id = :n"
                        " ORDER BY ns.position, ns.created_at"
                    ),
                    {"n": notebook_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def get(
        self, actor: ActorContext, notebook_id: uuid.UUID, source_id: uuid.UUID
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT ns.id, ns.local_name, ns.status, ns.status_detail,"
                        " ns.selected_for_chat, ns.created_at, mv.page_count,"
                        " sa.byte_size, sa.sha256"
                        " FROM notebook_sources ns"
                        " JOIN material_versions mv ON mv.id = ns.material_version_id"
                        " JOIN source_assets sa ON sa.id = mv.source_asset_id"
                        " WHERE ns.id = :id AND ns.notebook_id = :n"
                    ),
                    {"id": source_id, "n": notebook_id},
                )
            ).mappings().first()
        if row is None:
            raise SourceNotFound()
        return dict(row)

    async def update(
        self, actor: ActorContext, notebook_id: uuid.UUID, source_id: uuid.UUID, *,
        local_name: Optional[str] = None,
        selected_for_chat: Optional[bool] = None,
    ) -> dict[str, Any]:
        sets: list[str] = []
        params: dict[str, Any] = {"id": source_id, "n": notebook_id}
        if local_name is not None:
            local_name = local_name.strip()
            if not local_name:
                raise SourceValidation("Numele nu poate fi vid.")
            sets.append("local_name = :name")
            params["name"] = local_name
        if selected_for_chat is not None:
            sets.append("selected_for_chat = :sel")
            params["sel"] = selected_for_chat
        if not sets:
            raise SourceValidation("Nimic de actualizat.")
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text(f"UPDATE notebook_sources SET {', '.join(sets)} WHERE id = :id"),
                params,
            )
            if result.rowcount == 0:
                raise SourceNotFound()
            # selection changes shape the chat context → new revision (A17)
            if selected_for_chat is not None:
                await conn.execute(
                    text(
                        "UPDATE digital_notebooks SET context_revision = context_revision + 1"
                        " WHERE id = :n"
                    ),
                    {"n": notebook_id},
                )
            row = (
                await conn.execute(
                    text("SELECT id, local_name, status, selected_for_chat"
                         " FROM notebook_sources WHERE id = :id"),
                    {"id": source_id},
                )
            ).mappings().one()
        return dict(row)

    async def delete(
        self, actor: ActorContext, notebook_id: uuid.UUID, source_id: uuid.UUID
    ) -> bool:
        # No cascade to SourceAsset/MaterialVersion (ADR-0006): the bytes stay
        # while templates/snapshots/other copies reference them.
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text("DELETE FROM notebook_sources WHERE id = :id AND notebook_id = :n"),
                {"id": source_id, "n": notebook_id},
            )
            if result.rowcount:
                await conn.execute(
                    text(
                        "UPDATE digital_notebooks SET context_revision = context_revision + 1"
                        " WHERE id = :n"
                    ),
                    {"n": notebook_id},
                )
        return bool(result.rowcount)

    async def download(
        self, actor: ActorContext, notebook_id: uuid.UUID, source_id: uuid.UUID
    ) -> tuple[bytes, str, Optional[str]]:
        """Authorized proxy download — no public permanent URLs (ADR-0004)."""
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT sa.storage_key, sa.kind, sa.text_content, sa.mime_type,"
                        " sa.original_name FROM notebook_sources ns"
                        " JOIN material_versions mv ON mv.id = ns.material_version_id"
                        " JOIN source_assets sa ON sa.id = mv.source_asset_id"
                        " WHERE ns.id = :id AND ns.notebook_id = :n"
                    ),
                    {"id": source_id, "n": notebook_id},
                )
            ).mappings().first()
        if row is None:
            raise SourceNotFound()
        if row["kind"] == "text":
            return (
                (row["text_content"] or "").encode("utf-8"),
                row["mime_type"],
                row["original_name"],
            )
        return self._storage.read_bytes(row["storage_key"]), row["mime_type"], row["original_name"]

    async def retry(
        self, actor: ActorContext, notebook_id: uuid.UUID, source_id: uuid.UUID
    ) -> bool:
        """Manual retry for an errored source: requeue its latest job."""
        from open_notebook.jobs.guguta.queue import requeue as job_requeue

        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT ns.status, mv.id AS mv_id FROM notebook_sources ns"
                        " JOIN material_versions mv ON mv.id = ns.material_version_id"
                        " WHERE ns.id = :id AND ns.notebook_id = :n"
                    ),
                    {"id": source_id, "n": notebook_id},
                )
            ).first()
        if row is None:
            raise SourceNotFound()
        if row[0] != "error":
            raise SourceValidation(
                "Doar materialele în eroare pot fi retrimise la procesare."
            )
        ok = False
        async with actor_connection(self._engine, actor.actor_id) as conn:
            job_row = (
                await conn.execute(
                    text(
                        "SELECT id FROM processing_jobs WHERE target_id = :mv"
                        " AND target_type = 'material_version'"
                        " AND status IN ('failed','cancelled')"
                        " ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"mv": row[1]},
                )
            ).first()
        if job_row is not None:
            ok = await job_requeue(self._engine, job_row[0], actor.actor_id)
        if not ok:
            raise SourceValidation("Niciun job eșuat de retrimis.")
        if ok:
            async with actor_connection(self._engine, actor.actor_id) as conn:
                await conn.execute(
                    text("UPDATE notebook_sources SET status = 'processing',"
                         " status_detail = NULL WHERE id = :id"),
                    {"id": source_id},
                )
        return ok
