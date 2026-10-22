"""Direct Gemini API, reusing Guguță's validated prompts and citation contract.

Google's OpenAI-compatible endpoint is used directly; requests never pass
through OpenRouter. Only opaque tool signatures are retained in agent memory.
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger

from open_notebook.ai.guguta.openrouter import (
    OpenRouterChatProvider,
    OpenRouterClient,
    OpenRouterError,
)


class GeminiClient(OpenRouterClient):
    _base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    _label = "Gemini"
    _allowed_endpoints = ("chat/completions",)
    _retriable_codes = (408, 429, 500, 502, 503, 504, 529)

    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self._key = config.gemini_api_key.get_secret_value().strip()
        self._timeout = config.gemini_timeout_seconds
        self._retries = config.gemini_max_retries
        self._transport = transport
        self._model = config.gemini_chat_model
        self._thinking = config.gemini_thinking_level
        self._max_tokens = config.gemini_max_output_tokens
        # Read by the shared prompt builder; routing fields are omitted below.
        self.provider_sort = "throughput"
        self.interactive_provider_sort = "latency"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._key}

    def _private_payload(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Gemini 3.6+ ignores custom sampling; Google is retiring these fields.
        allowed = {"messages", "tools", "tool_choice", "response_format"}
        return {
            **{key: value for key, value in payload.items() if key in allowed},
            "model": self._model,
            "max_tokens": self._max_tokens,
            "extra_body": {"google": {"thinking_config": {
                "thinking_level": self._thinking, "include_thoughts": False,
            }}},
        }

    @staticmethod
    def _upstream_error(code: Any) -> OpenRouterError:
        if code in (401, 403):
            return OpenRouterError("Gemini: verifică cheia API și accesul proiectului.")
        if code == 404:
            return OpenRouterError("Gemini: modelul configurat nu este disponibil.")
        return OpenRouterError("Gemini a respins cererea sau nu a putut-o procesa. Reîncearcă în câteva momente.")

    async def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        ok = False
        try:
            result = await super().post(endpoint, payload)
            ok = True
            return result
        finally:
            logger.info("gemini_request_complete stage={} seconds={:.2f} ok={}",
                        "tools" if payload.get("tools") else "completion",
                        time.monotonic() - started, ok)


class GeminiChatProvider(OpenRouterChatProvider):
    preserve_tool_context = True

    def __init__(self, config: Any, *, transport: Any = None) -> None:
        self.model_name = config.gemini_chat_model
        self._max_tokens = config.gemini_max_output_tokens
        self._review_enabled = config.chat_answer_review
        self._client = GeminiClient(config, transport=transport)

    def _tool_call_metadata(self, call: dict[str, Any]) -> dict[str, Any]:
        extra = call.get("extra_content")
        google = extra.get("google") if isinstance(extra, dict) else None
        signature = google.get("thought_signature") if isinstance(google, dict) else None
        if signature is None:
            return {}
        if not isinstance(signature, str) or not 1 <= len(signature) <= 65536:
            raise ValueError("invalid_tool_signature")
        return {"extra_content": {"google": {"thought_signature": signature}}}


def completion_client(config: Any) -> OpenRouterClient | None:
    if config.chat_provider == "gemini":
        return GeminiClient(config)
    if config.chat_provider == "openrouter":
        return OpenRouterClient(config)
    return None


def completion_model(config: Any) -> str:
    return str(config.gemini_chat_model if config.chat_provider == "gemini" else config.openrouter_chat_model)
