"""Export de quiz către PlayQuiz extern (play-quiz.com) cu cont automat (ADR-023).

Fluxul este server-la-server: API-ul Guguță creează (sau actualizează) contul
elevului la PlayQuiz, urcă quizul și cere un token de handoff de unică folosință;
browserul primește doar URL-ul de handoff. Cheia de partener nu părăsește
procesul API.

Contractul de partener (docs/guguta/PLAN_INTEGRARE_PLAYQUIZ_COM.md §4) nu este
încă confirmat de echipa PlayQuiz: clientul HTTP și maparea stau în acest modul
ca ajustările să fie ieftine. Nu se trimit indicii, concepte sau dovezi; nu se
jurnalizează date personale.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import NotFoundError, OpenNotebookError

logger = logging.getLogger(__name__)

GRID_QUESTION_TYPES = ("multiple_choice", "multiple_select")
MAX_QUESTIONS = 50
MAX_ANSWERS = 10
MAX_CONTENT_CHARS = 1000
MAX_TITLE_CHARS = 200
TIME_PER_QUESTION = {"easy": 40, "medium": 30, "hard": 20}
PAYLOAD_VERSION = "1"


class PlayQuizDisabled(OpenNotebookError):
    """Exportul nu este configurat pe această instanță."""


class PlayQuizNotExportable(OpenNotebookError):
    """Quizul nu poate fi trimis (nu este gata, are întrebări non-grilă sau depășește limitele)."""


class PlayQuizConsentRequired(OpenNotebookError):
    """Utilizatorul nu a consimțit încă la transmiterea datelor către PlayQuiz."""


class PlayQuizUnavailable(OpenNotebookError):
    """PlayQuiz nu a răspuns sau a răspuns cu eroare."""


class PlayQuizExportNotFound(NotFoundError):
    pass


def _clip(value: str, limit: int) -> str:
    cleaned = " ".join((value or "").split())
    return cleaned[:limit]


def build_payload(
    quiz: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    *,
    category: str,
    language: str = "RO",
) -> dict[str, Any]:
    """Maparea Guguță → PlayQuiz (plan §5). Pură, fără I/O.

    Returnează corpul pentru ``POST /partner/guguta/quizzes`` fără identificatorii
    externi (``external_id``, ``account_external_id``), pe care îi adaugă serviciul.
    """
    if quiz.get("status") != "ready":
        raise PlayQuizNotExportable("Quizul nu este încă gata.")
    if not questions:
        raise PlayQuizNotExportable("Quizul nu are întrebări.")
    if len(questions) > MAX_QUESTIONS:
        raise PlayQuizNotExportable(
            f"PlayQuiz acceptă cel mult {MAX_QUESTIONS} de întrebări într-un quiz."
        )
    mapped: list[dict[str, Any]] = []
    multiple = False
    for question in questions:
        kind = question.get("question_type")
        if kind not in GRID_QUESTION_TYPES:
            raise PlayQuizNotExportable(
                "Doar quizurile alcătuite integral din întrebări grilă pot fi deschise în PlayQuiz."
            )
        options = list(question.get("options") or [])
        answers = [_clip(str(o.get("text", "")), MAX_CONTENT_CHARS) for o in options if o.get("is_correct")]
        wrong = [_clip(str(o.get("text", "")), MAX_CONTENT_CHARS) for o in options if not o.get("is_correct")]
        answers = [a for a in answers if a]
        wrong = [w for w in wrong if w]
        if not answers:
            raise PlayQuizNotExportable("O întrebare nu are răspuns corect.")
        if len(answers) + len(wrong) > MAX_ANSWERS:
            raise PlayQuizNotExportable(
                f"PlayQuiz acceptă cel mult {MAX_ANSWERS} variante de răspuns la o întrebare."
            )
        if kind == "multiple_select" or len(answers) > 1:
            multiple = True
        content = _clip(str(question.get("prompt", "")), MAX_CONTENT_CHARS)
        if not content:
            raise PlayQuizNotExportable("O întrebare nu are enunț.")
        mapped.append({"content": content, "answers": answers, "wrong_answers": wrong})
    title = _clip(str(quiz.get("title") or ""), MAX_TITLE_CHARS) or "Quiz Guguță"
    quiz_type = "MULTIPLE_CHOICE" if multiple else "SINGLE_CHOICE"
    difficulty = str(quiz.get("difficulty") or "medium")
    body: dict[str, Any] = {
        "title": title,
        "language": language,
        "quiz_type": quiz_type,
        "category": category,
        "time_per_question": TIME_PER_QUESTION.get(difficulty, TIME_PER_QUESTION["medium"]),
        "questions": mapped,
    }
    digest = hashlib.sha256(
        json.dumps(
            {"v": PAYLOAD_VERSION, "title": title, "quiz_type": quiz_type, "questions": mapped},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    body["content_hash"] = f"sha256:{digest}"
    return body


class PlayQuizClient:
    """Client HTTP pentru endpointurile de partener (plan §4)."""

    def __init__(
        self,
        base_url: str,
        partner_key: str,
        *,
        hmac_secret: str = "",
        timeout_seconds: float = 10,
        retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._partner_key = partner_key
        self._hmac_secret = hmac_secret
        self._timeout = timeout_seconds
        self._retries = max(0, retries)
        self._transport = transport

    def _headers(self, body: bytes) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._partner_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Guguta-Timestamp": str(int(time.time())),
            "Idempotency-Key": uuid.uuid4().hex,
        }
        if self._hmac_secret:
            message = headers["X-Guguta-Timestamp"].encode("ascii") + b"." + body
            headers["X-Guguta-Signature"] = hmac.new(
                self._hmac_secret.encode("utf-8"), message, hashlib.sha256
            ).hexdigest()
        return headers

    async def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        url = f"{self._base_url}{path}"
        last_error: Exception | None = None
        headers = self._headers(body)
        for attempt in range(self._retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._timeout, transport=self._transport, follow_redirects=False,
                ) as client:
                    response = await client.post(url, content=body, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning("playquiz request failed path=%s attempt=%s", path, attempt + 1)
                continue
            if response.status_code >= 500:
                last_error = PlayQuizUnavailable(f"PlayQuiz a răspuns {response.status_code}.")
                logger.warning(
                    "playquiz server error path=%s status=%s attempt=%s",
                    path,
                    response.status_code,
                    attempt + 1,
                )
                continue
            if response.status_code >= 300:
                logger.error(
                    "playquiz rejected request path=%s status=%s", path, response.status_code
                )
                raise PlayQuizUnavailable(
                    "PlayQuiz a refuzat cererea. Încearcă din nou mai târziu."
                )
            try:
                data = response.json()
            except ValueError as exc:
                raise PlayQuizUnavailable("PlayQuiz a răspuns într-un format neașteptat.") from exc
            if not isinstance(data, dict):
                raise PlayQuizUnavailable("PlayQuiz a răspuns într-un format neașteptat.")
            return data
        raise PlayQuizUnavailable(
            "PlayQuiz nu este disponibil acum. Încearcă din nou mai târziu."
        ) from last_error

    @staticmethod
    def account_payload(
        *,
        external_id: str,
        email: str | None,
        display_name: str,
        language: str = "RO",
        class_level: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "external_id": external_id,
            "display_name": display_name,
            "language": language,
        }
        if email:
            payload["email"] = email
        if class_level:
            payload["class_level"] = class_level
        return payload

    async def ensure_account(
        self,
        *,
        external_id: str,
        email: str | None,
        display_name: str,
        language: str = "RO",
        class_level: str | None = None,
    ) -> dict[str, Any]:
        payload = self.account_payload(
            external_id=external_id,
            email=email,
            display_name=display_name,
            language=language,
            class_level=class_level,
        )
        return await self._post("/partner/guguta/accounts", payload)

    async def upsert_quiz(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post("/partner/guguta/quizzes", payload)

    async def handoff(self, *, account_external_id: str, quiz_id: str) -> dict[str, Any]:
        return await self._post(
            "/partner/guguta/handoff",
            {"account_external_id": account_external_id, "quiz_id": quiz_id},
        )


def _required_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if value is None or str(value).strip() == "":
        raise PlayQuizUnavailable("PlayQuiz a răspuns într-un format neașteptat.")
    return str(value)


class PlayQuizExportService:
    """Starea și exportul unui quiz către PlayQuiz, sub RLS-ul utilizatorului."""

    def __init__(
        self,
        engine: AsyncEngine,
        config: GugutaConfig,
        client: PlayQuizClient | None = None,
    ) -> None:
        self._engine = engine
        self._config = config
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def _load(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None, bool]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            quiz = (
                (
                    await conn.execute(
                        text(
                            "SELECT id,notebook_id,title,difficulty,status FROM quizzes WHERE id=:id AND notebook_id=:n"
                        ),
                        {"id": quiz_id, "n": notebook_id},
                    )
                )
                .mappings()
                .first()
            )
            if not quiz:
                raise PlayQuizExportNotFound()
            questions = (
                (
                    await conn.execute(
                        text(
                            "SELECT id,position,question_type,prompt,options FROM quiz_questions WHERE quiz_id=:id ORDER BY position"
                        ),
                        {"id": quiz_id},
                    )
                )
                .mappings()
                .all()
            )
            export = (
                (
                    await conn.execute(
                        text(
                            "SELECT quiz_id,playquiz_account_id,playquiz_quiz_id,play_url,content_hash,exported_at,last_handoff_at FROM playquiz_exports WHERE quiz_id=:id"
                        ),
                        {"id": quiz_id},
                    )
                )
                .mappings()
                .first()
            )
            consent = (
                await conn.execute(
                    text("SELECT 1 FROM playquiz_consents WHERE user_id=:u"),
                    {"u": actor.actor_id},
                )
            ).first()
        return (
            dict(quiz),
            [dict(q) for q in questions],
            dict(export) if export else None,
            consent is not None,
        )

    async def status(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> dict[str, Any]:
        quiz, questions, export, consent = await self._load(actor, notebook_id, quiz_id)
        exportable = True
        reason: str | None = None
        try:
            build_payload(quiz, questions, category=self._config.playquiz_category)
        except PlayQuizNotExportable as exc:
            exportable = False
            reason = str(exc)
        return {
            "enabled": self.enabled,
            "consent_given": consent,
            "exportable": exportable,
            "reason": reason,
            "exported": export is not None,
            "play_url": export["play_url"] if export else None,
            "exported_at": export["exported_at"].isoformat() if export else None,
        }

    async def _identity(self, actor: ActorContext) -> tuple[str, str | None]:
        async with actor_connection(self._engine, actor.actor_id) as conn:
            user = (
                (
                    await conn.execute(
                        text("SELECT display_name, email FROM users WHERE id=:id"),
                        {"id": actor.actor_id},
                    )
                )
                .mappings()
                .first()
            )
        display_name = (user["display_name"] if user else None) or actor.display_name or "Elev Guguță"
        email = (user["email"] if user else None) or None
        return str(display_name), email

    async def preview(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> dict[str, Any]:
        """Corpurile exacte pe care le-ar trimite exportul către PlayQuiz (plan §4).

        Nu face niciun apel extern și nu înregistrează consimțământ; servește la
        verificarea mapării (de către elev/profesor sau de echipa PlayQuiz).
        """
        quiz, questions, export, consent = await self._load(actor, notebook_id, quiz_id)
        payload = build_payload(quiz, questions, category=self._config.playquiz_category)
        display_name, email = await self._identity(actor)
        external_user = str(actor.actor_id)
        account = PlayQuizClient.account_payload(
            external_id=external_user, email=email, display_name=display_name
        )
        body = dict(payload)
        body["external_id"] = str(quiz_id)
        body["account_external_id"] = external_user
        return {
            "enabled": self.enabled,
            "consent_given": consent,
            "already_exported": export is not None and export["content_hash"] == payload["content_hash"],
            "requests": [
                {"method": "POST", "path": "/partner/guguta/accounts", "body": account},
                {"method": "POST", "path": "/partner/guguta/quizzes", "body": body},
                {
                    "method": "POST",
                    "path": "/partner/guguta/handoff",
                    "body": {"account_external_id": external_user, "quiz_id": "<quiz_id primit de la PlayQuiz>"},
                },
            ],
        }

    async def export(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        *,
        consent: bool,
    ) -> dict[str, Any]:
        if self._client is None:
            raise PlayQuizDisabled("Conexiunea cu PlayQuiz nu este încă disponibilă. Poți continua quizul aici.")
        quiz, questions, export, consent_given = await self._load(actor, notebook_id, quiz_id)
        payload = build_payload(quiz, questions, category=self._config.playquiz_category)
        if not consent_given and not consent:
            raise PlayQuizConsentRequired(
                "Este nevoie de acordul tău ca numele și e-mailul să fie transmise către PlayQuiz."
            )
        async with actor_connection(self._engine, actor.actor_id) as conn:
            if not consent_given:
                await conn.execute(
                    text(
                        "INSERT INTO playquiz_consents (user_id) VALUES (:u) ON CONFLICT (user_id) DO NOTHING"
                    ),
                    {"u": actor.actor_id},
                )
        display_name, email = await self._identity(actor)
        external_user = str(actor.actor_id)
        external_quiz = str(quiz_id)

        created = False
        updated = False
        if export and export["content_hash"] == payload["content_hash"]:
            account_id = export["playquiz_account_id"]
            playquiz_quiz_id = export["playquiz_quiz_id"]
            play_url = export["play_url"]
        else:
            account = await self._client.ensure_account(
                external_id=external_user, email=email, display_name=display_name
            )
            account_id = _required_str(account, "account_id")
            body = dict(payload)
            body["external_id"] = external_quiz
            body["account_external_id"] = external_user
            result = await self._client.upsert_quiz(body)
            playquiz_quiz_id = _required_str(result, "quiz_id")
            play_url = str(result.get("play_url") or "")
            created = export is None
            updated = export is not None
        handoff = await self._client.handoff(
            account_external_id=external_user, quiz_id=playquiz_quiz_id
        )
        url = _required_str(handoff, "url")

        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO playquiz_exports (quiz_id,user_id,playquiz_account_id,playquiz_quiz_id,play_url,content_hash,last_handoff_at) "
                    "VALUES (:q,:u,:a,:p,:url,:h,now()) "
                    "ON CONFLICT (quiz_id) DO UPDATE SET playquiz_account_id=EXCLUDED.playquiz_account_id, playquiz_quiz_id=EXCLUDED.playquiz_quiz_id, "
                    "play_url=EXCLUDED.play_url, content_hash=EXCLUDED.content_hash, last_handoff_at=now(), "
                    "exported_at=CASE WHEN playquiz_exports.content_hash=EXCLUDED.content_hash THEN playquiz_exports.exported_at ELSE now() END"
                ),
                {
                    "q": quiz_id,
                    "u": actor.actor_id,
                    "a": account_id,
                    "p": playquiz_quiz_id,
                    "url": play_url,
                    "h": payload["content_hash"],
                },
            )
        logger.info(
            "playquiz export quiz=%s created=%s updated=%s questions=%s",
            quiz_id,
            created,
            updated,
            len(questions),
        )
        return {
            "url": url,
            "quiz_id": playquiz_quiz_id,
            "play_url": play_url,
            "created": created,
            "updated": updated,
        }
