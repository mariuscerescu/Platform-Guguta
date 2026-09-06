"""Embedding providers for the Guguță pipeline.

`HashEmbeddingProvider` is a deterministic mock for development/tests and for
the controlled-mock validation the guide allows until AI provider decisions
(D-02) close. Real providers plug into the same interface; each change of
model/revision/dimension means a NEW embedding space (A27) — never reuse.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    model_name: str
    model_revision: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class HashEmbeddingProvider:
    """Deterministic hash-based vectors; NOT a semantic model (mock only)."""

    def __init__(self, dimension: int = 8) -> None:
        self.model_name = "guguta-hash-mock"
        self.model_revision = "v1"
        self.dimension = dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for t in texts:
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            values: list[float] = []
            for i in range(self.dimension):
                chunk = digest[(i * 4) % len(digest): (i * 4) % len(digest) + 4]
                n = int.from_bytes(chunk, "big")
                # map to [-1, 1)
                values.append((n / 0xFFFFFFFF) * 2 - 1)
            norm = math.sqrt(sum(v * v for v in values)) or 1.0
            vectors.append([v / norm for v in values])
        return vectors


def get_provider(name: str, dimension: int) -> EmbeddingProvider:
    if name == "hash":
        return HashEmbeddingProvider(dimension=dimension)
    raise ValueError(f"provider de embedding necunoscut: {name}")
