"""Admin services: central AI credentials + content reports (L5).

The admin role is enforced twice: in the service (ActorContext) and inside
the SECURITY DEFINER DB functions (migration 0005). Secrets are never
returned by any endpoint — metadata only.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.auth.guguta.actor import ActorContext
from open_notebook.auth.guguta.crypto import CredentialCrypto
from open_notebook.database.guguta.engine import actor_connection
from open_notebook.exceptions import NotFoundError


class AdminService:
    def __init__(self, engine: AsyncEngine, crypto: CredentialCrypto) -> None:
        self._engine = engine
        self._crypto = crypto

    def _require_admin(self, actor: ActorContext) -> None:
        actor.require_role("admin")

    async def set_credential(
        self, actor: ActorContext, *, provider: str, name: str, secret_value: str,
    ) -> dict[str, Any]:
        self._require_admin(actor)
        token, key_id = self._crypto.encrypt(secret_value)
        cred_id = uuid.uuid4()
        async with self._engine.begin() as conn:
            new_id = (
                await conn.execute(
                    text(
                        "SELECT guguta_admin_set_credential(:a, :p, :n, :k, :payload)"
                    ),
                    {"a": actor.actor_id, "p": provider, "n": name,
                     "k": key_id, "payload": token},
                )
            ).scalar_one()
        cred_id = new_id
        return {"id": str(cred_id), "provider": provider, "name": name,
                "key_id": key_id}

    async def list_credentials(self, actor: ActorContext) -> list[dict[str, Any]]:
        self._require_admin(actor)
        async with self._engine.begin() as conn:
            rows = (
                await conn.execute(
                    text("SELECT * FROM guguta_admin_list_credentials(:a)"),
                    {"a": actor.actor_id},
                )
            ).mappings().all()
        # metadata only — the encrypted payload is never returned
        return [
            {
                "id": str(r["id"]), "provider": r["provider"], "name": r["name"],
                "key_id": r["key_id"], "created_at": r["created_at"],
                "rotated_at": r["rotated_at"],
            }
            for r in rows
        ]

    async def delete_credential(self, actor: ActorContext, cred_id: uuid.UUID) -> None:
        self._require_admin(actor)
        async with self._engine.begin() as conn:
            await conn.execute(
                text("SELECT guguta_admin_delete_credential(:a, :id)"),
                {"a": actor.actor_id, "id": cred_id},
            )

    async def rotate_credential(
        self, actor: ActorContext, cred_id: uuid.UUID, *, new_secret: Optional[str] = None,
    ) -> dict[str, Any]:
        """Re-encrypt with the primary key (provider value unchanged), or store
        a new secret under the primary key."""
        self._require_admin(actor)
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT provider, name, key_id, encrypted_payload"
                        " FROM guguta_admin_get_credential(:a, :id)"
                    ),
                    {"a": actor.actor_id, "id": cred_id},
                )
            ).mappings().first()
        if row is None:
            raise NotFoundError()
        if new_secret is not None:
            plaintext = new_secret
        else:
            # re-encrypt the existing value under the primary key
            plaintext = self._crypto.decrypt(row["encrypted_payload"], row["key_id"])
        token, key_id = self._crypto.encrypt(plaintext)
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "SELECT guguta_admin_set_credential(:a, :p, :n, :k, :payload)"
                ),
                {"a": actor.actor_id, "p": row["provider"], "n": row["name"],
                 "k": key_id, "payload": token},
            )
        return {"id": str(cred_id), "key_id": key_id, "rotated": True}

    async def decrypt_for_use(
        self, actor: ActorContext, provider: str, name: str
    ) -> str:
        """Provider-side decryption during AI calls; audited in the DB."""
        async with self._engine.begin() as conn:
            token = (
                await conn.execute(
                    text("SELECT guguta_credential_decrypt(:a, :p, :n)"),
                    {"a": actor.actor_id, "p": provider, "n": name},
                )
            ).scalar_one()
        return self._crypto.decrypt(token)

    # -- content reports ------------------------------------------------------

    async def create_report(
        self, actor: ActorContext, *, target_type: str, target_id: uuid.UUID,
        reason: str,
    ) -> dict[str, Any]:
        if target_type not in ("message", "source", "notebook", "note"):
            from open_notebook.exceptions import InvalidInputError

            raise InvalidInputError("Tip de țintă neacceptat.")
        reason = reason.strip()[:2000]
        if not reason:
            from open_notebook.exceptions import InvalidInputError

            raise InvalidInputError("Motivul este obligatoriu.")
        event_id = uuid.uuid4()
        async with actor_connection(self._engine, actor.actor_id) as conn:
            await conn.execute(
                text(
                    "INSERT INTO audit_events (id, actor_id, action, target_type,"
                    " target_id, result, details)"
                    " VALUES (:id, :a, 'content_report', :tt, :tid, 'allowed',"
                    " CAST(:d AS jsonb))"
                ),
                {"id": event_id, "a": actor.actor_id, "tt": target_type,
                 "tid": target_id, "d": _json({"reason": reason})},
            )
        return {"id": str(event_id), "status": "înregistrat"}

    async def list_reports(self, actor: ActorContext) -> list[dict[str, Any]]:
        """Admin-only listing of content reports (audit access server-side)."""
        self._require_admin(actor)
        async with actor_connection(
            self._engine, actor.actor_id, audit_access=True
        ) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT id, actor_id, action, target_type, target_id, details,"
                        " created_at FROM audit_events WHERE action = 'content_report'"
                        " ORDER BY created_at DESC LIMIT 200"
                    )
                )
            ).mappings().all()
        return [dict(r) for r in rows]


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
