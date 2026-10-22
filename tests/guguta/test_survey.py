"""Public feedback: real persistence, anonymity boundary, aggregation and retries."""
from __future__ import annotations

import copy
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from api.services.guguta.survey import (
    QUESTIONS,
    SURVEY_VERSION,
    SurveyService,
    validate_answers,
)
from open_notebook.exceptions import InvalidInputError


def answers() -> dict[str, Any]:
    return {q["id"]: "" if q["type"] == "text" else [q["options"][0]["value"]]
            if q["type"] == "multiple" else q["options"][0]["value"] for q in QUESTIONS}


def test_exactly_twenty_questions_and_strict_answers() -> None:
    assert len(QUESTIONS) == 20
    assert [q["number"] for q in QUESTIONS] == list(range(1, 21))
    assert [q["id"] for q in QUESTIONS if not q["required"]] == ["q19", "q20"]
    assert validate_answers(answers()) == answers()
    for changes in ({"q04": True}, {"q16": ["none", "voice"]}, {"q16": ["voice", "voice"]},
                    {"q17": ["read", "listen", "images", "practice"]}, {"q19": "me@example.org"},
                    {"q20": "+373 600 12 345"}, {"q20": "x" * 1001}):
        with pytest.raises(InvalidInputError):
            validate_answers(answers() | changes)


@pytest.mark.asyncio
async def test_anonymous_submit_public_results_and_retries(guguta_db: dict[str, Any], migrator_engine: Any) -> None:
    from api.guguta_app import create_guguta_app
    from open_notebook.database.guguta.config import GugutaConfig

    app = create_guguta_app(GugutaConfig(environment="ci", auth_mode="test",
        database_url_api=guguta_db["api_dsn"], database_url_worker=guguta_db["worker_dsn"],
        database_url_migrator=guguta_db["migrator_dsn"], server_secret="survey-test-secret",
        cors_origins=["http://localhost:3000"], public_origin="http://localhost:3000"))
    # Even a browser with an existing account cookie must not resolve identity.
    app.state.guguta_sessions.resolve_actor = AsyncMock(side_effect=AssertionError("survey looked up identity"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:3000", cookies={"guguta_session": "ignored-account-cookie"}) as client:
        definition = await client.get("/api/v1/survey")
        assert len(definition.json()["questions"]) == 20
        assert definition.headers["cache-control"] == "no-store"
        nonce = (await client.get("/api/v1/survey/session")).json()
        payload = nonce | {"version": SURVEY_VERSION, "acknowledged": True,
                           "answers": answers() | {"q04": "5", "q05": "na", "q16": ["chat", "voice"],
                                                   "q19": "Mi-a plăcut vocea.", "q20": "=1+1"}}
        headers = {"Origin": "http://localhost:3000", "X-Guguta-Survey": "1"}
        # Origin and explicit participation acknowledgement are mandatory.
        assert (await client.post("/api/v1/survey/responses", json=payload, headers=headers | {"Origin": "https://other.example"})).status_code == 403
        assert (await client.post("/api/v1/survey/responses", json=payload | {"acknowledged": False}, headers=headers)).status_code == 422
        assert (await client.post("/api/v1/survey/responses", json=payload | {"user_id": str(uuid.uuid4())}, headers=headers)).status_code == 422
        forged = payload | {"submission_id": str(uuid.uuid4())}
        assert (await client.post("/api/v1/survey/responses", json=forged, headers=headers)).status_code == 422
        for _ in range(2):
            response = await client.post("/api/v1/survey/responses", json=payload, headers=headers)
            assert response.status_code == 201, response.text
        # A retry with different content still cannot alter the accepted opinion.
        changed = copy.deepcopy(payload)
        changed["answers"]["q04"] = "1"
        assert (await client.post("/api/v1/survey/responses", json=changed, headers=headers)).status_code == 201
        result = (await client.get("/api/v1/survey/results")).json()
        assert result["total"] == 1
        assert result["questions"][3]["mean"] == 5
        assert result["questions"][4]["mean"] is None
        assert result["questions"][4]["rated_count"] == 0
        assert sum(o["count"] for o in result["questions"][15]["options"]) == 2
        assert nonce["submission_id"] not in str(result)
        comments = (await client.get("/api/v1/survey/comments?question=q19")).json()
        assert comments == {"comments": ["Mi-a plăcut vocea."], "offset": 0}
        exported = (await client.get("/api/v1/survey/export.csv")).text
        assert "Mi-a plăcut vocea." in exported
        assert "'=1+1" in exported
        assert nonce["submission_id"] not in exported
        app.state.guguta_sessions.resolve_actor.assert_not_awaited()
    async with app.state.guguta_engine.connect() as conn:
        # API role cannot read raw per-pupil answer profiles or timestamps.
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(text("SELECT * FROM survey_responses"))
    with migrator_engine.connect() as conn:
        columns = set(conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='survey_responses'" )).scalars())
        assert columns == {"submission_id", "version", "submitted_on", "answers"}
        assert conn.execute(text("SELECT count(*) FROM survey_responses")).scalar_one() == 1
    await app.state.guguta_engine.dispose()


def test_submission_tokens_expire(monkeypatch: Any) -> None:
    service = SurveyService(AsyncMock(), "test-secret")
    nonce = service.start()
    monkeypatch.setattr("api.services.guguta.survey.time.time", lambda: 9_999_999_999)
    with pytest.raises(InvalidInputError, match="expirat"):
        service._verify(uuid.UUID(nonce["submission_id"]), nonce["token"])
