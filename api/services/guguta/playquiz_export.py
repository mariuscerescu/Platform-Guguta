"""Export de quiz către PlayQuiz extern (play-quiz.com) cu cont automat (ADR-023).

Contract verificat în EduPlatform-BE e39a0c3: quiz cu X-Partner-Key, apoi
cont + play_token → login_url. Linkul quizului se păstrează înainte de cererea
pentru cont. POST-urile nu se repetă automat: PlayQuiz nu deduplică quizurile.
Nu se trimit indicii, concepte sau dovezi și nu se jurnalizează date personale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

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
TIME_PER_QUESTION = {"easy": 40, "medium": 30, "hard": 20}
PAYLOAD_VERSION = "2"


class PlayQuizDisabled(OpenNotebookError):
    """Exportul nu este configurat pe această instanță."""


class PlayQuizNotExportable(OpenNotebookError):
    """Quizul nu poate fi trimis (nu este gata, are întrebări non-grilă sau depășește limitele)."""


class PlayQuizConsentRequired(OpenNotebookError):
    """Utilizatorul nu a consimțit încă la transmiterea datelor către PlayQuiz."""


class PlayQuizUnavailable(OpenNotebookError):
    """PlayQuiz nu a răspuns sau a răspuns cu eroare."""


class PlayQuizAccountConflict(OpenNotebookError):
    """Emailul are deja un cont PlayQuiz care trebuie accesat separat."""


class PlayQuizExportNotFound(NotFoundError):
    pass


def _clip(value: str, limit: int) -> str:
    cleaned = " ".join((value or "").split())
    return cleaned[:limit]


def build_payload(
    quiz: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Corpul exact pentru POST /api/partner/quizzes, fără metadate locale."""
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
        answers = [
            str(o.get("text", "")).strip() for o in options if o.get("is_correct")
        ]
        wrong = [
            str(o.get("text", "")).strip() for o in options if not o.get("is_correct")
        ]
        if not answers:
            raise PlayQuizNotExportable("O întrebare nu are răspuns corect.")
        if not wrong:
            raise PlayQuizNotExportable(
                "Fiecare întrebare grilă trebuie să aibă și un răspuns greșit."
            )
        if any(not a or len(a) > MAX_CONTENT_CHARS for a in answers + wrong):
            raise PlayQuizNotExportable(
                "Variantele de răspuns trebuie să conțină între 1 și 1000 de caractere."
            )
        if len(answers) + len(wrong) > MAX_ANSWERS:
            raise PlayQuizNotExportable(
                f"PlayQuiz acceptă cel mult {MAX_ANSWERS} variante de răspuns la o întrebare."
            )
        if kind == "multiple_select" or len(answers) > 1:
            multiple = True
        content = str(question.get("prompt", "")).strip()
        if not content:
            raise PlayQuizNotExportable("O întrebare nu are enunț.")
        if len(content) > MAX_CONTENT_CHARS:
            raise PlayQuizNotExportable(
                "PlayQuiz acceptă enunțuri de cel mult 1000 de caractere."
            )
        mapped.append({"content": content, "answers": answers, "wrongAnswers": wrong})
    quiz_type = "MULTIPLE_CHOICE" if multiple else "SINGLE_CHOICE"
    difficulty = str(quiz.get("difficulty") or "medium")
    body: dict[str, Any] = {
        "quizType": quiz_type,
        "timePerQuestion": TIME_PER_QUESTION.get(
            difficulty, TIME_PER_QUESTION["medium"]
        ),
        "questions": mapped,
    }
    return body


def payload_hash(payload: Mapping[str, Any]) -> str:
    """Hash local al întregului conținut trimis, inclusiv timpul pe întrebare."""
    digest = hashlib.sha256(
        json.dumps(
            {"v": PAYLOAD_VERSION, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


class PlayQuizClient:
    """Client pentru contractul activ PlayQuiz; nu repetă POST-uri nesigure."""

    def __init__(
        self,
        base_url: str,
        partner_key: str,
        *,
        timeout_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._partner_key = partner_key
        self._timeout = timeout_seconds
        self._transport = transport

    async def _post(self, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    f"{self._base_url}{path}",
                    json=dict(payload),
                    headers={
                        "X-Partner-Key": self._partner_key,
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            logger.warning("playquiz request failed path=%s", path)
            raise PlayQuizUnavailable(
                "PlayQuiz nu a răspuns. Quizul rămâne disponibil aici."
            ) from exc
        if response.status_code >= 300:
            logger.warning(
                "playquiz rejected request path=%s status=%s",
                path,
                response.status_code,
            )
            # Recunoaștem conflictul fără a returna/jurnaliza corpul cu emailul elevului.
            if path.endswith("/accounts") and response.status_code in (400, 409):
                message = response.text.lower()
                if any(
                    marker in message
                    for marker in (
                        "err_partner_email_taken",
                        "already has a play quiz account",
                        "are deja un cont play quiz",
                        "deja există un cont play quiz",
                    )
                ):
                    raise PlayQuizAccountConflict(
                        "Există deja un cont PlayQuiz cu acest e-mail. "
                        "Conectează-te în PlayQuiz cu parola acelui cont, apoi deschide quizul."
                    )
            if response.status_code in (401, 403):
                raise PlayQuizUnavailable(
                    "Conectarea la PlayQuiz nu este configurată corect. Încearcă mai târziu."
                )
            raise PlayQuizUnavailable(
                "PlayQuiz nu poate finaliza cererea acum. Quizul rămâne disponibil aici."
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise PlayQuizUnavailable(
                "PlayQuiz a răspuns într-un format neașteptat."
            ) from exc
        if not isinstance(data, dict):
            raise PlayQuizUnavailable("PlayQuiz a răspuns într-un format neașteptat.")
        return data

    @staticmethod
    def account_payload(
        *,
        external_id: str,
        email: str | None,
        display_name: str,
        play_token: str,
    ) -> dict[str, Any]:
        if not email or not email.strip():
            raise PlayQuizNotExportable(
                "Ai nevoie de o adresă de e-mail în contul Guguță pentru a folosi PlayQuiz."
            )
        return {
            "external_id": external_id,
            "email": email.strip(),
            "display_name": _clip(display_name, 100),
            "language": "RO",
            "play_token": play_token,
        }

    async def ensure_account(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post("/partner/guguta/accounts", payload)

    async def create_quiz(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return await self._post("/partner/quizzes", payload)

    def _url(self, value: Any, path: str) -> str:
        """Acceptăm numai linkuri de pe originea configurată, fără credentiale."""
        url = str(value or "")
        try:
            parsed, base = urlsplit(url), urlsplit(self._base_url)
            same_origin = (parsed.scheme, parsed.hostname, parsed.port) == (
                base.scheme,
                base.hostname,
                base.port,
            )
        except ValueError:
            same_origin = False
        if (
            not same_origin
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.path != path
        ):
            raise PlayQuizUnavailable("PlayQuiz a întors un link neașteptat.")
        return url

    def play_link(self, value: Any) -> tuple[str, str]:
        raw = str(value or "")
        try:
            token = str(uuid.UUID(urlsplit(raw).path.rsplit("/", 1)[-1]))
            url = self._url(raw, f"/partners/play/{token}")
            if urlsplit(url).query:
                raise ValueError("unexpected query")
        except ValueError as exc:
            raise PlayQuizUnavailable(
                "PlayQuiz a întors un link de quiz neașteptat."
            ) from exc
        return url, token

    def login_link(self, value: Any, play_token: str) -> str:
        url = self._url(value, "/login")
        query = parse_qs(urlsplit(url).query)
        if len(query.get("partner", [])) != 1 or query.get("play") != [play_token]:
            raise PlayQuizUnavailable(
                "PlayQuiz a întors un link de autentificare neașteptat."
            )
        return url


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
                            "SELECT quiz_id,playquiz_account_id,play_token,play_url,content_hash,exported_at,last_handoff_at FROM playquiz_exports WHERE quiz_id=:id"
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
            build_payload(quiz, questions)
            _, email = await self._identity(actor)
            if not email:
                raise PlayQuizNotExportable(
                    "Ai nevoie de o adresă de e-mail în contul Guguță pentru a folosi PlayQuiz."
                )
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
        display_name = (
            (user["display_name"] if user else None)
            or actor.display_name
            or "Elev Guguță"
        )
        email = (user["email"] if user else None) or None
        return str(display_name), email

    async def preview(
        self, actor: ActorContext, notebook_id: uuid.UUID, quiz_id: uuid.UUID
    ) -> dict[str, Any]:
        """Contractul efectiv, fără cereri externe sau înregistrarea acordului."""
        quiz, questions, export, consent = await self._load(actor, notebook_id, quiz_id)
        payload = build_payload(quiz, questions)
        reuse = bool(
            export
            and export.get("play_token")
            and export["content_hash"] == payload_hash(payload)
        )
        token = (
            str(export["play_token"])
            if reuse and export
            else "<play_token din playUrl>"
        )
        display_name, email = await self._identity(actor)
        account = PlayQuizClient.account_payload(
            external_id=str(actor.actor_id),
            email=email,
            display_name=display_name,
            play_token=token,
        )
        requests = []
        if not reuse:
            requests.append(
                {"method": "POST", "path": "/api/partner/quizzes", "body": payload}
            )
        requests.append(
            {"method": "POST", "path": "/api/partner/guguta/accounts", "body": account}
        )
        return {
            "enabled": self.enabled,
            "consent_given": consent,
            "already_exported": reuse,
            "requests": requests,
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
            raise PlayQuizDisabled(
                "Conexiunea cu PlayQuiz nu este încă disponibilă. Poți continua quizul aici."
            )
        # Blocare între procese/workeri. Conexiunea separată păstrează lockul și
        # permite salvarea linkului înainte de autentificarea care poate eșua.
        lock_key = int.from_bytes(
            hashlib.sha256(quiz_id.bytes).digest()[:8], "big", signed=True
        )
        async with actor_connection(self._engine, actor.actor_id) as lock:
            acquired = await lock.scalar(
                text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key}
            )
            if not acquired:
                raise PlayQuizUnavailable(
                    "Quizul este deja în curs de trimitere. Încearcă din nou peste câteva secunde."
                )
            return await self._export_locked(
                actor, notebook_id, quiz_id, consent=consent
            )

    async def _export_locked(
        self,
        actor: ActorContext,
        notebook_id: uuid.UUID,
        quiz_id: uuid.UUID,
        *,
        consent: bool,
    ) -> dict[str, Any]:
        assert self._client is not None
        quiz, questions, export, consent_given = await self._load(
            actor, notebook_id, quiz_id
        )
        payload = build_payload(quiz, questions)
        digest = payload_hash(payload)
        if not consent_given and not consent:
            raise PlayQuizConsentRequired(
                "Este nevoie de acordul tău ca numele și e-mailul să fie transmise către PlayQuiz."
            )
        display_name, email = await self._identity(actor)
        # Validăm emailul înainte de orice efect extern.
        account_payload = PlayQuizClient.account_payload(
            external_id=str(actor.actor_id),
            email=email,
            display_name=display_name,
            play_token="pending",
        )
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO playquiz_consents (user_id) VALUES (:u) ON CONFLICT (user_id) DO NOTHING"
                ),
                {"u": actor.actor_id},
            )

        reused = bool(
            export and export.get("play_token") and export["content_hash"] == digest
        )
        if reused and export:
            # Revalidăm inclusiv linkurile persistate (originea poate fi schimbată).
            play_url, token = self._client.play_link(export["play_url"])
            if token != export["play_token"]:
                raise PlayQuizUnavailable("Linkul quizului salvat nu este valid.")
        else:
            result = await self._client.create_quiz(payload)
            play_url, token = self._client.play_link(result.get("playUrl"))
            # Confirmăm tokenul chiar dacă cererea următoare de cont eșuează.
            async with actor_connection(self._engine, actor.actor_id) as conn:
                await conn.execute(
                    text(
                        "INSERT INTO playquiz_exports (quiz_id,user_id,play_token,play_url,content_hash) "
                        "VALUES (:q,:u,:t,:url,:h) "
                        "ON CONFLICT (quiz_id) DO UPDATE SET play_token=EXCLUDED.play_token, "
                        "playquiz_quiz_id=NULL, play_url=EXCLUDED.play_url, content_hash=EXCLUDED.content_hash, "
                        "last_handoff_at=NULL, exported_at=now()"
                    ),
                    {
                        "q": quiz_id,
                        "u": actor.actor_id,
                        "t": token,
                        "url": play_url,
                        "h": digest,
                    },
                )
        account_payload["play_token"] = token
        account = await self._client.ensure_account(account_payload)
        account_id = _required_str(account, "account_id")
        url = self._client.login_link(account.get("login_url"), token)
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "UPDATE playquiz_exports SET playquiz_account_id=:a,last_handoff_at=now() WHERE quiz_id=:q"
                ),
                {"a": account_id, "q": quiz_id},
            )
        logger.info(
            "playquiz export quiz=%s reused=%s questions=%s",
            quiz_id,
            reused,
            len(questions),
        )
        return {
            "url": url,
            "play_token": token,
            "play_url": play_url,
            "created": not reused and export is None,
            "updated": not reused and export is not None,
        }
