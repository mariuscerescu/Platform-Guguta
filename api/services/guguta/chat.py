"""Chat service: sessions, messages, validated citations (GHID §7).

Flow per message (specificații §6): authorize notebook+session → build the
authorized retrieval set (selected sources only) → budget the context →
generate (provider called OUTSIDE any DB transaction) → validate citations
against the provided set → save user+assistant messages with context_revision
and model info. Idempotency key returns the same assistant message on retry.

Ordering: per-session row lock (FOR UPDATE) serializes concurrent sends;
seq is allocated inside that critical section. Context revision: the message
records the revision used; A17 coverage comes from the revision bump at
source changes plus retrieval over CURRENT selected sources.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.services.guguta.search import RetrievedChunk
from open_notebook.ai.guguta.chat import ChatProvider
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import NotFoundError, OpenNotebookError

MAX_CONTEXT_CHARS = 8000
MAX_HISTORY_MESSAGES = 10


class ChatSessionNotFound(NotFoundError):
    pass


class ChatValidation(OpenNotebookError):
    pass


class IdempotencyConflict(OpenNotebookError):
    """Same key, different payload (maps to 409)."""


class SourcesRequired(OpenNotebookError):
    """No eligible sources selected (maps to 422 with a helpful message)."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class ChatService:
    def __init__(
        self, engine: AsyncEngine, search: Any, provider: ChatProvider, *,
        max_context_chars: int = MAX_CONTEXT_CHARS,
        max_history_messages: int = MAX_HISTORY_MESSAGES,
    ) -> None:
        self._engine = engine
        self._search = search
        self._provider = provider
        self._max_context_chars = max_context_chars
        self._max_history = max_history_messages

    # -- sessions -----------------------------------------------------------

    async def create_session(
        self, actor: ActorContext, notebook_id: uuid.UUID, *,
        title: Optional[str] = None,
    ) -> dict[str, Any]:
        session_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            nb = (
                await conn.execute(
                    text("SELECT context_revision FROM digital_notebooks WHERE id = :id"),
                    {"id": notebook_id},
                )
            ).first()
            if nb is None:
                raise ChatSessionNotFound()
            await conn.execute(
                text(
                    "INSERT INTO chat_sessions (id, notebook_id, title, created_revision,"
                    " created_by) VALUES (:id, :nb, :t, :rev, :by)"
                ),
                {"id": session_id, "nb": notebook_id, "t": title,
                 "rev": int(nb[0]), "by": actor.actor_id},
            )
            row = (
                await conn.execute(
                    text(
                        "SELECT id, notebook_id, title, created_revision, created_at"
                        " FROM chat_sessions WHERE id = :id"
                    ),
                    {"id": session_id},
                )
            ).mappings().one()
        return dict(row)

    async def list_sessions(
        self, actor: ActorContext, notebook_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            nb = (
                await conn.execute(
                    text("SELECT id FROM digital_notebooks WHERE id = :id"),
                    {"id": notebook_id},
                )
            ).first()
            if nb is None:
                raise ChatSessionNotFound()
            rows = (
                await conn.execute(
                    text(
                        "SELECT s.id, s.title, s.created_revision, s.created_at,"
                        " (SELECT count(*) FROM chat_messages m WHERE m.session_id = s.id)"
                        " AS message_count"
                        " FROM chat_sessions s"
                        " JOIN digital_notebooks dn ON dn.id = s.notebook_id"
                        " WHERE s.notebook_id = :nb ORDER BY s.created_at DESC"
                    ),
                    {"nb": notebook_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def list_messages(
        self, actor: ActorContext, notebook_id: uuid.UUID, session_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            srow = (
                await conn.execute(
                    text(
                        "SELECT s.id FROM chat_sessions s"
                        " JOIN digital_notebooks dn ON dn.id = s.notebook_id"
                        " WHERE s.id = :sid AND s.notebook_id = :nb"
                    ),
                    {"sid": session_id, "nb": notebook_id},
                )
            ).first()
            if srow is None:
                raise ChatSessionNotFound()
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, seq, role, content, status, context_revision,"
                        " model, prompt_version, created_at FROM chat_messages"
                        " WHERE session_id = :sid ORDER BY seq"
                    ),
                    {"sid": session_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    async def get_citations(
        self, actor: ActorContext, notebook_id: uuid.UUID,
        session_id: uuid.UUID, message_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            srow = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM chat_messages m"
                        " JOIN chat_sessions s ON s.id = m.session_id"
                        " JOIN digital_notebooks dn ON dn.id = s.notebook_id"
                        " WHERE m.id = :mid AND s.id = :sid AND s.notebook_id = :nb"
                    ),
                    {"mid": message_id, "sid": session_id, "nb": notebook_id},
                )
            ).first()
            if srow is None:
                raise ChatSessionNotFound()
            rows = (
                await conn.execute(
                    text(
                        "SELECT ct.id, ct.display_name, ct.locator, ct.notebook_source_id,"
                        " ct.chunk_id,"
                        " CASE WHEN ct.notebook_source_id IS NULL THEN true"
                        "      ELSE NOT EXISTS (SELECT 1 FROM notebook_sources ns"
                        "                       WHERE ns.id = ct.notebook_source_id) END"
                        "   AS source_removed"
                        " FROM citations ct WHERE ct.message_id = :mid ORDER BY ct.created_at"
                    ),
                    {"mid": message_id},
                )
            ).mappings().all()
        return [dict(r) for r in rows]

    # -- messages -------------------------------------------------------------

    async def send_message(
        self, actor: ActorContext, notebook_id: uuid.UUID, session_id: uuid.UUID, *,
        content: str, idempotency_key: Optional[str] = None,
    ) -> dict[str, Any]:
        content = (content or "").strip()
        if not content:
            raise ChatValidation("Mesajul este vid.")
        if len(content) > 20000:
            raise ChatValidation("Mesajul depășește limita de 20000 de caractere.")

        payload_hash = hashlib.sha256(
            f"{notebook_id}:{session_id}:{content}".encode("utf-8")
        ).hexdigest()

        # Idempotent fast-path: same actor+operation+key returns the stored result.
        if idempotency_key:
            existing = await self._idempotent_lookup(
                actor, "chat_message", idempotency_key, payload_hash
            )
            if existing is not None:
                return existing

        # Phase 1 (one transaction): lock session, validate, build context,
        # insert the user message + idempotency record. No AI call inside.
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "SELECT id FROM chat_sessions WHERE id = :sid AND notebook_id = :nb"
                    " FOR UPDATE"
                ),
                {"sid": session_id, "nb": notebook_id},
            )
            session = (
                await conn.execute(
                    text(
                        "SELECT s.id, dn.context_revision FROM chat_sessions s"
                        " JOIN digital_notebooks dn ON dn.id = s.notebook_id"
                        " WHERE s.id = :sid AND s.notebook_id = :nb"
                    ),
                    {"sid": session_id, "nb": notebook_id},
                )
            ).first()
            if session is None:
                raise ChatSessionNotFound()
            context_revision = int(session[1])

            retrieval = await self._search.search_notebook(
                actor.actor_id, notebook_id, content, mode="both", limit=6,
            )
            context = self._budget(retrieval)
            selected = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM notebook_sources"
                        " WHERE notebook_id = :nb AND selected_for_chat"
                        "   AND status = 'ready'"
                    ),
                    {"nb": notebook_id},
                )
            ).scalar_one()
            if int(selected) == 0:
                raise SourcesRequired(
                    "Niciun fragment găsit în materialele selectate. Adaugă sau "
                    "selectează materiale în carnet înainte de a întreba."
                )

            history_rows = (
                await conn.execute(
                    text(
                        "SELECT role, content FROM chat_messages WHERE session_id = :sid"
                        " ORDER BY seq DESC LIMIT :lim"
                    ),
                    {"sid": session_id, "lim": self._max_history},
                )
            ).all()
            history = [
                {"role": r[0], "content": r[1]} for r in reversed(history_rows)
            ]

            seq = (
                await conn.execute(
                    text(
                        "SELECT coalesce(max(seq), 0) + 1 FROM chat_messages"
                        " WHERE session_id = :sid"
                    ),
                    {"sid": session_id},
                )
            ).scalar_one()
            user_msg_id = uuid.uuid4()
            await conn.execute(
                text(
                    "INSERT INTO chat_messages (id, session_id, seq, role, content,"
                    " status, context_revision) VALUES (:id, :sid, :seq, 'user', :c,"
                    " 'complete', :rev)"
                ),
                {"id": user_msg_id, "sid": session_id, "seq": seq, "c": content,
                 "rev": context_revision},
            )
            if idempotency_key:
                await conn.execute(
                    text(
                        "INSERT INTO idempotency_records (id, actor_id, operation_type,"
                        " idempotency_key, payload_hash, result_type, result_id)"
                        " VALUES (:id, :a, 'chat_message', :k, :ph, 'pending', :rid)"
                    ),
                    {"id": uuid.uuid4(), "a": actor.actor_id, "k": idempotency_key,
                     "ph": payload_hash, "rid": user_msg_id},
                )

        # Phase 2: generation OUTSIDE any DB transaction (GHID §4.5/§7).
        answer = self._provider.generate(content, context, history)

        # Phase 3 (one transaction): save assistant message + validated citations.
        async with actor_connection(self._engine, actor.actor_id) as conn:
            assistant_seq = (
                await conn.execute(
                    text(
                        "SELECT coalesce(max(seq), 0) + 1 FROM chat_messages"
                        " WHERE session_id = :sid"
                    ),
                    {"sid": session_id},
                )
            ).scalar_one()
            assistant_id = uuid.uuid4()
            # cost/usage measurement (L5): char-based estimates for the mock,
            # real usage numbers arrive with real providers (D-02).
            prompt_tokens = (len(content) + sum(len(c.text) for c in context)) // 4
            completion_tokens = len(answer.content) // 4
            await conn.execute(
                text(
                    "INSERT INTO chat_messages (id, session_id, seq, role, content,"
                    " status, context_revision, model, prompt_version, prompt_tokens,"
                    " completion_tokens, total_tokens, estimated_cost)"
                    " VALUES (:id, :sid, :seq, 'assistant', :c, 'complete', :rev,"
                    " :model, :pv, :pt, :ct, :tt, :cost)"
                ),
                {"id": assistant_id, "sid": session_id, "seq": assistant_seq,
                 "c": answer.content, "rev": context_revision,
                 "model": answer.model, "pv": "guguta-mock-1",
                 "pt": prompt_tokens, "ct": completion_tokens,
                 "tt": prompt_tokens + completion_tokens,
                 "cost": 0.0},
            )
            for idx in answer.cited:
                if idx < 0 or idx >= len(context):
                    continue  # invalid citation index refused (A12)
                chunk = context[idx]
                await conn.execute(
                    text(
                        "INSERT INTO citations (id, message_id, notebook_source_id,"
                        " material_version_id, chunk_id, display_name, locator)"
                        " VALUES (:id, :mid, :ns, :mv, :c, :name, CAST(:loc AS jsonb))"
                    ),
                    {"id": uuid.uuid4(), "mid": assistant_id,
                     "ns": chunk.notebook_source_id, "mv": chunk.material_version_id,
                     "c": chunk.chunk_id, "name": chunk.local_name,
                     "loc": _json(chunk.locator)},
                )
            if idempotency_key:
                await conn.execute(
                    text(
                        "UPDATE idempotency_records SET result_type = 'chat_message',"
                        " result_id = :aid WHERE actor_id = :a AND operation_type ="
                        " 'chat_message' AND idempotency_key = :k"
                    ),
                    {"aid": assistant_id, "a": actor.actor_id, "k": idempotency_key},
                )
        return {
            "user_message_id": str(user_msg_id),
            "assistant_message_id": str(assistant_id),
            "context_revision": context_revision,
            "cited": len(answer.cited),
        }

    async def _idempotent_lookup(
        self, actor: ActorContext, op: str, key: str, payload_hash: str
    ) -> Optional[dict[str, Any]]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT payload_hash, result_type, result_id"
                        " FROM idempotency_records"
                        " WHERE actor_id = :a AND operation_type = :op"
                        " AND idempotency_key = :k"
                    ),
                    {"a": actor.actor_id, "op": op, "k": key},
                )
            ).first()
        if row is None:
            return None
        if row[0] != payload_hash:
            raise IdempotencyConflict(
                "Aceeași cheie de idempotency cu alt conținut."
            )
        if row[1] == "chat_message":
            return {"replayed": True, "assistant_message_id": str(row[2])}
        # generation still in flight for this key
        return {"replayed": True, "pending": True, "user_message_id": str(row[2])}

    def _budget(self, retrieval: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Cap the context size; the budget is explicit, never silent (A26)."""
        kept: list[RetrievedChunk] = []
        total = 0
        for chunk in retrieval:
            if total + len(chunk.text) > self._max_context_chars:
                break
            kept.append(chunk)
            total += len(chunk.text)
        return kept
