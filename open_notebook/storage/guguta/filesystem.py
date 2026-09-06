"""Filesystem storage backend (ADR-0004).

Layout: <root>/<prefix>/<xx>/<yy>/<uuid> — sharded to avoid huge dirs.
Keys are validated strictly: no absolute paths, no '..' segments, no
backslashes, restricted character set. Symlinks inside the root are not
followed for writes (files are created with O_EXCL).
"""

from __future__ import annotations

import os
import re
import uuid
from typing import BinaryIO

from open_notebook.storage.guguta.base import (
    StorageKeyNotFound,
    StorageKeyRejected,
)

_KEY_RE = re.compile(r"^[a-z0-9]+(/[a-z0-9]+)*$")


class FilesystemStorage:
    def __init__(self, root: str) -> None:
        self._root = os.path.abspath(root)
        os.makedirs(self._root, exist_ok=True)

    # -- key handling ------------------------------------------------------

    def _validate(self, key: str) -> str:
        if not key or "\\" in key or ".." in key:
            raise StorageKeyRejected("cheie de stocare neacceptată")
        if key.startswith("/") or ":" in key:
            raise StorageKeyRejected("cheie de stocare neacceptată")
        if not _KEY_RE.match(key):
            raise StorageKeyRejected("cheie de stocare neacceptată")
        return key

    def _path(self, key: str) -> str:
        key = self._validate(key)
        path = os.path.abspath(os.path.join(self._root, key))
        if not path.startswith(self._root + os.sep):
            # defence in depth: never escape the root
            raise StorageKeyRejected("cheie în afara rădăcinii")
        return path

    # -- operations ---------------------------------------------------------

    def save_bytes(self, data: bytes, *, prefix: str = "assets") -> str:
        if not re.match(r"^[a-z0-9/-]*$", prefix):
            raise StorageKeyRejected("prefix neacceptat")
        uid = uuid.uuid4().hex
        key = f"{prefix}/{uid[0:2]}/{uid[2:4]}/{uid}"
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return key

    def read_bytes(self, key: str) -> bytes:
        path = self._path(key)
        if not os.path.isfile(path):
            raise StorageKeyNotFound("cheia nu există")
        with open(path, "rb") as fh:
            return fh.read()

    def open(self, key: str) -> BinaryIO:
        path = self._path(key)
        if not os.path.isfile(path):
            raise StorageKeyNotFound("cheia nu există")
        return open(path, "rb")

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not os.path.isfile(path):
            return False
        os.unlink(path)
        return True

    def exists(self, key: str) -> bool:
        try:
            return os.path.isfile(self._path(key))
        except StorageKeyRejected:
            return False
