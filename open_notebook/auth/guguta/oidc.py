"""OIDC Authorization Code + PKCE client (ADR-0003).

Minimal, explicit implementation:
- login: state + nonce + S256 code_verifier; the triple travels to the
  callback in a signed, HttpOnly cookie (HMAC via itsdangerous-style signing
  implemented locally with hashlib/hmac — no extra dependency).
- callback: code exchange (client auth), JWKS fetch, ID token validation
  (issuer, audience, expiry, nonce), association by issuer + subject.

Only stdlib + httpx; signature verification uses authlib's JsonWebToken/JWK.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebToken
from authlib.jose.errors import JoseError


class OidcError(Exception):
    pass


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class OidcResult:
    issuer: str
    subject: str
    email: Optional[str]
    email_verified: bool
    display_name: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _sign(secret: bytes, payload: str) -> str:
    return _b64url(hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest())


class SignedStateCodec:
    """Signs small JSON payloads (state/nonce/verifier) for the round-trip."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    def dump(self, payload: dict[str, Any]) -> str:
        body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        return f"{body}.{_sign(self._secret, body)}"

    def load(self, value: str, max_age_seconds: int = 600) -> dict[str, Any]:
        try:
            body, sig = value.rsplit(".", 1)
        except ValueError as exc:
            raise OidcError("malformed state") from exc
        if not hmac.compare_digest(sig, _sign(self._secret, body)):
            raise OidcError("bad state signature")
        raw = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if float(raw.get("ts", 0)) + max_age_seconds < time.time():
            raise OidcError("state expired")
        return raw


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class OidcClient:
    def __init__(self, config: OidcConfig, http: Optional[httpx.AsyncClient] = None) -> None:
        self._cfg = config
        self._http = http or httpx.AsyncClient(timeout=15)
        self._authorization_endpoint: Optional[str] = None

    async def _discovery(self) -> dict[str, Any]:
        if getattr(self, "_discovery_cache", None) is None:
            self._discovery_cache = await self._get(
                f"{self._cfg.issuer.rstrip('/')}/.well-known/openid-configuration"
            )
        return self._discovery_cache

    async def begin_login(self, codec: SignedStateCodec) -> tuple[str, str]:
        """Build the authorize redirect. The authorization endpoint comes from
        discovery — never assumed to be `<issuer>/authorize` (F02)."""
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier, challenge = _pkce_pair()
        cookie_value = codec.dump(
            {"state": state, "nonce": nonce, "verifier": verifier, "ts": time.time()}
        )
        discovery = await self._discovery()
        authorization_endpoint = discovery.get("authorization_endpoint")
        if not authorization_endpoint:
            raise OidcError("provider discovery incomplete")
        params = {
            "response_type": "code",
            "client_id": self._cfg.client_id,
            "redirect_uri": self._cfg.redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        url = f"{authorization_endpoint}?{urlencode(params)}"
        return url, cookie_value

    async def complete_login(self, codec: SignedStateCodec,
                             state_cookie: str, returned_state: str,
                             code: str) -> OidcResult:
        cookie = codec.load(state_cookie)
        if not hmac.compare_digest(str(cookie.get("state")), returned_state or ""):
            raise OidcError("state mismatch")

        discovery = await self._discovery()
        token_endpoint = discovery.get("token_endpoint")
        jwks_uri = discovery.get("jwks_uri")
        if not token_endpoint or not jwks_uri:
            raise OidcError("provider discovery incomplete")

        token_resp = await self._http.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._cfg.redirect_uri,
                "client_id": self._cfg.client_id,
                "client_secret": self._cfg.client_secret,
                "code_verifier": cookie["verifier"],
            },
            headers={"Accept": "application/json"},
        )
        if token_resp.status_code != 200:
            raise OidcError("token exchange failed")
        id_token = token_resp.json().get("id_token")
        if not id_token:
            raise OidcError("no id_token in token response")

        jwks = await self._get(jwks_uri)
        claims = self._validate_id_token(id_token, jwks, str(cookie.get("nonce")))

        subject = claims.get("sub")
        if not subject:
            raise OidcError("id_token without sub")
        email = claims.get("email")
        name = claims.get("preferred_username") or claims.get("name") or email or subject
        return OidcResult(
            issuer=self._cfg.issuer,
            subject=str(subject),
            email=email if isinstance(email, str) else None,
            email_verified=bool(claims.get("email_verified", False)),
            display_name=str(name)[:255],
        )

    def _validate_id_token(self, token: str, jwks: dict[str, Any],
                           expected_nonce: str) -> dict[str, Any]:
        jwt = JsonWebToken(["RS256", "ES256"])
        try:
            header_segment = token.split(".")[0]
            header_unverified = json.loads(
                base64.urlsafe_b64decode(
                    header_segment + "=" * (-len(header_segment) % 4)
                )
            )
            kid = header_unverified.get("kid")
            keys = jwks.get("keys", [])
            key_data = next((k for k in keys if k.get("kid") == kid), None)
            if key_data is None:
                raise OidcError("id_token kid not found in JWKS")
            claims = jwt.decode(
                token,
                key_data,
                claims_options={
                    "iss": {"value": self._cfg.issuer},
                    "aud": {"value": self._cfg.client_id},
                },
            )
        except JoseError as exc:
            raise OidcError(f"id_token validation failed: {exc}") from exc
        try:
            claims.validate(now=int(time.time()), leeway=60)
        except JoseError as exc:
            # covers ExpiredTokenError / ImmatureTokenError etc.
            raise OidcError(f"id_token claims invalid: {exc}") from exc
        if expected_nonce and not hmac.compare_digest(
            str(claims.get("nonce", "")), expected_nonce
        ):
            raise OidcError("nonce mismatch")
        return dict(claims)

    async def _get(self, url: str) -> dict[str, Any]:
        resp = await self._http.get(url, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            raise OidcError(f"GET {url} failed")
        return dict(resp.json())

    async def aclose(self) -> None:
        await self._http.aclose()
