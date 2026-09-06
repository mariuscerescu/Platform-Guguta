"""Guguță authentication core (ADR-0003).

Components:
- sessions: opaque server-side sessions (token hash stored, cookie helpers,
  CSRF token derived via HMAC from the session token hash — no extra column).
- actor: ActorContext carried by services; built only from a validated session.
- oidc: Authorization Code + PKCE client with manual JWKS/ID-token validation.

Test/synthetic login exists only when the config allows it (development/ci,
``GUGUTA_AUTH_MODE=test``); the API refuses it otherwise and startup fails in
staging/production with that configuration (GugutaConfig validator).
"""

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.auth.guguta.sessions import SessionService

__all__ = ["ActorContext", "SessionService"]
