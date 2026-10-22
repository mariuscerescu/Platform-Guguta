"""Worker handler for asynchronous quiz generation."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.quizzes import PROMPT_VERSION, QuizGenerator
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import ConfigurationError
from open_notebook.jobs.guguta.queue import ClaimedJob, LeaseStale, fail

logger = logging.getLogger("guguta.quizzes")


async def _status(
    engine: AsyncEngine,
    actor: uuid.UUID,
    quiz: uuid.UUID,
    status: str,
    error: str | None = None,
) -> None:
    async with actor_connection(engine, actor) as conn:
        await conn.execute(
            text("UPDATE quizzes SET status=:s,error_detail=:e WHERE id=:id"),
            {"s": status, "e": error, "id": quiz},
        )


async def _load(
    engine: AsyncEngine, actor: uuid.UUID, quiz_id: uuid.UUID, max_chars: int
):
    async with actor_connection(engine, actor) as conn:
        quiz = (
            (
                await conn.execute(
                    text(
                        "SELECT quantity,difficulty,question_types,instructions,selected_source_ids FROM quizzes WHERE id=:id"
                    ),
                    {"id": quiz_id},
                )
            )
            .mappings()
            .first()
        )
        if not quiz:
            raise ValueError("Quiz-ul nu mai există.")
        ids = [uuid.UUID(v) for v in quiz["selected_source_ids"]]
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT c.id,c.text,c.locator,ns.id source_id,ns.local_name FROM notebook_sources ns JOIN LATERAL (SELECT pa.id FROM processing_artifacts pa WHERE pa.material_version_id=ns.material_version_id AND pa.status='complete' ORDER BY pa.created_at DESC LIMIT 1) latest ON true JOIN chunks c ON c.artifact_id=latest.id WHERE ns.id=ANY(:ids) AND ns.status='ready' ORDER BY ns.position,c.position"
                    ),
                    {"ids": ids},
                )
            )
            .mappings()
            .all()
        )
    if len({r["source_id"] for r in rows}) != len(ids):
        raise ValueError("Un material selectat nu mai este gata sau nu mai există.")
    evidence: list[dict[str, str]] = []
    lookup = {}
    remaining = max_chars
    for row in rows:
        if remaining <= 0:
            break
        content = str(row["text"] or "").strip()[:remaining]
        remaining -= len(content)
        if not content:
            continue
        label = f"E{len(evidence) + 1}"
        evidence.append(
            {"id": label, "source_name": str(row["local_name"]), "text": content}
        )
        lookup[label] = {
            "source_id": str(row["source_id"]),
            "chunk_id": str(row["id"]),
            "source_name": str(row["local_name"]),
            "locator": dict(row["locator"] or {}),
        }
    if not evidence:
        raise ValueError("Materialele selectate nu conțin text procesat.")
    return quiz, evidence, lookup


async def process_quiz(engine: AsyncEngine, config: Any, job: ClaimedJob) -> None:
    if job.actor_id is None:
        await fail(
            engine,
            job.id,
            job.lease_token,
            "job quiz fără proprietar",
            target_revision=job.target_revision,
            permanent=True,
        )
        return
    try:
        await _status(engine, job.actor_id, job.target_id, "generating")
        quiz, evidence, lookup = await _load(
            engine, job.actor_id, job.target_id, config.quiz_max_source_chars
        )
        generated = await QuizGenerator(config).generate(
            quantity=quiz["quantity"],
            difficulty=quiz["difficulty"],
            question_types=quiz["question_types"],
            instructions=quiz["instructions"],
            evidence=evidence,
        )
        async with actor_connection(engine, job.actor_id) as conn:
            live = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM processing_jobs WHERE id=:j AND lease_token=:t AND status IN ('claimed','running') AND target_revision=:r AND (lease_until IS NULL OR lease_until>now())"
                    ),
                    {"j": job.id, "t": job.lease_token, "r": job.target_revision},
                )
            ).first()
            if not live:
                raise LeaseStale("lease quiz expirat înainte de publicare")
            await conn.execute(
                text("DELETE FROM quiz_questions WHERE quiz_id=:id"),
                {"id": job.target_id},
            )
            for pos, q in enumerate(generated.questions):
                refs = [lookup[v] for v in q.evidence_ids]
                await conn.execute(
                    text(
                        "INSERT INTO quiz_questions (id,quiz_id,position,question_type,prompt,hint,concepts,options,accepted_answers,reference_answer,required_concepts,optional_concepts,evidence) VALUES (:id,:quiz,:pos,:kind,:prompt,:hint,CAST(:concepts AS jsonb),CAST(:options AS jsonb),CAST(:accepted AS jsonb),:reference,CAST(:required AS jsonb),CAST(:optional AS jsonb),CAST(:evidence AS jsonb))"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "quiz": job.target_id,
                        "pos": pos,
                        "kind": q.question_type,
                        "prompt": q.prompt,
                        "hint": q.hint,
                        "concepts": json.dumps(q.concepts, ensure_ascii=False),
                        "options": json.dumps(q.options, ensure_ascii=False),
                        "accepted": json.dumps(q.accepted_answers, ensure_ascii=False),
                        "reference": q.reference_answer,
                        "required": json.dumps(q.required_concepts, ensure_ascii=False),
                        "optional": json.dumps(q.optional_concepts, ensure_ascii=False),
                        "evidence": json.dumps(refs, ensure_ascii=False),
                    },
                )
            if not (
                await conn.execute(
                    text(
                        "UPDATE quizzes SET title=:title,status='ready',model_name=:model,prompt_version=:prompt,error_detail=NULL,completed_at=now() WHERE id=:id RETURNING id"
                    ),
                    {
                        "title": generated.title,
                        "model": generated.model,
                        "prompt": PROMPT_VERSION,
                        "id": job.target_id,
                    },
                )
            ).first():
                raise LeaseStale("quiz-ul a fost șters")
            if not (
                await conn.execute(
                    text(
                        "UPDATE processing_jobs SET status='succeeded',completed_at=now(),last_error=NULL WHERE id=:j AND lease_token=:t AND status IN ('claimed','running') RETURNING id"
                    ),
                    {"j": job.id, "t": job.lease_token},
                )
            ).first():
                raise LeaseStale("jobul quiz nu a putut fi finalizat")
    except LeaseStale:
        raise
    except Exception as exc:  # noqa: BLE001 -- queue boundary records provider failures
        permanent = isinstance(exc, (ValueError, ConfigurationError))
        message = str(exc)[:2000] or "Generarea quiz-ului a eșuat."
        try:
            state = await fail(
                engine,
                job.id,
                job.lease_token,
                message,
                target_revision=job.target_revision,
                permanent=permanent,
            )
        except LeaseStale:
            logger.warning("Eșecul quiz nu a putut fi salvat: lease expirat")
            return
        await _status(
            engine,
            job.actor_id,
            job.target_id,
            "failed" if state == "failed" else "queued",
            message if state == "failed" else None,
        )
