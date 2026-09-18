"""Worker handler for asynchronous Audio Overview generation."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.audio_overview import (
    MOSS_MODEL,
    PROMPT_VERSION,
    AudioScriptGenerator,
    MossTtsClient,
)
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import ConfigurationError
from open_notebook.jobs.guguta.queue import ClaimedJob, LeaseStale, fail
from open_notebook.storage.guguta.base import StorageBackend

logger = logging.getLogger("guguta.audio_overview")


async def _set_status(
    engine: AsyncEngine,
    actor_id: uuid.UUID,
    overview_id: uuid.UUID,
    status: str,
    *,
    error: str | None = None,
) -> None:
    async with actor_connection(engine, actor_id) as conn:
        await conn.execute(
            text(
                "UPDATE audio_overviews SET status = :status, error_detail = :error "
                "WHERE id = :id"
            ),
            {"status": status, "error": error, "id": overview_id},
        )


async def _load_input(
    engine: AsyncEngine,
    actor_id: uuid.UUID,
    overview_id: uuid.UUID,
    max_chars: int,
) -> tuple[str, list[dict[str, str]]]:
    async with actor_connection(engine, actor_id) as conn:
        overview = (
            await conn.execute(
                text(
                    "SELECT format, selected_source_ids FROM audio_overviews "
                    "WHERE id = :id FOR UPDATE"
                ),
                {"id": overview_id},
            )
        ).mappings().first()
        if overview is None:
            raise ValueError("Rezumatul audio nu mai există.")
        source_ids = [uuid.UUID(value) for value in overview["selected_source_ids"]]
        rows = (
            await conn.execute(
                text(
                    "SELECT ns.id, ns.local_name, string_agg(c.text, E'\\n' ORDER BY c.position) AS content "
                    "FROM notebook_sources ns "
                    "JOIN LATERAL ("
                    "  SELECT pa.id FROM processing_artifacts pa "
                    "  WHERE pa.material_version_id = ns.material_version_id "
                    "    AND pa.status = 'complete' ORDER BY pa.created_at DESC LIMIT 1"
                    ") latest ON true "
                    "JOIN chunks c ON c.artifact_id = latest.id "
                    "WHERE ns.id = ANY(:ids) AND ns.status = 'ready' "
                    "GROUP BY ns.id, ns.local_name, ns.position "
                    "ORDER BY ns.position"
                ),
                {"ids": source_ids},
            )
        ).mappings().all()
    if len(rows) != len(source_ids):
        raise ValueError("Un material selectat nu mai este gata sau nu mai există.")
    remaining = max_chars
    sources: list[dict[str, str]] = []
    for row in rows:
        content = str(row["content"] or "").strip()
        if remaining <= 0:
            break
        content = content[:remaining]
        remaining -= len(content)
        if content:
            sources.append({"name": str(row["local_name"]), "text": content})
    if not sources:
        raise ValueError("Materialele selectate nu conțin text procesat.")
    return str(overview["format"]), sources


async def process_audio_overview(
    engine: AsyncEngine,
    storage: StorageBackend,
    config: Any,
    job: ClaimedJob,
) -> None:
    if job.actor_id is None:
        await fail(
            engine,
            job.id,
            job.lease_token,
            "job audio fără proprietar",
            target_revision=job.target_revision,
            permanent=True,
        )
        return

    stored_key: str | None = None
    try:
        await _set_status(engine, job.actor_id, job.target_id, "generating_script")
        format_name, sources = await _load_input(
            engine,
            job.actor_id,
            job.target_id,
            config.audio_overview_max_source_chars,
        )
        script = await AudioScriptGenerator(config).generate(
            format_name=format_name, sources=sources
        )
        async with actor_connection(engine, job.actor_id) as conn:
            await conn.execute(
                text(
                    "UPDATE audio_overviews SET title = :title, script_text = :script, "
                    "script_model_name = :model, tts_model_name = :tts_model, "
                    "prompt_version = :prompt, "
                    "status = 'synthesizing', error_detail = NULL WHERE id = :id"
                ),
                {
                    "title": script.title,
                    "script": script.script,
                    "model": script.model,
                    "tts_model": MOSS_MODEL,
                    "prompt": PROMPT_VERSION,
                    "id": job.target_id,
                },
            )

        audio, duration = await MossTtsClient(config).synthesize(script.script)
        stored_key = storage.save_bytes(audio, prefix="audio")

        # Publish the artifact and complete the queue row in one transaction.
        # The lease predicate fences a stale worker before it can expose audio.
        async with actor_connection(engine, job.actor_id) as conn:
            published = await conn.execute(
                text(
                    "UPDATE audio_overviews ao SET status = 'ready', "
                    "audio_storage_key = :key, mime_type = 'audio/wav', "
                    "duration_seconds = :duration, error_detail = NULL, completed_at = now() "
                    "WHERE ao.id = :id AND EXISTS ("
                    "  SELECT 1 FROM processing_jobs pj WHERE pj.id = :job "
                    "  AND pj.lease_token = :token AND pj.status IN ('claimed','running') "
                    "  AND pj.target_revision = :revision "
                    "  AND (pj.lease_until IS NULL OR pj.lease_until > now())"
                    ") RETURNING ao.id"
                ),
                {
                    "key": stored_key,
                    "duration": round(duration, 2),
                    "id": job.target_id,
                    "job": job.id,
                    "token": job.lease_token,
                    "revision": job.target_revision,
                },
            )
            if published.first() is None:
                raise LeaseStale("lease audio expirat înainte de publicare")
            completed = await conn.execute(
                text(
                    "UPDATE processing_jobs SET status = 'succeeded', completed_at = now(), "
                    "last_error = NULL WHERE id = :job AND lease_token = :token "
                    "AND status IN ('claimed','running') RETURNING id"
                ),
                {"job": job.id, "token": job.lease_token},
            )
            if completed.first() is None:
                raise LeaseStale("jobul audio nu a putut fi finalizat")
    except LeaseStale:
        if stored_key:
            storage.delete(stored_key)
        raise
    except Exception as exc:
        if stored_key:
            storage.delete(stored_key)
        permanent = isinstance(exc, (ValueError, ConfigurationError))
        message = str(exc)[:2000] or "Generarea audio a eșuat."
        try:
            status = await fail(
                engine,
                job.id,
                job.lease_token,
                message,
                target_revision=job.target_revision,
                permanent=permanent,
            )
        except LeaseStale:
            logger.warning("Eșecul Audio Overview nu a putut fi salvat: lease expirat")
            return
        await _set_status(
            engine,
            job.actor_id,
            job.target_id,
            "failed" if status == "failed" else "queued",
            error=message if status == "failed" else None,
        )
