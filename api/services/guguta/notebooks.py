"""Notebook CRUD service — authorization on the server, RLS as second layer.

Repositories here always receive an ActorContext; ownership comes from the
session, never from client input. Lists paginate with allowlisted sorting.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import NotFoundError, OpenNotebookError

SortKey = Literal["created_desc", "created_asc", "title_asc", "title_desc", "updated_desc"]

_SORTS: dict[SortKey, str] = {
    "created_desc": "created_at DESC, id DESC",
    "created_asc": "created_at ASC, id ASC",
    "title_asc": "title ASC, id ASC",
    "title_desc": "title DESC, id DESC",
    "updated_desc": "updated_at DESC, id DESC",
}

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


class NotebookNotFound(NotFoundError):
    """Raised for missing or foreign notebooks (API maps to 404)."""


class NotebookValidation(OpenNotebookError):
    """Invalid input (API maps to 422)."""


def _clamp_page(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), PAGE_SIZE_MAX)
    return page, page_size


class NotebookService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self, actor: ActorContext, *, title: str, description: Optional[str] = None,
        origin: str = "personal",
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise NotebookValidation("Titlul este obligatoriu.")
        if len(title) > 500:
            raise NotebookValidation("Titlul depășește 500 de caractere.")
        nb_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO digital_notebooks (id, owner_id, title, description, origin) "
                    "VALUES (:id, :owner, :title, :description, :origin)"
                ),
                {
                    "id": nb_id,
                    "owner": actor.actor_id,
                    "title": title,
                    "description": description,
                    "origin": origin,
                },
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT id, owner_id, title, description, status, origin, "
                        "context_revision, created_at, updated_at "
                        "FROM digital_notebooks WHERE id = :id"
                    ),
                    {"id": nb_id},
                )
            ).mappings().one()
        return dict(row)

    async def list_for_actor(
        self, actor: ActorContext, *, page: int = 1, page_size: int = PAGE_SIZE_DEFAULT,
        sort: SortKey = "created_desc", status: Optional[str] = None,
    ) -> dict[str, Any]:
        page, page_size = _clamp_page(page, page_size)
        order = _SORTS[sort]
        status_filter = "AND status = :status" if status in ("active", "archived") else ""
        params: dict[str, Any] = {
            "limit": page_size + 1,
            "offset": (page - 1) * page_size,
        }
        if status_filter:
            params["status"] = status
        async with actor_connection(self._engine, actor.actor_id) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, title, description, status, origin, context_revision, "
                        "created_at, updated_at FROM digital_notebooks "
                        f"WHERE status <> 'deleted' {status_filter} "
                        f"ORDER BY {order} LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
            ).mappings().all()
            total = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM digital_notebooks "
                        f"WHERE status <> 'deleted' {status_filter}"
                    ),
                    params,
                )
            ).scalar_one()
        has_next = len(rows) > page_size
        rows = rows[:page_size]
        return {
            "items": [dict(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
            "has_next": has_next,
        }

    async def get(self, actor: ActorContext, notebook_id: uuid.UUID) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT id, owner_id, title, description, status, origin, "
                        "context_revision, created_at, updated_at "
                        "FROM digital_notebooks WHERE id = :id"
                    ),
                    {"id": notebook_id},
                )
            ).mappings().first()
        if row is None:
            raise NotebookNotFound()
        return dict(row)

    async def update(
        self, actor: ActorContext, notebook_id: uuid.UUID, *,
        title: Optional[str] = None, description: Optional[str] = None,
        archive: Optional[bool] = None,
    ) -> dict[str, Any]:
        sets: list[str] = []
        params: dict[str, Any] = {"id": notebook_id}
        if title is not None:
            title = title.strip()
            if not title:
                raise NotebookValidation("Titlul nu poate fi vid.")
            if len(title) > 500:
                raise NotebookValidation("Titlul depășește 500 de caractere.")
            sets.append("title = :title")
            params["title"] = title
        if description is not None:
            sets.append("description = :description")
            params["description"] = description
        if archive is True:
            sets.extend(["status = 'archived'", "archived_at = now()"])
        elif archive is False:
            sets.extend(["status = 'active'", "archived_at = NULL"])
        if not sets:
            raise NotebookValidation("Nimic de actualizat.")
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text(
                    "UPDATE digital_notebooks SET "
                    + ", ".join(sets)
                    + " WHERE id = :id"
                ),
                params,
            )
            if result.rowcount == 0:
                raise NotebookNotFound()
            row = (
                await conn.execute(
                    text(
                        "SELECT id, owner_id, title, description, status, origin, "
                        "context_revision, created_at, updated_at "
                        "FROM digital_notebooks WHERE id = :id"
                    ),
                    {"id": notebook_id},
                )
            ).mappings().one()
        return dict(row)

    async def delete(self, actor: ActorContext, notebook_id: uuid.UUID) -> int:
        """Logical delete (retention keeps data); revocation of active share
        packages is implemented in L7 — tracked in the checklist."""
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text("DELETE FROM digital_notebooks WHERE id = :id"),
                {"id": notebook_id},
            )
        return int(result.rowcount or 0)
