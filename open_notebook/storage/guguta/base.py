"""Storage backend interface and error types (ADR-0004)."""

from __future__ import annotations

from typing import BinaryIO, Protocol, runtime_checkable


class StorageError(Exception):
    """Storage operation failed."""


class StorageKeyRejected(StorageError):
    """Malformed or unsafe storage key (path traversal etc.)."""


class StorageKeyNotFound(StorageError):
    """Requested key does not exist."""


@runtime_checkable
class StorageBackend(Protocol):
    def save_bytes(self, data: bytes, *, prefix: str = "assets") -> str:
        """Persist bytes under a server-generated key; returns the key."""
        ...

    def read_bytes(self, key: str) -> bytes:
        """Read the full content for a key."""
        ...

    def open(self, key: str) -> BinaryIO:
        """Open a read stream for a key."""
        ...

    def delete(self, key: str) -> bool:
        """Delete a key; returns True if it existed."""
        ...

    def exists(self, key: str) -> bool:
        ...
