"""Bounded, request-authorized PDF page images for mathematical evidence.

Images supplement original chunks; they never become a different source and
never contain data from an unselected or unauthorized notebook material.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import math
import threading
import uuid
from collections import OrderedDict
from dataclasses import replace

from sqlalchemy import bindparam, text

from api.services.guguta.search import RetrievedChunk
from open_notebook.database.guguta.engine import actor_connection

logger = logging.getLogger(__name__)
_PDFIUM_LOCK = threading.Lock()


class PdfPageEvidence:
    def __init__(
        self,
        engine,
        storage,
        *,
        max_pages: int = 4,
        cache_bytes: int = 16 * 1024 * 1024,
    ):
        self._engine = engine
        self._storage = storage
        self._max_pages = max_pages
        self._cache_bytes = cache_bytes
        self._cache: OrderedDict[tuple[str, int], bytes] = OrderedDict()
        self._size = 0
        self._render_lock = asyncio.Lock()

    async def enrich(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID, chunks: list[RetrievedChunk]
    ) -> list[RetrievedChunk]:
        # Incoming chunks may already contain a previous render. Authorization
        # failures must clear those pixels too, including cache hits.
        chunks = [replace(c, image_url=None) for c in chunks]
        source_ids = list(
            {c.notebook_source_id for c in chunks if c.locator.get("page")}
        )
        if not source_ids:
            return chunks
        # Check source selection and notebook authorization on EVERY request,
        # including cache hits. The cache is not an access-control shortcut.
        statement = text(
            "SELECT mv.id,sa.storage_key,sa.sha256,sa.mime_type FROM notebook_sources ns "
            "JOIN material_versions mv ON mv.id=ns.material_version_id "
            "JOIN source_assets sa ON sa.id=mv.source_asset_id "
            "WHERE ns.notebook_id=:nb AND ns.id IN :source_ids "
            "AND ns.selected_for_chat AND ns.status='ready' AND sa.kind='file' "
            "AND sa.mime_type='application/pdf'"
        ).bindparams(bindparam("source_ids", expanding=True))
        async with actor_connection(self._engine, actor_id) as conn:
            rows = (
                (
                    await conn.execute(
                        statement, {"nb": notebook_id, "source_ids": source_ids}
                    )
                )
                .mappings()
                .all()
            )
        assets = {r["id"]: r for r in rows}
        seen = set()
        enriched = []
        for chunk in chunks:
            asset = assets.get(chunk.material_version_id)
            page = chunk.locator.get("page")
            key = (str(asset["sha256"]), page) if asset is not None else None
            if (
                asset is None
                or type(page) is not int
                or page < 1
                or key in seen
                or len(seen) >= self._max_pages
            ):
                enriched.append(chunk)
                continue
            seen.add(key)
            try:
                async with self._render_lock:
                    png = self._cache.get(key)
                    if png is None:
                        png = await asyncio.to_thread(
                            self._render, asset["storage_key"], page
                        )
                        self._cache[key] = png
                        self._size += len(png)
                        while self._size > self._cache_bytes and self._cache:
                            _, old = self._cache.popitem(last=False)
                            self._size -= len(old)
                    elif key in self._cache:
                        self._cache.move_to_end(key)
                enriched.append(
                    replace(
                        chunk,
                        image_url="data:image/png;base64,"
                        + base64.b64encode(png).decode("ascii"),
                    )
                )
            except Exception as exc:
                logger.warning("PDF page evidence unavailable (%s)", type(exc).__name__)
                enriched.append(chunk)
        # For an exact page transcription, damaged OCR is a competing answer,
        # not useful evidence. Show the original page once, with its identity,
        # and let the model read the exercise directly. Semantic queries keep
        # text as well as images for cross-page synthesis.
        visual_pages = {
            (c.material_version_id, c.locator.get("page"))
            for c in enriched
            if c.image_url
        }
        output = []
        kept_visual = set()
        for chunk in enriched:
            key = (chunk.material_version_id, chunk.locator.get("page"))
            if chunk.mode == "locator" and key in visual_pages:
                if key in kept_visual:
                    continue
                kept_visual.add(key)
                chunk = replace(
                    chunk,
                    extracted_text=chunk.text,
                    text=(
                        f"Pagina PDF: {chunk.locator.get('page')}; "
                        f"pagina tipărită: {chunk.locator.get('printed_page')}. "
                        "Examinează imaginea originală pentru cerința utilizatorului, "
                        "inclusiv obiectele desenate, fracțiile, formulele și schemele."
                    ),
                )
            output.append(chunk)
        return output

    async def crop(
        self, actor_id: uuid.UUID, notebook_id: uuid.UUID,
        chunk: RetrievedChunk, region: tuple[float, float, float, float],
    ) -> RetrievedChunk | None:
        """Render a region from the original PDF after fresh authorization.

        Coordinates use the full page, normalized from top-left. Re-rendering
        the PDF gives small text more detail than resizing an existing PNG.
        """
        if (len(region) != 4 or any(not math.isfinite(v) or v < 0 or v > 1 for v in region)
            or region[0] >= region[2] or region[1] >= region[3]):
            raise ValueError("Regiunea imaginii este invalidă.")
        page_number = chunk.locator.get("page")
        if type(page_number) is not int or page_number < 1:
            return None
        async with actor_connection(self._engine, actor_id) as conn:
            row = (await conn.execute(text(
                "SELECT sa.storage_key FROM notebook_sources ns "
                "JOIN material_versions mv ON mv.id=ns.material_version_id "
                "JOIN source_assets sa ON sa.id=mv.source_asset_id "
                "WHERE ns.notebook_id=:nb AND ns.id=:source "
                "AND mv.id=:mv AND ns.selected_for_chat AND ns.status='ready' "
                "AND sa.kind='file' AND sa.mime_type='application/pdf'"
            ), {"nb": notebook_id, "source": chunk.notebook_source_id,
                "mv": chunk.material_version_id})).scalar_one_or_none()
        if row is None:
            return None
        try:
            async with self._render_lock:
                png = await asyncio.to_thread(self._render, row, page_number, region)
        except Exception as exc:
            logger.warning("PDF region evidence unavailable (%s)", type(exc).__name__)
            return None
        return replace(
            chunk,
            image_url="data:image/png;base64," + base64.b64encode(png).decode("ascii"),
            locator={**chunk.locator, "image_region": list(region)},
            text=(f"Decupaj din pagina PDF {page_number}, regiunea {region}. "
                  "Coordonatele se raportează la pagina originală întreagă."),
        )

    def _render(
        self, storage_key: str, page_number: int,
        region: tuple[float, float, float, float] | None = None,
    ) -> bytes:
        import pypdfium2

        data = self._storage.read_bytes(storage_key)
        # PDFium is not thread safe. Close every native handle before releasing
        # the process-wide render lock; no document text enters error messages.
        with _PDFIUM_LOCK:
            with pypdfium2.PdfDocument(data) as document:
                if page_number > len(document):
                    raise ValueError("PDF page out of range")
                page = document[page_number - 1]
                try:
                    width, height = page.get_size()
                    crop = (0, 0, 0, 0)
                    scale = min(2.0, 2048 / max(width, height))
                    if region is not None:
                        left, top, right, bottom = region
                        crop = (width * left, height * (1 - bottom),
                                width * (1 - right), height * top)
                        scale = min(6.0, 2048 / max(width * (right-left), height * (bottom-top)))
                    bitmap = page.render(scale=scale, crop=crop)
                    try:
                        output = io.BytesIO()
                        bitmap.to_pil().save(output, format="PNG")
                        return output.getvalue()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
