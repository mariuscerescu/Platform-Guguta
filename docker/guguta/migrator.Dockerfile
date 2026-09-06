# Guguță migrator image (ADR-0007): runs `alembic upgrade head` exactly once
# per release. Contains only the PostgreSQL stack — no SurrealDB, no AI deps.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN pip install --no-cache-dir \
    "sqlalchemy[asyncio]>=2.0.36,<2.1" \
    "psycopg[binary,pool]>=3.2.3,<3.3" \
    "alembic>=1.14.0,<1.15" \
    "pgvector>=0.3.6,<0.4" \
    "pydantic-settings>=2.6.0,<3" \
    "loguru>=0.7.2,<0.8"

WORKDIR /app

# Only the pieces the migrations need; the full application image arrives
# with the Guguță build delivery (L8 builds from a fixed commit).
# Note: open_notebook/database/ has no __init__.py upstream (namespace pkg).
COPY alembic.ini ./
COPY alembic ./alembic
COPY open_notebook/__init__.py open_notebook/__init__.py
COPY open_notebook/database/guguta ./open_notebook/database/guguta

CMD ["alembic", "upgrade", "head"]
