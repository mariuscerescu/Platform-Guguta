"""Actual PlayQuiz contract, persistence, consent, isolation and failure recovery."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import text

from api.services.guguta.playquiz_export import (
    PlayQuizClient,
    PlayQuizNotExportable,
    PlayQuizUnavailable,
    build_payload,
    payload_hash,
)
from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import actor_connection
from tests.guguta.test_materials_worker import _config, _cookies, _drain, _headers
from tests.guguta.test_materials_worker import _login as dev_login

TOKEN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PLAY_URL = f"https://pq.example/partners/play/{TOKEN}"


def _quiz(**overrides: Any) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "title": "Fracții",
        "difficulty": "medium",
        "status": "ready",
        **overrides,
    }


def _question(
    kind: str = "multiple_choice",
    correct: list[str] | None = None,
    wrong: list[str] | None = None,
    prompt: str = "Cât fac 3 + 4?",
) -> dict[str, Any]:
    options = [
        {"text": t, "is_correct": True}
        for t in (correct if correct is not None else ["7"])
    ]
    options += [
        {"text": t, "is_correct": False}
        for t in (wrong if wrong is not None else ["6", "8"])
    ]
    return {"question_type": kind, "prompt": prompt, "options": options}


def test_exact_quiz_payload_and_hash() -> None:
    payload = build_payload(_quiz(), [_question()])
    assert payload == {
        "quizType": "SINGLE_CHOICE",
        "timePerQuestion": 30,
        "questions": [
            {"content": "Cât fac 3 + 4?", "answers": ["7"], "wrongAnswers": ["6", "8"]}
        ],
    }
    assert payload_hash(payload) == payload_hash(
        build_payload(_quiz(title="Alt titlu"), [_question()])
    )
    assert payload_hash(payload) != payload_hash(
        build_payload(_quiz(difficulty="hard"), [_question()])
    )
    multiple = build_payload(
        _quiz(), [_question(), _question("multiple_select", ["2", "8"], ["3"])]
    )
    assert multiple["quizType"] == "MULTIPLE_CHOICE"


@pytest.mark.parametrize(
    "quiz,questions",
    [
        (_quiz(status="generating"), [_question()]),
        (_quiz(), []),
        (_quiz(), [_question("short_answer")]),
        (_quiz(), [_question(), _question("fill_in_blank")]),
        (_quiz(), [_question(correct=[])]),
        (_quiz(), [_question(wrong=[])]),
        (_quiz(), [_question(wrong=[" "])]),
        (_quiz(), [_question(correct=["x" * 1001])]),
        (_quiz(), [_question(prompt="x" * 1001)]),
        (_quiz(), [_question(wrong=[str(i) for i in range(10)])]),
        (_quiz(), [_question() for _ in range(51)]),
    ],
)
def test_no_silent_truncation_or_incompatible_quizzes(
    quiz: dict[str, Any], questions: list[dict[str, Any]]
) -> None:
    with pytest.raises(PlayQuizNotExportable):
        build_payload(quiz, questions)


@pytest.mark.asyncio
async def test_client_exact_header_account_and_no_redirects() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"account_id": 42})

    client = PlayQuizClient(
        "https://pq.example/api/",
        "synthetic-key",
        transport=httpx.MockTransport(handler),
    )
    body = client.account_payload(
        external_id="u1", email="a@b.md", display_name="Ana", play_token=TOKEN
    )
    assert body == {
        "external_id": "u1",
        "email": "a@b.md",
        "display_name": "Ana",
        "language": "RO",
        "play_token": TOKEN,
    }
    await client.ensure_account(body)
    assert str(seen[0].url) == "https://pq.example/api/partner/guguta/accounts"
    assert seen[0].headers["X-Partner-Key"] == "synthetic-key"
    assert (
        "authorization" not in seen[0].headers
        and "idempotency-key" not in seen[0].headers
    )
    assert json.loads(seen[0].content) == body
    seen.clear()

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            307, headers={"Location": "https://other.example/collect"}
        )

    client = PlayQuizClient(
        "https://pq.example/api", "k", transport=httpx.MockTransport(redirect)
    )
    with pytest.raises(PlayQuizUnavailable):
        await client.create_quiz({})
    assert len(seen) == 1


@pytest.mark.parametrize("failure", ["timeout", "503", "403", "invalid_json"])
@pytest.mark.asyncio
async def test_client_never_retries_non_idempotent_posts(failure: str) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic", request=request)
        if failure == "invalid_json":
            return httpx.Response(200, text="bad")
        return httpx.Response(int(failure), json={"message": "failed"})

    client = PlayQuizClient(
        "https://pq.example/api", "k", transport=httpx.MockTransport(handler)
    )
    with pytest.raises(PlayQuizUnavailable):
        await client.create_quiz({})
    assert len(calls) == 1


def test_url_validation_and_pending_config() -> None:
    client = PlayQuizClient("https://pq.example/api", "k")
    assert client.play_link(PLAY_URL) == (PLAY_URL, TOKEN)
    assert client.login_link(
        f"https://pq.example/login?partner=one-use&play={TOKEN}", TOKEN
    )
    for url in [
        f"https://evil.example/partners/play/{TOKEN}",
        f"javascript:alert(1)",
        f"https://pq.example@evil.example/partners/play/{TOKEN}",
        PLAY_URL + "?extra=1",
    ]:
        with pytest.raises(PlayQuizUnavailable):
            client.play_link(url)
    with pytest.raises(PlayQuizUnavailable):
        client.login_link("https://pq.example/login?partner=x&play=wrong", TOKEN)
    assert not GugutaConfig(
        playquiz_api_url="https://play-quiz.com/api"
    ).playquiz_enabled
    assert GugutaConfig(
        playquiz_api_url="https://play-quiz.com/api", playquiz_partner_key="k"
    ).playquiz_enabled
    with pytest.raises(ValueError):
        GugutaConfig(playquiz_api_url="https://user:secret@play-quiz.com/api")


class FakePlayQuiz:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.account_status = 200
        self.quiz_status = 200
        self.quiz_wait: asyncio.Event | None = None
        self.quiz_started = asyncio.Event()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path, body = request.url.path, json.loads(request.content)
        self.calls.append((path, body))
        assert request.headers["X-Partner-Key"] == "partner-key"
        assert "authorization" not in request.headers
        if path == "/api/partner/quizzes":
            assert set(body) == {"quizType", "timePerQuestion", "questions"}
            for q in body["questions"]:
                assert set(q) == {"content", "answers", "wrongAnswers"}
            self.quiz_started.set()
            if self.quiz_wait is not None:
                await self.quiz_wait.wait()
            return httpx.Response(self.quiz_status, json={"playUrl": PLAY_URL})
        if path == "/api/partner/guguta/accounts":
            assert set(body) == {
                "external_id",
                "email",
                "display_name",
                "language",
                "play_token",
            }
            assert body["play_token"] == TOKEN
            if self.account_status == 400:
                return httpx.Response(
                    400,
                    json={
                        "message": "The email synthetic@example.md already has a Play Quiz account: sign in to Play Quiz with its password"
                    },
                )
            return httpx.Response(
                self.account_status,
                json={
                    "account_id": 7,
                    "created": True,
                    "password_set": False,
                    "login_url": f"https://pq.example/login?partner=synthetic-{len(self.calls)}&play={TOKEN}",
                    "login_expires_in": 900,
                },
            )
        raise AssertionError("Unexpected endpoint: " + path)


async def _login(client: AsyncClient, name: str) -> dict[str, str]:
    auth = await dev_login(client, name)
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    engine = client._transport.app.state.guguta_engine  # type: ignore[attr-defined]
    async with actor_connection(engine, uuid.UUID(me["id"])) as conn:
        await conn.execute(
            text("UPDATE users SET email=:email WHERE id=:id"),
            {"email": f"{me['id']}@synthetic.example", "id": me["id"]},
        )
    return auth


@pytest_asyncio.fixture()
async def playquiz_app(
    guguta_db: dict[str, Any],
) -> AsyncIterator[tuple[AsyncClient, FakePlayQuiz]]:
    api = pytest.importorskip("api.guguta_app")
    from api.services.guguta.playquiz_export import PlayQuizExportService

    cfg = _config(guguta_db["api_dsn"]).model_copy(
        update={
            "chat_provider": "mock",
            "playquiz_api_url": "https://pq.example/api",
            "playquiz_partner_key": SecretStr("partner-key"),
        }
    )
    app = api.create_guguta_app(cfg)
    fake = FakePlayQuiz()
    app.state.guguta_playquiz_export = PlayQuizExportService(
        app.state.guguta_engine,
        cfg,
        PlayQuizClient(
            "https://pq.example/api", "partner-key", transport=httpx.MockTransport(fake)
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        yield client, fake


@pytest_asyncio.fixture()
async def export_worker(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    """Worker de test (ca în test_quizzes) ca materialele să devină gata."""
    from open_notebook.database.guguta.engine import create_engine_for_role
    from open_notebook.jobs.guguta.embeddings import HashEmbeddingProvider
    from open_notebook.jobs.guguta.worker import Worker
    from open_notebook.storage.guguta.filesystem import FilesystemStorage

    class TestWorker(Worker):
        def __init__(self) -> None:
            cfg = _config(guguta_db["worker_dsn"]).model_copy(
                update={"chat_provider": "mock"}
            )
            self._config = cfg
            self._engine = create_engine_for_role(cfg, "worker")
            self._storage = FilesystemStorage("./.guguta-test-storage")
            self._provider = HashEmbeddingProvider(dimension=8)
            self._stopping = __import__("asyncio").Event()

    worker = TestWorker()
    yield worker
    await worker.aclose()


async def _ready_quiz(
    client: AsyncClient, auth: dict[str, str], worker: Any, *, kinds: list[str]
) -> tuple[str, str]:
    """Carnet + material procesat + quiz marcat gata, cu întrebări adăugate manual."""
    notebook = (
        await client.post(
            "/api/v1/notebooks",
            json={"title": "Matematică"},
            cookies=_cookies(auth),
            headers=_headers(auth),
        )
    ).json()
    source = await client.post(
        f"/api/v1/notebooks/{notebook['id']}/sources/text",
        json={
            "title": "Adunarea",
            "text": "Trei plus patru fac șapte. Doi și opt sunt numere pare.",
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert source.status_code == 201, source.text
    await _drain(worker)
    created = await client.post(
        f"/api/v1/notebooks/{notebook['id']}/quizzes",
        json={
            "source_ids": [source.json()["source"]["id"]],
            "quantity": "fewer",
            "difficulty": "easy",
            "question_types": ["multiple_choice"],
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert created.status_code == 202, created.text
    quiz_id = created.json()["id"]
    # Quizul este marcat gata direct în bază (generarea este testată în test_quizzes).
    from sqlalchemy import text

    from open_notebook.database.guguta.engine import actor_connection

    engine = client._transport.app.state.guguta_engine  # type: ignore[attr-defined]
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    async with actor_connection(engine, uuid.UUID(me["id"])) as conn:
        await conn.execute(
            text("UPDATE quizzes SET status='ready', title='Adunarea' WHERE id=:id"),
            {"id": quiz_id},
        )
    for position, kind in enumerate(kinds):
        if kind in ("multiple_choice", "multiple_select"):
            body = {
                "question_type": kind,
                "prompt": f"Întrebarea {position + 1}",
                "options": [
                    {
                        "id": "a",
                        "text": "7",
                        "is_correct": True,
                        "rationale": "3 + 4 = 7",
                    },
                    {"id": "b", "text": "6", "is_correct": False, "rationale": "nu"},
                    {
                        "id": "c",
                        "text": "8",
                        "is_correct": kind == "multiple_select",
                        "rationale": "par",
                    },
                ],
            }
        else:
            body = {
                "question_type": kind,
                "prompt": f"Întrebarea {position + 1}",
                "accepted_answers": ["șapte"],
            }
        added = await client.post(
            f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/questions",
            json=body,
            cookies=_cookies(auth),
            headers=_headers(auth),
        )
        assert added.status_code == 201, added.text
    return notebook["id"], quiz_id


@pytest.mark.asyncio
async def test_export_consent_preview_reuse_updates_and_rls(
    playquiz_app: tuple[AsyncClient, FakePlayQuiz], export_worker: Any
) -> None:
    client, fake = playquiz_app
    auth = await _login(client, f"Elev {uuid.uuid4().hex[:6]}")
    nb, quiz = await _ready_quiz(
        client, auth, export_worker, kinds=["multiple_choice", "multiple_select"]
    )
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
    status = (await client.get(url, cookies=_cookies(auth))).json()
    assert status["enabled"] and status["exportable"] and not status["consent_given"]
    preview = (await client.get(url + "/payload", cookies=_cookies(auth))).json()
    assert [r["path"] for r in preview["requests"]] == [
        "/api/partner/quizzes",
        "/api/partner/guguta/accounts",
    ]
    assert preview["requests"][0]["body"]["quizType"] == "MULTIPLE_CHOICE"
    assert not fake.calls
    denied = await client.post(
        url, json={}, cookies=_cookies(auth), headers=_headers(auth)
    )
    assert denied.status_code == 409 and denied.json()["code"] == "consent_required"
    assert not fake.calls
    first = await client.post(
        url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
    )
    assert first.status_code == 200, first.text
    assert first.json()["created"] and first.json()["play_token"] == TOKEN
    assert first.json()["url"].startswith("https://pq.example/login?partner=")
    assert [p for p, _ in fake.calls] == [
        "/api/partner/quizzes",
        "/api/partner/guguta/accounts",
    ]
    assert fake.calls[0][1] == preview["requests"][0]["body"]
    expected_account = preview["requests"][1]["body"] | {"play_token": TOKEN}
    assert fake.calls[1][1] == expected_account
    second = await client.post(
        url, json={}, cookies=_cookies(auth), headers=_headers(auth)
    )
    assert second.status_code == 200, second.text
    assert not second.json()["created"] and not second.json()["updated"]
    assert second.json()["url"] != first.json()["url"]
    assert [p for p, _ in fake.calls[2:]] == ["/api/partner/guguta/accounts"]
    preview = (await client.get(url + "/payload", cookies=_cookies(auth))).json()
    assert preview["already_exported"] and len(preview["requests"]) == 1
    assert preview["requests"][0]["body"]["play_token"] == TOKEN
    detail = (
        await client.get(
            f"/api/v1/notebooks/{nb}/quizzes/{quiz}", cookies=_cookies(auth)
        )
    ).json()
    edit = await client.put(
        f"/api/v1/notebooks/{nb}/quizzes/{quiz}/questions/{detail['questions'][0]['id']}",
        json={
            "question_type": "multiple_choice",
            "prompt": "Modificată",
            "options": [
                {"id": "a", "text": "7", "is_correct": True, "rationale": "da"},
                {"id": "b", "text": "6", "is_correct": False, "rationale": "nu"},
            ],
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert edit.status_code == 200
    third = await client.post(
        url, json={}, cookies=_cookies(auth), headers=_headers(auth)
    )
    assert third.status_code == 200 and third.json()["updated"]
    assert [p for p, _ in fake.calls[3:]] == [
        "/api/partner/quizzes",
        "/api/partner/guguta/accounts",
    ]
    other = await _login(client, f"Alt elev {uuid.uuid4().hex[:6]}")
    for suffix in ["", "/payload"]:
        assert (
            await client.get(url + suffix, cookies=_cookies(other))
        ).status_code == 404
    assert (
        await client.post(
            url,
            json={"consent": True},
            cookies=_cookies(other),
            headers=_headers(other),
        )
    ).status_code == 404


@pytest.mark.parametrize("account_status", [503, 400])
@pytest.mark.asyncio
async def test_account_failure_preserves_quiz_for_retry(
    playquiz_app: tuple[AsyncClient, FakePlayQuiz],
    export_worker: Any,
    account_status: int,
) -> None:
    client, fake = playquiz_app
    auth = await _login(client, f"Retry {uuid.uuid4().hex[:6]}")
    nb, quiz = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice"])
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
    fake.account_status = account_status
    response = await client.post(
        url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
    )
    assert response.status_code == (409 if account_status == 400 else 503), (
        response.text
    )
    if account_status == 400:
        assert response.json()["code"] == "playquiz_account_conflict"
        assert "synthetic@example.md" not in response.text
    status = (await client.get(url, cookies=_cookies(auth))).json()
    assert status["exported"] and status["play_url"] == PLAY_URL
    fake.account_status = 200
    response = await client.post(
        url, json={}, cookies=_cookies(auth), headers=_headers(auth)
    )
    assert response.status_code == 200, response.text
    assert [p for p, _ in fake.calls].count("/api/partner/quizzes") == 1


@pytest.mark.asyncio
async def test_simultaneous_clicks_do_not_create_duplicate_quizzes(
    playquiz_app: tuple[AsyncClient, FakePlayQuiz], export_worker: Any
) -> None:
    client, fake = playquiz_app
    auth = await _login(client, f"Concurrent {uuid.uuid4().hex[:6]}")
    nb, quiz = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice"])
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
    fake.quiz_wait = asyncio.Event()
    first = asyncio.create_task(
        client.post(
            url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
        )
    )
    try:
        await asyncio.wait_for(fake.quiz_started.wait(), timeout=10)
        second = await client.post(
            url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
        )
        assert second.status_code == 503 and "deja în curs" in second.json()["message"]
    finally:
        fake.quiz_wait.set()
    assert (await first).status_code == 200
    assert [p for p, _ in fake.calls].count("/api/partner/quizzes") == 1


@pytest.mark.asyncio
async def test_incompatible_quiz_missing_email_and_partner_outage(
    playquiz_app: tuple[AsyncClient, FakePlayQuiz], export_worker: Any
) -> None:
    client, fake = playquiz_app
    auth = await _login(client, f"Invalid {uuid.uuid4().hex[:6]}")
    nb, quiz = await _ready_quiz(
        client, auth, export_worker, kinds=["multiple_choice", "fill_in_blank"]
    )
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
    assert not (await client.get(url, cookies=_cookies(auth))).json()["exportable"]
    assert (
        await client.post(
            url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
        )
    ).status_code == 409
    assert not fake.calls
    nb, quiz = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice"])
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
    fake.quiz_status = 503
    assert (
        await client.post(
            url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
        )
    ).status_code == 503
    assert len(fake.calls) == 1
    assert not (await client.get(url, cookies=_cookies(auth))).json()["exported"]
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    engine = client._transport.app.state.guguta_engine  # type: ignore[attr-defined]
    async with actor_connection(engine, uuid.UUID(me["id"])) as conn:
        await conn.execute(
            text("UPDATE users SET email=NULL WHERE id=:id"), {"id": me["id"]}
        )
    assert not (await client.get(url, cookies=_cookies(auth))).json()["exportable"]
    assert (
        await client.post(url, json={}, cookies=_cookies(auth), headers=_headers(auth))
    ).status_code == 409
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_prepared_url_without_key_stays_disabled(
    guguta_db: dict[str, Any], export_worker: Any
) -> None:
    api = pytest.importorskip("api.guguta_app")
    cfg = _config(guguta_db["api_dsn"]).model_copy(
        update={
            "chat_provider": "mock",
            "playquiz_api_url": "https://play-quiz.com/api",
        }
    )
    app = api.create_guguta_app(cfg)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3000"
    ) as client:
        auth = await _login(client, f"Disabled {uuid.uuid4().hex[:6]}")
        assert (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()[
            "capabilities"
        ] == {"playquiz": False}
        nb, quiz = await _ready_quiz(
            client, auth, export_worker, kinds=["multiple_choice"]
        )
        url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
        off = await client.post(
            url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth)
        )
        assert off.status_code == 409 and off.json()["code"] == "playquiz_disabled"
        preview = await client.get(url + "/payload", cookies=_cookies(auth))
        assert preview.status_code == 200 and not preview.json()["enabled"]
        assert preview.json()["requests"][0]["body"]["quizType"] == "SINGLE_CHOICE"
