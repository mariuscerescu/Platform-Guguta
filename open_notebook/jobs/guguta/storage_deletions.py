"""Durable deletion outbox; a failed unlink never loses the retry record."""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import text

from open_notebook.database.guguta.engine import actor_connection, system_connection

logger = logging.getLogger("guguta.storage_deletions")


async def drain_storage_deletions(
    engine, storage, *, actor_id: uuid.UUID | None = None
) -> int:
    connection = (
        actor_connection(engine, actor_id) if actor_id else system_connection(engine)
    )
    deleted = 0
    async with connection as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT storage_key FROM storage_deletions WHERE next_attempt_at<=now() "
                    "ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED"
                )
            )
        ).all()
        for (key,) in rows:
            try:
                await asyncio.to_thread(storage.delete, key)
            except Exception as exc:
                logger.warning(
                    "private storage deletion deferred (%s)", type(exc).__name__
                )
                if actor_id is None:
                    await conn.execute(
                        text(
                            "UPDATE storage_deletions SET attempts=attempts+1, "
                            "next_attempt_at=now()+interval '30 seconds' WHERE storage_key=:key"
                        ),
                        {"key": key},
                    )
                continue
            await conn.execute(
                text("DELETE FROM storage_deletions WHERE storage_key=:key"),
                {"key": key},
            )
            deleted += 1
    return deleted
