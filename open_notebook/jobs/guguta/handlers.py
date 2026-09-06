"""Job handler: material_version processing pipeline (GHID §6.2).

Steps: verify target → read bytes from private storage → extract text with
locators (A24 for scanned PDFs) → segment → ensure the active embedding space
→ publish artifact + chunks + embeddings + source status atomically → mark
the job complete (lease-checked).

Every domain write runs under the target owner's actor context (RLS).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.database.guguta.engine import actor_connection, system_connection
from open_notebook.exceptions import OpenNotebookError
from open_notebook.jobs.guguta import parsing
from open_notebook.jobs.guguta.embeddings import EmbeddingProvider
from open_notebook.jobs.guguta.queue import (
    ClaimedJob,
    LeaseStale,
    cancel_for_target,
    complete,
    fail,
)
from open_notebook.storage.guguta.base import StorageBackend

logger = logging.getLogger("guguta.jobs")

PARSER = "pypdf-text"
PARSER_VERSION = "1"
CHUNKER = "char-overlap"
CHUNKER_VERSION = "1"


class TargetGone(OpenNotebookError):
    """The source association disappeared while the job was queued."""


async def _ensure_embedding_space(
    conn: Any, provider: EmbeddingProvider
) -> uuid.UUID:
    """Return the active space; create+activate only if none exists.

    A mismatched active space means a different model is live: the job fails
    with an explicit error instead of mixing incompatible vectors (A27).
    """
    row = (
        await conn.execute(
            text(
                "SELECT id, model_name, model_revision, dimension "
                "FROM embedding_spaces WHERE is_active"
            )
        )
    ).mappings().first()
    if row is not None:
        if (
            row["model_name"] != provider.model_name
            or row["model_revision"] != provider.model_revision
            or int(row["dimension"]) != provider.dimension
        ):
            raise OpenNotebookError(
                "Spațiul vectorial activ folosește alt model "
                f"({row['model_name']}/{row['model_revision']}/{row['dimension']}). "
                "Reindexarea cu alt model se face prin un spațiu nou (A27)."
            )
        return row["id"]
    space_id = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO embedding_spaces (id, model_name, model_revision, dimension,"
            " distance_strategy, is_active) VALUES (:id, :m, :r, :d, 'cosine', true)"
        ),
        {"id": space_id, "m": provider.model_name, "r": provider.model_revision,
         "d": provider.dimension},
    )
    return space_id


async def process_material_version(
    engine: AsyncEngine,
    storage: StorageBackend,
    provider: EmbeddingProvider,
    job: ClaimedJob,
    *,
    chunk_size_chars: int = 2000,
    overlap_chars: int = 200,
) -> None:
    assert job.target_type == "material_version"
    mv_id = job.target_id
    if job.actor_id is None:
        raise OpenNotebookError("jobul de procesare necesită actorul proprietarului")
    actor_id = job.actor_id

    # 1) Load target under the owner's context; refetch bytes via storage key.
    async with actor_connection(engine, actor_id) as conn:
        target = (
            await conn.execute(
                text(
                    "SELECT mv.id, mv.version, mv.provenance, mv.page_count,"
                    " mv.created_by, sa.storage_key, sa.kind, sa.text_content,"
                    " sa.mime_type, ns.id AS source_id"
                    " FROM material_versions mv"
                    " JOIN source_assets sa ON sa.id = mv.source_asset_id"
                    " LEFT JOIN notebook_sources ns ON ns.material_version_id = mv.id"
                    " WHERE mv.id = :id"
                ),
                {"id": mv_id},
            )
        ).mappings().first()
    if target is None or target["source_id"] is None:
        # Source association removed while queued: cancel silently (GHID §6.3).
        await cancel_for_target(engine, "material_version", mv_id)
        await _cancel_job(engine, job)
        return
    source_id = target["source_id"]

    # 2) Extract (no DB transaction held).
    try:
        detected_kind = str((target["provenance"] or {}).get("kind") or target["kind"])
        if detected_kind == "text" or target["kind"] == "text":
            data = (target["text_content"] or "").encode("utf-8")
        else:
            data = storage.read_bytes(target["storage_key"])
        units, page_count = parsing.extract_units(detected_kind, data)
        chunks = parsing.segment(
            units, chunk_size_chars=chunk_size_chars, overlap_chars=overlap_chars
        )
        if not chunks:
            raise parsing.ExtractionError("Nu a rezultat niciun fragment din material.")
        vectors = provider.embed([c.text for c in chunks])
    except parsing.ExtractionError as exc:
        # Permanent: user-presentable error (A24, R42) — no blind retry.
        await _mark_source_error(engine, actor_id, source_id, str(exc))
        await _fail_quietly(engine, job, str(exc), permanent=True)
        return
    except Exception as exc:  # transient (storage/provider/network)
        await _fail_quietly(engine, job, f"eroare tranzitorie: {exc}", permanent=False)
        return

    # 3) Publish atomically: artifact + chunks + embeddings + source ready.
    artifact_id = uuid.uuid4()
    checksum_src = "\x1e".join(c.text for c in chunks)
    import hashlib

    checksum = hashlib.sha256(checksum_src.encode("utf-8")).hexdigest()
    try:
        async with actor_connection(engine, actor_id) as conn:
            space_id = await _ensure_embedding_space(conn, provider)
            await conn.execute(
                text(
                    "INSERT INTO processing_artifacts (id, material_version_id, parser,"
                    " parser_version, chunker, chunker_version, chunk_size, chunk_overlap,"
                    " status, result_checksum, completed_at)"
                    " VALUES (:id, :mv, :p, :pv, :c, :cv, :cs, :co, 'complete', :sum, now())"
                ),
                {"id": artifact_id, "mv": mv_id, "p": PARSER, "pv": PARSER_VERSION,
                 "c": CHUNKER, "cv": CHUNKER_VERSION, "cs": chunk_size_chars,
                 "co": overlap_chars, "sum": checksum},
            )
            for chunk, vec in zip(chunks, vectors):
                chunk_id = uuid.uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO chunks (id, artifact_id, position, text, locator,"
                        " char_start, char_end) VALUES (:id, :a, :pos, :t,"
                        " CAST(:loc AS jsonb), :cs, :ce)"
                    ),
                    {"id": chunk_id, "a": artifact_id, "pos": chunk.position,
                     "t": chunk.text, "loc": _json(chunk.locator),
                     "cs": chunk.char_start, "ce": chunk.char_end},
                )
                await conn.execute(
                    text(
                        "INSERT INTO embeddings (id, chunk_id, embedding_space_id, embedding)"
                        " VALUES (:id, :c, :s, :v)"
                    ),
                    {"id": uuid.uuid4(), "c": chunk_id, "s": space_id,
                     "v": str(vec)},
                )
            await conn.execute(
                text(
                    "UPDATE notebook_sources SET status = 'ready', status_detail = NULL"
                    " WHERE id = :id"
                ),
                {"id": source_id},
            )
    except Exception as exc:
        # Duplicate-artifact race or transient DB error: distinguish.
        if "ux_artifacts_mv_parser" in str(exc):
            await _fail_quietly(engine, job, "artefact deja publicat", permanent=True)
            return
        await _fail_quietly(engine, job, f"publicare eșuată: {exc}", permanent=False)
        return

    # 4) Lease-checked completion (refuses stale workers, GHID §6.3).
    try:
        await complete(engine, job.id, job.lease_token,
                       target_revision=job.target_revision)
    except LeaseStale:
        logger.warning("completare refuzată pentru job %s (lease/revizie)", job.id)


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


async def _mark_source_error(
    engine: AsyncEngine, actor_id: uuid.UUID, source_id: uuid.UUID, detail: str
) -> None:
    async with actor_connection(engine, actor_id) as conn:
        await conn.execute(
            text(
                "UPDATE notebook_sources SET status = 'error', status_detail = :d"
                " WHERE id = :id"
            ),
            {"id": source_id, "d": detail[:2000]},
        )


async def _cancel_job(engine: AsyncEngine, job: ClaimedJob) -> None:
    async with system_connection(engine) as conn:
        await conn.execute(
            text(
                "UPDATE processing_jobs SET status = 'cancelled', completed_at = now(),"
                " lease_token = NULL WHERE id = :id AND lease_token = :t"
            ),
            {"id": job.id, "t": job.lease_token},
        )


async def _fail_quietly(
    engine: AsyncEngine, job: ClaimedJob, error: str, *, permanent: bool
) -> None:
    try:
        await fail(engine, job.id, job.lease_token, error,
                   target_revision=job.target_revision, permanent=permanent)
    except LeaseStale:
        logger.warning("eșecul jobului %s nu a putut fi înregistrat (lease)", job.id)
