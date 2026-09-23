"""Unit coverage for Audio Overview focus instructions."""

from __future__ import annotations

import json
from typing import Any

import pytest

from open_notebook.ai.guguta.audio_overview import AudioScriptGenerator
from open_notebook.database.guguta.config import GugutaConfig


@pytest.mark.asyncio
async def test_audio_script_includes_user_focus() -> None:
    class FakeClient:
        payload: dict[str, Any] | None = None

        async def post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
            assert endpoint == "chat/completions"
            self.payload = payload
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "title": "Lumina în fotosinteză",
                                    "script": "Lumina oferă energia necesară fotosintezei. " * 4,
                                }
                            )
                        },
                    }
                ]
            }

    generator = AudioScriptGenerator(
        GugutaConfig(chat_provider="openrouter", openrouter_api_key="test")
    )
    fake_client = FakeClient()
    setattr(generator, "_client", fake_client)

    await generator.generate(
        format_name="brief",
        sources=[{"name": "Biologie", "text": "Lumina susține fotosinteza."}],
        instructions="Concentrează-te pe rolul luminii.",
    )

    assert fake_client.payload is not None
    messages = fake_client.payload["messages"]
    request_data = json.loads(messages[1]["content"])
    assert request_data["focus_requested_by_user"] == (
        "Concentrează-te pe rolul luminii."
    )
    assert "prioritizează acel subiect" in messages[0]["content"]
