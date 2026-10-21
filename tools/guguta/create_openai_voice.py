#!/usr/bin/env python3
"""Create Guguță's prompt-generated adult voice once; never edit deployment env."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from api.services.guguta.openai_voice_profile import (  # noqa: E402
    VOICE_NAME,
    VOICE_PROMPT,
    VOICE_SCRIPT_HINT,
)


async def create_voice(args: argparse.Namespace) -> str:
    if args.env_file:
        if not args.env_file.is_file():
            raise RuntimeError("Fișierul .env indicat nu există.")
        load_dotenv(args.env_file, override=False)

    voice_id = os.environ.get("GUGUTA_OPENAI_VOICE_ID", "").strip()
    if voice_id:
        raise RuntimeError("GUGUTA_OPENAI_VOICE_ID există deja; nu creez o voce duplicată.")
    api_key = os.environ.get("GUGUTA_OPENAI_API_KEY", "").strip() or (
        os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not api_key:
        raise RuntimeError("Configurează OPENAI_API_KEY în mediul procesului sau în --env-file.")
    if args.output.exists():
        raise RuntimeError("Fișierul rezultat există deja; nu creez o voce duplicată.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the output before the POST. On an ambiguous network failure, keep
    # the marker so rerunning cannot silently create another voice.
    with args.output.open("x", encoding="utf-8") as output:
        os.chmod(args.output, 0o600)
        json.dump({"status": "creation_requested", "name": VOICE_NAME}, output, ensure_ascii=False)
        output.write("\n")
    try:
        async with httpx.AsyncClient(timeout=90.0, follow_redirects=False) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/voices",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "type": "prompt", "name": VOICE_NAME, "model": "auto",
                    "prompt": VOICE_PROMPT, "script_hint": VOICE_SCRIPT_HINT,
                },
            )
        response.raise_for_status()
        result = response.json()
        voice_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(voice_id, str) or not re.fullmatch(r"voice_[A-Za-z0-9_-]{1,240}", voice_id):
            raise ValueError("invalid voice response")
    except (httpx.HTTPError, ValueError, TypeError):
        raise RuntimeError(
            "Crearea nu a putut fi confirmată. Verifică vocile în contul OpenAI înainte "
            "de a reîncerca; fișierul rezultat păstrează marcajul cererii."
        ) from None
    with args.output.open("w", encoding="utf-8") as output:
        json.dump({
            "status": "created", "id": voice_id, "name": VOICE_NAME,
            "type": "prompt", "prompt": VOICE_PROMPT, "script_hint": VOICE_SCRIPT_HINT,
        }, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return voice_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Read credentials from this .env (never modified).")
    parser.add_argument("--output", type=Path, help="New metadata JSON file outside the repository.")
    parser.add_argument("--show-profile", action="store_true", help="Print the voice profile without API calls.")
    args = parser.parse_args()
    if args.show_profile:
        print(json.dumps({"name": VOICE_NAME, "prompt": VOICE_PROMPT, "script_hint": VOICE_SCRIPT_HINT}, ensure_ascii=False, indent=2))
        return 0
    if args.output is None:
        parser.error("--output is required when creating a voice")
    try:
        voice_id = asyncio.run(create_voice(args))
    except (RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"GUGUTA_OPENAI_VOICE_ID={voice_id}")
    print("Adaugă această linie în .env și recreează serviciul API. Fișierul .env nu a fost modificat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
