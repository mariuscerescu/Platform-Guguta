"""Embedding providers for the Guguță pipeline.

`HashEmbeddingProvider` is a deterministic mock for development/tests and for
the controlled-mock validation the guide allows until AI provider decisions
(D-02) close. It builds a word-presence signature vector: texts sharing
vocabulary land closer together, so vector retrieval behaves meaningfully in
tests. Real providers plug into the same interface; each change of
model/revision/dimension means a NEW embedding space (A27) — never reuse.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Awaitable, Protocol, Sequence

_TOKEN_RE = re.compile(r"[a-z0-9ăâîșțşţ]+", re.IGNORECASE)


class EmbeddingProvider(Protocol):
    model_name: str
    model_revision: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]] | Awaitable[list[list[float]]]: ...


class HashEmbeddingProvider:
    """Deterministic word-presence signature; NOT a semantic model (mock only)."""

    def __init__(self, dimension: int = 8) -> None:
        self.model_name = "guguta-hash-mock"
        self.model_revision = "v1"
        self.dimension = dimension

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimension
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = digest[0] % self.dimension
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


def get_provider(name: str, dimension: int, config: Any = None) -> EmbeddingProvider:
    if name == "hash":
        return HashEmbeddingProvider(dimension=dimension)
    if name == "openrouter" and config is not None:
        from open_notebook.ai.guguta.openrouter import OpenRouterEmbeddingProvider
        return OpenRouterEmbeddingProvider(config)
    if name == "local" and config is not None:
        from open_notebook.ai.guguta.local_retrieval import LocalEmbeddingProvider
        return LocalEmbeddingProvider(config)
    raise ValueError(f"provider de embedding necunoscut: {name}")
