"""Real PostgreSQL/API/worker pipeline. Live provider calls require explicit opt-in."""
import json
import os
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from api.guguta_app import create_guguta_app
from open_notebook.ai.guguta.openrouter import OpenRouterClient
from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import actor_connection, system_connection
from open_notebook.jobs.guguta.worker import Worker
from tests.guguta.test_materials_worker import _config


async def run_pipeline(guguta_db, tmp_path, monkeypatch, live):
    cfg = _config(guguta_db["api_dsn"]).model_copy(update={
        "database_url_worker": guguta_db["worker_dsn"],
        "storage_root": str(tmp_path / "storage"),
        "chat_provider": "openrouter", "embedding_provider": "openrouter",
        "embedding_dimension": 2048, "rerank_provider": "openrouter",
        "openrouter_api_key": GugutaConfig(_env_file=".env.guguta.local").openrouter_api_key
        if live else GugutaConfig(_env_file=None, openrouter_api_key="synthetic").openrouter_api_key,
    })
    app = create_guguta_app(cfg)
    worker = Worker(cfg)
    original = OpenRouterClient.post
    calls = []

    async def post(client, endpoint, payload):
        # Regression: never retain an API/worker DB connection during external AI.
        assert app.state.guguta_engine.pool.checkedout() == 0
        assert getattr(worker._engine.pool, "checkedout")() == 0
        calls.append((endpoint, payload["model"]))
        if live:
            return await original(client, endpoint, payload)
        if endpoint == "embeddings":
            return {"data": [{"index": i, "embedding": [1.0] * 2048} for i, _ in enumerate(payload["input"])]}
        if endpoint == "rerank":
            assert all("NESELECTAT" not in doc for doc in payload["documents"])
            order = sorted(range(len(payload["documents"])), key=lambda i: "Fotosinteza" not in payload["documents"][i])
            return {"results": [{"index": i, "relevance_score": 1 - pos * 0.1} for pos, i in enumerate(order[:payload["top_n"]])]}
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"answer": "Plantele folosesc lumina pentru fotosinteză [1].", "cited": [0]})}}], "usage": {"prompt_tokens": 80, "completion_tokens": 20, "cost": 0}}

    monkeypatch.setattr(OpenRouterClient, "post", post)
    old_space = None
    try:
        async with system_connection(worker._engine) as conn:
            await conn.execute(text("UPDATE processing_jobs SET status='cancelled' WHERE status IN ('queued','running','claimed')"))
        # Fresh namespace: original tests may have activated the hash embedding space.
        import sqlalchemy as sa
        db = sa.create_engine(guguta_db["migrator_dsn"])
        with db.begin() as sync_conn:
            old_space = sync_conn.execute(text("SELECT id FROM embedding_spaces WHERE is_active")).scalar_one_or_none()
            sync_conn.execute(text("UPDATE embedding_spaces SET is_active=false WHERE is_active"))
        db.dispose()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
            login = await client.post("/api/v1/auth/dev-login", json={"display_name": "Synthetic OpenRouter " + uuid.uuid4().hex})
            assert login.status_code == 200
            headers = {"X-Guguta-CSRF": login.headers["X-Guguta-CSRF"], "Origin": "http://localhost:3000"}
            nb = (await client.post("/api/v1/notebooks", headers=headers, json={"title": "Synthetic OpenRouter"})).json()["id"]
            source_ids = []
            for title, content in [("Biologie", "Fotosinteza folosește energia luminii pentru a transforma apa și dioxidul de carbon în substanțe organice, eliberând oxigen."),
                                   ("Geometrie", "Un triunghi are trei laturi și trei unghiuri."),
                                   ("Ascuns", "NESELECTAT: Acest material nu trebuie transmis la reranker sau LLM.")]:
                response = await client.post(f"/api/v1/notebooks/{nb}/sources/text", headers=headers, json={"title": title, "text": content})
                assert response.status_code == 201
                sid = response.json()["source"]["id"]
                source_ids.append(sid)
                assert await worker.process_one()
                assert (await client.get(f"/api/v1/notebooks/{nb}/sources/{sid}")).json()["status"] == "ready"
            assert (await client.patch(f"/api/v1/notebooks/{nb}/sources/{source_ids[2]}", headers=headers, json={"selected_for_chat": False})).status_code == 200
            session = (await client.post(f"/api/v1/notebooks/{nb}/sessions", headers=headers, json={})).json()["id"]
            result = await client.post(f"/api/v1/notebooks/{nb}/sessions/{session}/messages", headers=headers,
                                      json={"content": "De ce au plantele nevoie de lumină?", "idempotency_key": uuid.uuid4().hex})
            assert result.status_code == 200, result.text
            messages = (await client.get(f"/api/v1/notebooks/{nb}/sessions/{session}/messages")).json()
            answer = messages[-1]
            assert "lumin" in answer["content"].lower() and answer["status"] == "complete"
            citations = (await client.get(f"/api/v1/notebooks/{nb}/sessions/{session}/messages/{answer['id']}/citations")).json()
            assert citations and all(str(c["notebook_source_id"]) != source_ids[2] for c in citations)
            async with actor_connection(app.state.guguta_engine, uuid.UUID(login.json()["id"])) as conn:
                row = (await conn.execute(text("SELECT model,prompt_tokens,completion_tokens,prompt_version FROM chat_messages WHERE id=:id"), {"id": uuid.UUID(answer["id"])})).mappings().one()
            assert row["model"] == cfg.openrouter_chat_model and row["prompt_version"] == "guguta-openrouter-grounded-7"
            assert row["prompt_tokens"] > 0 and row["completion_tokens"] > 0
            assert {e for e, _ in calls} == {"embeddings", "rerank", "chat/completions"}
            if live:
                path = Path("docs/guguta/openrouter-live-results.json")
                path.write_text(json.dumps({"date": "2026-09-07", "passed": True,
                    "calls": calls, "embedding_dimension": 2048, "answer": answer["content"],
                    "citations": len(citations), "usage": dict(row),
                    "no_sql_connection_during_ai": True}, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        import sqlalchemy as sa
        restore = sa.create_engine(guguta_db["migrator_dsn"])
        with restore.begin() as sync_conn:
            sync_conn.execute(text("UPDATE embedding_spaces SET is_active=false WHERE is_active"))
            if old_space is not None:
                sync_conn.execute(text("UPDATE embedding_spaces SET is_active=true WHERE id=:s"), {"s": old_space})
        restore.dispose()
        await worker.aclose()
        await app.state.guguta_engine.dispose()


@pytest.mark.asyncio
async def test_openrouter_pipeline_contract(guguta_db, tmp_path, monkeypatch):
    await run_pipeline(guguta_db, tmp_path, monkeypatch, False)


@pytest.mark.asyncio
async def test_reindex_preserves_active_space_on_failure_and_resumes(guguta_db, tmp_path, monkeypatch):
    import sqlalchemy as sa

    from open_notebook.ai.guguta.openrouter import (
        OpenRouterEmbeddingProvider,
        OpenRouterError,
    )
    from scripts.guguta_reindex_openrouter import reindex

    await run_pipeline(guguta_db, tmp_path, monkeypatch, False)
    db = sa.create_engine(guguta_db["migrator_dsn"])
    previous = uuid.uuid4()
    with db.begin() as conn:
        original = conn.execute(text("SELECT id FROM embedding_spaces WHERE is_active")).scalar_one_or_none()
        conn.execute(text("UPDATE embedding_spaces SET is_active=false WHERE is_active"))
        conn.execute(text("INSERT INTO embedding_spaces(id,model_name,model_revision,dimension,distance_strategy,is_active) VALUES(:id,'synthetic-old','1',8,'cosine',true)"), {"id": previous})
    cfg = GugutaConfig(_env_file=None, database_url_migrator=guguta_db["migrator_dsn"],
        embedding_provider="openrouter", embedding_dimension=2048, openrouter_api_key="synthetic",
        openrouter_embedding_revision="reindex-synthetic-" + uuid.uuid4().hex)
    async def fail(provider, texts):
        raise OpenRouterError("synthetic transient failure")
    monkeypatch.setattr(OpenRouterEmbeddingProvider, "embed", fail)
    try:
        with pytest.raises(OpenRouterError):
            await reindex(cfg)
        with db.connect() as conn:
            assert conn.execute(text("SELECT id FROM embedding_spaces WHERE is_active")).scalar_one() == previous
        async def succeed(provider, texts):
            return [[1.0] * 2048 for _ in texts]
        monkeypatch.setattr(OpenRouterEmbeddingProvider, "embed", succeed)
        assert await reindex(cfg) >= 3
        assert await reindex(cfg) == 0
        with db.connect() as conn:
            assert conn.execute(text("SELECT model_revision FROM embedding_spaces WHERE is_active")).scalar_one() == cfg.openrouter_embedding_revision
            missing = conn.execute(text("SELECT count(*) FROM chunks c WHERE NOT EXISTS (SELECT 1 FROM embeddings e JOIN embedding_spaces s ON s.id=e.embedding_space_id WHERE e.chunk_id=c.id AND s.is_active)")).scalar_one()
            assert missing == 0
    finally:
        with db.begin() as conn:
            conn.execute(text("UPDATE embedding_spaces SET is_active=false WHERE is_active"))
            if original is not None:
                conn.execute(text("UPDATE embedding_spaces SET is_active=true WHERE id=:id"), {"id": original})
        db.dispose()


@pytest.mark.skipif(os.environ.get("GUGUTA_LIVE_OPENROUTER") != "1", reason="Explicit live opt-in required")
@pytest.mark.asyncio
async def test_openrouter_pipeline_live(guguta_db, tmp_path, monkeypatch):
    await run_pipeline(guguta_db, tmp_path, monkeypatch, True)
