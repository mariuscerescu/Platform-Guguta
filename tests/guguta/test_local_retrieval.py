"""Network-free contract tests for the private Qwen adapters."""
import json
from types import SimpleNamespace

import httpx
import pytest

from open_notebook.ai.guguta.local_retrieval import (
    LocalEmbeddingProvider,
    LocalReranker,
    LocalRetrievalError,
)
from open_notebook.database.guguta.config import GugutaConfig


def config(**kwargs):
    return GugutaConfig(
        _env_file=None,
        embedding_provider="local",
        embedding_dimension=1024,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_embedding_distinguishes_queries_and_documents_and_reorders():
    calls = []

    def response(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "revision": body["revision"],
                "data": [
                    {"index": index, "embedding": [float(index + 1)] * 1024}
                    for index in reversed(range(len(body["input"])))
                ]
            },
        )

    provider = LocalEmbeddingProvider(
        config(local_embedding_batch_size=2),
        transport=httpx.MockTransport(response),
    )
    assert len(await provider.embed(["document"])) == 1
    result = await provider.embed_queries(["q1", "q2"])
    assert [vector[0] for vector in result] == [1.0, 2.0]
    assert calls[0]["input_type"] == "document"
    assert calls[1]["input_type"] == "query"
    assert calls[1]["model"] == "Qwen/Qwen3-Embedding-0.6B"


@pytest.mark.asyncio
async def test_embedding_rejects_invalid_dimension():
    provider = LocalEmbeddingProvider(
        config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"data": [{"index": 0, "embedding": [1.0]}]}
            )
        ),
    )
    with pytest.raises(LocalRetrievalError):
        await provider.embed(["text"])


@pytest.mark.asyncio
async def test_reranker_keeps_original_authorized_objects():
    chunks = [
        SimpleNamespace(text="matematică", locator={"page": 1}),
        SimpleNamespace(text="plante", locator={"page": 2}),
    ]
    provider = LocalReranker(
        config(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "Qwen/Qwen3-Reranker-0.6B",
                    "revision": "e61197ed45024b0ed8a2d74b80b4d909f1255473",
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.1},
                    ]
                },
            )
        ),
    )
    result = await provider.rank("plante", chunks, 2)
    assert result[0] is chunks[1]
    assert result[0].locator == {"page": 2}


def test_local_provider_config_is_pinned_and_private():
    cfg = config(rerank_provider="local")
    assert cfg.local_embedding_revision == (
        "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
    )
    assert cfg.local_rerank_revision == (
        "e61197ed45024b0ed8a2d74b80b4d909f1255473"
    )
    with pytest.raises(ValueError):
        config(local_retrieval_base_url="https://remote.example")
    with pytest.raises(ValueError):
        GugutaConfig(
            _env_file=None,
            embedding_provider="local",
            embedding_dimension=2048,
        )
