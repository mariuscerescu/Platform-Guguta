"""Opaque server-side sessions (ADR-0003).

- Session token: 32 random bytes, base64url — only its SHA-256 hash is stored.
- Cookie: HttpOnly, SameSite=Lax, Secure when the public origin is HTTPS.
- CSRF: derived token = HMAC-SHA256(server_secret, token_hash) — verifiable
  without storing anything extra; presented via X-Guguta-CSRF on mutations.
- Expiry: absolute + inactivity (sliding) limits; logout revokes.
- Session mechanics (create/resolve/revoke) run through SECURITY DEFINER
  functions (migration 0002) because they execute before an actor context
  exists; every other path to the sessions table stays RLS-protected.
- Account suspension invalidates sessions on next validation (status check).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext

SESSION_COOKIE = "guguta_session"
CSRF_HEADER = "X-Guguta-CSRF"


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionService:
    def __init__(self, engine: AsyncEngine, *, server_secret: str,
                 absolute_ttl: timedelta, inactivity_ttl: timedelta) -> None:
        self._engine = engine
        self._secret = server_secret.encode("utf-8")
        self._absolute_ttl = absolute_ttl
        self._inactivity_ttl = inactivity_ttl

    def csrf_token_for(self, session_token: str) -> str:
        """CSRF token bound to this session's token hash (HMAC)."""
        return hmac.new(self._secret, _hash_token(session_token).encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def verify_csrf(self, session_token: str, presented: Optional[str]) -> bool:
        if not presented:
            return False
        expected = self.csrf_token_for(session_token)
        return hmac.compare_digest(expected, presented)

    async def create_session(self, user_id: uuid.UUID) -> tuple[str, str]:
        """Create a session; returns (session_token, csrf_token)."""
        token = secrets.token_urlsafe(32)
        async with self._engine.begin() as conn:
            await conn.execute(
                text("SELECT guguta_create_session(:u, :h, :ttl)"),
                {
                    "u": user_id,
                    "h": _hash_token(token),
                    "ttl": f"{self._absolute_ttl.total_seconds()} seconds",
                },
            )
        return token, self.csrf_token_for(token)

    async def resolve_actor(self, session_token: str) -> Optional[ActorContext]:
        """Validate the session cookie and return the actor, or None.

        Checks: hash exists, not revoked, not expired (absolute), inactivity
        window, user active. Sliding window: updates last_seen_at (in the
        SECURITY DEFINER resolver).
        """
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text("SELECT * FROM guguta_resolve_session(:h, :ina)"),
                    {
                        "h": _hash_token(session_token),
                        "ina": f"{self._inactivity_ttl.total_seconds()} seconds",
                    },
                )
            ).mappings().first()
        if row is None:
            return None
        if row["o_status"] != "active":
            return None
        return ActorContext(
            actor_id=row["o_user_id"],
            display_name=row["o_display_name"],
            roles=frozenset(row["o_roles"] or []),
        )

    async def revoke(self, session_token: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("SELECT guguta_revoke_session(:h) AS revoked"),
                {"h": _hash_token(session_token)},
            )
        return int(result.scalar_one() or 0) > 0

    async def revoke_all_for_user(self, actor_id: uuid.UUID) -> int:
        """Used on account suspension/deletion or explicit security action."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("SELECT guguta_revoke_all_for_user(:u) AS revoked"),
                {"u": actor_id},
            )
        return int(result.scalar_one() or 0)

    @staticmethod
    def cookie_args(public_origin: str) -> dict[str, Any]:
        return {
            "key": SESSION_COOKIE,
            "httponly": True,
            "samesite": "lax",
            "secure": public_origin.startswith("https://"),
            "path": "/",
        }
