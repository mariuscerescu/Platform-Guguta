"""Garbage collection for unreferenced source assets (L7, ADR-0006).

Two phases (GHID §8.3), both safe to retry:
1. MARK: assets with no remaining references (material_versions →
   notebook_sources / template_materials / share_materials / pending jobs)
   older than the retention window become `gc_candidate`.
2. DELETE: candidates are re-verified; still-unreferenced ones lose their
   stored bytes and rows. Anything re-referenced in between is kept.

Runs as a maintenance task with the migrator-role connection (system scope);
it never runs concurrently with itself (single release job pattern).
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from open_notebook.storage.guguta.base import StorageBackend

logger = logging.getLogger("guguta.gc")

_MARK_SQL = """
UPDATE source_assets SET retention_status = 'gc_candidate'
WHERE retention_status = 'retained'
  AND created_at < now() - make_interval(days => :retention_days)
  AND NOT EXISTS (
      SELECT 1 FROM material_versions mv
      WHERE mv.source_asset_id = source_assets.id)
"""

_DELETE_SQL = """
WITH unreferenced AS (
    SELECT sa.id, sa.storage_key FROM source_assets sa
    WHERE sa.retention_status = 'gc_candidate'
      AND NOT EXISTS (SELECT 1 FROM material_versions mv
                      WHERE mv.source_asset_id = sa.id)
    FOR UPDATE
), deleted AS (
    DELETE FROM source_assets sa USING unreferenced u WHERE sa.id = u.id
    RETURNING sa.id, u.storage_key
)
SELECT id, storage_key FROM deleted
"""

_RESTORE_SQL = """
UPDATE source_assets SET retention_status = 'retained'
WHERE retention_status = 'gc_candidate'
  AND EXISTS (SELECT 1 FROM material_versions mv
              WHERE mv.source_asset_id = source_assets.id)
"""


async def gc_sweep(
    engine: AsyncEngine, storage: StorageBackend, *, retention_days: int = 30
) -> dict[str, int]:
    """Run one GC cycle. Returns counters for the report/alerting."""
    # Phase 1: mark candidates past retention.
    async with engine.begin() as conn:
        result = await conn.execute(
            text(_MARK_SQL), {"retention_days": retention_days}
        )
        marked = int(result.rowcount or 0)
        # restore anything that gained references since it was marked
        await conn.execute(text(_RESTORE_SQL))

    # Phase 2: re-verify, delete rows, then their stored bytes.
    deleted = 0
    storage_failures = 0
    async with engine.begin() as conn:
        rows = (
            await conn.execute(text(_DELETE_SQL))
        ).all()
    for asset_id, storage_key in rows:
        if storage_key:
            try:
                storage.delete(storage_key)
            except Exception:  # pragma: no cover
                storage_failures += 1
                logger.warning("nu am putut șterge obiectul %s", storage_key)
        deleted += 1
        _ = asset_id

    logger.info(
        "GC: marcate=%s șterse=%s eșecuri_stocare=%s", marked, deleted,
        storage_failures,
    )
    return {"marked": marked, "deleted": deleted, "storage_failures": storage_failures}
