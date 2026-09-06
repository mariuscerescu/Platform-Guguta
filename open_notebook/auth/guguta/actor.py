"""Actor context — the only trusted identity carrier in Guguță services.

Built exclusively from a validated session (server-side). Client-supplied
``owner_id`` or user IDs never grant ownership (specificații §3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

from open_notebook.exceptions import OpenNotebookError


class ActorDenied(OpenNotebookError):
    """Raised when the actor lacks permission for the operation (maps to 403)."""


@dataclass(frozen=True)
class ActorContext:
    actor_id: uuid.UUID
    display_name: str
    roles: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

    @property
    def is_catalog_editor(self) -> bool:
        return "catalog_editor" in self.roles

    def require_role(self, role: str) -> None:
        if role not in self.roles:
            raise ActorDenied(f"role required: {role}")

    def require_any_role(self, *roles: str) -> None:
        if not any(r in self.roles for r in roles):
            raise ActorDenied(f"one role required: {', '.join(roles)}")


def actor_id_or_none(actor: Optional[ActorContext]) -> Optional[uuid.UUID]:
    return actor.actor_id if actor else None
