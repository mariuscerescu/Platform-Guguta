# Guguță Edu Platform - Deployment Notes for Agents

This file records the live deployment shape for `https://tineri.math.md/edu-platform`.
It is intentionally operational and secret-free. Do not paste `.env` values, API keys,
PostgreSQL passwords, session secrets, or cookie material into logs, commits, or chat.

## Live Host Topology

Public traffic enters through the host nginx that already serves `tineri.math.md`.
The Guguță stack itself exposes only one loopback port:

```text
Browser
  -> https://tineri.math.md/edu-platform/...
  -> host nginx location /edu-platform
  -> http://127.0.0.1:8300
  -> frontend container, Next.js on port 3001
  -> Next rewrite /edu-platform/guguta-api/* to api:5055
  -> FastAPI api container
  -> PostgreSQL/pgvector db container and worker container on Docker network
```

Only `frontend` binds a host port, and it is bound to `127.0.0.1`. The API,
worker, and database are internal Docker services.

## Existing Apps on the Same Domain

Before touching nginx, inspect the active host config and preserve the audio routes.
At the time of this deployment they are served by a separate stack under
`/opt/dataset-maker-app` via `tts-suite-proxy` on `127.0.0.1:8000`:

- `https://tineri.math.md/audio/dataset-builder/`
- `https://tineri.math.md/audio/voice-recorder/`

Do not replace the whole nginx server block. Add or update only the
`location /edu-platform` block. After any nginx change, verify the two audio URLs
still return HTTP 200.

Useful inspection commands:

```bash
sudo nginx -T
find /etc/nginx -maxdepth 3 -type f
find /opt/dataset-maker-app -maxdepth 3 -type f
curl -I https://tineri.math.md/audio/dataset-builder/
curl -I https://tineri.math.md/audio/voice-recorder/
```

## Repository and Compose Commands

Repo path on the server:

```bash
/home/jupyter-marius/Platform-Guguta
```

The server currently has legacy `docker-compose` v1. Use `--project-name` every
time so the stack name stays stable, because the Compose file is v1-compatible
and does not use the top-level `name:` key.

```bash
cd /home/jupyter-marius/Platform-Guguta
sudo docker-compose --project-name guguta-edu -f deploy/edu-platform/docker-compose.yml ps
sudo docker-compose --project-name guguta-edu -f deploy/edu-platform/docker-compose.yml build api frontend
sudo docker-compose --project-name guguta-edu -f deploy/edu-platform/docker-compose.yml up -d --no-deps api frontend
```

Known Compose v1 issue: recreating a service may fail with `KeyError:
ContainerConfig` and leave the old container renamed and stopped. The safe
workaround is to remove only the stopped renamed container, then run `up` again.
Do not remove volumes.

```bash
sudo docker ps -a --filter name=guguta-edu_frontend_1 --format '{{.ID}} {{.Names}} {{.Status}}'
sudo docker rm <stopped-container-id>
sudo docker-compose --project-name guguta-edu -f deploy/edu-platform/docker-compose.yml up -d --no-deps frontend
```

## Environment File

Live env file:

```bash
/home/jupyter-marius/Platform-Guguta/deploy/edu-platform/.env
```

It must exist on the server and stay mode `600`. It is ignored by Git. Required
high-level values:

- `GUGUTA_ENVIRONMENT=production`
- `GUGUTA_AUTH_MODE=password`
- `GUGUTA_BASE_PATH=/edu-platform`
- `GUGUTA_HTTP_PORT=8300`
- `GUGUTA_PUBLIC_ORIGIN=https://tineri.math.md`
- `GUGUTA_CORS_ORIGINS=["https://tineri.math.md"]`
- `GUGUTA_CHAT_PROVIDER=openrouter` and `GUGUTA_OPENROUTER_CHAT_MODEL=google/gemma-4-31b-it`
- `GUGUTA_EMBEDDING_PROVIDER=local`, `GUGUTA_RERANK_PROVIDER=local`, and `GUGUTA_EMBEDDING_DIMENSION=1024`
- local models `Qwen/Qwen3-Embedding-0.6B` and `Qwen/Qwen3-Reranker-0.6B`
- non-default server, credential-encryption, and PostgreSQL role secrets

`GUGUTA_BASE_PATH` is baked into the Next.js client bundle at build time. Any
change to it requires rebuilding the frontend image. Most runtime env changes
for API/worker require container recreation, not a frontend rebuild.

## Nginx Contract

The host nginx `location /edu-platform` must proxy to the frontend without
stripping the prefix:

```nginx
location /edu-platform {
    proxy_pass http://127.0.0.1:8300;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    client_max_body_size 32m;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    send_timeout 600s;
}
```

Important: `proxy_pass` has no trailing slash. A trailing slash strips
`/edu-platform` and breaks the Next.js basePath.

## Frontend Routing Contract

The app has separate user-facing routes:

- `/edu-platform` - landing page
- `/edu-platform/login` - login
- `/edu-platform/register` - registration
- `/edu-platform/app` - notebook list
- `/edu-platform/notebook/<id>` - opened notebook and chat

The frontend Docker image uses `WORKDIR /site`. Do not change it back to
`/app`; using `/app` collides with the Next.js `app/` source directory and the
public `/app` route, causing `/edu-platform` to serve the notebook list instead
of the landing page.

## Chat Generation Behavior

The notebook page posts to:

```text
/edu-platform/guguta-api/api/v1/notebooks/<notebook_id>/sessions/<session_id>/messages/stream
```

The endpoint returns Server-Sent Events as `data: {json}\n\n`. OpenRouter chat is
currently validated as one complete JSON answer, then emitted word by word to
the browser. While waiting, the backend sends `ping` events every 15 seconds so
proxies do not close the connection.

Retrieval updates (2026-10-06, ADR-014): explicit page queries use indexed
printed/PDF locator metadata, and chat uses request-local validated citations.
`GUGUTA_CHAT_PDF_IMAGES=true` supplies original PDF page images to the configured
image-capable model, rather than relying on damaged mathematical OCR alone.
`GUGUTA_CHAT_ANSWER_REVIEW=true` enables an additional source-based review
completion before publishing the answer; this increases latency and cost.
Both options default to false. Existing documents and embeddings are unchanged.
The mathematics evaluation also found residual visual transcription errors
with Gemma after source-based review. GPT-5.4 was used in a historical evaluation,
but the user explicitly requires Gemma 4 31B and prohibits more expensive models.
The live configuration must remain
`GUGUTA_OPENROUTER_CHAT_MODEL=google/gemma-4-31b-it`, without implicit model
fallbacks. Do not run expensive alternative-model probes. Local Qwen embedding
and reranking models remain unchanged. The historical GPT-5.4 result does not
prove the same score for Gemma; new evaluation must use Gemma throughout.
The complete Gemma rerun on 2026-10-06 scored 98 correct, 2 partial, and 0 failed
answers on the same frozen 100-question suite. All 100 requests completed and
cited a reference page. See `docs/guguta/retrieval-evaluation-2026-10-06.md` for
the remaining errors and validation scope.
Lexical retrieval folds historical/current Romanian diacritics and uses
PostgreSQL's built-in Romanian stemming, with query instruction/function words
filtered out when subject terms remain. This affects retrieval ranking only;
stored source text and embeddings are untouched and no migration is required.
Visible citation markers use the ordered saved citation list, not sparse
indexes into the hidden retrieval context. No migration is needed.

The UI must not spin forever. Backend streaming now enforces the configured
`GUGUTA_CHAT_TOTAL_TIMEOUT_SECONDS`, logs stream failures, and emits an `error`
event when generation is too slow or invalid. The frontend also aborts a stuck
stream after about 310 seconds and shows a clear error.

For answers with no sources, the server strips citation markers like `[1]` but
must not prepend the old fixed phrase:

```text
Nu am materiale din carnet care să acopere întrebarea, așa că îți răspund din cunoștințele generale:
```

## Verification Checklist

After deployment or config changes:

```bash
curl -s -o /dev/null -w '%{http_code}\n' https://tineri.math.md/edu-platform
curl -s https://tineri.math.md/edu-platform/guguta-api/healthz
curl -s https://tineri.math.md/edu-platform/guguta-api/readyz
curl -s -o /dev/null -w '%{http_code}\n' https://tineri.math.md/edu-platform/login
curl -s -o /dev/null -w '%{http_code}\n' https://tineri.math.md/edu-platform/register
curl -s -o /dev/null -w '%{http_code}\n' https://tineri.math.md/edu-platform/app
curl -s -o /dev/null -w '%{http_code}\n' https://tineri.math.md/audio/dataset-builder/
curl -s -o /dev/null -w '%{http_code}\n' https://tineri.math.md/audio/voice-recorder/
```

For chat debugging, create a temporary account through the public API, create a
notebook and session, then `curl -N` the stream. A healthy stream contains
`user_saved`, optional `ping`, one or more `token` events, and final `done`.

## Git Hygiene

Before pushing:

```bash
git status --short
git diff --check
python3 -m py_compile api/services/guguta/chat.py open_notebook/ai/guguta/openrouter.py
```

Never commit `deploy/edu-platform/.env`, cookies, temporary curl outputs,
Playwright caches, screenshots, or server logs.
