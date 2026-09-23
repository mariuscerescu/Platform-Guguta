"""Async adapters for the private Qwen retrieval service.

The service is intentionally local-only: source-derived text must never be
redirected to an arbitrary URL through configuration drift.  Responses are
validated before vectors, scores, or provider-selected indexes enter the
application.
"""
from __future__ import annotations

import asyncio
import math
from typing import Any, Sequence

import httpx

from open_notebook.exceptions import ExternalServiceError


class LocalRetrievalError(ExternalServiceError):
    """Sanitized local inference failure safe for API/job status output."""


class LocalRetrievalClient:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self._base_url = config.local_retrieval_base_url.rstrip("/") + "/"
        self._timeout = config.local_retrieval_timeout_seconds
        self._transport = transport

    async def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(self._timeout, connect=5),
                    follow_redirects=False,
                    transport=self._transport,
                ) as client:
                    response = await client.post(endpoint, json=payload)
                    if response.status_code != 200:
                        raise LocalRetrievalError(
                            "Serviciul local Qwen nu a putut procesa cererea."
                        )
                    try:
                        data = response.json()
                    except ValueError:
                        raise LocalRetrievalError(
                            "Serviciul local Qwen a returnat JSON invalid."
                        ) from None
                    if not isinstance(data, dict):
                        raise LocalRetrievalError(
                            "Serviciul local Qwen a returnat un răspuns invalid."
                        )
                    return data
        except LocalRetrievalError:
            raise
        except (httpx.HTTPError, TimeoutError):
            raise LocalRetrievalError(
                "Serviciul local Qwen este indisponibil sau a depășit timpul de așteptare."
            ) from None


class LocalEmbeddingProvider:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self.model_name = config.local_embedding_model
        self.model_revision = config.local_embedding_revision
        self.dimension = config.embedding_dimension
        self._batch_size = config.local_embedding_batch_size
        self._client = LocalRetrievalClient(config, transport=transport)

    async def _embed(
        self, texts: Sequence[str], *, input_type: str
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            data = await self._client.post(
                "v1/embeddings",
                {
                    "model": self.model_name,
                    "revision": self.model_revision,
                    "input": batch,
                    "input_type": input_type,
                    "dimensions": self.dimension,
                    "encoding_format": "float",
                },
            )
            try:
                if (
                    data["model"] != self.model_name
                    or data["revision"] != self.model_revision
                ):
                    raise ValueError()
                rows = data["data"]
                if not isinstance(rows, list) or len(rows) != len(batch):
                    raise ValueError()
                if any(type(row["index"]) is not int for row in rows):
                    raise ValueError()
                rows = sorted(rows, key=lambda row: row["index"])
                if [row["index"] for row in rows] != list(range(len(batch))):
                    raise ValueError()
                for row in rows:
                    vector = row["embedding"]
                    if not isinstance(vector, list) or len(vector) != self.dimension:
                        raise ValueError()
                    if any(
                        type(value) not in (int, float) or not math.isfinite(value)
                        for value in vector
                    ):
                        raise ValueError()
                    if not any(vector):
                        raise ValueError()
                    vectors.append([float(value) for value in vector])
            except (KeyError, TypeError, ValueError):
                raise LocalRetrievalError(
                    "Embeddings locale invalide: număr, indici sau dimensiune incompatibile."
                ) from None
        return vectors

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed corpus passages without a query instruction."""
        return await self._embed(texts, input_type="document")

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed retrieval queries with the Qwen task instruction."""
        return await self._embed(texts, input_type="query")


class LocalReranker:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self.model_name = config.local_rerank_model
        self.model_revision = config.local_rerank_revision
        self._client = LocalRetrievalClient(config, transport=transport)

    async def rank(self, query: str, chunks: Sequence[Any], limit: int) -> list[Any]:
        if not chunks:
            return []
        count = min(limit, len(chunks))
        data = await self._client.post(
            "v1/rerank",
            {
                "model": self.model_name,
                "revision": self.model_revision,
                "query": query,
                "documents": [chunk.text for chunk in chunks],
                "top_n": count,
            },
        )
        try:
            if (
                data["model"] != self.model_name
                or data["revision"] != self.model_revision
            ):
                raise ValueError()
            rows = data["results"]
            if not isinstance(rows, list) or len(rows) != count:
                raise ValueError()
            indexes = [row["index"] for row in rows]
            if any(
                type(index) is not int or not 0 <= index < len(chunks)
                for index in indexes
            ):
                raise ValueError()
            if len(set(indexes)) != count:
                raise ValueError()
            if any(
                type(row["relevance_score"]) not in (int, float)
                or not math.isfinite(row["relevance_score"])
                for row in rows
            ):
                raise ValueError()
            rows = sorted(
                rows, key=lambda row: row["relevance_score"], reverse=True
            )
            # Keep the original authorized objects, never provider-echoed text.
            return [chunks[row["index"]] for row in rows]
        except (KeyError, TypeError, ValueError):
            raise LocalRetrievalError(
                "Reranking local invalid: indici sau scoruri incompatibile."
            ) from None
