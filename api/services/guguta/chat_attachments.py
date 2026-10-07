"""Private conversation attachments sharing the material/OCR pipeline."""

from __future__ import annotations

from typing import Any

from sqlalchemy import bindparam, text

from api.services.guguta.sources import SourceNotFound, SourceValidation
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.jobs.guguta.storage_deletions import drain_storage_deletions


class ChatAttachmentsService:
    def __init__(self, sources) -> None:
        self._sources = sources
        self._engine = sources._engine
        self._storage = sources._storage

    @property
    def limits(self) -> dict[str, int]:
        sources = self._sources
        return {
            "max_file_mib": sources._attachment_bytes // (1024 * 1024),
            "max_total_mib": sources._attachment_total_bytes // (1024 * 1024),
            "max_per_message": sources._attachment_message_count,
            "max_per_session": sources._attachment_session_count,
            "max_image_pixels": sources._max_image_pixels,
            "max_image_dimension": sources._max_image_dimension,
        }

    async def _authorize(self, conn, notebook_id, session_id, *, lock=False):
        row = (
            await conn.execute(
                text(
                    "SELECT id FROM chat_sessions WHERE notebook_id=:nb AND id=:sid"
                    + (" FOR UPDATE" if lock else "")
                ),
                {"nb": notebook_id, "sid": session_id},
            )
        ).first()
        if row is None:
            raise SourceNotFound()

    async def list(self, actor, notebook_id, session_id) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await self._authorize(conn, notebook_id, session_id)
        sources = await self._sources.list_for_notebook(
            actor, notebook_id, chat_session_id=session_id
        )
        return {"attachments": sources, "limits": self.limits}

    async def upload(self, actor, notebook_id, session_id, files) -> dict[str, Any]:
        if not files or len(files) > self.limits["max_per_message"]:
            raise SourceValidation(
                f"Selectează între 1 și {self.limits['max_per_message']} fișiere."
            )
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await self._authorize(conn, notebook_id, session_id)
        # Validate the batch before creating any association; bounded reads.
        data = []
        for file in files:
            content = await file.read(self._sources._attachment_bytes + 1)
            if len(content) > self._sources._attachment_bytes:
                raise SourceValidation(
                    f"Maximum {self.limits['max_file_mib']} MiB pe fișier."
                )
            data.append((file.filename, content))
        if (
            sum(len(content) for _, content in data)
            > self._sources._attachment_total_bytes
        ):
            raise SourceValidation(
                f"Maximum {self.limits['max_total_mib']} MiB în total pentru un mesaj."
            )
        created = []
        try:
            for name, content in data:
                result = await self._sources._create_source(
                    actor,
                    notebook_id,
                    data=content,
                    original_name=name,
                    local_name=name,
                    chat_session_id=session_id,
                )
                created.append(result["source"])
        except Exception:
            for source in created:
                await self.remove(actor, notebook_id, session_id, source["id"])
            raise
        return {"attachments": created, "limits": self.limits}

    async def validate(self, actor, notebook_id, session_id, ids):
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await self._authorize(conn, notebook_id, session_id)
            await self._validate_on_conn(conn, session_id, ids)

    async def _validate_on_conn(self, conn, session_id, ids):
        if len(ids) > self.limits["max_per_message"] or len(set(ids)) != len(ids):
            raise SourceValidation(
                f"Maximum {self.limits['max_per_message']} atașamente distincte într-un mesaj."
            )
        if not ids:
            return
        rows = (
            await conn.execute(
                text(
                    "SELECT ns.id,ns.status,sa.byte_size FROM notebook_sources ns "
                    "JOIN material_versions mv ON mv.id=ns.material_version_id "
                    "JOIN source_assets sa ON sa.id=mv.source_asset_id "
                    "WHERE ns.chat_session_id=:sid AND ns.id IN :ids"
                ).bindparams(bindparam("ids", expanding=True)),
                {"sid": session_id, "ids": ids},
            )
        ).all()
        if len(rows) != len(ids):
            raise SourceNotFound()
        if any(row.status != "ready" for row in rows):
            raise SourceValidation(
                "Așteaptă procesarea atașamentelor sau elimină fișierele în eroare."
            )
        if sum(row.byte_size for row in rows) > self._sources._attachment_total_bytes:
            raise SourceValidation(
                "Atașamentele depășesc limita totală pentru un mesaj."
            )

    async def bind(self, conn, session_id, message_id, ids):
        await self._validate_on_conn(conn, session_id, ids)
        if not ids:
            return
        result = await conn.execute(
            text(
                "UPDATE notebook_sources SET chat_message_id=:msg "
                "WHERE chat_session_id=:sid AND chat_message_id IS NULL AND id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"sid": session_id, "msg": message_id, "ids": ids},
        )
        if result.rowcount != len(ids):
            raise SourceValidation("Un atașament este deja asociat altui mesaj.")

    async def check_file(self, actor, notebook_id, session_id, source_id):
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await self._authorize(conn, notebook_id, session_id)
            found = (
                await conn.execute(
                    text(
                        "SELECT id FROM notebook_sources WHERE notebook_id=:nb AND chat_session_id=:sid AND id=:id"
                    ),
                    {"nb": notebook_id, "sid": session_id, "id": source_id},
                )
            ).first()
            if found is None:
                raise SourceNotFound()

    async def remove(self, actor, notebook_id, session_id, source_id) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await self._authorize(conn, notebook_id, session_id, lock=True)
            result = await conn.execute(
                text(
                    "DELETE FROM notebook_sources WHERE notebook_id=:nb AND chat_session_id=:sid AND id=:id"
                ),
                {"nb": notebook_id, "sid": session_id, "id": source_id},
            )
            if result.rowcount == 0:
                raise SourceNotFound()
        await drain_storage_deletions(
            self._engine, self._storage, actor_id=actor.actor_id
        )
        return True

    async def delete_chat(self, actor, notebook_id, session_id) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            # Same lock order as uploads: user -> chat -> associated jobs.
            await conn.execute(
                text("SELECT id FROM users WHERE id=:id FOR UPDATE"),
                {"id": actor.actor_id},
            )
            await self._authorize(conn, notebook_id, session_id, lock=True)
            await conn.execute(
                text(
                    "DELETE FROM idempotency_records WHERE result_id IN "
                    "(SELECT id FROM chat_messages WHERE session_id=:sid)"
                ),
                {"sid": session_id},
            )
            await conn.execute(
                text("DELETE FROM chat_sessions WHERE id=:sid"), {"sid": session_id}
            )
        await drain_storage_deletions(
            self._engine, self._storage, actor_id=actor.actor_id
        )
        return True
