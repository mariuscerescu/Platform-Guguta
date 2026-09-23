"""Private GPU service for Qwen3 embeddings and reranking.

The process loads both pinned 0.6B models once.  It is reachable only on the
Docker network; the public API validates every response before using it.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

import torch
import torch.nn.functional as functional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from transformers import AutoModel, AutoModelForCausalLM, AutoTokenizer

logger = logging.getLogger("guguta.qwen_retrieval")

EMBEDDING_MODEL = os.environ.get(
    "QWEN_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"
)
EMBEDDING_REVISION = os.environ.get(
    "QWEN_EMBEDDING_REVISION", "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
)
RERANK_MODEL = os.environ.get(
    "QWEN_RERANK_MODEL", "Qwen/Qwen3-Reranker-0.6B"
)
RERANK_REVISION = os.environ.get(
    "QWEN_RERANK_REVISION", "e61197ed45024b0ed8a2d74b80b4d909f1255473"
)
DEVICE = os.environ.get("QWEN_RETRIEVAL_DEVICE", "cuda:0")
MAX_LENGTH = int(os.environ.get("QWEN_RETRIEVAL_MAX_LENGTH", "2048"))
EMBED_BATCH_SIZE = int(os.environ.get("QWEN_EMBEDDING_BATCH_SIZE", "16"))
RERANK_BATCH_SIZE = int(os.environ.get("QWEN_RERANK_BATCH_SIZE", "2"))
TASK_INSTRUCTION = os.environ.get(
    "QWEN_RETRIEVAL_INSTRUCTION",
    "Given a question about educational materials, retrieve relevant passages "
    "that answer the question",
)
EMBEDDING_DIMENSION = 1024


class EmbeddingRequest(BaseModel):
    model: str
    revision: str
    input: list[str] = Field(min_length=1, max_length=32)
    input_type: Literal["query", "document"] = "document"
    dimensions: int = EMBEDDING_DIMENSION
    encoding_format: Literal["float"] = "float"

    @field_validator("input")
    @classmethod
    def validate_texts(cls, texts: list[str]) -> list[str]:
        if any(not text.strip() or len(text) > 20_000 for text in texts):
            raise ValueError("texts must be non-empty and at most 20000 characters")
        return texts


class RerankRequest(BaseModel):
    model: str
    revision: str
    query: str = Field(min_length=1, max_length=4_000)
    documents: list[str] = Field(min_length=1, max_length=50)
    top_n: int = Field(ge=1, le=50)

    @field_validator("documents")
    @classmethod
    def validate_documents(cls, documents: list[str]) -> list[str]:
        if any(not text.strip() or len(text) > 20_000 for text in documents):
            raise ValueError("documents must be non-empty and at most 20000 characters")
        return documents


class QwenRuntime:
    def __init__(self) -> None:
        if not DEVICE.startswith("cuda") or not torch.cuda.is_available():
            raise RuntimeError("Qwen retrieval requires an available CUDA GPU")
        dtype = torch.float16
        self._embedding_tokenizer = AutoTokenizer.from_pretrained(
            EMBEDDING_MODEL, revision=EMBEDDING_REVISION, padding_side="left"
        )
        self._embedding_model = AutoModel.from_pretrained(
            EMBEDDING_MODEL,
            revision=EMBEDDING_REVISION,
            torch_dtype=dtype,
        ).to(DEVICE).eval()
        self._rerank_tokenizer = AutoTokenizer.from_pretrained(
            RERANK_MODEL, revision=RERANK_REVISION, padding_side="left"
        )
        self._rerank_model = AutoModelForCausalLM.from_pretrained(
            RERANK_MODEL,
            revision=RERANK_REVISION,
            torch_dtype=dtype,
        ).to(DEVICE).eval()
        self._false_token_id = self._rerank_tokenizer.convert_tokens_to_ids("no")
        self._true_token_id = self._rerank_tokenizer.convert_tokens_to_ids("yes")
        self._prefix_tokens = self._rerank_tokenizer.encode(
            '<|im_start|>system\nJudge whether the Document meets the requirements '
            'based on the Query and the Instruct provided. Note that the answer can '
            'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n',
            add_special_tokens=False,
        )
        self._suffix_tokens = self._rerank_tokenizer.encode(
            "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n",
            add_special_tokens=False,
        )
        self._lock = asyncio.Lock()

    @staticmethod
    def _last_token_pool(
        hidden_states: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        if bool((attention_mask[:, -1].sum() == attention_mask.shape[0]).item()):
            return hidden_states[:, -1]
        sequence_lengths = attention_mask.sum(dim=1) - 1
        rows = torch.arange(hidden_states.shape[0], device=hidden_states.device)
        return hidden_states[rows, sequence_lengths]

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        with torch.inference_mode():
            for start in range(0, len(texts), EMBED_BATCH_SIZE):
                batch = texts[start : start + EMBED_BATCH_SIZE]
                encoded = self._embedding_tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=MAX_LENGTH,
                    return_tensors="pt",
                ).to(DEVICE)
                outputs = self._embedding_model(**encoded, use_cache=False)
                pooled = self._last_token_pool(
                    outputs.last_hidden_state, encoded["attention_mask"]
                )
                normalized = functional.normalize(pooled, p=2, dim=1)
                vectors.extend(normalized.float().cpu().tolist())
        return vectors

    async def embed(
        self, texts: list[str], input_type: Literal["query", "document"]
    ) -> list[list[float]]:
        if input_type == "query":
            texts = [
                f"Instruct: {TASK_INSTRUCTION}\nQuery:{text}" for text in texts
            ]
        async with self._lock:
            return await asyncio.to_thread(self._embed_sync, texts)

    def _rerank_sync(self, query: str, documents: list[str]) -> list[float]:
        formatted = [
            f"<Instruct>: {TASK_INSTRUCTION}\n<Query>: {query}\n<Document>: {document}"
            for document in documents
        ]
        scores: list[float] = []
        with torch.inference_mode():
            for start in range(0, len(formatted), RERANK_BATCH_SIZE):
                batch = formatted[start : start + RERANK_BATCH_SIZE]
                tokenized = self._rerank_tokenizer(
                    batch,
                    padding=False,
                    truncation=True,
                    max_length=MAX_LENGTH
                    - len(self._prefix_tokens)
                    - len(self._suffix_tokens),
                    return_attention_mask=False,
                )
                input_ids = [
                    self._prefix_tokens + ids + self._suffix_tokens
                    for ids in tokenized["input_ids"]
                ]
                encoded = self._rerank_tokenizer.pad(
                    {"input_ids": input_ids}, padding=True, return_tensors="pt"
                ).to(DEVICE)
                logits = self._rerank_model(**encoded, use_cache=False).logits[:, -1, :]
                yes_no = torch.stack(
                    [
                        logits[:, self._false_token_id],
                        logits[:, self._true_token_id],
                    ],
                    dim=1,
                )
                probabilities = functional.softmax(yes_no.float(), dim=1)[:, 1]
                scores.extend(probabilities.cpu().tolist())
        return scores

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        async with self._lock:
            return await asyncio.to_thread(self._rerank_sync, query, documents)


app = FastAPI(title="Guguță Qwen retrieval", docs_url=None, redoc_url=None)
runtime = QwenRuntime()


@app.get("/healthz")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "device": DEVICE,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_revision": EMBEDDING_REVISION,
        "rerank_model": RERANK_MODEL,
        "rerank_revision": RERANK_REVISION,
    }


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> dict[str, object]:
    if (
        request.model != EMBEDDING_MODEL
        or request.revision != EMBEDDING_REVISION
        or request.dimensions != EMBEDDING_DIMENSION
    ):
        raise HTTPException(status_code=400, detail="model or dimension mismatch")
    try:
        vectors = await runtime.embed(request.input, request.input_type)
    except Exception:
        logger.exception("Qwen embedding inference failed")
        raise HTTPException(status_code=503, detail="embedding inference failed") from None
    return {
        "object": "list",
        "model": EMBEDDING_MODEL,
        "revision": EMBEDDING_REVISION,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
    }


@app.post("/v1/rerank")
async def rerank(request: RerankRequest) -> dict[str, object]:
    if (
        request.model != RERANK_MODEL
        or request.revision != RERANK_REVISION
        or request.top_n > len(request.documents)
    ):
        raise HTTPException(status_code=400, detail="model or top_n mismatch")
    try:
        scores = await runtime.rerank(request.query, request.documents)
    except Exception:
        logger.exception("Qwen reranking inference failed")
        raise HTTPException(status_code=503, detail="reranking inference failed") from None
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)
    return {
        "model": RERANK_MODEL,
        "revision": RERANK_REVISION,
        "results": [
            {"index": index, "relevance_score": score}
            for index, score in ranked[: request.top_n]
        ],
    }
