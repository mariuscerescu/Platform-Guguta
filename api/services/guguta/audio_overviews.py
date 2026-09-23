"""Audio Overview service: authorization, persistence and job submission."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.jobs.guguta.queue import enqueue, requeue
from open_notebook.storage.guguta.base import StorageBackend

logger = logging.getLogger(__name__)


class AudioOverviewNotFound(NotFoundError):
    pass


class AudioOverviewService:
    def __init__(self, engine: AsyncEngine, storage: StorageBackend) -> None:
        self._engine = engine
        self._storage = storage

    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        result = dict(row)
        for key in ("id", "notebook_id", "job_id"):
            if result.get(key) is not None:
                result[key] = str(result[key])
        if result.get("duration_seconds") is not None:
            result["duration_seconds"] = float(result["duration_seconds"])
        return result

    async def create(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        *,
        format_name: str,
        source_ids: list[uuid.UUID],
        instructions: str | None,
    ) -> dict[str, Any]:
        if format_name not in ("brief", "deep_dive"):
            raise InvalidInputError("Formatul audio nu este acceptat.")
        unique_ids = list(dict.fromkeys(source_ids))
        if not unique_ids:
            raise InvalidInputError("Selectează cel puțin un material gata de procesare.")

        overview_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            notebook = (
                await conn.execute(
                    text("SELECT id FROM digital_notebooks WHERE id = :n AND status = 'active'"),
                    {"n": notebook_id},
                )
            ).first()
            if notebook is None:
                raise AudioOverviewNotFound()
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, status FROM notebook_sources "
                        "WHERE notebook_id = :n AND id = ANY(:ids)"
                    ),
                    {"n": notebook_id, "ids": unique_ids},
                )
            ).all()
            if len(rows) != len(unique_ids):
                raise InvalidInputError("Un material selectat nu aparține carnetului.")
            if any(row.status != "ready" for row in rows):
                raise InvalidInputError("Toate materialele selectate trebuie să fie gata.")

            await conn.execute(
                text(
                    "INSERT INTO audio_overviews "
                    "(id, notebook_id, created_by, format, selected_source_ids, instructions, status) "
                    "VALUES (:id, :n, :actor, :format, CAST(:sources AS jsonb), :instructions, 'queued')"
                ),
                {
                    "id": overview_id,
                    "n": notebook_id,
                    "actor": actor.actor_id,
                    "format": format_name,
                    "sources": json.dumps([str(value) for value in unique_ids]),
                    "instructions": (instructions or "").strip() or None,
                },
            )
            job_id = await enqueue(
                self._engine,
                conn,
                job_type="generate_audio_overview",
                target_type="audio_overview",
                target_id=overview_id,
                actor_id=actor.actor_id,
                payload={"format": format_name},
                max_attempts=2,
                deadline_seconds=3600,
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT id, notebook_id, format, selected_source_ids, instructions, status, "
                        "title, duration_seconds, error_detail, created_at, updated_at, "
                        "completed_at FROM audio_overviews WHERE id = :id"
                    ),
                    {"id": overview_id},
                )
            ).mappings().one()
        result = self._serialize(row)
        result["job_id"] = str(job_id)
        return result

    async def list_for_notebook(
        self, actor: ActorContext, notebook_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT ao.id, ao.notebook_id, ao.format, ao.selected_source_ids, ao.instructions, "
                        "ao.status, ao.title, ao.duration_seconds, ao.error_detail, "
                        "ao.created_at, ao.updated_at, ao.completed_at, "
                        "(SELECT pj.id FROM processing_jobs pj "
                        " WHERE pj.target_type = 'audio_overview' AND pj.target_id = ao.id "
                        " ORDER BY pj.created_at DESC LIMIT 1) AS job_id "
                        "FROM audio_overviews ao WHERE ao.notebook_id = :n "
                        "ORDER BY ao.created_at DESC"
                    ),
                    {"n": notebook_id},
                )
            ).mappings().all()
        return [self._serialize(row) for row in rows]

    async def get(
        self, actor: ActorContext, notebook_id: uuid.UUID, overview_id: uuid.UUID
    ) -> dict[str, Any]:
        rows = await self.list_for_notebook(actor, notebook_id)
        for row in rows:
            if row["id"] == str(overview_id):
                return row
        raise AudioOverviewNotFound()

    async def download(
        self, actor: ActorContext, notebook_id: uuid.UUID, overview_id: uuid.UUID
    ) -> tuple[bytes, str, str]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT title, audio_storage_key, mime_type, status "
                        "FROM audio_overviews WHERE id = :id AND notebook_id = :n"
                    ),
                    {"id": overview_id, "n": notebook_id},
                )
            ).mappings().first()
        if row is None:
            raise AudioOverviewNotFound()
        if row["status"] != "ready" or not row["audio_storage_key"]:
            raise InvalidInputError("Rezumatul audio nu este încă disponibil.")
        return (
            self._storage.read_bytes(row["audio_storage_key"]),
            row["mime_type"],
            (row["title"] or "Rezumat audio") + ".wav",
        )

    async def retry(
        self, actor: ActorContext, notebook_id: uuid.UUID, overview_id: uuid.UUID
    ) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT ao.status, pj.id FROM audio_overviews ao "
                        "JOIN processing_jobs pj ON pj.target_type = 'audio_overview' "
                        "AND pj.target_id = ao.id "
                        "WHERE ao.id = :id AND ao.notebook_id = :n "
                        "ORDER BY pj.created_at DESC LIMIT 1"
                    ),
                    {"id": overview_id, "n": notebook_id},
                )
            ).first()
        if row is None:
            raise AudioOverviewNotFound()
        if row.status != "failed":
            raise InvalidInputError("Poate fi reluat numai un rezumat audio eșuat.")
        ok = await requeue(self._engine, row.id, actor.actor_id)
        if ok:
            async with actor_connection(self._engine, actor.actor_id) as conn:
                await conn.execute(
                    text(
                        "UPDATE audio_overviews SET status = 'queued', error_detail = NULL "
                        "WHERE id = :id"
                    ),
                    {"id": overview_id},
                )
        return ok

    async def delete(
        self, actor: ActorContext, notebook_id: uuid.UUID, overview_id: uuid.UUID
    ) -> bool:
        """Delete an overview and fence any queued/running generation job."""
        storage_key: str | None = None
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT audio_storage_key FROM audio_overviews "
                        "WHERE id = :id AND notebook_id = :n FOR UPDATE"
                    ),
                    {"id": overview_id, "n": notebook_id},
                )
            ).mappings().first()
            if row is None:
                return False
            storage_key = row["audio_storage_key"]
            await conn.execute(
                text(
                    "UPDATE processing_jobs SET status = 'cancelled', "
                    "completed_at = now(), lease_until = NULL "
                    "WHERE target_type = 'audio_overview' AND target_id = :id "
                    "AND status IN ('queued','claimed','running')"
                ),
                {"id": overview_id},
            )
            deleted = await conn.execute(
                text(
                    "DELETE FROM audio_overviews WHERE id = :id AND notebook_id = :n"
                ),
                {"id": overview_id, "n": notebook_id},
            )
        if storage_key:
            try:
                self._storage.delete(storage_key)
            except Exception:  # noqa: BLE001 -- deletion remains authoritative
                # The database remains the source of truth. A storage cleanup
                # failure must not resurrect a deleted user-visible artifact.
                logger.exception(
                    "failed to remove audio artifact for overview %s", overview_id
                )
        return bool(deleted.rowcount)
