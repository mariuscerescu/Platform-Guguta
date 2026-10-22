"""Înregistrare cu școală, clasă și consimțăminte; profil propriu; ștergerea contului."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.routers.guguta_v1 import PRIVACY_POLICY_VERSION, _normalize_class_level
from open_notebook.exceptions import InvalidInputError
from tests.guguta.test_materials_worker import _config

ORIGIN = {"Origin": "http://localhost:3000"}


@pytest.mark.parametrize(
    "raw,expected",
    [("V", "V"), ("5", "V"), ("a V-a", "V"), ("clasa a 5-a", "V"), (" xii ", "XII"), ("1", "I")],
)
def test_class_level_normalization(raw: str, expected: str) -> None:
    assert _normalize_class_level(raw) == expected


@pytest.mark.parametrize("raw", ["0", "13", "XIII", "a treia", ""])
def test_class_level_rejects_out_of_range(raw: str) -> None:
    with pytest.raises(InvalidInputError):
        _normalize_class_level(raw)


@pytest_asyncio.fixture()
async def password_client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(
        _config(guguta_db["api_dsn"]).model_copy(update={"chat_provider": "mock", "auth_mode": "password"})
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost:3000") as client:
        yield client


def _registration(**overrides: Any) -> dict[str, Any]:
    body = {
        "first_name": "Ana",
        "last_name": "Popescu",
        "email": f"ana.{uuid.uuid4().hex[:8]}@exemplu.md",
        "password": "parola-secreta-1",
        "school": "Liceul Teoretic „Mihai Eminescu”, Chișinău",
        "class_level": "a 5-a",
        "privacy_accepted": True,
        "parent_consent": True,
    }
    body.update(overrides)
    return body


async def _register(client: AsyncClient, **overrides: Any) -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    body = _registration(**overrides)
    resp = await client.post("/api/v1/auth/register", json=body, headers=ORIGIN)
    assert resp.status_code == 200, resp.text
    session = resp.cookies.get("guguta_session")
    assert session is not None
    auth = {"guguta_session": session}
    headers = {"X-Guguta-CSRF": resp.headers.get("X-Guguta-CSRF", ""), **ORIGIN}
    return body, auth, headers


@pytest.mark.asyncio
async def test_register_requires_privacy_and_parent_consent(password_client: AsyncClient) -> None:
    config = (await password_client.get("/api/v1/auth/config")).json()
    assert config == {"auth_mode": "password", "privacy_version": PRIVACY_POLICY_VERSION}

    refused = await password_client.post(
        "/api/v1/auth/register", json=_registration(privacy_accepted=False), headers=ORIGIN
    )
    assert refused.status_code == 422 and "confidențialitate" in refused.json()["message"]

    minor = await password_client.post(
        "/api/v1/auth/register", json=_registration(class_level="III", parent_consent=False), headers=ORIGIN
    )
    assert minor.status_code == 422 and "părinte" in minor.json()["message"]

    # Clasa a IX-a nu cere confirmarea părintelui.
    older = await password_client.post(
        "/api/v1/auth/register", json=_registration(class_level="IX", parent_consent=False), headers=ORIGIN
    )
    assert older.status_code == 200, older.text

    bad_class = await password_client.post(
        "/api/v1/auth/register", json=_registration(class_level="XIII"), headers=ORIGIN
    )
    assert bad_class.status_code == 422


@pytest.mark.asyncio
async def test_me_exposes_profile_and_consents_then_patch(password_client: AsyncClient) -> None:
    body, cookies, headers = await _register(password_client)
    me = (await password_client.get("/api/v1/auth/me", cookies=cookies)).json()
    assert me["display_name"] == "Ana Popescu"
    assert me["email"] == body["email"]
    assert me["school"] == body["school"]
    assert me["class_level"] == "V"
    assert me["consents"] == {
        "privacy": PRIVACY_POLICY_VERSION,
        "terms": PRIVACY_POLICY_VERSION,
        "parent": PRIVACY_POLICY_VERSION,
    }

    patched = await password_client.patch(
        "/api/v1/auth/me", json={"school": "Gimnaziul Nr. 7", "class_level": "6"}, cookies=cookies, headers=headers
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["school"] == "Gimnaziul Nr. 7" and patched.json()["class_level"] == "VI"

    empty = await password_client.patch("/api/v1/auth/me", json={}, cookies=cookies, headers=headers)
    assert empty.status_code == 422

    # Alt utilizator nu vede profilul primului.
    _, other_cookies, _ = await _register(password_client, first_name="Ion")
    other = (await password_client.get("/api/v1/auth/me", cookies=other_cookies)).json()
    assert other["display_name"] == "Ion Popescu" and other["school"] == body["school"]


@pytest.mark.asyncio
async def test_delete_account_removes_notebooks_credentials_and_session(password_client: AsyncClient) -> None:
    body, cookies, headers = await _register(password_client)
    notebook = await password_client.post(
        "/api/v1/notebooks", json={"title": "Al meu"}, cookies=cookies, headers=headers
    )
    assert notebook.status_code == 201, notebook.text

    deleted = await password_client.delete("/api/v1/auth/me", cookies=cookies, headers=headers)
    assert deleted.status_code == 200 and deleted.json() == {"ok": True}

    # Sesiunea nu mai este valabilă, autentificarea cu parola nu mai merge, e-mailul e liber.
    assert (await password_client.get("/api/v1/auth/me", cookies=cookies)).status_code == 401
    login = await password_client.post(
        "/api/v1/auth/login", json={"email": body["email"], "password": body["password"]}, headers=ORIGIN
    )
    assert login.status_code == 401
    again = await password_client.post("/api/v1/auth/register", json=_registration(email=body["email"]), headers=ORIGIN)
    assert again.status_code == 200, again.text
    session = again.cookies.get("guguta_session")
    assert session is not None
    fresh = {"guguta_session": session}
    notebooks = (await password_client.get("/api/v1/notebooks", cookies=fresh)).json()
    assert all(item["title"] != "Al meu" for item in (notebooks if isinstance(notebooks, list) else notebooks.get("items", [])))
