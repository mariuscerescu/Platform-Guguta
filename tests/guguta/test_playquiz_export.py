"""PlayQuiz extern (ADR-023): mapare, client de partener, export idempotent, consimțământ."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from api.services.guguta.playquiz_export import (
    PlayQuizClient,
    PlayQuizNotExportable,
    PlayQuizUnavailable,
    build_payload,
)
from open_notebook.database.guguta.config import GugutaConfig
from tests.guguta.test_materials_worker import (
    _config,
    _cookies,
    _drain,
    _headers,
    _login,
)


def _quiz(**overrides: Any) -> dict[str, Any]:
    base = {"id": uuid.uuid4(), "title": "Fracții", "difficulty": "medium", "status": "ready"}
    base.update(overrides)
    return base


def _question(kind: str, correct: list[str], wrong: list[str], prompt: str = "Cât fac 3 + 4?") -> dict[str, Any]:
    options = [{"id": f"c{i}", "text": t, "is_correct": True} for i, t in enumerate(correct)]
    options += [{"id": f"w{i}", "text": t, "is_correct": False} for i, t in enumerate(wrong)]
    return {"id": uuid.uuid4(), "position": 0, "question_type": kind, "prompt": prompt, "options": options}


# --- maparea (plan §5) -------------------------------------------------------


def test_payload_single_choice_mapping_and_hash_is_stable() -> None:
    questions = [_question("multiple_choice", ["7"], ["6", "8", "12"])]
    payload = build_payload(_quiz(), questions, category="guguta")
    assert payload["quiz_type"] == "SINGLE_CHOICE"
    assert payload["language"] == "RO"
    assert payload["category"] == "guguta"
    assert payload["time_per_question"] == 30
    assert payload["questions"] == [
        {"content": "Cât fac 3 + 4?", "answers": ["7"], "wrong_answers": ["6", "8", "12"]}
    ]
    assert payload["content_hash"].startswith("sha256:")
    again = build_payload(_quiz(id=uuid.uuid4()), questions, category="altceva")
    assert again["content_hash"] == payload["content_hash"]  # hash-ul nu depinde de id/categorie
    changed = build_payload(_quiz(), [_question("multiple_choice", ["7"], ["6", "8", "13"])], category="guguta")
    assert changed["content_hash"] != payload["content_hash"]


def test_payload_multiple_select_difficulty_and_clipping() -> None:
    questions = [
        _question("multiple_choice", ["2"], ["3"]),
        _question("multiple_select", ["2", "8"], ["3", "9"], prompt="  Care   sunt  pare? " + "x" * 2000),
    ]
    payload = build_payload(_quiz(difficulty="hard", title="t" * 500), questions, category="guguta")
    assert payload["quiz_type"] == "MULTIPLE_CHOICE"
    assert payload["time_per_question"] == 20
    assert len(payload["title"]) == 200
    assert payload["questions"][1]["content"].startswith("Care sunt pare? x")
    assert len(payload["questions"][1]["content"]) == 1000
    assert payload["questions"][1]["answers"] == ["2", "8"]


@pytest.mark.parametrize(
    "quiz,questions",
    [
        (_quiz(status="generating"), [_question("multiple_choice", ["7"], ["6"])]),
        (_quiz(), []),
        (_quiz(), [_question("fill_in_blank", ["7"], [])]),
        (_quiz(), [_question("multiple_choice", ["7"], ["6"]), _question("short_answer", ["7"], [])]),
        (_quiz(), [_question("multiple_choice", [], ["6", "8"])]),
        (_quiz(), [_question("multiple_choice", ["7"], [str(i) for i in range(10)])]),
        (_quiz(), [_question("multiple_choice", ["7"], ["6"]) for _ in range(51)]),
    ],
)
def test_payload_refuses_non_exportable(quiz: dict[str, Any], questions: list[dict[str, Any]]) -> None:
    with pytest.raises(PlayQuizNotExportable):
        build_payload(quiz, questions, category="guguta")


# --- clientul de partener (plan §4) -------------------------------------------


@pytest.mark.asyncio
async def test_client_sends_partner_headers_and_hmac_signature() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"account_id": 42, "created": True})

    client = PlayQuizClient(
        "https://play-quiz.example/api/",
        "partner-key",
        hmac_secret="hmac-secret",
        transport=httpx.MockTransport(handler),
    )
    result = await client.ensure_account(external_id="u1", email="a@b.md", display_name="Ana")
    assert result == {"account_id": 42, "created": True}
    request = seen[0]
    assert str(request.url) == "https://play-quiz.example/api/partner/guguta/accounts"
    assert request.headers["authorization"] == "Bearer partner-key"
    assert request.headers["idempotency-key"]
    assert request.headers["x-guguta-timestamp"].isdigit()
    import hashlib
    import hmac as hmac_mod

    expected = hmac_mod.new(
        b"hmac-secret",
        request.headers["x-guguta-timestamp"].encode() + b"." + request.content,
        hashlib.sha256,
    ).hexdigest()
    assert request.headers["x-guguta-signature"] == expected
    assert json.loads(request.content) == {
        "external_id": "u1", "display_name": "Ana", "language": "RO", "email": "a@b.md"
    }


@pytest.mark.asyncio
async def test_client_retries_on_5xx_then_succeeds() -> None:
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="down")
        return httpx.Response(200, json={"url": "https://play-quiz.example/handoff?token=t", "expires_in": 60})

    client = PlayQuizClient("https://play-quiz.example/api", "k", retries=2, transport=httpx.MockTransport(handler))
    result = await client.handoff(account_external_id="u1", quiz_id="5")
    assert result["url"].endswith("token=t")
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_client_gives_up_after_retries_and_rejects_4xx() -> None:
    async def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = PlayQuizClient("https://play-quiz.example/api", "k", retries=1, transport=httpx.MockTransport(down))
    with pytest.raises(PlayQuizUnavailable):
        await client.handoff(account_external_id="u1", quiz_id="5")

    async def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "bad key"})

    client = PlayQuizClient("https://play-quiz.example/api", "k", transport=httpx.MockTransport(forbidden))
    with pytest.raises(PlayQuizUnavailable):
        await client.upsert_quiz({"external_id": "q"})


# --- configurarea ---------------------------------------------------------------


def test_config_requires_partner_key_with_url() -> None:
    with pytest.raises(ValueError):
        GugutaConfig(playquiz_api_url="https://play-quiz.com/api")
    cfg = GugutaConfig(playquiz_api_url="https://play-quiz.com/api", playquiz_partner_key="k")
    assert cfg.playquiz_enabled is True
    assert GugutaConfig().playquiz_enabled is False


# --- fluxul prin API (PostgreSQL de test) ----------------------------------------


class FakePlayQuiz:
    """Server de partener simulat: numără apelurile și întoarce răspunsuri conforme cu §4."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content)
        self.calls.append((path, body))
        if path.endswith("/accounts"):
            return httpx.Response(200, json={"account_id": 7, "created": True})
        if path.endswith("/quizzes"):
            return httpx.Response(200, json={"quiz_id": 99, "play_url": "https://pq.example/quiz/custom/99"})
        if path.endswith("/handoff"):
            return httpx.Response(200, json={"url": f"https://pq.example/handoff?token={len(self.calls)}", "expires_in": 60})
        return httpx.Response(404)


@pytest_asyncio.fixture()
async def playquiz_app(guguta_db: dict[str, Any]) -> AsyncIterator[tuple[AsyncClient, FakePlayQuiz]]:
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
        PlayQuizClient("https://pq.example/api", "partner-key", transport=httpx.MockTransport(fake)),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
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
            cfg = _config(guguta_db["worker_dsn"]).model_copy(update={"chat_provider": "mock"})
            self._config = cfg
            self._engine = create_engine_for_role(cfg, "worker")
            self._storage = FilesystemStorage("./.guguta-test-storage")
            self._provider = HashEmbeddingProvider(dimension=8)
            self._stopping = __import__("asyncio").Event()

    worker = TestWorker()
    yield worker
    await worker.aclose()


async def _ready_quiz(client: AsyncClient, auth: dict[str, str], worker: Any, *, kinds: list[str]) -> tuple[str, str]:
    """Carnet + material procesat + quiz marcat gata, cu întrebări adăugate manual."""
    notebook = (
        await client.post("/api/v1/notebooks", json={"title": "Matematică"}, cookies=_cookies(auth), headers=_headers(auth))
    ).json()
    source = await client.post(
        f"/api/v1/notebooks/{notebook['id']}/sources/text",
        json={"title": "Adunarea", "text": "Trei plus patru fac șapte. Doi și opt sunt numere pare."},
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert source.status_code == 201, source.text
    await _drain(worker)
    created = await client.post(
        f"/api/v1/notebooks/{notebook['id']}/quizzes",
        json={"source_ids": [source.json()["source"]["id"]], "quantity": "fewer", "difficulty": "easy", "question_types": ["multiple_choice"]},
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
        await conn.execute(text("UPDATE quizzes SET status='ready', title='Adunarea' WHERE id=:id"), {"id": quiz_id})
    for position, kind in enumerate(kinds):
        if kind in ("multiple_choice", "multiple_select"):
            body = {
                "question_type": kind,
                "prompt": f"Întrebarea {position + 1}",
                "options": [
                    {"id": "a", "text": "7", "is_correct": True, "rationale": "3 + 4 = 7"},
                    {"id": "b", "text": "6", "is_correct": False, "rationale": "nu"},
                    {"id": "c", "text": "8", "is_correct": kind == "multiple_select", "rationale": "par"},
                ],
            }
        else:
            body = {"question_type": kind, "prompt": f"Întrebarea {position + 1}", "accepted_answers": ["șapte"]}
        added = await client.post(
            f"/api/v1/notebooks/{notebook['id']}/quizzes/{quiz_id}/questions",
            json=body,
            cookies=_cookies(auth),
            headers=_headers(auth),
        )
        assert added.status_code == 201, added.text
    return notebook["id"], quiz_id


@pytest.mark.asyncio
async def test_export_flow_consent_idempotency_and_capability(
    playquiz_app: tuple[AsyncClient, FakePlayQuiz], export_worker: Any
) -> None:
    client, fake = playquiz_app
    auth = await _login(client, f"Elev PQ {uuid.uuid4().hex[:6]}")
    me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
    assert me["capabilities"] == {"playquiz": True}
    nb, quiz = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice", "multiple_select"])
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"

    status = (await client.get(url, cookies=_cookies(auth))).json()
    assert status == {
        "enabled": True, "consent_given": False, "exportable": True, "reason": None,
        "exported": False, "play_url": None, "exported_at": None,
    }

    denied = await client.post(url, json={}, cookies=_cookies(auth), headers=_headers(auth))
    assert denied.status_code == 409 and denied.json()["code"] == "consent_required"
    assert fake.calls == []

    first = await client.post(url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth))
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True and first.json()["url"].startswith("https://pq.example/handoff?token=")
    assert [p for p, _ in fake.calls] == [
        "/api/partner/guguta/accounts", "/api/partner/guguta/quizzes", "/api/partner/guguta/handoff"
    ]
    account_body = fake.calls[0][1]
    assert account_body["external_id"] == me["id"] and "password" not in account_body
    quiz_body = fake.calls[1][1]
    assert quiz_body["external_id"] == quiz and quiz_body["account_external_id"] == me["id"]
    assert quiz_body["quiz_type"] == "MULTIPLE_CHOICE" and len(quiz_body["questions"]) == 2
    assert quiz_body["questions"][1]["answers"] == ["7", "8"]
    assert fake.calls[2][1] == {"account_external_id": me["id"], "quiz_id": "99"}

    # Al doilea click: consimțământul este reținut, quizul nu se recreează, doar handoff nou.
    second = await client.post(url, json={}, cookies=_cookies(auth), headers=_headers(auth))
    assert second.status_code == 200, second.text
    assert second.json()["created"] is False and second.json()["updated"] is False
    assert [p for p, _ in fake.calls[3:]] == ["/api/partner/guguta/handoff"]
    status = (await client.get(url, cookies=_cookies(auth))).json()
    assert status["consent_given"] is True and status["exported"] is True
    assert status["play_url"] == "https://pq.example/quiz/custom/99"

    # Conținut schimbat → re-export (cont + quiz + handoff).
    questions = (await client.get(f"/api/v1/notebooks/{nb}/quizzes/{quiz}", cookies=_cookies(auth))).json()["questions"]
    edited = await client.put(
        f"/api/v1/notebooks/{nb}/quizzes/{quiz}/questions/{questions[0]['id']}",
        json={
            "question_type": "multiple_choice", "prompt": "Întrebarea 1 (modificată)",
            "options": [{"id": "a", "text": "7", "is_correct": True, "rationale": "da"}, {"id": "b", "text": "6", "is_correct": False, "rationale": "nu"}],
        },
        cookies=_cookies(auth),
        headers=_headers(auth),
    )
    assert edited.status_code == 200, edited.text
    third = await client.post(url, json={}, cookies=_cookies(auth), headers=_headers(auth))
    assert third.status_code == 200 and third.json()["updated"] is True
    assert [p for p, _ in fake.calls[4:]] == [
        "/api/partner/guguta/accounts", "/api/partner/guguta/quizzes", "/api/partner/guguta/handoff"
    ]

    # Alt utilizator nu vede exportul (RLS) și nu găsește quizul.
    other = await _login(client, f"Alt elev {uuid.uuid4().hex[:6]}")
    assert (await client.get(url, cookies=_cookies(other))).status_code == 404


@pytest.mark.asyncio
async def test_export_refuses_mixed_quiz_and_reports_playquiz_outage(
    playquiz_app: tuple[AsyncClient, FakePlayQuiz], export_worker: Any
) -> None:
    client, fake = playquiz_app
    auth = await _login(client, f"Elev PQ {uuid.uuid4().hex[:6]}")
    nb, quiz = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice", "fill_in_blank"])
    url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
    status = (await client.get(url, cookies=_cookies(auth))).json()
    assert status["exportable"] is False and "grilă" in status["reason"]
    refused = await client.post(url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth))
    assert refused.status_code == 409 and refused.json()["code"] == "not_exportable"
    assert fake.calls == []

    nb2, quiz2 = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice"])

    async def outage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    service = client._transport.app.state.guguta_playquiz_export  # type: ignore[attr-defined]
    service._client = PlayQuizClient("https://pq.example/api", "k", retries=0, transport=httpx.MockTransport(outage))
    down = await client.post(
        f"/api/v1/notebooks/{nb2}/quizzes/{quiz2}/playquiz",
        json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth),
    )
    assert down.status_code == 503 and down.json()["code"] == "playquiz_unavailable"
    state = (await client.get(f"/api/v1/notebooks/{nb2}/quizzes/{quiz2}/playquiz", cookies=_cookies(auth))).json()
    assert state["exported"] is False


@pytest.mark.asyncio
async def test_capability_off_without_configuration(guguta_db: dict[str, Any], export_worker: Any) -> None:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]).model_copy(update={"chat_provider": "mock"}))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
        auth = await _login(client, f"Elev fără PQ {uuid.uuid4().hex[:6]}")
        me = (await client.get("/api/v1/auth/me", cookies=_cookies(auth))).json()
        assert me["capabilities"] == {"playquiz": False}
        nb, quiz = await _ready_quiz(client, auth, export_worker, kinds=["multiple_choice"])
        url = f"/api/v1/notebooks/{nb}/quizzes/{quiz}/playquiz"
        assert (await client.get(url, cookies=_cookies(auth))).json()["enabled"] is False
        off = await client.post(url, json={"consent": True}, cookies=_cookies(auth), headers=_headers(auth))
        assert off.status_code == 409 and off.json()["code"] == "playquiz_disabled"
        for legacy in ("/api/v1/auth/playquiz-profile", "/api/v1/auth/playquiz-quizzes"):
            assert (await client.get(legacy, cookies=_cookies(auth))).status_code == 404
