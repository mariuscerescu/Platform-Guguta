"""Maintenance-only reindex: new inactive space, activate only after completeness.

Run from repo root with PYTHONPATH=.; stop API and worker first. Reads only
the Guguță DB selected by the migrator DSN. Never deletes source text or files.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import text

from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.database.guguta.engine import create_migrator_engine
from open_notebook.jobs.guguta.embeddings import get_provider


async def reindex(config: GugutaConfig) -> int:
    if config.embedding_provider not in ("openrouter", "local"):
        raise ValueError("Select a real GUGUTA_EMBEDDING_PROVIDER")
    engine = create_migrator_engine(config)
    provider = get_provider(
        config.embedding_provider, config.embedding_dimension, config
    )
    batch_size = (
        config.local_embedding_batch_size
        if config.embedding_provider == "local"
        else config.openrouter_embedding_batch_size
    )
    try:
        async with engine.begin() as conn:
            row = (await conn.execute(text(
                "SELECT id FROM embedding_spaces WHERE model_name=:m AND model_revision=:r"
                " AND dimension=:d ORDER BY is_active DESC,created_at DESC LIMIT 1"
            ), {"m": provider.model_name, "r": provider.model_revision, "d": provider.dimension})).first()
            space_id = row[0] if row else uuid.uuid4()
            if row is None:
                await conn.execute(text(
                    "INSERT INTO embedding_spaces(id,model_name,model_revision,dimension,distance_strategy,is_active)"
                    " VALUES(:id,:m,:r,:d,'cosine',false)"
                ), {"id": space_id, "m": provider.model_name, "r": provider.model_revision, "d": provider.dimension})
        count = 0
        while True:
            async with engine.begin() as conn:
                chunks = (await conn.execute(text(
                    "SELECT c.id,c.text FROM chunks c WHERE NOT EXISTS"
                    " (SELECT 1 FROM embeddings e WHERE e.chunk_id=c.id AND e.embedding_space_id=:s)"
                    " ORDER BY c.id LIMIT :lim"
                ), {"s": space_id, "lim": batch_size})).all()
            if not chunks:
                break
            vectors = await provider.embed([c.text for c in chunks])
            async with engine.begin() as conn:
                for chunk, vector in zip(chunks, vectors, strict=True):
                    await conn.execute(text(
                        "INSERT INTO embeddings(id,chunk_id,embedding_space_id,embedding)"
                        " VALUES(:id,:c,:s,CAST(:v AS vector)) ON CONFLICT(chunk_id,embedding_space_id) DO NOTHING"
                    ), {"id": uuid.uuid4(), "c": chunk.id, "s": space_id, "v": str(vector)})
            count += len(chunks)
        async with engine.begin() as conn:
            # Maintenance command: block writes during final completeness check/swap.
            await conn.execute(text("LOCK TABLE chunks,embeddings,embedding_spaces IN SHARE ROW EXCLUSIVE MODE"))
            missing = (await conn.execute(text(
                "SELECT count(*) FROM chunks c WHERE NOT EXISTS"
                " (SELECT 1 FROM embeddings e WHERE e.chunk_id=c.id AND e.embedding_space_id=:s)"
            ), {"s": space_id})).scalar_one()
            if missing:
                raise RuntimeError("Concurrent writes detected; keep API/worker stopped and rerun")
            await conn.execute(text("UPDATE embedding_spaces SET is_active=false WHERE is_active"))
            await conn.execute(text("UPDATE embedding_spaces SET is_active=true WHERE id=:s"), {"s": space_id})
        return count
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maintenance", action="store_true", required=True,
                        help="Confirms API/worker are stopped on the target DB")
    parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    cfg = GugutaConfig(_env_file=(".env.guguta", ".env.guguta.local"))
    print("Chunks reindexed:", asyncio.run(reindex(cfg)))
