"""Credential encryption for the central AI configuration (GHID §7.2, L5).

Fernet (AES-128-CBC + HMAC) keyed by SHA-256 of the per-id secret.
Rotation: decrypt with MultiFernet (primary first, fallbacks after),
re-encrypt with the primary key and store the new key_id. Secrets live in
the environment, never in Git (R08).
"""

from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CredentialCrypto:
    def __init__(self, keys: dict[str, str], primary_id: str) -> None:
        if not keys or primary_id not in keys:
            raise ValueError(
                "GUGUTA_CREDENTIAL_ENCRYPTION_KEYS/GUGUTA_CREDENTIAL_KEY_PRIMARY_ID "
                "sunt incomplete."
            )
        self._keys = keys
        self._primary_id = primary_id
        fernets = [self._fernet(k) for _, k in keys.items()]
        self._multi = MultiFernet(fernets)
        self._primary = self._fernet(keys[primary_id])

    @staticmethod
    def _fernet(secret: str) -> Fernet:
        derived = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(derived))

    @property
    def primary_key_id(self) -> str:
        return self._primary_id

    def encrypt(self, plaintext: str) -> tuple[str, str]:
        """Returns (encrypted_token, key_id)."""
        return (
            self._primary.encrypt(plaintext.encode("utf-8")).decode("ascii"),
            self._primary_id,
        )

    def decrypt(self, token: str, key_id: Optional[str] = None) -> str:
        """Decrypt trying all configured keys (rotation fallbacks)."""
        fernet = self._multi
        if key_id and key_id in self._keys:
            # try the recorded key first, then the rest
            fernet = MultiFernet(
                [self._fernet(self._keys[key_id])]
                + [self._fernet(k) for k, v in self._keys.items() if k != key_id]
            )
        try:
            return fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Decriptarea credențialului a eșuat (cheie lipsă?).") from exc
