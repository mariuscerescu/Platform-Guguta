"""RLS isolation tests with the real runtime roles (A04/A11 groundwork, L1).

Two synthetic actors on the same pool of one connection per engine:
- A and B see only their own rows;
- B cannot read or mutate A's notebook by guessing its ID;
- no actor context -> zero rows (personal tables deny without an actor);
- actor context never survives transaction rollback + connection reuse;
- the worker role reaches the job queue without an actor but not personal data.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from open_notebook.database.guguta.engine import actor_connection, system_connection

pytestmark = pytest.mark.asyncio

ACTOR_A = uuid.uuid4()
ACTOR_B = uuid.uuid4()


async def _ensure_user(conn: AsyncConnection, actor_id: uuid.UUID, name: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO users (id, display_name, status, roles) "
            "VALUES (:id, :name, 'active', ARRAY['user']) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": actor_id, "name": name},
    )


async def _create_notebook(engine: AsyncEngine, actor_id: uuid.UUID, title: str) -> uuid.UUID:
    nb_id = uuid.uuid4()
    async with actor_connection(engine, actor_id) as conn:
        await _ensure_user(conn, actor_id, title)
        await conn.execute(
            text(
                "INSERT INTO digital_notebooks (id, owner_id, title) VALUES (:id, :o, :t)"
            ),
            {"id": nb_id, "o": actor_id, "t": title},
        )
    return nb_id


@pytest_asyncio.fixture()
async def seeded(engine_api_and_worker: tuple[AsyncEngine, AsyncEngine]) -> None:
    api_engine, _ = engine_api_and_worker
    await _create_notebook(api_engine, ACTOR_A, "Carnet A")
    await _create_notebook(api_engine, ACTOR_B, "Carnet B")


@pytest_asyncio.fixture()
async def engine_api_and_worker(
    api_engine: AsyncEngine, worker_engine: AsyncEngine
) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    yield api_engine, worker_engine


async def test_actors_see_only_their_notebooks(
    engine_api_and_worker: tuple[AsyncEngine, AsyncEngine], seeded: None
) -> None:
    api_engine, _ = engine_api_and_worker
    async with actor_connection(api_engine, ACTOR_A) as conn:
        rows = (await conn.execute(text("SELECT id, title FROM digital_notebooks"))).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "Carnet A"

    async with actor_connection(api_engine, ACTOR_B) as conn:
        rows = (await conn.execute(text("SELECT title FROM digital_notebooks"))).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Carnet B"


async def test_b_cannot_touch_a_notebook_by_id(
    engine_api_and_worker: tuple[AsyncEngine, AsyncEngine], seeded: None
) -> None:
    api_engine, _ = engine_api_and_worker
    nb_a = await _create_notebook(api_engine, ACTOR_A, "A id probe")
    async with actor_connection(api_engine, ACTOR_B) as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM digital_notebooks WHERE id = :id"), {"id": nb_a}
            )
        ).fetchall()
        assert rows == []
        result = await conn.execute(
            text("UPDATE digital_notebooks SET title = 'hacked' WHERE id = :id"),
            {"id": nb_a},
        )
        assert result.rowcount == 0
        result = await conn.execute(
            text("DELETE FROM digital_notebooks WHERE id = :id"), {"id": nb_a}
        )
        assert result.rowcount == 0


async def test_no_actor_context_denies_personal_tables(
    api_engine: AsyncEngine, seeded: None
) -> None:
    async with system_connection(api_engine) as conn:
        rows = (await conn.execute(text("SELECT count(*) FROM digital_notebooks"))).scalar()
        assert rows == 0
        rows = (await conn.execute(text("SELECT count(*) FROM users"))).scalar()
        assert rows == 0


async def test_actor_context_does_not_survive_connection_reuse(
    api_engine: AsyncEngine, seeded: None
) -> None:
    """pool_size=1: B's transaction reuses the exact connection A just used."""
    async with api_engine.connect() as conn:
        trans = await conn.begin()
        await conn.execute(
            text("SELECT set_config('app.actor_id', :a, true)"), {"a": str(ACTOR_A)}
        )
        rows = (await conn.execute(text("SELECT count(*) FROM digital_notebooks"))).scalar_one()
        assert rows >= 1  # A sees only A's rows (others created by this suite too)
        await trans.rollback()
        # Same physical connection, fresh transaction without actor context:
        rows = (await conn.execute(text("SELECT count(*) FROM digital_notebooks"))).scalar()
        assert rows == 0


async def test_b_cannot_write_chat_into_a_session(
    api_engine: AsyncEngine, seeded: None
) -> None:
    api_engine_x = api_engine
    session_a = uuid.uuid4()
    nb_a = await _create_notebook(api_engine_x, ACTOR_A, "A chat probe")
    async with actor_connection(api_engine_x, ACTOR_A) as conn:
        await conn.execute(
            text(
                "INSERT INTO chat_sessions (id, notebook_id, created_by) VALUES (:s, :n, :u)"
            ),
            {"s": session_a, "n": nb_a, "u": ACTOR_A},
        )
    async with actor_connection(api_engine_x, ACTOR_B) as conn:
        with pytest.raises(Exception):
            await conn.execute(
                text(
                    "INSERT INTO chat_messages (id, session_id, seq, role, content, context_revision) "
                    "VALUES (:id, :s, 1, 'user', 'intrusion', 1)"
                ),
                {"id": uuid.uuid4(), "s": session_a},
            )


async def test_worker_reaches_queue_but_not_personal_data(
    worker_engine: AsyncEngine, api_engine: AsyncEngine, seeded: None
) -> None:
    job_id = uuid.uuid4()
    async with actor_connection(api_engine, ACTOR_A) as conn:
        await conn.execute(
            text(
                "INSERT INTO processing_jobs (id, job_type, target_type, target_id, actor_id) "
                "VALUES (:id, 'process_material_version', 'material_version', :t, :a)"
            ),
            {"id": job_id, "t": uuid.uuid4(), "a": ACTOR_A},
        )
    async with system_connection(worker_engine) as conn:
        rows = (
            await conn.execute(
                text("SELECT id FROM processing_jobs WHERE id = :id"), {"id": job_id}
            )
        ).fetchall()
        assert len(rows) == 1  # the queue is the worker's domain
        personal = (
            await conn.execute(text("SELECT count(*) FROM digital_notebooks"))
        ).scalar()
        assert personal == 0  # ...but personal tables stay closed without an actor
        # With the validated actor, the worker may touch that user's data:
        await conn.execute(
            text("SELECT set_config('app.actor_id', :a, true)"), {"a": str(ACTOR_A)}
        )
        personal = (
            await conn.execute(text("SELECT count(*) FROM digital_notebooks"))
        ).scalar_one()
        assert personal >= 1  # ...and personal rows of that user are reachable
