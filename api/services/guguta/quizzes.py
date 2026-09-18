"""Quiz artifacts, secure grading and persistent attempts."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.quizzes import (
    QUESTION_TYPES,
    QuizGenerator,
    normalize_answer,
)
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.jobs.guguta.queue import enqueue, requeue


class QuizNotFound(NotFoundError):
    pass


class QuizService:
    def __init__(self, engine: AsyncEngine, config: Any) -> None:
        self._engine = engine
        self._generator = QuizGenerator(config)

    @staticmethod
    def _ser(row: Any) -> dict[str, Any]:
        value = dict(row)
        for key in ("id", "notebook_id", "quiz_id", "user_id", "created_by", "job_id"):
            if value.get(key) is not None:
                value[key] = str(value[key])
        return value

    async def create(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        *,
        source_ids: list[uuid.UUID],
        quantity: str,
        difficulty: str,
        question_types: list[str],
        instructions: str | None,
    ) -> dict[str, Any]:
        if quantity not in ("fewer", "standard", "more") or difficulty not in (
            "easy",
            "medium",
            "hard",
        ):
            raise InvalidInputError("Configurația quiz-ului nu este validă.")
        types = list(dict.fromkeys(question_types))
        if not types or any(v not in QUESTION_TYPES for v in types):
            raise InvalidInputError("Selectează cel puțin un tip valid de întrebare.")
        ids = list(dict.fromkeys(source_ids))
        if not ids:
            raise InvalidInputError("Selectează cel puțin un material gata.")
        quiz_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            if not (
                await conn.execute(
                    text(
                        "SELECT 1 FROM digital_notebooks WHERE id=:n AND status='active'"
                    ),
                    {"n": notebook_id},
                )
            ).first():
                raise QuizNotFound()
            sources = (
                await conn.execute(
                    text(
                        "SELECT id,status FROM notebook_sources WHERE notebook_id=:n AND id=ANY(:ids)"
                    ),
                    {"n": notebook_id, "ids": ids},
                )
            ).all()
            if len(sources) != len(ids) or any(r.status != "ready" for r in sources):
                raise InvalidInputError(
                    "Toate materialele selectate trebuie să fie gata și să aparțină carnetului."
                )
            await conn.execute(
                text(
                    "INSERT INTO quizzes (id,notebook_id,created_by,quantity,difficulty,question_types,instructions,selected_source_ids,status) VALUES (:id,:n,:u,:q,:d,CAST(:types AS jsonb),:i,CAST(:sources AS jsonb),'queued')"
                ),
                {
                    "id": quiz_id,
                    "n": notebook_id,
                    "u": actor.actor_id,
                    "q": quantity,
                    "d": difficulty,
                    "types": json.dumps(types),
                    "i": (instructions or "").strip() or None,
                    "sources": json.dumps([str(v) for v in ids]),
                },
            )
            job = await enqueue(
                self._engine,
                conn,
                job_type="generate_quiz",
                target_type="quiz",
                target_id=quiz_id,
                actor_id=actor.actor_id,
                max_attempts=2,
                deadline_seconds=1800,
            )
        return {
            "id": str(quiz_id),
            "notebook_id": str(notebook_id),
            "status": "queued",
            "question_count": 0,
            "job_id": str(job),
        }

    async def list(
        self, actor: ActorContext, notebook_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT q.id,q.notebook_id,q.quantity,q.difficulty,q.question_types,q.instructions,q.selected_source_ids,q.status,q.title,q.error_detail,q.created_at,q.updated_at,q.completed_at,(SELECT count(*) FROM quiz_questions x WHERE x.quiz_id=q.id) question_count,(SELECT pj.id FROM processing_jobs pj WHERE pj.target_type='quiz' AND pj.target_id=q.id ORDER BY pj.created_at DESC LIMIT 1) job_id FROM quizzes q WHERE q.notebook_id=:n ORDER BY q.created_at DESC"
                        ),
                        {"n": notebook_id},
                    )
                )
                .mappings()
                .all()
            )
        return [self._ser(r) for r in rows]

    def _public_question(self, row: Any) -> dict[str, Any]:
        q = self._ser(row)
        q["options"] = [{"id": v["id"], "text": v["text"]} for v in q["options"]]
        q.pop("accepted_answers", None)
        q.pop("reference_answer", None)
        q.pop("required_concepts", None)
        q.pop("optional_concepts", None)
        return q

    async def get(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            quiz = (
                (
                    await conn.execute(
                        text(
                            "SELECT id,notebook_id,quantity,difficulty,question_types,instructions,selected_source_ids,status,title,error_detail,created_at,updated_at,completed_at FROM quizzes WHERE id=:id AND notebook_id=:n"
                        ),
                        {"id": quiz_id, "n": notebook_id},
                    )
                )
                .mappings()
                .first()
            )
            if not quiz:
                raise QuizNotFound()
            questions = (
                (
                    await conn.execute(
                        text(
                            "SELECT id,quiz_id,position,question_type,prompt,hint,concepts,options,accepted_answers,reference_answer,required_concepts,optional_concepts,version FROM quiz_questions WHERE quiz_id=:id ORDER BY position"
                        ),
                        {"id": quiz_id},
                    )
                )
                .mappings()
                .all()
            )
            attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT id,quiz_id,user_id,current_index,question_order,answers,started_at,updated_at,completed_at FROM quiz_attempts WHERE quiz_id=:id AND user_id=:u AND completed_at IS NULL ORDER BY updated_at DESC LIMIT 1"
                        ),
                        {"id": quiz_id, "u": actor.actor_id},
                    )
                )
                .mappings()
                .first()
            )
        value = self._ser(quiz)
        value["questions"] = [self._public_question(q) for q in questions]
        value["active_attempt"] = self._ser(attempt) if attempt else None
        return value

    async def delete(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "UPDATE processing_jobs SET status='cancelled',completed_at=now(),lease_until=NULL WHERE target_type='quiz' AND target_id=:id AND status IN ('queued','claimed','running')"
                ),
                {"id": quiz_id},
            )
            result = await conn.execute(
                text("DELETE FROM quizzes WHERE id=:id AND notebook_id=:n"),
                {"id": quiz_id, "n": notebook_id},
            )
        return bool(result.rowcount)

    async def retry(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT q.status,j.id FROM quizzes q JOIN processing_jobs j ON j.target_type='quiz' AND j.target_id=q.id WHERE q.id=:id AND q.notebook_id=:n ORDER BY j.created_at DESC LIMIT 1"
                    ),
                    {"id": quiz_id, "n": notebook_id},
                )
            ).first()
        if not row:
            raise QuizNotFound()
        if row.status != "failed":
            raise InvalidInputError("Poate fi reluat numai un quiz eșuat.")
        ok = await requeue(self._engine, row.id, actor.actor_id)
        if ok:
            async with actor_connection(self._engine, actor.actor_id) as conn:
                await conn.execute(
                    text(
                        "UPDATE quizzes SET status='queued',error_detail=NULL WHERE id=:id"
                    ),
                    {"id": quiz_id},
                )
        return ok

    async def create_attempt(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            quiz = (
                await conn.execute(
                    text("SELECT status FROM quizzes WHERE id=:id AND notebook_id=:n"),
                    {"id": quiz_id, "n": notebook_id},
                )
            ).first()
            if not quiz:
                raise QuizNotFound()
            if quiz.status != "ready":
                raise InvalidInputError("Quiz-ul nu este încă gata.")
            order = [
                str(r.id)
                for r in (
                    await conn.execute(
                        text(
                            "SELECT id FROM quiz_questions WHERE quiz_id=:id ORDER BY position"
                        ),
                        {"id": quiz_id},
                    )
                ).all()
            ]
            if not order:
                raise InvalidInputError("Quiz-ul nu conține întrebări.")
            attempt = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO quiz_attempts (id,quiz_id,user_id,question_order,answers) VALUES (:id,:q,:u,CAST(:o AS jsonb),'{}'::jsonb)"
                ),
                {
                    "id": attempt,
                    "q": quiz_id,
                    "u": actor.actor_id,
                    "o": json.dumps(order),
                },
            )
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM quiz_attempts WHERE id=:id"),
                        {"id": attempt},
                    )
                )
                .mappings()
                .one()
            )
        return self._ser(row)

    async def answer(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        question_id: uuid.UUID,
        response: str | list[str],
        hint_used: bool,
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            attempt = (
                (
                    await conn.execute(
                        text(
                            "SELECT * FROM quiz_attempts WHERE id=:a AND quiz_id=:q AND user_id=:u AND completed_at IS NULL"
                        ),
                        {"a": attempt_id, "q": quiz_id, "u": actor.actor_id},
                    )
                )
                .mappings()
                .first()
            )
            question = (
                (
                    await conn.execute(
                        text(
                            "SELECT x.* FROM quiz_questions x JOIN quizzes q ON q.id=x.quiz_id WHERE x.id=:x AND x.quiz_id=:q AND q.notebook_id=:n"
                        ),
                        {"x": question_id, "q": quiz_id, "n": notebook_id},
                    )
                )
                .mappings()
                .first()
            )
            if not attempt or not question:
                raise QuizNotFound()
        kind = question["question_type"]
        feedback = ""
        correct_answer: Any = None
        if kind in ("multiple_choice", "multiple_select"):
            selected = {response} if isinstance(response, str) else set(response)
            correct = {str(o["id"]) for o in question["options"] if o["is_correct"]}
            status = "correct" if selected == correct else "incorrect"
            correct_answer = sorted(correct)
            feedback = " ".join(
                str(o["rationale"])
                for o in question["options"]
                if str(o["id"]) in selected | correct
            )
        elif kind == "fill_in_blank":
            raw = response if isinstance(response, str) else " ".join(response)
            accepted = {normalize_answer(v) for v in question["accepted_answers"]}
            status = "correct" if normalize_answer(raw) in accepted else "incorrect"
            correct_answer = list(question["accepted_answers"])
            feedback = (
                "Răspuns acceptat."
                if status == "correct"
                else f"Răspunsul așteptat este: {question['reference_answer']}"
            )
        else:
            raw = response if isinstance(response, str) else " ".join(response)
            refs = list(question["evidence"] or [])
            chunk_ids = [uuid.UUID(v["chunk_id"]) for v in refs]
            async with actor_connection(self._engine, actor.actor_id) as conn:
                chunks = (
                    (
                        await conn.execute(
                            text("SELECT id,text FROM chunks WHERE id=ANY(:ids)"),
                            {"ids": chunk_ids},
                        )
                    )
                    .mappings()
                    .all()
                )
            by_id = {str(v["id"]): str(v["text"]) for v in chunks}
            evidence = [{**v, "text": by_id.get(v["chunk_id"], "")} for v in refs]
            grade = await self._generator.grade_short(
                prompt=question["prompt"],
                response=raw,
                reference_answer=question["reference_answer"],
                required_concepts=question["required_concepts"],
                evidence=evidence,
            )
            status = grade["status"]
            feedback = grade["feedback"]
            correct_answer = question["reference_answer"]
        snapshot = {
            "response": response,
            "status": status,
            "feedback": feedback,
            "correct_answer": correct_answer,
            "hint_used": hint_used,
            "answered_at": datetime.now(timezone.utc).isoformat(),
            "question_version": question["version"],
            "prompt": question["prompt"],
            "concepts": question["concepts"],
        }
        answers = dict(attempt["answers"] or {})
        answers[str(question_id)] = snapshot
        done = len(answers) >= len(attempt["question_order"])
        idx = min(
            len(attempt["question_order"]) - 1,
            max(
                attempt["current_index"],
                attempt["question_order"].index(str(question_id)),
            ),
        )
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "UPDATE quiz_attempts SET answers=CAST(:answers AS jsonb),current_index=:idx,completed_at=CASE WHEN :done THEN now() ELSE NULL END WHERE id=:id AND user_id=:u RETURNING *"
                        ),
                        {
                            "answers": json.dumps(answers, ensure_ascii=False),
                            "idx": idx,
                            "done": done,
                            "id": attempt_id,
                            "u": actor.actor_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return {"attempt": self._ser(row), "result": snapshot}

    async def results(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        attempt_id: uuid.UUID,
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT a.* FROM quiz_attempts a JOIN quizzes q ON q.id=a.quiz_id WHERE a.id=:a AND q.id=:q AND q.notebook_id=:n AND a.user_id=:u"
                        ),
                        {
                            "a": attempt_id,
                            "q": quiz_id,
                            "n": notebook_id,
                            "u": actor.actor_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if not row:
            raise QuizNotFound()
        answers = row["answers"] or {}
        correct = sum(v["status"] == "correct" for v in answers.values())
        partial = sum(v["status"] == "partial" for v in answers.values())
        total = len(row["question_order"])
        concepts: dict[str, dict[str, int]] = {}
        for ans in answers.values():
            for concept in ans.get("concepts", []):
                stat = concepts.setdefault(concept, {"correct": 0, "total": 0})
                stat["total"] += 1
                stat["correct"] += ans["status"] == "correct"
        return {
            "correct": correct,
            "partial": partial,
            "incorrect": len(answers) - correct - partial,
            "total": total,
            "score": round((correct + partial * 0.5) / total, 4) if total else 0,
            "concept_performance": [{"concept": k, **v} for k, v in concepts.items()],
            "attempt": self._ser(row),
        }

    async def explain(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        question_id: uuid.UUID,
        response: Any,
    ) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            q = (
                (
                    await conn.execute(
                        text(
                            "SELECT x.prompt,x.reference_answer,x.options,x.evidence FROM quiz_questions x JOIN quizzes z ON z.id=x.quiz_id WHERE x.id=:x AND z.id=:q AND z.notebook_id=:n"
                        ),
                        {"x": question_id, "q": quiz_id, "n": notebook_id},
                    )
                )
                .mappings()
                .first()
            )
            if not q:
                raise QuizNotFound()
            refs = list(q["evidence"] or [])
            ids = [uuid.UUID(v["chunk_id"]) for v in refs]
            chunks = (
                (
                    await conn.execute(
                        text("SELECT id,text FROM chunks WHERE id=ANY(:ids)"),
                        {"ids": ids},
                    )
                )
                .mappings()
                .all()
            )
        reference = q["reference_answer"] or "; ".join(
            o["text"] for o in q["options"] if o["is_correct"]
        )
        by = {str(v["id"]): str(v["text"]) for v in chunks}
        evidence = [{**v, "text": by.get(v["chunk_id"], "")} for v in refs]
        return {
            "explanation": await self._generator.explain(
                question=q["prompt"],
                response=response,
                reference_answer=reference,
                evidence=evidence,
            ),
            "evidence": refs,
        }

    @staticmethod
    def _validate_manual_question(data: dict[str, Any]) -> None:
        kind = data.get("question_type")
        options = data.get("options") or []
        if kind not in QUESTION_TYPES or not str(data.get("prompt") or "").strip():
            raise InvalidInputError("Întrebarea nu este validă.")
        correct = sum(bool(option.get("is_correct")) for option in options)
        if kind == "multiple_choice" and (len(options) < 2 or correct != 1):
            raise InvalidInputError(
                "Alegerea unică trebuie să aibă exact un răspuns corect."
            )
        if kind == "multiple_select" and (len(options) < 2 or correct < 1):
            raise InvalidInputError(
                "Alegerea multiplă trebuie să aibă cel puțin două răspunsuri corecte."
            )
        if kind == "fill_in_blank" and not data.get("accepted_answers"):
            raise InvalidInputError("Adaugă cel puțin un răspuns acceptat.")
        if (
            kind == "short_answer"
            and not str(data.get("reference_answer") or "").strip()
        ):
            raise InvalidInputError("Adaugă răspunsul de referință.")

    async def add_question(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        *,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_manual_question(data)
        async with actor_connection(self._engine, actor.actor_id) as conn:
            quiz = (
                await conn.execute(
                    text("SELECT 1 FROM quizzes WHERE id=:q AND notebook_id=:n"),
                    {"q": quiz_id, "n": notebook_id},
                )
            ).first()
            if not quiz:
                raise QuizNotFound()
            position = int(
                (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(max(position),-1)+1 FROM quiz_questions WHERE quiz_id=:q"
                        ),
                        {"q": quiz_id},
                    )
                ).scalar_one()
            )
            question_id = uuid.uuid4()
            row = (
                (
                    await conn.execute(
                        text(
                            "INSERT INTO quiz_questions (id,quiz_id,position,question_type,prompt,hint,concepts,options,accepted_answers,reference_answer,required_concepts,optional_concepts,evidence) VALUES (:id,:q,:p,:kind,:prompt,:hint,CAST(:concepts AS jsonb),CAST(:options AS jsonb),CAST(:accepted AS jsonb),:reference,CAST(:required AS jsonb),CAST(:optional AS jsonb),'[]'::jsonb) RETURNING *"
                        ),
                        {
                            "id": question_id,
                            "q": quiz_id,
                            "p": position,
                            "kind": data["question_type"],
                            "prompt": data["prompt"].strip(),
                            "hint": str(data.get("hint") or "").strip(),
                            "concepts": json.dumps(data.get("concepts") or []),
                            "options": json.dumps(
                                data.get("options") or [], ensure_ascii=False
                            ),
                            "accepted": json.dumps(
                                data.get("accepted_answers") or [], ensure_ascii=False
                            ),
                            "reference": str(
                                data.get("reference_answer") or ""
                            ).strip(),
                            "required": json.dumps(data.get("required_concepts") or []),
                            "optional": json.dumps(data.get("optional_concepts") or []),
                        },
                    )
                )
                .mappings()
                .one()
            )
        return self._public_question(row)

    async def update_question(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        question_id: uuid.UUID,
        *,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        self._validate_manual_question(data)
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "UPDATE quiz_questions x SET question_type=:kind,prompt=:prompt,hint=:hint,concepts=CAST(:concepts AS jsonb),options=CAST(:options AS jsonb),accepted_answers=CAST(:accepted AS jsonb),reference_answer=:reference,required_concepts=CAST(:required AS jsonb),optional_concepts=CAST(:optional AS jsonb),version=version+1 FROM quizzes q WHERE x.id=:id AND x.quiz_id=:quiz AND q.id=x.quiz_id AND q.notebook_id=:n RETURNING x.*"
                        ),
                        {
                            "kind": data["question_type"],
                            "prompt": data["prompt"].strip(),
                            "hint": str(data.get("hint") or "").strip(),
                            "concepts": json.dumps(data.get("concepts") or []),
                            "options": json.dumps(
                                data.get("options") or [], ensure_ascii=False
                            ),
                            "accepted": json.dumps(
                                data.get("accepted_answers") or [], ensure_ascii=False
                            ),
                            "reference": str(
                                data.get("reference_answer") or ""
                            ).strip(),
                            "required": json.dumps(data.get("required_concepts") or []),
                            "optional": json.dumps(data.get("optional_concepts") or []),
                            "id": question_id,
                            "quiz": quiz_id,
                            "n": notebook_id,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if not row:
            raise QuizNotFound()
        return self._public_question(row)

    async def delete_question(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        question_id: uuid.UUID,
    ) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(
                text(
                    "DELETE FROM quiz_questions x USING quizzes q WHERE x.id=:id AND x.quiz_id=:quiz AND q.id=x.quiz_id AND q.notebook_id=:n"
                ),
                {"id": question_id, "quiz": quiz_id, "n": notebook_id},
            )
        return bool(result.rowcount)
