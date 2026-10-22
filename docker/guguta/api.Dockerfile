# Guguță API/worker image (L8): built from a fixed commit, target runtime
# WITHOUT SurrealDB / surreal-commands / podcast stack / SQLite checkpoints.
# Same image serves API (`uvicorn api.guguta_app:app`) and worker
# (`python -m open_notebook.jobs.guguta.worker`) with different roles/DSNs.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir \
    "fastapi>=0.115,<1" \
    "uvicorn[standard]>=0.30,<1" \
    "python-multipart>=0.0.20,<0.1" \
    "sqlalchemy[asyncio]>=2.0.36,<2.1" \
    "psycopg[binary,pool]>=3.2.3,<3.3" \
    "alembic>=1.14.0,<1.15" \
    "pgvector>=0.3.6,<0.4" \
    "pydantic>=2.9.2,<3" \
    "pydantic-settings>=2.6.0,<3" \
    "authlib>=1.3.2,<2" \
    "cryptography>=43,<44" \
    "pypdf>=5.0.0,<6" \
    "pypdfium2==5.11.0" \
    "pillow>=12.0,<13" \
    "liteparse==2.14.6" \
    "httpx>=0.27,<1" \
    "loguru>=0.7.2,<0.8" \
    "langgraph==1.2.5" \
    "langchain-core==1.4.7" \
    "python-dotenv>=1.2.2,<2"

# Run as non-root (GHID §10.3); writable temp dirs declared below.
RUN useradd --create-home --uid 10001 guguta

WORKDIR /app

# Explicit source list — the target runtime never ships the legacy stack.
# (namespace packages: api/services has no __init__.py by design)
COPY alembic.ini ./
COPY alembic ./alembic
COPY open_notebook/__init__.py open_notebook/__init__.py
COPY open_notebook/exceptions.py open_notebook/exceptions.py
COPY open_notebook/database/guguta ./open_notebook/database/guguta
COPY open_notebook/auth/guguta ./open_notebook/auth/guguta
COPY open_notebook/storage/guguta ./open_notebook/storage/guguta
COPY open_notebook/jobs/guguta ./open_notebook/jobs/guguta
COPY open_notebook/ai/guguta ./open_notebook/ai/guguta
COPY api/__init__.py api/__init__.py
COPY api/routers/__init__.py api/routers/__init__.py
COPY api/routers/guguta_v1.py api/routers/guguta_v1.py
COPY api/routers/guguta_voice.py api/routers/guguta_voice.py
COPY api/routers/guguta_survey.py api/routers/guguta_survey.py
COPY api/services/guguta ./api/services/guguta
COPY api/guguta_app.py api/guguta_app.py
COPY scripts/guguta_reindex_openrouter.py scripts/guguta_reindex_openrouter.py
COPY scripts/guguta_reindex_embeddings.py scripts/guguta_reindex_embeddings.py
COPY scripts/guguta_agent_smoke.py scripts/guguta_agent_smoke.py

# Build metadata (set via --build-arg from CI / docker build)
ARG GUGUTA_COMMIT=unknown
ENV GUGUTA_COMMIT=${GUGUTA_COMMIT}

RUN mkdir -p /app/.guguta_storage /data/guguta_storage \
    && chown -R guguta:guguta /app /data
USER guguta

EXPOSE 5055

# API default; the worker runs the same image with
# command: python -m open_notebook.jobs.guguta.worker
CMD ["uvicorn", "api.guguta_app:app", "--host", "0.0.0.0", "--port", "5055"]
