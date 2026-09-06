"""Notes service: private notes + saving chat answers as notes (L5).

Notes are personal, editable, excluded from share snapshots (L7 allowlist)
and never injected into the model context implicitly (specificații §5).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import NotFoundError, OpenNotebookError


class NoteNotFound(NotFoundError):
    pass


class NoteValidation(OpenNotebookError):
    pass


class NotesService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self, actor: ActorContext, notebook_id: uuid.UUID, *, title: str,
        content: str, source_message_id: Optional[uuid.UUID] = None,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        content = (content or "").strip()
        if not title:
            raise NoteValidation("Titlul notiței este obligatoriu.")
        if not content:
            raise NoteValidation("Conținutul notiței este obligatoriu.")
        note_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            nb = (
                await conn.execute(
                    text("SELECT id FROM digital_notebooks WHERE id = :id"),
                    {"id": notebook_id},
                )
            ).first()
            if nb is None:
                raise NoteNotFound()
            if source_message_id is not None:
                msg = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM chat_messages m"
                            " JOIN chat_sessions s ON s.id = m.session_id"
                            " WHERE m.id = :mid AND s.notebook_id = :nb"
                        ),
                        {"mid": source_message_id, "nb": notebook_id},
                    )
                ).first()
                if msg is None:
                    raise NoteValidation("Mesajul sursă nu aparține carnetului.")
            await conn.execute(
                text(
                    "INSERT INTO notes (id, notebook_id, created_by, title, content,"
                    " source_message_id) VALUES (:id, :nb, :by, :t, :c, :src)"
                ),
                {"id": note_id, "nb": notebook_id, "by": actor.actor_id,
                 "t": title[:500], "c": content, "src": source_message_id},
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT id, notebook_id, title, content, source_message_id,"
                        " created_at, updated_at FROM notes WHERE id = :id"
                    ),
                    {"id": note_id},
                )
            ).mappings().one()
        return dict(row)

    async def list_for_notebook(
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
                raise NoteNotFound()
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, title, content, source_message_id, created_at,"
                        " updated_at FROM notes WHERE notebook_id = :nb"
                        " ORDER BY updated_at DESC"
                    ),
                    {"nb": notebook_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def get(
        self, actor: ActorContext, notebook_id: uuid.UUID, note_id: uuid.UUID
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, title, content, source_message_id, created_at,"
                        " updated_at FROM notes WHERE id = :id AND notebook_id = :nb"
                    ),
                    {"id": note_id, "nb": notebook_id},
                )
            ).mappings().first()
        if row is None:
            raise NoteNotFound()
        return dict(row)

    async def update(
        self, actor: ActorContext, notebook_id: uuid.UUID, note_id: uuid.UUID, *,
        title: Optional[str] = None, content: Optional[str] = None,
    ) -> dict[str, Any]:
        sets: list[str] = []
        params: dict[str, Any] = {"id": note_id, "nb": notebook_id}
        if title is not None:
            title = title.strip()
            if not title:
                raise NoteValidation("Titlul nu poate fi vid.")
            sets.append("title = :title")
            params["title"] = title
        if content is not None:
            content = content.strip()
            if not content:
                raise NoteValidation("Conținutul nu poate fi vid.")
            sets.append("content = :content")
            params["content"] = content
        if not sets:
            raise NoteValidation("Nimic de actualizat.")
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text(f"UPDATE notes SET {', '.join(sets)} WHERE id = :id"),
                params,
            )
            if result.rowcount == 0:
                raise NoteNotFound()
            row = (
                await conn.execute(
                    text(
                        "SELECT id, title, content, source_message_id, updated_at"
                        " FROM notes WHERE id = :id"
                    ),
                    {"id": note_id},
                )
            ).mappings().one()
        return dict(row)

    async def delete(
        self, actor: ActorContext, notebook_id: uuid.UUID, note_id: uuid.UUID
    ) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text("DELETE FROM notes WHERE id = :id AND notebook_id = :nb"),
                {"id": note_id, "nb": notebook_id},
            )
        return bool(result.rowcount)
