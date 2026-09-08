"""OpenRouter adapters. Async HTTP, exact models, no implicit model fallback.

Errors never contain provider bodies, request headers, document text or keys.
Clients are scoped to each request so API/worker lifecycles cannot leak sockets.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import math
import re
from typing import Any, Sequence

import httpx

from open_notebook.ai.guguta.chat import SYSTEM_PROMPT, ChatAnswer
from open_notebook.exceptions import ExternalServiceError

PROMPT_VERSION = "guguta-openrouter-1"


class OpenRouterError(ExternalServiceError):
    """Sanitized upstream failure, safe for the job status/API."""


async def invoke(method: Any, *args: Any) -> Any:
    """Support existing synchronous mocks without blocking the event loop."""
    if inspect.iscoroutinefunction(method):
        return await method(*args)
    result = await asyncio.to_thread(method, *args)
    return await result if inspect.isawaitable(result) else result


class OpenRouterClient:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self._key = config.openrouter_api_key.get_secret_value()
        self._timeout = config.openrouter_timeout_seconds
        self._retries = config.openrouter_max_retries
        self._transport = transport

    async def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Fixed trusted destination; never follow a redirect carrying the key.
        retriable_codes = (429, 502, 503, 504, 529)
        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient(
                    base_url="https://openrouter.ai/api/v1/",
                    headers={"Authorization": "Bearer " + self._key,
                             "X-Title": "Guguta"},
                    timeout=httpx.Timeout(self._timeout, connect=10),
                    follow_redirects=False, transport=self._transport,
                ) as client:
                    for attempt in range(self._retries + 1):
                        response = await client.post(endpoint, json=payload)
                        retriable = response.status_code in retriable_codes
                        data: Any = None
                        if not retriable:
                            try:
                                data = response.json()
                            except ValueError:
                                raise OpenRouterError(
                                    "OpenRouter a returnat JSON invalid."
                                ) from None
                            # OpenRouter semnalează supraîncărcarea upstream
                            # cu HTTP 200 + error.code 502 în body (variante
                            # :free) — retriable exact ca un HTTP 502.
                            if isinstance(data, dict) and isinstance(
                                data.get("error"), dict
                            ):
                                err = data["error"]
                                code = err.get("code")
                                if isinstance(code, int) and code in retriable_codes:
                                    retriable = True
                                else:
                                    raise OpenRouterError(
                                        "OpenRouter: "
                                        + str(err.get("message", "eroare de procesare"))
                                    ) from None
                        if retriable and attempt < self._retries:
                            try:
                                delay = float(
                                    response.headers.get("Retry-After", 2 ** attempt)
                                )
                            except ValueError:
                                delay = float(2 ** attempt)
                            if not math.isfinite(delay) or delay > 10:
                                delay = float(2 ** attempt)
                            await asyncio.sleep(max(1.0, delay))
                            continue
                        if retriable:
                            raise OpenRouterError(
                                "OpenRouter ocupat (upstream suprasolicitat); "
                                "reîncercați în câteva momente."
                            ) from None
                        if not isinstance(data, dict):
                            raise OpenRouterError("OpenRouter a returnat JSON invalid.")
                        return data
        except (httpx.HTTPError, TimeoutError):
            raise OpenRouterError("OpenRouter: conexiune eșuată sau timp de așteptare depășit.") from None
        raise OpenRouterError("OpenRouter indisponibil.")


class OpenRouterEmbeddingProvider:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self.model_name = config.openrouter_embedding_model
        self.model_revision = config.openrouter_embedding_revision
        self.dimension = config.embedding_dimension
        self._batch_size = config.openrouter_embedding_batch_size
        self._client = OpenRouterClient(config, transport=transport)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start:start + self._batch_size])
            data = await self._client.post("embeddings", {
                "model": self.model_name, "input": batch, "encoding_format": "float",
            })
            try:
                rows = data["data"]
                if not isinstance(rows, list) or len(rows) != len(batch):
                    raise ValueError()
                if any(type(row["index"]) is not int for row in rows):
                    raise ValueError()
                rows = sorted(rows, key=lambda row: row["index"])
                if [r["index"] for r in rows] != list(range(len(batch))):
                    raise ValueError()
                for row in rows:
                    vector = row["embedding"]
                    if not isinstance(vector, list) or len(vector) != self.dimension:
                        raise ValueError()
                    if any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
                        raise ValueError()
                    if not any(vector):
                        raise ValueError()
                    vectors.append([float(v) for v in vector])
            except (KeyError, TypeError, ValueError):
                raise OpenRouterError("Embeddings invalide: număr, indici sau dimensiune incompatibile.") from None
        return vectors


class OpenRouterReranker:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self.model_name = config.openrouter_rerank_model
        self._client = OpenRouterClient(config, transport=transport)

    async def rank(self, query: str, chunks: Sequence[Any], limit: int) -> list[Any]:
        if not chunks:
            return []
        count = min(limit, len(chunks))
        data = await self._client.post("rerank", {
            "model": self.model_name, "query": query,
            "documents": [c.text for c in chunks], "top_n": count,
        })
        try:
            rows = data["results"]
            if not isinstance(rows, list) or len(rows) != count:
                raise ValueError()
            indexes = [r["index"] for r in rows]
            if any(type(i) is not int or not 0 <= i < len(chunks) for i in indexes):
                raise ValueError()
            if len(set(indexes)) != count:
                raise ValueError()
            if any(type(r["relevance_score"]) not in (int, float) or not math.isfinite(r["relevance_score"]) for r in rows):
                raise ValueError()
            rows = sorted(rows, key=lambda r: r["relevance_score"], reverse=True)
            # Use original objects, never document text/metadata echoed by provider.
            return [chunks[r["index"]] for r in rows]
        except (KeyError, TypeError, ValueError):
            raise OpenRouterError("Reranking invalid: indici sau scoruri incompatibile.") from None


class OpenRouterChatProvider:
    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self.model_name = config.openrouter_chat_model
        self._max_tokens = config.openrouter_max_output_tokens
        self._client = OpenRouterClient(config, transport=transport)

    async def generate(self, question: str, context_chunks: Sequence[Any],
                       history: Sequence[dict[str, str]]) -> ChatAnswer:
        if not context_chunks:
            return ChatAnswer("Nu găsesc informația în materialele selectate ale carnetului.",
                              [], self.model_name, prompt_version=PROMPT_VERSION)
        instruction = (
            SYSTEM_PROMPT + " Returnează numai JSON valid cu câmpurile answer (text) și cited "
            "(lista indicilor întregi, de la 0, ai fragmentelor folosite). În answer citează "
            "fragmentele prin [1], [2] etc., unde [1] corespunde indicelui 0. "
            "Nu folosi citări din istoricul conversației. Dacă materialele nu oferă "
            "răspunsul, spune asta și returnează cited: []. Nu divulga raționamentul intern."
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": instruction}]
        messages.extend({"role": m["role"], "content": m["content"]}
                        for m in history if m.get("role") in ("user", "assistant"))
        messages.append({"role": "user", "content": json.dumps({
            "question": question,
            "untrusted_source_fragments": [{"index": i, "text": c.text}
                                            for i, c in enumerate(context_chunks)],
        }, ensure_ascii=False)})
        data = await self._client.post("chat/completions", {
            "model": self.model_name, "messages": messages,
            "max_tokens": self._max_tokens, "temperature": 0,
        })
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError()
            raw = choice["message"]["content"].strip()
            if raw.startswith("```json") and raw.endswith("```"):
                raw = raw[7:-3].strip()
            obj = json.loads(raw)
            answer, cited = obj["answer"], obj["cited"]
            if not isinstance(answer, str) or not answer.strip() or not isinstance(cited, list):
                raise ValueError()
            if any(type(i) is not int or not 0 <= i < len(context_chunks) for i in cited):
                raise ValueError()
            cited = list(dict.fromkeys(cited))
            markers = {int(i) - 1 for i in re.findall(r"\[(\d+)\]", answer)}
            if markers != set(cited):
                raise ValueError()
            usage = data.get("usage", {})
            pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
            cost = usage.get("cost")
            if any(v is not None and (type(v) is not int or v < 0) for v in (pt, ct)):
                raise ValueError()
            if cost is not None and (type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0):
                raise ValueError()
            return ChatAnswer(answer.strip(), cited, self.model_name, pt, ct, cost, PROMPT_VERSION)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise OpenRouterError("Răspuns AI invalid sau incomplet; răspunsul nu a fost publicat.") from None

    def generate_stream(self, question: str, context_chunks: Sequence[Any],
                        history: Sequence[dict[str, str]]) -> Any:
        """SSE: răspunsul complet vine din generate() (validat), apoi tokenii
        se emit cuvânt cu cuvânt. Latența e dominată de unica completare;
        streaming la nivel de token OpenRouter = upgrade viitor."""
        return self._tokens(self.generate(question, context_chunks, history))

    @staticmethod
    async def _tokens(result: Any) -> Any:
        import inspect

        answer = await result if inspect.isawaitable(result) else result
        for word in str(answer.content).split(" "):
            yield word + " "
