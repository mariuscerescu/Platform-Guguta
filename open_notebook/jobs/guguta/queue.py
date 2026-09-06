"""Guguță durable job queue on PostgreSQL (ADR-0002).

Delivery: at-least-once. Claims use FOR UPDATE SKIP LOCKED in a short
transaction. Completions verify lease_token AND target_revision â€” a stale
worker cannot publish (A21). Backoff uses exponential delay with jitter.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.database.guguta.engine import system_connection


class LeaseStale(Exception):
    """The completion was refused: lease lost or target revision advanced."""


class JobNotFound(Exception):
    pass


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    job_type: str
    target_type: str
    target_id: uuid.UUID
    target_revision: int
    actor_id: Optional[uuid.UUID]
    payload: dict[str, Any]
    lease_token: str
    attempts: int


DEFAULT_LEASE_SECONDS = 300
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_MAX_CONCURRENT_PER_USER = 2


async def enqueue(
    engine: AsyncEngine, conn: Any, *,
    job_type: str, target_type: str, target_id: uuid.UUID,
    target_revision: int = 1, actor_id: Optional[uuid.UUID] = None,
    payload: Optional[dict[str, Any]] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    deadline_seconds: Optional[int] = None,
) -> uuid.UUID:
    """Insert a job inside the caller's transaction (same tx as the target)."""
    job_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO processing_jobs (id, job_type, target_type, target_id, "
            "target_revision, actor_id, payload, max_attempts, deadline) "
            "VALUES (:id, :jt, :tt, :tid, :trev, :actor, CAST(:payload AS jsonb), :maxa, "
            "CASE WHEN CAST(:dl AS float8) IS NULL THEN NULL"
            " ELSE now() + make_interval(secs => CAST(:dl AS float8)) END)"
        ),
        {
            "id": job_id,
            "jt": job_type,
            "tt": target_type,
            "tid": target_id,
            "trev": target_revision,
            "actor": actor_id,
            "payload": _json(payload or {}),
            "maxa": max_attempts,
            "dl": deadline_seconds,
        },
    )
    return job_id


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


async def claim(
    engine: AsyncEngine, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
    worker_name: str = "worker",
    max_concurrent_per_user: int = DEFAULT_MAX_CONCURRENT_PER_USER,
) -> Optional[ClaimedJob]:
    """Claim one runnable job (queued, or with an expired lease).

    F11 controls applied at claim time: expired deadlines fail the job,
    the attempts budget is enforced, and the per-user concurrency cap is
    respected."""
    lease_token = secrets.token_urlsafe(24)
    async with system_connection(engine) as conn:
        # sweep: jobs past their deadline or out of attempts never run again
        await conn.execute(
            text(
                "UPDATE processing_jobs SET status = 'failed', completed_at = now(),"
                " last_error = coalesce(last_error, 'deadline depășit / încercări epuizate')"
                " WHERE status IN ('queued','claimed','running')"
                "   AND ("
                "     (deadline IS NOT NULL AND deadline < now())"
                "     OR (attempts >= max_attempts AND status <> 'failed')"
                "   )"
            )
        )
        row = (
            await conn.execute(
                text(
                    "WITH runnable AS ("
                    "  SELECT id FROM processing_jobs"
                    "  WHERE (status = 'queued' AND run_after <= now()"
                    "         AND attempts < max_attempts"
                    "         AND (deadline IS NULL OR deadline > now()))"
                    "     OR (status IN ('claimed','running')"
                    "         AND lease_until IS NOT NULL AND lease_until < now()"
                    "         AND attempts < max_attempts"
                    "         AND (deadline IS NULL OR deadline > now()))"
                    "   AND (actor_id IS NULL OR actor_id NOT IN ("
                    "        SELECT j2.actor_id FROM processing_jobs j2"
                    "        WHERE j2.status IN ('claimed','running')"
                    "          AND j2.actor_id IS NOT NULL"
                    "        GROUP BY j2.actor_id"
                    "        HAVING count(*) >= :maxc))"
                    "  ORDER BY created_at"
                    "  FOR UPDATE SKIP LOCKED LIMIT 1"
                    ") "
                    "UPDATE processing_jobs j SET"
                    "  status = 'running', lease_owner = :owner,"
                    "  lease_token = :token,"
                    "  lease_until = now() + make_interval(secs => :lease),"
                    "  heartbeat_at = now(), attempts = attempts + 1"
                    " FROM runnable r WHERE j.id = r.id"
                    " RETURNING j.id, j.job_type, j.target_type, j.target_id,"
                    "           j.target_revision, j.actor_id, j.payload, j.attempts"
                ),
                {
                    "owner": worker_name,
                    "token": lease_token,
                    "lease": lease_seconds,
                    "maxc": max_concurrent_per_user,
                },
            )
        ).mappings().first()
        if row is None:
            return None
        return ClaimedJob(
            id=row["id"],
            job_type=row["job_type"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            target_revision=int(row["target_revision"]),
            actor_id=row["actor_id"],
            payload=dict(row["payload"] or {}),
            lease_token=lease_token,
            attempts=int(row["attempts"]),
        )


async def heartbeat(
    engine: AsyncEngine, job_id: uuid.UUID, lease_token: str, *,
    extend_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    async with system_connection(engine) as conn:
        result = await conn.execute(
            text(
                "UPDATE processing_jobs SET lease_until = now() + make_interval(secs => :s),"
                " heartbeat_at = now()"
                " WHERE id = :id AND lease_token = :t AND status IN ('claimed','running')"
            ),
            {"id": job_id, "t": lease_token, "s": extend_seconds},
        )
    return bool(result.rowcount)


async def complete(
    engine: AsyncEngine, job_id: uuid.UUID, lease_token: str, *,
    target_revision: int,
) -> None:
    """Mark succeeded; refuses stale leases (incl. expired lease_until),
    outdated target revisions, or a lost token (F10/F11)."""
    async with system_connection(engine) as conn:
        row = (
            await conn.execute(
                text(
                    "UPDATE processing_jobs SET status = 'succeeded',"
                    " completed_at = now(), last_error = NULL"
                    " WHERE id = :id AND lease_token = :t"
                    "   AND status IN ('claimed','running')"
                    "   AND target_revision = :trev"
                    "   AND (lease_until IS NULL OR lease_until > now())"
                    " RETURNING id"
                ),
                {"id": job_id, "t": lease_token, "trev": target_revision},
            )
        ).first()
    if row is None:
        raise LeaseStale("jobul nu a putut fi finalizat: lease expirat sau țintă modificată")


async def fail(
    engine: AsyncEngine, job_id: uuid.UUID, lease_token: str, error: str, *,
    target_revision: int, base_backoff_seconds: int = 5, max_backoff_seconds: int = 300,
    permanent: bool = False,
) -> str:
    """Record failure; requeue with jittered exponential backoff until the
    attempts budget is exhausted (or immediately for permanent errors).
    Returns the new status: 'queued' or 'failed'.
    """
    async with system_connection(engine) as conn:
        row = (
            await conn.execute(
                text(
                    "UPDATE processing_jobs SET"
                    "  last_error = :err,"
                    "  lease_token = NULL, lease_owner = NULL, lease_until = NULL,"
                    "  status = CASE"
                    "    WHEN :perm THEN 'failed'"
                    "    WHEN attempts >= max_attempts THEN 'failed'"
                    "    ELSE 'queued' END,"
                    "  run_after = CASE"
                    "    WHEN :perm OR attempts >= max_attempts THEN run_after"
                    "    ELSE now() + make_interval(secs => LEAST("
                    "           CAST(:maxb AS float8),"
                    "           CAST(:baseb AS float8) * power(2, GREATEST(0, attempts - 1))"
                    "           * (0.5 + random()))) END"
                    " WHERE id = :id AND lease_token = :t"
                    "   AND status IN ('claimed','running')"
                    "   AND target_revision = :trev"
                    " RETURNING status"
                ),
                {
                    "err": error[:2000],
                    "id": job_id,
                    "t": lease_token,
                    "trev": target_revision,
                    "baseb": base_backoff_seconds,
                    "maxb": max_backoff_seconds,
                    "perm": permanent,
                },
            )
        ).first()
    if row is None:
        raise LeaseStale("jobul nu a putut fi marcat eșuat: lease expirat")
    return str(row[0])


async def cancel_for_target(    engine: AsyncEngine, target_type: str, target_id: uuid.UUID
) -> int:
    """Cancel queued jobs whose target disappeared (GHID Â§6.3)."""
    async with system_connection(engine) as conn:
        result = await conn.execute(
            text(
                "UPDATE processing_jobs SET status = 'cancelled', completed_at = now()"
                " WHERE target_type = :tt AND target_id = :tid"
                "   AND status IN ('queued','claimed')"
            ),
            {"tt": target_type, "tid": target_id},
        )
    return int(result.rowcount or 0)


async def requeue(
    engine: AsyncEngine, job_id: uuid.UUID, actor_id: uuid.UUID
) -> bool:
    """Manual retry by the owning user; resets lease state."""
    from open_notebook.database.guguta.engine import actor_connection

    async with actor_connection(engine, actor_id) as conn:
        result = await conn.execute(
            text(
                "UPDATE processing_jobs SET status = 'queued', run_after = now(),"
                " attempts = 0, last_error = NULL,"
                " lease_token = NULL, lease_owner = NULL, lease_until = NULL"
                " WHERE id = :id AND actor_id = :actor"
                "   AND status IN ('failed','cancelled')"
            ),
            {"id": job_id, "actor": actor_id},
        )
    return bool(result.rowcount)


async def get_job_for_actor(
    engine: AsyncEngine, job_id: uuid.UUID, actor_id: uuid.UUID
) -> Optional[dict[str, Any]]:
    async with system_connection(engine) as conn:
        await conn.execute(
            text("SELECT set_config('app.actor_id', :a, true)"),
            {"a": str(actor_id)},
        )
        row = (
            await conn.execute(
                text(
                    "SELECT id, job_type, target_type, target_id, status, attempts,"
                    " max_attempts, last_error, created_at, updated_at, completed_at"
                    " FROM processing_jobs WHERE id = :id"
                ),
                {"id": job_id},
            )
        ).mappings().first()
    return dict(row) if row else None
