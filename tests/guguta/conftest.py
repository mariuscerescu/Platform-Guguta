"""Fixtures for Guguță PostgreSQL integration tests (real migrations, real roles).

Requires a running PostgreSQL with the pgvector extension (compose:
``docker compose -f docker-compose.guguta.yml --project-name guguta up -d db``).
Tests skip when the database is unreachable so the rest of the suite stays
green in environments without Docker.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, AsyncIterator, Iterator

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy import make_url

TEST_MIGRATOR_DSN = os.environ.get(
    "GUGUTA_TEST_DATABASE_URL",
    "postgresql+psycopg://guguta_migrator:guguta_dev_migrator@127.0.0.1:5433/guguta",
)

if sys.platform == "win32":
    # psycopg async mode requires SelectorEventLoop (Proactor is default here).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
API_PASSWORD = os.environ.get("GUGUTA_PG_API_PASSWORD", "guguta_dev_api")
WORKER_PASSWORD = os.environ.get("GUGUTA_PG_WORKER_PASSWORD", "guguta_dev_worker")
TEST_DB_NAME = "guguta_test"


def _render(url: sa.URL) -> str:
    """Render a URL without masking the password.

    Plain ``str(url)`` hides the password as '***' — parsing that back
    produces literal '***' credentials and auth failures.
    """
    return url.render_as_string(hide_password=False)


def _role_dsn(role: str, password: str, database: str | None = None) -> str:
    url = make_url(TEST_MIGRATOR_DSN)
    url = url.set(
        drivername="postgresql+psycopg",
        username=role,
        password=password,
        database=database or url.database,
    )
    return _render(url)


def _server_available() -> bool:
    engine = sa.create_engine(
        make_url(TEST_MIGRATOR_DSN).set(database="postgres"),
        connect_args={"connect_timeout": 5},
    )
    try:
        with engine.connect():
            return True
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def guguta_db() -> Iterator[dict[str, Any]]:
    """Create an ephemeral test database, run migrations from zero, yield DSNs."""
    if not _server_available():
        pytest.skip(
            "PostgreSQL for Guguță tests is not reachable "
            f"({TEST_MIGRATOR_DSN}); start compose db to run these tests"
        )

    url = make_url(TEST_MIGRATOR_DSN)
    server_dsn = _render(url.set(database="postgres"))
    # All schema work and tests run against the ephemeral test database —
    # never against the main `guguta` database (which the compose migrator
    # image may have created from older code).
    test_dsn = _render(url.set(database=TEST_DB_NAME))
    engine = sa.create_engine(server_dsn, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.exec_driver_sql(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
        conn.exec_driver_sql(f'CREATE DATABASE "{TEST_DB_NAME}"')
        # Make sure runtime roles exist with dev passwords for this server.
        for role, pwd in (("guguta_api", API_PASSWORD), ("guguta_worker", WORKER_PASSWORD)):
            conn.exec_driver_sql(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') "
                f"THEN CREATE ROLE {role} LOGIN; END IF; END $$;"
            )
            conn.exec_driver_sql(
                f"ALTER ROLE {role} WITH PASSWORD '{pwd}'"
            )
    engine.dispose()

    os.environ["GUGUTA_DATABASE_URL_MIGRATOR"] = test_dsn
    from alembic.config import Config

    from alembic import command

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo_root, "alembic"))
    command.upgrade(cfg, "head")

    yield {
        "migrator_dsn": test_dsn,
        "api_dsn": _role_dsn("guguta_api", API_PASSWORD, TEST_DB_NAME),
        "worker_dsn": _role_dsn("guguta_worker", WORKER_PASSWORD, TEST_DB_NAME),
    }

    cleanup = sa.create_engine(server_dsn, isolation_level="AUTOCOMMIT")
    with cleanup.connect() as conn:
        conn.exec_driver_sql(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        )
        conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"')
    cleanup.dispose()


@pytest.fixture()
def migrator_engine(guguta_db: dict[str, Any]) -> sa.Engine:
    return sa.create_engine(guguta_db["migrator_dsn"])


@pytest_asyncio.fixture()
async def api_engine(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    """Pool of exactly one connection: proves actor context never survives reuse."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        guguta_db["api_dsn"],
        pool_size=1,
        max_overflow=0,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def worker_engine(guguta_db: dict[str, Any]) -> AsyncIterator[Any]:
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        guguta_db["worker_dsn"],
        pool_size=1,
        max_overflow=0,
    )
    try:
        yield engine
    finally:
        await engine.dispose()
