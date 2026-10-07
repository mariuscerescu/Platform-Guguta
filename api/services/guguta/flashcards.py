"""Flashcard decks: authorization, persistence and study progress."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.ai.guguta.flashcards import FlashcardGenerator
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.jobs.guguta.queue import enqueue, requeue


class FlashcardDeckNotFound(NotFoundError):
    pass


class FlashcardService:
    def __init__(self, engine: AsyncEngine, config: Any) -> None:
        self._engine = engine
        self._generator = FlashcardGenerator(config)

    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        value = dict(row)
        for key in ("id", "notebook_id", "deck_id", "user_id", "job_id"):
            if value.get(key) is not None:
                value[key] = str(value[key])
        return value

    async def create(
        self, actor: ActorContext, notebook_id: uuid.UUID, *, source_ids: list[uuid.UUID],
        quantity: str, difficulty: str, instructions: str | None,
    ) -> dict[str, Any]:
        if quantity not in ("fewer", "standard", "more"):
            raise InvalidInputError("Numărul de cartonașe nu este acceptat.")
        if difficulty not in ("easy", "medium", "hard"):
            raise InvalidInputError("Nivelul de dificultate nu este acceptat.")
        unique_ids = list(dict.fromkeys(source_ids))
        if not unique_ids:
            raise InvalidInputError("Selectează cel puțin un material gata.")
        deck_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            notebook = (await conn.execute(
                text("SELECT id FROM digital_notebooks WHERE id=:n AND status='active'"),
                {"n": notebook_id},
            )).first()
            if notebook is None:
                raise FlashcardDeckNotFound()
            rows = (await conn.execute(
                text("SELECT id,status FROM notebook_sources WHERE notebook_id=:n AND chat_session_id IS NULL AND id=ANY(:ids)"),
                {"n": notebook_id, "ids": unique_ids},
            )).all()
            if len(rows) != len(unique_ids):
                raise InvalidInputError("Un material selectat nu aparține carnetului.")
            if any(row.status != "ready" for row in rows):
                raise InvalidInputError("Toate materialele selectate trebuie să fie gata.")
            await conn.execute(text(
                "INSERT INTO flashcard_decks "
                "(id,notebook_id,created_by,quantity,difficulty,instructions,selected_source_ids,language,status) "
                "VALUES (:id,:n,:actor,:q,:d,:i,CAST(:sources AS jsonb),'ro','queued')"
            ), {"id": deck_id, "n": notebook_id, "actor": actor.actor_id, "q": quantity,
                "d": difficulty, "i": (instructions or "").strip() or None,
                "sources": json.dumps([str(v) for v in unique_ids])})
            job_id = await enqueue(
                self._engine, conn, job_type="generate_flashcards", target_type="flashcard_deck",
                target_id=deck_id, actor_id=actor.actor_id, max_attempts=2, deadline_seconds=1800,
            )
            row = (await conn.execute(text(
                "SELECT id,notebook_id,quantity,difficulty,instructions,selected_source_ids,status,"
                "title,error_detail,created_at,updated_at,completed_at FROM flashcard_decks WHERE id=:id"
            ), {"id": deck_id})).mappings().one()
        result = self._serialize(row)
        result["job_id"] = str(job_id)
        result["card_count"] = 0
        return result

    async def list_for_notebook(self, actor: ActorContext, notebook_id: uuid.UUID) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            rows = (await conn.execute(text(
                "SELECT d.id,d.notebook_id,d.quantity,d.difficulty,d.instructions,d.selected_source_ids,"
                "d.status,d.title,d.error_detail,d.created_at,d.updated_at,d.completed_at,"
                "(SELECT count(*) FROM flashcards c WHERE c.deck_id=d.id) AS card_count,"
                "(SELECT pj.id FROM processing_jobs pj WHERE pj.target_type='flashcard_deck' "
                " AND pj.target_id=d.id ORDER BY pj.created_at DESC LIMIT 1) AS job_id "
                "FROM flashcard_decks d WHERE d.notebook_id=:n ORDER BY d.created_at DESC"
            ), {"n": notebook_id})).mappings().all()
        return [self._serialize(row) for row in rows]

    async def get(self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            deck = (await conn.execute(text(
                "SELECT id,notebook_id,quantity,difficulty,instructions,selected_source_ids,status,title,"
                "error_detail,created_at,updated_at,completed_at FROM flashcard_decks "
                "WHERE id=:id AND notebook_id=:n"
            ), {"id": deck_id, "n": notebook_id})).mappings().first()
            if deck is None:
                raise FlashcardDeckNotFound()
            cards = (await conn.execute(text(
                "SELECT id,deck_id,position,front,back,concept,evidence FROM flashcards "
                "WHERE deck_id=:id ORDER BY position"
            ), {"id": deck_id})).mappings().all()
            session = (await conn.execute(text(
                "SELECT id,deck_id,user_id,mode,card_order,current_index,results,started_at,updated_at,completed_at "
                "FROM flashcard_sessions WHERE deck_id=:id AND user_id=:u AND completed_at IS NULL "
                "ORDER BY updated_at DESC LIMIT 1"
            ), {"id": deck_id, "u": actor.actor_id})).mappings().first()
        value = self._serialize(deck)
        value["cards"] = [self._serialize(card) for card in cards]
        value["active_session"] = self._serialize(session) if session else None
        return value

    async def delete(self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(text(
                "UPDATE processing_jobs SET status='cancelled',completed_at=now(),lease_until=NULL "
                "WHERE target_type='flashcard_deck' AND target_id=:id AND status IN ('queued','claimed','running')"
            ), {"id": deck_id})
            result = await conn.execute(text(
                "DELETE FROM flashcard_decks WHERE id=:id AND notebook_id=:n"
            ), {"id": deck_id, "n": notebook_id})
        return bool(result.rowcount)

    async def retry(
        self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID
    ) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT d.status,j.id FROM flashcard_decks d JOIN processing_jobs j "
                        "ON j.target_type='flashcard_deck' AND j.target_id=d.id "
                        "WHERE d.id=:id AND d.notebook_id=:n "
                        "ORDER BY j.created_at DESC LIMIT 1"
                    ),
                    {"id": deck_id, "n": notebook_id},
                )
            ).first()
        if row is None:
            raise FlashcardDeckNotFound()
        if row.status != "failed":
            raise InvalidInputError("Poate fi reluat numai un set eșuat.")
        ok = await requeue(self._engine, row.id, actor.actor_id)
        if ok:
            async with actor_connection(self._engine, actor.actor_id) as conn:
                await conn.execute(
                    text(
                        "UPDATE flashcard_decks SET status='queued',error_detail=NULL "
                        "WHERE id=:id"
                    ),
                    {"id": deck_id},
                )
        return ok

    async def delete_card(self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID, card_id: uuid.UUID) -> bool:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            result = await conn.execute(text(
                "DELETE FROM flashcards c USING flashcard_decks d WHERE c.id=:card AND c.deck_id=:deck "
                "AND d.id=c.deck_id AND d.notebook_id=:n"
            ), {"card": card_id, "deck": deck_id, "n": notebook_id})
        return bool(result.rowcount)

    async def create_session(self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID, *, mode: str) -> dict[str, Any]:
        if mode not in ("all", "same", "missed"):
            raise InvalidInputError("Modul de studiu nu este acceptat.")
        async with actor_connection(self._engine, actor.actor_id) as conn:
            deck = (await conn.execute(text(
                "SELECT id,status FROM flashcard_decks WHERE id=:id AND notebook_id=:n"
            ), {"id": deck_id, "n": notebook_id})).first()
            if deck is None:
                raise FlashcardDeckNotFound()
            if deck.status != "ready":
                raise InvalidInputError("Setul de flashcards nu este încă gata.")
            all_ids = [str(row.id) for row in (await conn.execute(text(
                "SELECT id FROM flashcards WHERE deck_id=:id ORDER BY position"
            ), {"id": deck_id})).all()]
            if mode == "all":
                order = all_ids
            else:
                prior = (await conn.execute(text(
                    "SELECT card_order,results FROM flashcard_sessions WHERE deck_id=:id AND user_id=:u "
                    "ORDER BY updated_at DESC LIMIT 1"
                ), {"id": deck_id, "u": actor.actor_id})).mappings().first()
                if prior is None:
                    order = all_ids
                elif mode == "same":
                    order = [value for value in prior["card_order"] if value in all_ids]
                else:
                    order = [value for value in prior["card_order"] if value in all_ids and prior["results"].get(value) == "missed"]
            if not order:
                raise InvalidInputError("Nu există cartonașe pentru această sesiune.")
            session_id = uuid.uuid4()
            await conn.execute(text(
                "INSERT INTO flashcard_sessions (id,deck_id,user_id,mode,card_order,current_index,results) "
                "VALUES (:id,:deck,:u,:mode,CAST(:order AS jsonb),0,'{}'::jsonb)"
            ), {"id": session_id, "deck": deck_id, "u": actor.actor_id, "mode": mode,
                "order": json.dumps(order)})
            row = (await conn.execute(text(
                "SELECT id,deck_id,user_id,mode,card_order,current_index,results,started_at,updated_at,completed_at "
                "FROM flashcard_sessions WHERE id=:id"
            ), {"id": session_id})).mappings().one()
        return self._serialize(row)

    async def update_session(self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID,
                             session_id: uuid.UUID, *, current_index: int, results: dict[str, str],
                             card_order: list[str] | None = None, completed: bool = False) -> dict[str, Any]:
        if current_index < 0 or any(v not in ("got_it", "missed") for v in results.values()):
            raise InvalidInputError("Progresul sesiunii nu este valid.")
        async with actor_connection(self._engine, actor.actor_id) as conn:
            allowed = {str(row.id) for row in (await conn.execute(text(
                "SELECT c.id FROM flashcards c JOIN flashcard_decks d ON d.id=c.deck_id "
                "WHERE d.id=:deck AND d.notebook_id=:n"
            ), {"deck": deck_id, "n": notebook_id})).all()}
            if not allowed:
                raise FlashcardDeckNotFound()
            if any(key not in allowed for key in results) or (card_order and any(v not in allowed for v in card_order)):
                raise InvalidInputError("Sesiunea conține cartonașe necunoscute.")
            row = (await conn.execute(text(
                "UPDATE flashcard_sessions SET current_index=:idx, results=CAST(:results AS jsonb), "
                "card_order=COALESCE(CAST(:card_order AS jsonb),card_order), "
                "completed_at=CASE WHEN :done THEN now() ELSE completed_at END "
                "WHERE id=:id AND deck_id=:deck AND user_id=:u RETURNING "
                "id,deck_id,user_id,mode,card_order,current_index,results,started_at,updated_at,completed_at"
            ), {"idx": current_index, "results": json.dumps(results),
                "card_order": json.dumps(card_order) if card_order else None, "done": completed,
                "id": session_id, "deck": deck_id, "u": actor.actor_id})).mappings().first()
        if row is None:
            raise FlashcardDeckNotFound()
        return self._serialize(row)

    async def csv_export(self, actor: ActorContext, notebook_id: uuid.UUID, deck_id: uuid.UUID) -> tuple[bytes, str]:
        deck = await self.get(actor, notebook_id, deck_id)
        target = io.StringIO()
        writer = csv.writer(target)
        writer.writerow(["front", "back", "concept", "sources"])
        for card in deck["cards"]:
            names = "; ".join(ref.get("source_name", "") for ref in card["evidence"])
            writer.writerow([card["front"], card["back"], card.get("concept") or "", names])
        filename = (deck.get("title") or "flashcards").replace('"', "") + ".csv"
        return target.getvalue().encode("utf-8-sig"), filename

    async def explain(self, actor: ActorContext, notebook_id: uuid.UUID,
                      deck_id: uuid.UUID, card_id: uuid.UUID) -> dict[str, Any]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (await conn.execute(text(
                "SELECT c.front,c.back,c.evidence FROM flashcards c "
                "JOIN flashcard_decks d ON d.id=c.deck_id "
                "WHERE c.id=:card AND d.id=:deck AND d.notebook_id=:n"
            ), {"card": card_id, "deck": deck_id, "n": notebook_id})).mappings().first()
            if row is None:
                raise FlashcardDeckNotFound()
            refs = list(row["evidence"] or [])
            chunk_ids = [uuid.UUID(ref["chunk_id"]) for ref in refs]
            chunks = (await conn.execute(text(
                "SELECT id,text FROM chunks WHERE id=ANY(:ids)"
            ), {"ids": chunk_ids})).mappings().all()
        text_by_id = {str(item["id"]): str(item["text"]) for item in chunks}
        evidence = [{**ref, "text": text_by_id.get(ref["chunk_id"], "")} for ref in refs]
        explanation = await self._generator.explain(
            front=str(row["front"]), back=str(row["back"]), evidence=evidence
        )
        return {"explanation": explanation, "evidence": refs}
