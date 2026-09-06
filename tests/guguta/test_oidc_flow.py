"""L2 probe: full OIDC flow against a fake issuer (GHID §4, ADR-0003).

The fake provider signs ID tokens with a fresh RSA key, serves discovery +
JWKS, and exchanges the code. Covers: happy path (subject association),
tampered state, and expired token rejection.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from authlib.jose import JsonWebToken
from cryptography.hazmat.primitives.asymmetric import rsa

from open_notebook.auth.guguta.oidc import (
    OidcClient,
    OidcConfig,
    OidcError,
    SignedStateCodec,
)

pytestmark = pytest.mark.asyncio

ISSUER = "https://fake-issuer.example"


def _int_b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _make_provider() -> tuple[httpx.AsyncClient, dict[str, Any]]:
    """Fake OIDC provider over httpx.MockTransport, with an RSA signing key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    jwk = {
        "kty": "RSA", "n": _int_b64(pub.n), "e": _int_b64(pub.e),
        "kid": "test-key", "alg": "RS256", "use": "sig",
    }
    jwks = {"keys": [jwk]}
    issued: dict[str, dict[str, Any]] = {}
    jwt = JsonWebToken(["RS256"])

    def sign_id_token(nonce: str, aud: str, *, expired: bool = False) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER, "aud": aud, "sub": "user-sub-42",
            "nonce": nonce, "email": "elev@example.md",
            "email_verified": True, "name": "Elev Test",
            "iat": now - 3600 if expired else now,
            "exp": now - 3600 if expired else now + 600,
        }
        return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key).decode()

    async def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks.json",
            })
        if url.endswith("/jwks.json"):
            return httpx.Response(200, json=jwks)
        if url.endswith("/token"):
            form = dict(
                pair.split("=", 1) for pair in request.content.decode().split("&")
            )
            code = form.get("code", "")
            meta = issued.pop(code, None)
            if meta is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={
                "id_token": sign_id_token(meta["nonce"], form.get("client_id", ""),
                                          expired=meta.get("expired", False)),
                "access_token": "at", "token_type": "Bearer",
            })
        return httpx.Response(404)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=10)
    return http_client, issued


def _make_client() -> tuple[OidcClient, dict[str, dict[str, Any]]]:
    http_client, issued = _make_provider()
    client = OidcClient(
        OidcConfig(issuer=ISSUER, client_id="guguta-dev",
                   client_secret="s", redirect_uri="http://localhost:3000/callback"),
        http=http_client,
    )
    return client, issued


def _decode_cookie_state(cookie: str) -> dict[str, Any]:
    body = cookie.split(".")[0]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


async def test_oidc_happy_path() -> None:
    client, issued = _make_client()
    codec = SignedStateCodec("test-secret")
    url, cookie = client.begin_login(codec)
    assert "code_challenge_method=S256" in url

    qs = parse_qs(urlparse(url).query)
    code = "auth-code-1"
    issued[code] = {"nonce": _decode_cookie_state(cookie)["nonce"]}

    result = await client.complete_login(codec, cookie, qs["state"][0], code)
    assert result.subject == "user-sub-42"
    assert result.email == "elev@example.md"
    await client.aclose()


async def test_oidc_rejects_tampered_state() -> None:
    client, issued = _make_client()
    codec = SignedStateCodec("test-secret")
    _, cookie = client.begin_login(codec)
    with pytest.raises(OidcError):
        await client.complete_login(codec, cookie, "tampered-state", "code")
    await client.aclose()


async def test_oidc_rejects_expired_id_token() -> None:
    client, issued = _make_client()
    codec = SignedStateCodec("test-secret")
    url, cookie = client.begin_login(codec)
    qs = parse_qs(urlparse(url).query)
    code = "expired-code"
    issued[code] = {
        "nonce": _decode_cookie_state(cookie)["nonce"], "expired": True,
    }
    with pytest.raises(OidcError):
        await client.complete_login(codec, cookie, qs["state"][0], code)
    await client.aclose()
