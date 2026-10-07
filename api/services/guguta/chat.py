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

import asyncio
import hashlib
import json
import logging
import uuid
from copy import copy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from api.services.guguta.search import RetrievedChunk, requested_page
from open_notebook.ai.guguta.chat import ChatAnswer, ChatProvider
from open_notebook.ai.guguta.openrouter import invoke
from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import (
    ExternalServiceError,
    NotFoundError,
    OpenNotebookError,
)

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 24000
MAX_HISTORY_MESSAGES = 10


class ChatSessionNotFound(NotFoundError):
    pass


class ChatValidation(OpenNotebookError):
    pass


class IdempotencyConflict(OpenNotebookError):
    """Same key, different payload (maps to 409)."""


class SourcesRequired(OpenNotebookError):
    """No eligible sources selected (maps to 422 with a helpful message).

    Păstrat pentru contractul de erori al API-ului, dar **nu mai este ridicat**:
    întrebarea se acceptă și fără materiale selectate, iar răspunsul de atunci
    poate explica din cunoștințe generale fără citări inventate.
    """


class ChatProviderUnavailable(ExternalServiceError):
    """The AI provider failed (maps to 502 — controlled, no partial answer)."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class ChatService:
    def __init__(
        self, engine: AsyncEngine, search: Any, provider: ChatProvider, *,
        max_context_chars: int = MAX_CONTEXT_CHARS,
        max_history_messages: int = MAX_HISTORY_MESSAGES,
        total_timeout_seconds: float = 120,
    ) -> None:
        self._total_timeout = total_timeout_seconds
        self._engine = engine
        self._search = search
        self._provider = provider
        self._pdf_evidence = None
        self._agent = None
        self._max_context_chars = max_context_chars
        self._max_history = max_history_messages
        # F09: a 'pending' generation older than this is recovered on retry
        self._pending_recovery_seconds = 300
        self._attachments = None
        self._attachment_ids = []

    def for_session(self, session_id, attachment_ids=()):
        scoped = copy(self)
        scoped._attachment_ids = list(attachment_ids)
        if callable(getattr(self._search, "for_session", None)):
            scoped._search = self._search.for_session(session_id)
        if self._pdf_evidence is not None:
            scoped._pdf_evidence = self._pdf_evidence.for_session(session_id)
        if self._agent is not None:
            scoped._agent = copy(self._agent)
            scoped._agent._search = scoped._search
            if scoped._pdf_evidence is not None:
                scoped._agent._pdf = scoped._pdf_evidence
            elif self._agent._pdf is not None:
                scoped._agent._pdf = self._agent._pdf.for_session(session_id)
        return scoped

    async def _bind_attachments(self, conn, session_id, message_id):
        if self._attachments is not None:
            await self._attachments.bind(conn, session_id, message_id, self._attachment_ids)

    # -- streaming (SSE) -------------------------------------------------------

    async def send_message_stream(
        self, actor: ActorContext, notebook_id: uuid.UUID,
        session_id: uuid.UUID, *, content: str,
        idempotency_key: Optional[str] = None,
    ):
        """SSE generator: yields Server-Sent Events for a chat response.

        Events (SSE `data:` field, one JSON object per event):
        - {"event": "user_saved", "user_message_id": ..., "assistant_message_id": ...}
        - {"event": "token", "text": "..."}
        - {"event": "done", "assistant_message_id": ..., "cited": N}
        - {"event": "error", "code": ..., "message": ...}
        """

        content = (content or "").strip()
        if not content:
            raise ChatValidation("Mesajul este vid.")

        # streaming nu folosește idempotency (faza 2 e incompletă până la done)
        request_deadline = asyncio.get_running_loop().time() + self._total_timeout

        # Resolve follow-up references from the current-revision conversation
        # before retrieval. Provider calls remain outside DB transactions.
        async with actor_connection(self._engine, actor.actor_id) as conn:
            snapshot = (await conn.execute(text(
                "SELECT dn.context_revision FROM chat_sessions s JOIN digital_notebooks dn"
                " ON dn.id=s.notebook_id WHERE s.id=:sid AND dn.id=:nb"
            ), {"sid": session_id, "nb": notebook_id})).scalar_one_or_none()
            if snapshot is None:
                raise ChatSessionNotFound()
            history = await self._history(conn, session_id, int(snapshot))
        try:
            async with asyncio.timeout_at(request_deadline):
                retrieval = await self._retrieve(
                    actor.actor_id, notebook_id, content, history,
                )
                context = self._budget(retrieval)
                if self._pdf_evidence is not None:
                    context = await self._pdf_evidence.enrich(actor.actor_id, notebook_id, context)
        except TimeoutError:
            raise ChatProviderUnavailable(
                "Generarea a durat prea mult. Reîncercați peste câteva momente."
            ) from None

        # Phase 1 (single tx): validate session, save user message
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text("SELECT id FROM chat_sessions WHERE id = :sid AND notebook_id = :nb FOR UPDATE"),
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
            if context_revision != int(snapshot):
                raise IdempotencyConflict(
                    "Materialele s-au schimbat în timpul căutării; repetă întrebarea."
                )

            # Întrebarea se salvează și fără dovezi; furnizorul răspunde atunci
            # educațional fără citări, ori cere datele concrete care lipsesc.
            seq = (
                await conn.execute(
                    text("SELECT coalesce(max(seq), 0) + 1 FROM chat_messages WHERE session_id = :sid"),
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
            await self._bind_attachments(conn, session_id, user_msg_id)

        # Phase 2: stream tokens from the provider, cu heartbeat la 15s —
        # proxyele taie conexiunile idle (next proxyTimeout 30s implicit)
        async def _generate():
            full_content = []
            answer = None
            loop = asyncio.get_running_loop()
            deadline = request_deadline
            try:
                yield json.dumps({"event": "user_saved", "user_message_id": str(user_msg_id)})
                queue: asyncio.Queue[Any] = asyncio.Queue()
                _STOP: dict[str, Any] = {"stop": True}

                async def _pump() -> None:
                    nonlocal answer, context
                    try:
                        # Keep the complete validated answer on THIS request.
                        # A shared provider.last_cited can race across sessions.
                        answer, context = await self._answer(
                            actor.actor_id, notebook_id, content, context, history,
                            context_revision=context_revision,
                        )
                        for word in answer.content.split(" "):
                            await queue.put(word+" ")
                    except Exception as exc:  # propagate to the consumer
                        await queue.put(exc)
                    finally:
                        await queue.put(_STOP)

                pump_task = asyncio.create_task(_pump())
                try:
                    while True:
                        remaining = deadline - loop.time()
                        if remaining <= 0:
                            raise ChatProviderUnavailable(
                                "Generarea a durat prea mult. Reîncercați peste câteva momente."
                            )
                        try:
                            item = await asyncio.wait_for(
                                queue.get(), timeout=min(15, remaining)
                            )
                        except asyncio.TimeoutError:
                            # keep-alive: orice bytes reșetează timerul proxyului
                            yield json.dumps({"event": "ping"})
                            continue
                        if isinstance(item, dict) and item.get("stop"):
                            break
                        if isinstance(item, BaseException):
                            raise item
                        full_content.append(item)
                        yield json.dumps({"event": "token", "text": item})
                finally:
                    pump_task.cancel()
                    await asyncio.gather(pump_task, return_exceptions=True)
                full_text = "".join(full_content).strip()
                if not full_text:
                    raise ChatValidation("Răspunsul gol al modelului.")

                # Phase 3: save assistant message + citations (one tx)
                async with actor_connection(self._engine, actor.actor_id) as conn:
                    locked = (await conn.execute(
                        text("SELECT id FROM chat_sessions WHERE id = :sid FOR UPDATE"),
                        {"sid": session_id},
                    )).first()
                    if locked is None:
                        raise ChatSessionNotFound()
                    current_revision = (await conn.execute(text(
                        "SELECT context_revision FROM digital_notebooks WHERE id=:nb"
                    ),{"nb":notebook_id})).scalar_one()
                    if current_revision != context_revision:
                        raise IdempotencyConflict("Materialele s-au schimbat în timpul generării; repetă întrebarea.")
                    assistant_seq = (
                        await conn.execute(
                            text("SELECT coalesce(max(seq), 0) + 1 FROM chat_messages WHERE session_id = :sid"),
                            {"sid": session_id},
                        )
                    ).scalar_one()
                    assistant_id = uuid.uuid4()
                    prompt_tokens = answer.prompt_tokens if answer.prompt_tokens is not None else (len(content)+sum(len(c.text) for c in context))//4
                    completion_tokens = answer.completion_tokens if answer.completion_tokens is not None else len(full_text)//4
                    await conn.execute(
                        text(
                            "INSERT INTO chat_messages (id, session_id, seq, role, content,"
                            " status, context_revision, model, prompt_version,prompt_tokens,"
                            " completion_tokens,total_tokens,estimated_cost)"
                            " VALUES (:id, :sid, :seq, 'assistant', :c, 'complete', :rev,"
                            " :model, :pv,:pt,:ct,:tt,:cost)"
                        ),
                        {"id": assistant_id, "sid": session_id, "seq": assistant_seq,
                         "c": full_text, "rev": context_revision,
                         "model": self._provider.model_name,
                         "pv": answer.prompt_version,"pt":prompt_tokens,"ct":completion_tokens,
                         "tt":prompt_tokens+completion_tokens,"cost":answer.estimated_cost or 0},
                    )
                    for citation_number,idx in enumerate(answer.cited,1):
                        if idx < 0 or idx >= len(context):
                            continue
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
                             "loc": json.dumps({**chunk.locator,"citation_number":citation_number})},
                        )
                yield json.dumps({"event": "done", "assistant_message_id": str(assistant_id),
                             "cited": len(answer.cited)})
            except Exception as exc:
                logger.exception(
                    "chat streaming failed actor=%s notebook=%s session=%s",
                    actor.actor_id, notebook_id, session_id,
                )
                yield json.dumps({"event": "error", "message": str(exc) or "Generarea a eșuat."})

        return _generate()

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
                        "SELECT id, seq, role,"
                        " CASE WHEN status = 'cancelled' THEN"
                        "   '[Generare anulată: contextul carnetului s-a schimbat]'"
                        "   ELSE content END AS content,"
                        " status, context_revision,"
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
                        " FROM citations ct WHERE ct.message_id = :mid ORDER BY "
                        " CASE WHEN ct.locator->>'citation_number' ~ '^[1-9][0-9]{0,3}$' "
                        " THEN (ct.locator->>'citation_number')::int END NULLS LAST,ct.created_at,ct.id"
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
            (f"{notebook_id}:{session_id}:{content}" +
             (":" + ",".join(sorted(map(str, self._attachment_ids))) if self._attachment_ids else "")).encode("utf-8")
        ).hexdigest()

        # Idempotent fast-path: same actor+operation+key returns the stored result.
        if idempotency_key:
            existing = await self._idempotent_lookup(
                actor, "chat_message", idempotency_key, payload_hash
            )
            if existing is not None:
                if existing.get("retry"):
                    # F09: failed/stale attempt — clean it and re-run the same
                    # operation once, so the key finalizes exactly one message.
                    await self._cleanup_failed_attempt(
                        actor, "chat_message", idempotency_key,
                        existing["user_message_id"],
                    )
                else:
                    return existing

        deadline = asyncio.get_running_loop().time() + self._total_timeout
        # Authenticate the session before any outbound provider request.
        async with actor_connection(self._engine, actor.actor_id) as conn:
            revision = (await conn.execute(text(
                "SELECT dn.context_revision FROM chat_sessions s JOIN digital_notebooks dn"
                " ON dn.id=s.notebook_id WHERE s.id=:sid AND dn.id=:nb"
            ), {"sid": session_id, "nb": notebook_id})).scalar_one_or_none()
            if revision is None:
                raise ChatSessionNotFound()
            initial_history = await self._history(conn, session_id, int(revision))
        try:
            retrieval = await asyncio.wait_for(
                self._retrieve(
                    actor.actor_id, notebook_id, content, initial_history,
                ),
                timeout=max(0.001, deadline - asyncio.get_running_loop().time()),
            )
        except TimeoutError:
            raise ChatProviderUnavailable("Căutarea AI a depășit timpul de așteptare.") from None
        context = self._budget(retrieval)
        if self._pdf_evidence is not None:
            try:
                async with asyncio.timeout_at(deadline):
                    context = await self._pdf_evidence.enrich(actor.actor_id, notebook_id, context)
            except TimeoutError:
                raise ChatProviderUnavailable("Încărcarea paginilor a depășit timpul de așteptare.") from None

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

            if context_revision != revision:
                raise IdempotencyConflict("Materialele s-au schimbat în timpul căutării; repetă întrebarea.")
            # Ca și pe fluxul cu streaming, întrebarea trece și fără dovezi;
            # tutorele poate explica fără a inventa citări sau date de exercițiu.

            # F07: the model context includes only messages generated under the
            # CURRENT revision. Older messages stay visible in UI history but
            # never re-enter the prompt after a source change (A17).
            history = await self._history(conn, session_id, context_revision)

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
            await self._bind_attachments(conn, session_id, user_msg_id)
            if idempotency_key:
                try:
                    await conn.execute(
                        text(
                            "INSERT INTO idempotency_records (id, actor_id, operation_type,"
                            " idempotency_key, payload_hash, result_type, result_id)"
                            " VALUES (:id, :a, 'chat_message', :k, :ph, 'pending', :rid)"
                        ),
                        {"id": uuid.uuid4(), "a": actor.actor_id, "k": idempotency_key,
                         "ph": payload_hash, "rid": user_msg_id},
                    )
                except Exception as exc:  # F13: concurrent same-key insert
                    if "ux_idempotency_records" in str(exc):
                        # the concurrent request won the record: replay/409 per
                        # contract (the tx is aborted — the client retries once
                        # for the rare failed-record race)
                        existing = await self._idempotent_lookup(
                            actor, "chat_message", idempotency_key, payload_hash
                        )
                        if existing is not None and not existing.get("retry"):
                            return existing
                        raise IdempotencyConflict(
                            "Operațiune concurentă pe aceeași cheie; repetați cererea."
                        )
                    raise

        # Phase 2: generation OUTSIDE any DB transaction (GHID §4.5/§7).
        try:
            answer, context = await asyncio.wait_for(self._answer(actor.actor_id, notebook_id, content, context, history, context_revision=context_revision),
                                            timeout=max(0.001, deadline - asyncio.get_running_loop().time()))
        except Exception as exc:
            # A26 + F09: controlled provider failure. The user message remains
            # as history; the idempotency record becomes 'failed' so a retry
            # with the same key can complete the operation (after cleanup).
            logger.warning(
                "chat provider a eșuat (notebook=%s, sesiune=%s): %s: %s",
                notebook_id, session_id, type(exc).__name__, exc,
            )
            if idempotency_key:
                async with actor_connection(self._engine, actor.actor_id) as conn:
                    await conn.execute(
                        text(
                            "UPDATE idempotency_records SET result_type = 'failed'"
                            " WHERE actor_id = :a AND operation_type = 'chat_message'"
                            " AND idempotency_key = :k AND result_type = 'pending'"
                        ),
                        {"a": actor.actor_id, "k": idempotency_key},
                    )
            raise ChatProviderUnavailable(
                "Furnizorul AI nu a răspuns. Încearcă din nou în câteva momente."
            ) from exc

        # Phase 3 (one transaction, F08): re-lock the session, re-check the
        # revision, allocate seq under the lock, save assistant message +
        # validated citations, finalize idempotency.
        async with actor_connection(self._engine, actor.actor_id) as conn:
            locked = (
                await conn.execute(
                    text(
                        "SELECT id FROM chat_sessions WHERE id = :sid FOR UPDATE"
                    ),
                    {"sid": session_id},
                )
            ).first()
            if locked is None:
                raise ChatSessionNotFound()
            current_revision = (
                await conn.execute(
                    text(
                        "SELECT context_revision FROM digital_notebooks WHERE id = :nb"
                    ),
                    {"nb": notebook_id},
                )
            ).scalar_one()
            cancelled = current_revision != context_revision
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
            prompt_tokens = answer.prompt_tokens if answer.prompt_tokens is not None else (len(content) + sum(len(c.text) for c in context)) // 4
            completion_tokens = answer.completion_tokens if answer.completion_tokens is not None else len(answer.content) // 4
            await conn.execute(
                text(
                    "INSERT INTO chat_messages (id, session_id, seq, role, content,"
                    " status, context_revision, model, prompt_version, prompt_tokens,"
                    " completion_tokens, total_tokens, estimated_cost)"
                    " VALUES (:id, :sid, :seq, 'assistant', :c, :st, :rev,"
                    " :model, :pv, :pt, :ct, :tt, :cost)"
                ),
                {"id": assistant_id, "sid": session_id, "seq": assistant_seq,
                 "c": answer.content,
                 "st": "cancelled" if cancelled else "complete",
                 "rev": context_revision,
                 "model": answer.model, "pv": answer.prompt_version,
                 "pt": prompt_tokens, "ct": completion_tokens,
                 "tt": prompt_tokens + completion_tokens,
                 "cost": answer.estimated_cost if answer.estimated_cost is not None else 0.0},
            )
            if not cancelled:
                for citation_number,idx in enumerate(answer.cited,1):
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
                         "loc": json.dumps({**chunk.locator,"citation_number":citation_number})},
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
        result = {
            "user_message_id": str(user_msg_id),
            "assistant_message_id": str(assistant_id),
            "context_revision": context_revision,
            "cited": len(answer.cited) if not cancelled else 0,
        }
        if cancelled:
            result["cancelled"] = True  # A17: stale generation, not published
        return result

    async def _idempotent_lookup(
        self, actor: ActorContext, op: str, key: str, payload_hash: str
    ) -> Optional[dict[str, Any]]:
        """F09: resolve an idempotency record with recovery semantics.
        - completed  -> replay the stored result
        - pending, fresh -> 'pending' replay (generation in flight)
        - pending, older than the recovery timeout, or failed -> mark 'retry':
          the caller cleans the failed attempt and re-runs the operation.
        """
        async with actor_connection(self._engine, actor.actor_id) as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT payload_hash, result_type, result_id, created_at"
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
        if row[1] == "failed":
            return {"retry": True, "user_message_id": str(row[2])}
        # pending: recover stale generations (timeout = 5x chat timeout, min 5 min)
        age = (datetime.now(timezone.utc) - row[3]).total_seconds()
        if age > self._pending_recovery_seconds:
            return {"retry": True, "user_message_id": str(row[2])}
        return {"replayed": True, "pending": True, "user_message_id": str(row[2])}

    async def _cleanup_failed_attempt(
        self, actor: ActorContext, op: str, key: str, user_message_id: str
    ) -> None:
        """Remove the orphaned user message + record of a failed attempt so the
        retry with the same key completes exactly one operation (F09)."""
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text("DELETE FROM chat_messages WHERE id = :id"),
                {"id": uuid.UUID(user_message_id)},
            )
            await conn.execute(
                text(
                    "DELETE FROM idempotency_records WHERE actor_id = :a"
                    " AND operation_type = :op AND idempotency_key = :k"
                ),
                {"a": actor.actor_id, "op": op, "k": key},
            )

    async def _history(self, conn, session_id: uuid.UUID, revision: int) -> list[dict[str, Any]]:
        """Restore source/page references alongside current-revision messages.

        References are locator hints, never evidence. The agent reopens their
        original pages and reauthorizes selection before another provider call.
        """
        rows = (await conn.execute(text(
            "SELECT m.role,m.content,coalesce((SELECT jsonb_agg(jsonb_build_object("
            "'source_id',c.notebook_source_id,'material_version_id',c.material_version_id,"
            "'locator',c.locator) ORDER BY c.locator->'citation_number',c.created_at,c.id) FROM citations c "
            "WHERE c.message_id=m.id AND c.notebook_source_id IS NOT NULL "
            "AND c.material_version_id IS NOT NULL), '[]'::jsonb) AS source_refs "
            "FROM chat_messages m WHERE m.session_id=:sid AND m.context_revision=:rev "
            "AND m.status='complete' ORDER BY m.seq DESC LIMIT :lim"
        ), {"sid": session_id, "rev": revision, "lim": self._max_history})).mappings().all()
        return [dict(r) for r in reversed(rows)]

    async def _answer(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID, question: str,
        context: list[RetrievedChunk], history: list[dict[str, Any]],
        *, context_revision: int | None = None,
    ) -> tuple[ChatAnswer, list[RetrievedChunk]]:
        """Acquire adaptive evidence then use the existing citation validator."""
        result = None
        source_ids = list(self._attachment_ids)
        current_ids = set(source_ids)
        source_scopes = {source_id: "current_attachment" for source_id in current_ids}
        if callable(getattr(self._search, "list_sources", None)):
            sources = await self._search.list_sources(actor_id, notebook_id)
            has_attachments = bool(current_ids) or any(source.get("is_attachment") for source in sources)
            for source in sources:
                source_id = uuid.UUID(source["source_id"])
                source_scopes.setdefault(source_id, "chat_attachment" if source.get("is_attachment") else "notebook")
                # Keep conversation files available on later turns; preload
                # notebook images only when they cannot distract from attachments.
                if source.get("is_attachment") or (not has_attachments and requested_page(question) is None and
                    (source.get("mime_type") or "").startswith("image/")):
                    if source_id not in source_ids:
                        source_ids.append(source_id)
        if source_ids:
            attached = await self._search.attachment_context(actor_id, notebook_id, source_ids)
            # Preserve all current-file excerpts before older conversation files.
            attached.sort(key=lambda chunk: chunk.notebook_source_id not in current_ids)
            if self._pdf_evidence is not None:
                attached = await self._pdf_evidence.enrich(actor_id, notebook_id, attached)
            seen = {c.chunk_id for c in attached}
            context = self._budget(attached + [c for c in context if c.chunk_id not in seen])
        context = [replace(chunk, source_scope=source_scopes.get(chunk.notebook_source_id, "notebook"))
                   for chunk in context]
        if self._agent is not None and callable(getattr(self._provider, "choose_tools", None)):
            result = await self._agent.retrieve(
                actor_id, notebook_id, self._provider, question, history, context,
                expected_revision=context_revision,
                source_scopes=source_scopes,
            )
            context = self._budget(result.chunks)
        if callable(getattr(self._search, "authorize_chunks", None)):
            context = await self._search.authorize_chunks(actor_id, notebook_id, context)
        if callable(getattr(self._search, "context_revision", None)) and await self._search.context_revision(actor_id, notebook_id) is None:
            raise ChatSessionNotFound()
        answer = await invoke(self._provider.generate, question, context, history)
        if result is not None:
            usage = [*result.usage, (answer.prompt_tokens, answer.completion_tokens, answer.estimated_cost)]
            totals = [sum(row[i] for row in usage if row[i] is not None)
                      if any(row[i] is not None for row in usage) else None for i in range(3)]
            answer = answer._replace(
                prompt_tokens=totals[0], completion_tokens=totals[1], estimated_cost=totals[2],
                prompt_version=answer.prompt_version + "-agent-1",
            )
            logger.info("chat_agent_complete rounds=%d tools=%d images=%d", len(result.usage),
                        len(result.trace), sum(bool(c.image_url) for c in context))
        return answer, context

    def _budget(self, retrieval: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Cap the context size; the budget is explicit, never silent (A26)."""
        kept: list[RetrievedChunk] = []
        total = 0
        for chunk in retrieval:
            if total + len(chunk.text) > self._max_context_chars:
                continue
            kept.append(chunk)
            total += len(chunk.text)
        return kept

    async def _retrieve(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID,
        question: str, history: list[dict[str, str]],
    ) -> list[RetrievedChunk]:
        """Plan retrieval perspectives, then fuse and rerank their evidence.

        Planning is an optional quality layer: if it is unavailable or returns
        invalid output, the original question remains a safe retrieval query.
        """
        queries = [question]
        if requested_page(question) is not None:
            # The locator is already an exact retrieval plan. A model planner
            # must not reinterpret an exercise number as the PDF page.
            return await self._search.search_notebook(
                actor_id,notebook_id,question,mode="both",limit=8,
            )
        if self._agent is not None:
            # The agent resolves follow-ups from saved page references and
            # chooses its own queries. Avoid an additional fixed planner call.
            return []
        planner = getattr(self._provider, "plan_queries", None)
        if callable(planner):
            try:
                planned = await asyncio.wait_for(
                    invoke(planner, question, history), timeout=30,
                )
                if isinstance(planned, list):
                    queries.extend(q for q in planned if isinstance(q, str))
            except (ExternalServiceError, TimeoutError, TypeError, ValueError) as exc:
                logger.info(
                    "query planner indisponibil; folosesc întrebarea originală: %s",
                    type(exc).__name__,
                )
        multi = getattr(self._search, "search_notebook_multi", None)
        if callable(multi):
            return await multi(
                actor_id, notebook_id, queries, question,
                mode="both", limit=8,
            )
        return await self._search.search_notebook(
            actor_id, notebook_id, question, mode="both", limit=8,
        )
