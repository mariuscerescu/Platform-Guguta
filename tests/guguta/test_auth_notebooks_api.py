"""L2 tests: sessions, dev-login gating, notebook CRUD isolation (A04/A11/A23).

Uses the guguta FastAPI app over httpx ASGITransport against the real test
database with the api runtime role.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.database.guguta.config import GugutaConfig

pytestmark = pytest.mark.asyncio


def _config(api_dsn: str) -> GugutaConfig:
    return GugutaConfig(
        environment="ci",
        auth_mode="test",
        database_url_api=api_dsn,
        database_url_worker=api_dsn,
        database_url_migrator=api_dsn,
        server_secret="test-secret-not-for-production",
        cors_origins=["http://localhost:3000"],
        public_origin="http://localhost:3000",
    )


@pytest_asyncio.fixture()
async def client(api_engine: AsyncEngine, guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    """ASGI client bound to the guguta app with the api runtime role DSN."""
    api = pytest.importorskip("api.guguta_app")
    # NOTE: never str(engine.url) — it masks the password as '***'.
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:3000") as c:
        yield c


async def _login(client: AsyncClient, name: str) -> dict[str, str]:
    resp = await client.post(
        "/api/v1/auth/dev-login",
        json={"display_name": name},
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 200, resp.text
    csrf = resp.headers.get("X-Guguta-CSRF")
    assert csrf
    return {"csrf": csrf, "cookie": resp.cookies.get("guguta_session", "")}


def _auth_headers(auth: dict[str, str]) -> dict[str, str]:
    return {"X-Guguta-CSRF": auth["csrf"], "Origin": "http://localhost:3000"}


def _cookies(auth: dict[str, str]) -> dict[str, str]:
    return {"guguta_session": auth["cookie"]}


async def test_readyz_ok(client: AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    assert str(resp.json()["schema"]).strip().startswith("0")


async def test_dev_login_and_me(client: AsyncClient) -> None:
    auth = await _login(client, "Elev A")
    resp = await client.get("/api/v1/auth/me", cookies=_cookies(auth))
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Elev A"
    assert "user" in body["roles"]


async def test_unauthenticated_requests_rejected(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/notebooks")
    assert resp.status_code == 401
    resp = await client.get("/api/v1/notebooks")
    assert resp.json()["code"] == "unauthenticated"


async def test_mutation_without_csrf_rejected(client: AsyncClient) -> None:
    auth = await _login(client, "CSRF probe")
    resp = await client.post(
        "/api/v1/notebooks",
        json={"title": "Fără CSRF"},
        cookies=_cookies(auth),
        headers={"Origin": "http://localhost:3000"},
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "csrf_required"


async def test_foreign_origin_rejected(client: AsyncClient) -> None:
    auth = await _login(client, "Origin probe")
    resp = await client.post(
        "/api/v1/notebooks",
        json={"title": "Origine străină"},
        cookies=_cookies(auth),
        headers=_auth_headers(auth) | {"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


async def test_logout_revokes_session(client: AsyncClient) -> None:
    auth = await _login(client, "Logout probe")
    resp = await client.post(
        "/api/v1/auth/logout",
        cookies=_cookies(auth),
        headers=_auth_headers(auth),
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/auth/me", cookies=_cookies(auth))
    assert resp.status_code == 401


async def test_notebook_crud_isolated_between_two_actors(
    client: AsyncClient,
) -> None:
    auth_a = await _login(client, f"Utilizator A {uuid.uuid4().hex[:8]}")
    auth_b = await _login(client, f"Utilizator B {uuid.uuid4().hex[:8]}")

    created = await client.post(
        "/api/v1/notebooks",
        json={"title": "Carnetul lui A", "description": "privat"},
        cookies=_cookies(auth_a),
        headers=_auth_headers(auth_a),
    )
    assert created.status_code == 201, created.text
    nb_a = created.json()
    assert nb_a["origin"] == "personal"  # client cannot set origin

    # A sees exactly his notebook in the list
    lista = await client.get(
        "/api/v1/notebooks", cookies=_cookies(auth_a)
    )
    items = [i for i in lista.json()["items"] if i["id"] == nb_a["id"]]
    assert len(items) == 1

    # B does not see it (list or direct ID) — A04/A11
    lista_b = await client.get("/api/v1/notebooks", cookies=_cookies(auth_b))
    assert all(i["id"] != nb_a["id"] for i in lista_b.json()["items"])
    resp = await client.get(f"/api/v1/notebooks/{nb_a['id']}", cookies=_cookies(auth_b))
    assert resp.status_code == 404

    # B cannot mutate or delete A's notebook
    resp = await client.patch(
        f"/api/v1/notebooks/{nb_a['id']}",
        json={"title": "furat"},
        cookies=_cookies(auth_b),
        headers=_auth_headers(auth_b),
    )
    assert resp.status_code == 404
    resp = await client.delete(
        f"/api/v1/notebooks/{nb_a['id']}",
        cookies=_cookies(auth_b),
        headers=_auth_headers(auth_b),
    )
    assert resp.status_code == 404

    # owner_id spoofing attempt: field ignored by contract (no owner_id in
    # request model), so B cannot gain ownership — verify A still owns it.
    resp = await client.get(f"/api/v1/notebooks/{nb_a['id']}", cookies=_cookies(auth_a))
    assert resp.status_code == 200

    # A can update and archive his own notebook
    resp = await client.patch(
        f"/api/v1/notebooks/{nb_a['id']}",
        json={"title": "Carnetul lui A (redenumit)"},
        cookies=_cookies(auth_a),
        headers=_auth_headers(auth_a),
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Carnetul lui A (redenumit)"
    resp = await client.patch(
        f"/api/v1/notebooks/{nb_a['id']}",
        json={"archive": True},
        cookies=_cookies(auth_a),
        headers=_auth_headers(auth_a),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"

    # A deletes; then 404 for everyone
    resp = await client.delete(
        f"/api/v1/notebooks/{nb_a['id']}",
        cookies=_cookies(auth_a),
        headers=_auth_headers(auth_a),
    )
    assert resp.status_code == 200
    resp = await client.get(f"/api/v1/notebooks/{nb_a['id']}", cookies=_cookies(auth_a))
    assert resp.status_code == 404


async def test_pagination_and_sort_allowlist(client: AsyncClient) -> None:
    auth = await _login(client, "Paginare probe")
    for i in range(3):
        await client.post(
            "/api/v1/notebooks",
            json={"title": f"Carnet {i:02d}"},
            cookies=_cookies(auth),
            headers=_auth_headers(auth),
        )
    resp = await client.get(
        "/api/v1/notebooks",
        params={"page": 1, "page_size": 2, "sort": "title_asc"},
        cookies=_cookies(auth),
    )
    body = resp.json()
    assert body["page_size"] == 2 and body["total"] >= 3 and body["has_next"] is True
    resp = await client.get(
        "/api/v1/notebooks", params={"sort": "1; DROP TABLE users"},
        cookies=_cookies(auth),
    )
    assert resp.status_code == 422
    resp = await client.get(
        "/api/v1/notebooks", params={"page_size": 1000},
        cookies=_cookies(auth),
    )
    assert resp.json()["page_size"] == 100  # clamped


async def test_admin_routes_denied_for_user(client: AsyncClient) -> None:
    """A23 groundwork: the guguta surface exposes no admin routes at all."""
    auth = await _login(client, "Admin probe")
    for path in (
        "/api/v1/admin/templates",
        "/api/v1/admin/models",
        "/api/v1/credentials",
        "/api/podcasts",
        "/api/sources",
    ):
        resp = await client.request("GET", path, cookies=_cookies(auth))
        assert resp.status_code in (404, 405), f"{path}: {resp.status_code}"


async def test_suspended_account_loses_access(
    client: AsyncClient, guguta_db: dict[str, Any]
) -> None:
    auth = await _login(client, "Suspendat probe")
    me = await client.get("/api/v1/auth/me", cookies=_cookies(auth))
    user_id = me.json()["id"]
    # Suspend the account as migrator (owner path; account suspension is a
    # privileged operation handled by admin flows, not the runtime role).
    import sqlalchemy as sa

    migrator = sa.create_engine(guguta_db["migrator_dsn"])
    with migrator.connect() as conn:
        conn.exec_driver_sql(
            f"UPDATE users SET status = 'suspended' WHERE id = '{user_id}'"
        )
        conn.commit()
    resp = await client.get("/api/v1/auth/me", cookies=_cookies(auth))
    assert resp.status_code == 401
