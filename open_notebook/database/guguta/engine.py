"""Async engine and actor-scoped sessions for the Guguță stack (ADR-0007).

Actor context is set **transaction-local** with ``set_config(..., is_local =>
true)`` before any query in the transaction. The setting disappears on commit
or rollback, so a pooled connection never carries the previous actor.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from open_notebook.database.guguta.config import GugutaConfig


def create_engine_for_role(config: GugutaConfig, role: str) -> AsyncEngine:
    """Build an async engine for ``api`` or ``worker`` runtime roles."""
    if role == "api":
        url = config.database_url_api
    elif role == "worker":
        url = config.database_url_worker
    else:
        raise ValueError(f"unknown runtime role: {role}")
    if not url:
        raise ValueError(f"GUGUTA_DATABASE_URL_{role.upper()} is not configured")
    return create_async_engine(
        url,
        pool_size=config.db_pool_size,
        max_overflow=config.db_max_overflow,
        pool_timeout=config.db_pool_timeout_seconds,
        pool_pre_ping=True,
    )


def create_migrator_engine(config: GugutaConfig) -> AsyncEngine:
    """Build an engine for the single-per-release migration job (L1/L8)."""
    if not config.database_url_migrator:
        raise ValueError("GUGUTA_DATABASE_URL_MIGRATOR is not configured")
    return create_async_engine(config.database_url_migrator, pool_pre_ping=True)


@asynccontextmanager
async def actor_connection(
    engine: AsyncEngine,
    actor_id: uuid.UUID,
    *,
    share_context: Optional[uuid.UUID] = None,
    audit_access: bool = False,
) -> AsyncIterator[AsyncConnection]:
    """Open a transaction scoped to one actor (RLS context, ADR-0007).

    ``share_context`` names the share snapshot being previewed/imported and is
    only ever set by server code after token validation — never from client
    input alone. ``audit_access`` is reserved for verified administrative
    endpoints (set server-side after role checks).
    """
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.actor_id', :actor, true)"),
            {"actor": str(actor_id)},
        )
        if share_context is not None:
            await conn.execute(
                text("SELECT set_config('app.share_context', :snapshot, true)"),
                {"snapshot": str(share_context)},
            )
        if audit_access:
            await conn.execute(
                text("SELECT set_config('app.audit_access', 'granted', true)"),
            )
        logger.debug(f"actor session opened actor={actor_id}")
        yield conn


@asynccontextmanager
async def system_connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Open a transaction with no actor context (system paths).

    Only rows covered by role-specific policies (e.g. the job queue) are
    reachable this way; personal tables deny access without an actor.
    """
    async with engine.begin() as conn:
        yield conn
