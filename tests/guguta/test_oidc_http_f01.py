"""F01/F02 regression: the full OIDC flow over real HTTP routes, with a
cookie jar — login → fake issuer → callback → me → CSRF mutation → logout.
Plus F14 negative startup tests for the production configuration."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from authlib.jose import JsonWebToken
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient

from open_notebook.auth.guguta.oidc import OidcClient, OidcConfig
from open_notebook.database.guguta.config import GugutaConfig
from tests.guguta.test_materials_worker import _config

pytestmark = pytest.mark.asyncio

ISSUER = "https://fake-issuer.example"


def _int_b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _fake_oidc_transport() -> tuple[httpx.AsyncClient, dict[str, dict[str, Any]]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwk = {"kty": "RSA", "n": _int_b64(pub.n), "e": _int_b64(pub.e),
           "kid": "test-key", "alg": "RS256", "use": "sig"}
    jwks = {"keys": [jwk]}
    issued: dict[str, dict[str, Any]] = {}
    jwt = JsonWebToken(["RS256"])

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                # F02: a NON-default authorization path, served from discovery
                "authorization_endpoint": f"{ISSUER}/oauth2/v1/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks.json",
            })
        if url.endswith("/jwks.json"):
            return httpx.Response(200, json=jwks)
        if url.endswith("/token"):
            form = dict(
                pair.split("=", 1) for pair in request.content.decode().split("&")
            )
            meta = issued.pop(form.get("code", ""), None)
            if meta is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            now = int(time.time())
            claims = {
                "iss": ISSUER, "aud": form.get("client_id", ""), "sub": "oidc-sub-7",
                "nonce": meta["nonce"], "email": "elev@scoala.md",
                "email_verified": True, "name": "Elev OIDC",
                "iat": now, "exp": now + 600,
            }
            token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)
            return httpx.Response(200, json={
                "id_token": token.decode(), "access_token": "at",
                "token_type": "Bearer",
            })
        return httpx.Response(404)

    return (
        httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10),
        issued,
    )


def _oidc_config() -> GugutaConfig:
    base = _config(
        "postgresql+psycopg://guguta_api:guguta_dev_api@127.0.0.1:5433/guguta_test"
    )
    return base.model_copy(
        update={
            "auth_mode": "oidc",
            "oidc_issuer": ISSUER,
            "oidc_client_id": "guguta-dev",
            "oidc_client_secret": "s",
            "oidc_redirect_uri": "http://localhost:3001/api/v1/auth/oidc/callback",
            "public_origin": "http://localhost:3001",
            "cors_origins": ["http://localhost:3001", "http://localhost:3000"],
        }
    )


@pytest_asyncio.fixture()
async def oidc_app_client(guguta_db: dict[str, Any]) -> AsyncIterator[tuple[AsyncClient, dict[str, dict[str, Any]]]]:
    """App with auth_mode=oidc and the OIDC client backed by the fake issuer."""
    api = pytest.importorskip("api.guguta_app")
    # Use the isolated fixture's actual port/roles rather than assuming 5433.
    app = api.create_guguta_app(_oidc_config().model_copy(update={
        "database_url_api":guguta_db["api_dsn"],
        "database_url_worker":guguta_db["worker_dsn"],
        "database_url_migrator":guguta_db["migrator_dsn"],
    }))
    http_client, issued = _fake_oidc_transport()
    # inject the fake-issuer-backed client over the real one (F01 HTTP path)
    app.state.guguta_oidc = OidcClient(
        OidcConfig(issuer=ISSUER, client_id="guguta-dev",
                   client_secret="s", redirect_uri="http://localhost:3001/api/v1/auth/oidc/callback"),
        http=http_client,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3001"
    ) as c:
        yield c, issued
    await http_client.aclose()


async def test_oidc_full_http_flow_f01(oidc_app_client: tuple[AsyncClient, dict]) -> None:
    client, issued = oidc_app_client

    # 1. login redirect carries the state cookie ON the redirect itself (F01)
    r = await client.get("/api/v1/auth/oidc/login")
    assert r.status_code == 307, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "guguta_oidc_state=" in set_cookie
    state_cookie = set_cookie.split(";")[0]

    # 2. the authorize URL uses the DISCOVERY authorization endpoint (F02)
    assert "/oauth2/v1/authorize" in r.headers["location"]

    # 3. callback: exchange, provision, session cookie + CSRF on the redirect
    qs = parse_qs(urlparse(r.headers["location"]).query)
    code = "real-http-code"
    issued[code] = {"nonce": _nonce_from_state_cookie(
        "guguta_oidc_state=" + state_cookie.split("=", 1)[1])}
    r2 = await client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": code, "state": qs["state"][0]},
        headers={"Cookie": state_cookie},
    )
    assert r2.status_code == 303, r2.text
    set_session = r2.headers.get("set-cookie", "")
    assert "guguta_session=" in set_session  # F01: session cookie present
    csrf = r2.headers.get("X-Guguta-CSRF")
    assert csrf

    # 4. authenticated me() with the session cookie
    session_cookie = set_session.split(";")[0]
    me = await client.get(
        "/api/v1/auth/me", headers={"Cookie": session_cookie}
    )
    assert me.status_code == 200, me.text
    assert me.json()["display_name"] == "Elev OIDC"

    # 5. authenticated mutation with CSRF header
    h = {"Cookie": session_cookie, "X-Guguta-CSRF": csrf,
         "Origin": "http://localhost:3001"}
    nb = await client.post("/api/v1/notebooks", json={"title": "OIDC carnet"},
                           headers=h)
    assert nb.status_code == 201, nb.text

    # 6. logout revokes the session
    out = await client.post(
        "/api/v1/auth/logout", headers={"Cookie": session_cookie}
    )
    assert out.status_code == 200
    me2 = await client.get("/api/v1/auth/me", headers={"Cookie": session_cookie})
    assert me2.status_code == 401


def _nonce_from_state_cookie(state_cookie_header: str) -> str:
    """Extract the nonce from the signed state cookie value (test helper)."""
    value = state_cookie_header.split("=", 1)[1]
    body = value.split(".")[0]
    decoded = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    return decoded["nonce"]


@pytest_asyncio.fixture()
async def client(guguta_db: dict[str, Any]) -> AsyncIterator[AsyncClient]:
    api = pytest.importorskip("api.guguta_app")
    app = api.create_guguta_app(_config(guguta_db["api_dsn"]))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://localhost:3001"
    ) as c:
        yield c


async def test_oidc_routes_refused_in_test_mode(client: AsyncClient) -> None:
    r = await client.get("/api/v1/auth/oidc/login")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# F14: production configuration is fail-closed
# ---------------------------------------------------------------------------


def _base_production() -> dict[str, Any]:
    return {
        "environment": "production",
        "auth_mode": "oidc",
        "database_url_api": "postgresql+psycopg://api:s@db:5432/guguta",
        "database_url_worker": "postgresql+psycopg://worker:s@db:5432/guguta",
        "server_secret": "x" * 32,
        "credential_encryption_keys": {"k1": "y" * 32},
        "credential_key_primary_id": "k1",
        "public_origin": "https://guguta.md",
        "cors_origins": ["https://guguta.md"],
        "oidc_issuer": "https://idp.guguta.md",
        "oidc_client_id": "guguta",
        "oidc_client_secret": "oidc-secret",
        "oidc_redirect_uri": "https://guguta.md/api/v1/auth/oidc/callback",
        "chat_provider": "openrouter",
        "embedding_provider": "openrouter",
        "embedding_dimension": 2048,
        "openrouter_api_key": "sk-or-test-key-for-production-config",
        "rerank_provider": "openrouter",
        "api_mode": "guguta",
    }


def test_production_config_accepts_complete_safe_setup() -> None:
    cfg = GugutaConfig(**_base_production())
    assert cfg.environment == "production"


@pytest.mark.parametrize(
    "field, value, fragment",
    [
        ("server_secret", "", "SERVER_SECRET"),
        ("server_secret", "short", "min 16"),
        ("public_origin", "http://guguta.md", "PUBLIC_ORIGIN must use https"),
        ("chat_provider", "mock", "mock chat provider"),
        ("embedding_provider", "hash", "hash embedding provider"),
        ("oidc_issuer", "http://idp.guguta.md", "issuer must use https"),
        ("oidc_redirect_uri", "http://guguta.md/cb", "redirect URI must use https"),
        ("api_mode", "legacy", "legacy API surface"),
    ],
)
def test_production_refuses_unsafe_values(
    field: str, value: Any, fragment: str
) -> None:
    data = _base_production()
    data[field] = value
    with pytest.raises(ValueError, match=fragment.replace(" ", "\\s+")):
        GugutaConfig(**data)


def test_production_refuses_insecure_credential_keys() -> None:
    data = _base_production()
    data["credential_encryption_keys"] = {
        "k1": "dev-only-insecure-key-change-me",
    }
    with pytest.raises(ValueError, match="insecure"):
        GugutaConfig(**data)
