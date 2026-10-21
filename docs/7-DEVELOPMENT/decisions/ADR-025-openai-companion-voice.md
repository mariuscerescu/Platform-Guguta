# ADR-025: OpenAI voice alongside ElevenLabs

Date: 2026-10-17
Status: Accepted

## Context

Guguță needs a second voice provider with an original Romanian voice and a natural
Moldovan accent. The requested voice is masculine, warm and playful, with an adult
age of 20–21. Its accent and expressiveness require a listening check after creation.

## Decision

Use GPT-Live (`gpt-live-1`) over WebRTC for OpenAI conversations. The companion's
gear menu chooses ElevenLabs or OpenAI; ElevenLabs remains the initial default.
Keep dictation and text chat independent of the conversation provider. Identify
synthetic speech in the UI with “Voce generată cu AI”.

The authenticated API creates Live sessions using server-held credentials and a
configured saved voice. It authorizes notebook context before opening a paid
session. Context retrieval reuses the existing actor-scoped notebook, source and
chunk access checks. Homepage context describes the platform. Quiz/card context
contains the question, not hidden solutions. Browser requests cannot override
the upstream URL, model, credentials or saved voice.

Client delegation retrieves current authorized evidence through the API. Context
updates and retrieval results are sent in bounded Live append events. Late
results from a closed session or changed activity are discarded. Voice switching,
navigation and logout release microphone capture and invalidate old callbacks.
Each conversation creates fresh audio resources. Closure uses `session.close`
and waits briefly for `session.closed` before releasing the transport.

`openai_voice_profile.py` contains the original prompt used for both voice
creation and session instructions. The creation command is an explicit operator
action. It does not run on application startup and never changes `.env`. Each
request saves a local metadata file and prevents accidental repeat creation.

## Configuration

The operator manages the deployment's environment files. On the current server,
the API reads both `deploy/edu-platform/.env` and the voice override file
`/home/jupyter-tudor/integrations/guguta-elevenlabs-20261010/runtime/elevenlabs.env`.
The ElevenLabs credentials are in the latter; OpenAI can be added alongside them:

```dotenv
OPENAI_API_KEY=...
GUGUTA_OPENAI_VOICE_ID=voice_...
```

`GUGUTA_OPENAI_API_KEY` optionally overrides `OPENAI_API_KEY` for this feature.
Neither key is exposed in browser code or provider metadata. OpenAI remains
unconfigured until both a key and valid voice ID are present. Recreate the API
container after an environment change; a plain process restart does not update
Docker's environment.

From a Python environment with the project's `httpx` and `python-dotenv` packages:

```sh
python tools/guguta/create_openai_voice.py --show-profile
python tools/guguta/create_openai_voice.py \
  --env-file /home/jupyter-tudor/integrations/guguta-elevenlabs-20261010/runtime/elevenlabs.env \
  --output /tmp/guguta-openai-voice.json
```

The second command contacts OpenAI and prints the returned voice ID. Preserve the
metadata outside version control and add the ID to `.env`. If the result is
uncertain, inspect the account's saved voices before retrying. The script does
not include the API key in output or saved metadata. Do not run paid voice calls
as part of automated tests.

## Consequences

No database migration is required. OpenAI receives microphone audio and the
authorized educational excerpts needed for the conversation. Application storage
of Live sessions is disabled. Provider-specific retention remains governed by
the account's OpenAI settings. Preview and conversation usage is billed separately
from generating the saved voice.

Prompt-generated voices currently require GPT-Live; they cannot be substituted
into the existing TTS or legacy Realtime paths. Their generated accent must be
assessed by listening before considering the voice ready for students.

## References

- [OpenAI custom voices](https://developers.openai.com/api/docs/guides/custom-voices)
- [GPT-Live WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live)
- [Client delegation](https://developers.openai.com/api/docs/guides/live-delegation)
- [Session lifecycle](https://developers.openai.com/api/docs/guides/live-conversations)
