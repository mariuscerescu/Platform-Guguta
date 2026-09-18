"""Worker handler for asynchronous flashcard generation."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.flashcards import PROMPT_VERSION, FlashcardGenerator
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import ConfigurationError
from open_notebook.jobs.guguta.queue import ClaimedJob, LeaseStale, fail

logger = logging.getLogger("guguta.flashcards")


async def _set_status(engine: AsyncEngine, actor_id: uuid.UUID, deck_id: uuid.UUID,
                      status: str, error: str | None = None) -> None:
    async with actor_connection(engine, actor_id) as conn:
        await conn.execute(text(
            "UPDATE flashcard_decks SET status=:status,error_detail=:error WHERE id=:id"
        ), {"status": status, "error": error, "id": deck_id})


async def _load_input(engine: AsyncEngine, actor_id: uuid.UUID, deck_id: uuid.UUID,
                      max_chars: int) -> tuple[str, str, str | None, list[dict[str, str]], dict[str, dict[str, Any]]]:
    async with actor_connection(engine, actor_id) as conn:
        deck = (await conn.execute(text(
            "SELECT quantity,difficulty,instructions,selected_source_ids FROM flashcard_decks WHERE id=:id"
        ), {"id": deck_id})).mappings().first()
        if deck is None:
            raise ValueError("Setul de flashcards nu mai există.")
        source_ids = [uuid.UUID(value) for value in deck["selected_source_ids"]]
        rows = (await conn.execute(text(
            "SELECT c.id,c.text,c.locator,ns.id AS source_id,ns.local_name "
            "FROM notebook_sources ns JOIN LATERAL (SELECT pa.id FROM processing_artifacts pa "
            "WHERE pa.material_version_id=ns.material_version_id AND pa.status='complete' "
            "ORDER BY pa.created_at DESC LIMIT 1) latest ON true "
            "JOIN chunks c ON c.artifact_id=latest.id "
            "WHERE ns.id=ANY(:ids) AND ns.status='ready' ORDER BY ns.position,c.position"
        ), {"ids": source_ids})).mappings().all()
    found_sources = {row["source_id"] for row in rows}
    if len(found_sources) != len(source_ids):
        raise ValueError("Un material selectat nu mai este gata sau nu mai există.")
    remaining = max_chars
    evidence: list[dict[str, str]] = []
    lookup: dict[str, dict[str, Any]] = {}
    for row in rows:
        if remaining <= 0:
            break
        content = str(row["text"] or "").strip()[:remaining]
        remaining -= len(content)
        if not content:
            continue
        evidence_id = str(row["id"])
        evidence.append({"id": evidence_id, "source_name": str(row["local_name"]), "text": content})
        lookup[evidence_id] = {
            "source_id": str(row["source_id"]), "chunk_id": evidence_id,
            "source_name": str(row["local_name"]), "locator": dict(row["locator"] or {}),
        }
    if not evidence:
        raise ValueError("Materialele selectate nu conțin text procesat.")
    return str(deck["quantity"]), str(deck["difficulty"]), deck["instructions"], evidence, lookup


async def process_flashcard_deck(engine: AsyncEngine, config: Any, job: ClaimedJob) -> None:
    if job.actor_id is None:
        await fail(engine, job.id, job.lease_token, "job flashcards fără proprietar",
                   target_revision=job.target_revision, permanent=True)
        return
    try:
        await _set_status(engine, job.actor_id, job.target_id, "generating")
        quantity, difficulty, instructions, evidence, lookup = await _load_input(
            engine, job.actor_id, job.target_id, config.flashcard_max_source_chars
        )
        generated = await FlashcardGenerator(config).generate(
            quantity=quantity, difficulty=difficulty, instructions=instructions, evidence=evidence
        )
        async with actor_connection(engine, job.actor_id) as conn:
            live = (await conn.execute(text(
                "SELECT 1 FROM processing_jobs WHERE id=:job AND lease_token=:token "
                "AND status IN ('claimed','running') AND target_revision=:revision "
                "AND (lease_until IS NULL OR lease_until>now())"
            ), {"job": job.id, "token": job.lease_token, "revision": job.target_revision})).first()
            if live is None:
                raise LeaseStale("lease flashcards expirat înainte de publicare")
            await conn.execute(text("DELETE FROM flashcards WHERE deck_id=:id"), {"id": job.target_id})
            for position, card in enumerate(generated.cards):
                refs = [lookup[value] for value in card.evidence_ids]
                await conn.execute(text(
                    "INSERT INTO flashcards (id,deck_id,position,front,back,concept,evidence) "
                    "VALUES (:id,:deck,:pos,:front,:back,:concept,CAST(:evidence AS jsonb))"
                ), {"id": uuid.uuid4(), "deck": job.target_id, "pos": position,
                    "front": card.front, "back": card.back, "concept": card.concept or None,
                    "evidence": json.dumps(refs, ensure_ascii=False)})
            published = await conn.execute(text(
                "UPDATE flashcard_decks SET title=:title,status='ready',model_name=:model,"
                "prompt_version=:prompt,error_detail=NULL,completed_at=now() WHERE id=:id RETURNING id"
            ), {"title": generated.title, "model": generated.model, "prompt": PROMPT_VERSION,
                "id": job.target_id})
            if published.first() is None:
                raise LeaseStale("setul de flashcards a fost șters")
            completed = await conn.execute(text(
                "UPDATE processing_jobs SET status='succeeded',completed_at=now(),last_error=NULL "
                "WHERE id=:job AND lease_token=:token AND status IN ('claimed','running') RETURNING id"
            ), {"job": job.id, "token": job.lease_token})
            if completed.first() is None:
                raise LeaseStale("jobul flashcards nu a putut fi finalizat")
    except LeaseStale:
        raise
    except Exception as exc:  # noqa: BLE001 -- queue boundary records provider failures
        permanent = isinstance(exc, (ValueError, ConfigurationError))
        message = str(exc)[:2000] or "Generarea flashcards a eșuat."
        try:
            status = await fail(engine, job.id, job.lease_token, message,
                                target_revision=job.target_revision, permanent=permanent)
        except LeaseStale:
            logger.warning("Eșecul flashcards nu a putut fi salvat: lease expirat")
            return
        await _set_status(engine, job.actor_id, job.target_id,
                          "failed" if status == "failed" else "queued",
                          message if status == "failed" else None)
