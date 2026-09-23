"""Hybrid, page-aware PDF extraction for Guguță.

LiteParse handles the cheap native-text path and supplies layout/complexity
signals. Pages that look scanned, garbled, sparse, or structurally complex
are rendered and sent to the private PP-OCRv5 service. The two outputs are
normalized to :class:`TextUnit` objects so the existing chunker keeps page
and line provenance without knowing which parser produced the text.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from open_notebook.jobs.guguta.parsing import ExtractionError, TextUnit

logger = logging.getLogger("guguta.pdf")

LITEPARSE_VERSION = "2.14.6"
PPOCR_VERSION = "5-mobile-latin-full-page-v2"
PARSER_NAME = "liteparse+pp-ocrv5"
PARSER_VERSION = f"liteparse-{LITEPARSE_VERSION}_pp-ocrv5-{PPOCR_VERSION}"

_OCR_REASONS = frozenset({"scanned", "no-text", "sparse-text", "garbled", "vector-text"})
_IGNORED_OCR_LABELS = frozenset(
    {
        "header",
        "header_image",
        "footer",
        "footer_image",
        "number",
        "page_number",
        "image",
    }
)


class PdfExtractor(Protocol):
    parser_name: str
    parser_version: str

    async def extract(self, data: bytes) -> tuple[list[TextUnit], int]: ...

    async def aclose(self) -> None: ...


class PdfPipelineUnavailable(RuntimeError):
    """A local parser service failed transiently and the job may be retried."""


@dataclass(frozen=True)
class OcrBlock:
    text: str
    label: str
    bbox: list[float] | None
    order: int | None
    confidence: float | None = None


@dataclass(frozen=True)
class OcrPage:
    markdown: str
    blocks: list[OcrBlock]
    width: int | None
    height: int | None
    model: str


class PpOcrClient:
    """Client for the private PP-OCRv5 Mobile GPU service."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 300,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            # The GPU service owns one model and serializes inference. Keep
            # connections warm while requests wait in its bounded queue.
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=16),
        )

    async def parse_page(self, image: bytes, *, page_number: int) -> OcrPage:
        try:
            response = await self._client.post(
                "/v1/parse-page",
                files={"file": (f"page-{page_number}.png", image, "image/png")},
                data={"page_number": str(page_number)},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            detail = str(exc).strip() or type(exc).__name__
            raise PdfPipelineUnavailable(
                f"PP-OCRv5 nu este disponibil pentru pagina {page_number}: {detail}"
            ) from exc

        try:
            payload = response.json()
            markdown = payload.get("markdown") or ""
            if not isinstance(markdown, str):
                raise TypeError("markdown must be a string")
            blocks: list[OcrBlock] = []
            raw_blocks = payload.get("blocks") or []
            if not isinstance(raw_blocks, list):
                raise TypeError("blocks must be a list")
            for raw in raw_blocks:
                if not isinstance(raw, dict):
                    continue
                text = raw.get("text") or ""
                label = raw.get("label") or "text"
                if not isinstance(text, str) or not isinstance(label, str):
                    continue
                bbox = _valid_bbox(raw.get("bbox"))
                order_value = raw.get("order")
                order = order_value if isinstance(order_value, int) else None
                blocks.append(
                    OcrBlock(
                        text.strip(),
                        label,
                        bbox,
                        order,
                        _finite_number(raw.get("confidence")),
                    )
                )
            return OcrPage(
                markdown=markdown.strip(),
                blocks=blocks,
                width=_positive_int(payload.get("width")),
                height=_positive_int(payload.get("height")),
                model=str(payload.get("model") or "PP-OCRv5-mobile-latin"),
            )
        except (TypeError, ValueError) as exc:
            raise PdfPipelineUnavailable(
                f"PP-OCRv5 a returnat un rezultat invalid pentru pagina {page_number}."
            ) from exc

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class HybridPdfExtractor:
    """LiteParse native extraction with selective PP-OCRv5 page routing."""

    parser_name = PARSER_NAME
    parser_version = PARSER_VERSION

    def __init__(
        self,
        ocr: PpOcrClient,
        *,
        max_pages: int = 300,
        dpi: int = 150,
        liteparse_timeout_seconds: float = 120,
        ocr_every_page: bool = True,
        route_complex_layout: bool = True,
        render_batch_pages: int = 4,
        ocr_concurrency: int = 1,
    ) -> None:
        self._ocr = ocr
        self._max_pages = max_pages
        self._dpi = dpi
        self._liteparse_timeout_seconds = liteparse_timeout_seconds
        self._ocr_every_page = ocr_every_page
        self._route_complex_layout = route_complex_layout
        self._render_batch_pages = max(1, render_batch_pages)
        self._ocr_concurrency = max(1, ocr_concurrency)

    async def extract(self, data: bytes) -> tuple[list[TextUnit], int]:
        native = await asyncio.to_thread(self._parse_native, data)
        page_count = int(native.total_pages)
        if page_count <= 0:
            raise ExtractionError("PDF-ul nu conține pagini.")
        if page_count > self._max_pages:
            raise ExtractionError(
                f"PDF-ul are {page_count} pagini; limita este {self._max_pages}."
            )

        pages = sorted(native.pages, key=lambda page: int(page.page_num))
        routed: dict[int, list[str]] = {}
        for page in pages:
            reasons = _ocr_reasons(page, self._route_complex_layout)
            if self._ocr_every_page:
                reasons = list(dict.fromkeys([*reasons, "full-page-coverage"]))
            if reasons:
                routed[int(page.page_num)] = reasons

        ocr_pages: dict[int, OcrPage] = {}
        route_numbers = sorted(routed)
        for start in range(0, len(route_numbers), self._render_batch_pages):
            batch = route_numbers[start : start + self._render_batch_pages]
            screenshots = await asyncio.to_thread(self._render_pages, data, batch)
            by_page = {int(item.page_num): item for item in screenshots}
            missing = [page for page in batch if page not in by_page]
            if missing:
                raise PdfPipelineUnavailable(
                    "LiteParse nu a randat paginile pentru OCR: "
                    + ", ".join(map(str, missing))
                )
            semaphore = asyncio.Semaphore(self._ocr_concurrency)

            async def parse_one(page_number: int) -> tuple[int, OcrPage]:
                async with semaphore:
                    parsed = await self._ocr.parse_page(
                        by_page[page_number].image_bytes,
                        page_number=page_number,
                    )
                    return page_number, parsed

            parsed_batch = await asyncio.gather(
                *(parse_one(page_number) for page_number in batch)
            )
            ocr_pages.update(parsed_batch)

        units: list[TextUnit] = []
        for page in pages:
            page_number = int(page.page_num)
            native_units = _liteparse_units(page)
            if page_number in ocr_pages:
                page_units = _complete_page_units(
                    native_units,
                    ocr_pages[page_number],
                    page_number=page_number,
                    reasons=routed[page_number],
                    dpi=self._dpi,
                    native_page_label=getattr(page, "page_label", None),
                )
                if page_units:
                    units.extend(page_units)
                    continue
                # An empty OCR result must never discard exact native text.
                logger.warning(
                    "PP-OCRv5 nu a extras text din pagina %s (%s)",
                    page_number,
                    ", ".join(routed[page_number]),
                )
            units.extend(native_units)

        usable_chars = sum(len(unit.text.strip()) for unit in units)
        if not units or usable_chars < 20:
            raise ExtractionError(
                "PDF-ul nu conține text utilizabil; nici PP-OCRv5 nu a "
                "detectat suficient conținut pentru indexare."
            )
        return units, page_count

    def _parse_native(self, data: bytes) -> Any:
        try:
            from liteparse import LiteParse, ParseError
        except ImportError as exc:  # pragma: no cover - deployment packaging
            raise PdfPipelineUnavailable("LiteParse nu este instalat.") from exc

        parser = LiteParse(
            ocr_enabled=False,
            max_pages=self._max_pages,
            output_format="markdown",
            image_mode="off",
            extract_links=True,
            keep_headers_footers=False,
            extract_blocks=True,
            include_complexity=True,
            quiet=True,
            pool_size=1,
            parse_timeout=self._liteparse_timeout_seconds,
        )
        try:
            return parser.parse(data)
        except ParseError as exc:
            raise ExtractionError("PDF-ul nu a putut fi citit de LiteParse.") from exc
        finally:
            parser.close()

    def _render_pages(self, data: bytes, page_numbers: list[int]) -> list[Any]:
        try:
            from liteparse import LiteParse, ParseError
        except ImportError as exc:  # pragma: no cover - deployment packaging
            raise PdfPipelineUnavailable("LiteParse nu este instalat.") from exc
        parser = LiteParse(
            ocr_enabled=False,
            max_pages=self._max_pages,
            dpi=self._dpi,
            quiet=True,
        )
        try:
            # LiteParse accepts bytes for parse(), while screenshot() currently
            # accepts a filesystem path only.
            with tempfile.NamedTemporaryFile(suffix=".pdf") as source:
                source.write(data)
                source.flush()
                return list(parser.screenshot(source.name, page_numbers=page_numbers))
        except ParseError as exc:
            raise ExtractionError("Paginile PDF nu au putut fi randate pentru OCR.") from exc
        finally:
            parser.close()

    async def aclose(self) -> None:
        await self._ocr.aclose()


def _ocr_reasons(page: Any, route_complex_layout: bool) -> list[str]:
    complexity = getattr(page, "complexity", None)
    if complexity is None:
        return ["no-text"] if not str(getattr(page, "text", "")).strip() else []
    raw_reasons = [str(reason) for reason in (getattr(complexity, "reasons", None) or [])]
    reasons = [reason for reason in raw_reasons if reason in _OCR_REASONS]
    layout = getattr(complexity, "layout", None)
    if route_complex_layout and layout is not None and bool(getattr(layout, "is_complex", False)):
        reasons.extend(str(reason) for reason in (getattr(layout, "reasons", None) or []))
        if not getattr(layout, "reasons", None):
            reasons.append("complex-layout")
    # Do not OCR an otherwise healthy digital page merely because it contains
    # one illustration. LiteParse reports this as `embedded-images`.
    return list(dict.fromkeys(reasons))


def _liteparse_units(page: Any) -> list[TextUnit]:
    page_number = int(page.page_num)
    page_label = getattr(page, "page_label", None)
    width = _finite_number(getattr(page, "width", None))
    height = _finite_number(getattr(page, "height", None))
    blocks = getattr(page, "blocks", None) or []
    units: list[TextUnit] = []
    for order, block in enumerate(blocks, start=1):
        text = _liteparse_block_text(block)
        if not text.strip():
            continue
        bbox_obj = getattr(block, "bbox", None)
        bbox = None
        if bbox_obj is not None:
            x = _finite_number(getattr(bbox_obj, "x", None))
            y = _finite_number(getattr(bbox_obj, "y", None))
            w = _finite_number(getattr(bbox_obj, "width", None))
            h = _finite_number(getattr(bbox_obj, "height", None))
            if None not in (x, y, w, h):
                bbox = [x, y, x + w, y + h]  # type: ignore[operator]
        units.append(
            TextUnit(
                text=text.strip(),
                locator=_locator(
                    page_number,
                    engine="liteparse",
                    block_type=str(getattr(block, "kind", "text")),
                    block_order=order,
                    bbox=bbox,
                    width=width,
                    height=height,
                    coordinate_space="pdf_points_72dpi",
                    page_label=page_label,
                ),
            )
        )
    if units:
        return units
    page_text = str(getattr(page, "markdown", "") or getattr(page, "text", "")).strip()
    if not page_text:
        return []
    return [
        TextUnit(
            text=page_text,
            locator=_locator(
                page_number,
                engine="liteparse",
                width=width,
                height=height,
                coordinate_space="pdf_points_72dpi",
                page_label=page_label,
            ),
        )
    ]


def _liteparse_block_text(block: Any) -> str:
    kind = str(getattr(block, "kind", "paragraph"))
    text = str(getattr(block, "text", "") or "").strip()
    if kind == "heading" and text:
        level = getattr(block, "level", None)
        level = level if isinstance(level, int) and 1 <= level <= 6 else 2
        return f"{'#' * level} {text}"
    if kind == "list_item" and text:
        marker = str(getattr(block, "marker", "") or "-").strip()
        return f"{marker} {text}"
    if kind == "code":
        lines = getattr(block, "lines", None) or []
        if lines:
            lang = str(getattr(block, "lang", "") or "")
            return f"```{lang}\n" + "\n".join(map(str, lines)) + "\n```"
    if kind == "table":
        return _markdown_table(getattr(block, "header", None), getattr(block, "rows", None))
    if kind == "grid_fallback":
        return "\n".join(map(str, getattr(block, "lines", None) or []))
    return text


def _markdown_table(header: Any, rows: Any) -> str:
    header_cells = [_cell_text(cell) for cell in (header or [])]
    body = [[_cell_text(cell) for cell in row] for row in (rows or [])]
    column_count = max([len(header_cells), *(len(row) for row in body)], default=0)
    if column_count == 0:
        return ""
    if not header_cells:
        header_cells = [f"Coloana {index}" for index in range(1, column_count + 1)]
    header_cells += [""] * (column_count - len(header_cells))
    lines = [
        "| " + " | ".join(_escape_table(cell) for cell in header_cells) + " |",
        "| " + " | ".join("---" for _ in range(column_count)) + " |",
    ]
    for row in body:
        row = row + [""] * (column_count - len(row))
        lines.append("| " + " | ".join(_escape_table(cell) for cell in row) + " |")
    return "\n".join(lines)


def _ocr_units(
    page: OcrPage, *, page_number: int, reasons: list[str], dpi: int
) -> list[TextUnit]:
    units: list[TextUnit] = []
    ordered = sorted(
        enumerate(page.blocks),
        key=lambda item: (
            item[1].order is None,
            item[1].order if item[1].order is not None else item[0],
        ),
    )
    for fallback_order, block in ordered:
        if block.label in _IGNORED_OCR_LABELS or not block.text.strip():
            continue
        units.append(
            TextUnit(
                text=block.text.strip(),
                locator=_locator(
                    page_number,
                    engine="pp-ocrv5",
                    model=page.model,
                    block_type=block.label,
                    block_order=block.order or fallback_order + 1,
                    bbox=block.bbox,
                    width=page.width,
                    height=page.height,
                    coordinate_space=f"image_pixels_{dpi}dpi",
                    ocr_reasons=reasons,
                    ocr_confidence=block.confidence,
                ),
            )
        )
    if units or not page.markdown:
        return units
    return [
        TextUnit(
            text=page.markdown,
            locator=_locator(
                page_number,
                engine="pp-ocrv5",
                model=page.model,
                width=page.width,
                height=page.height,
                coordinate_space=f"image_pixels_{dpi}dpi",
                ocr_reasons=reasons,
            ),
        )
    ]


_PRINTED_PAGE_RE = re.compile(r"^[0-9]{1,4}$")


def _complete_page_units(
    native_units: list[TextUnit],
    page: OcrPage,
    *,
    page_number: int,
    reasons: list[str],
    dpi: int,
    native_page_label: object = None,
) -> list[TextUnit]:
    """Build one loss-averse, retrieval-friendly unit for a PDF page.

    Native PDF text is exact but cannot see words baked into illustrations.
    OCR sees the rendered page but can introduce recognition errors. Keeping
    both representations (unless they normalize identically) avoids choosing
    one failure mode over the other and keeps page/exercise labels adjacent to
    their content instead of publishing hundreds of one-character chunks.
    """

    native_text = "\n\n".join(
        unit.text.strip() for unit in native_units if unit.text.strip()
    )
    accepted_blocks = [
        block
        for block in sorted(
            page.blocks,
            key=lambda block: (
                block.order is None,
                block.order if block.order is not None else 0,
            ),
        )
        if block.label not in _IGNORED_OCR_LABELS and block.text.strip()
    ]
    ocr_text = "\n".join(block.text.strip() for block in accepted_blocks)
    if not native_text and not ocr_text:
        return []

    printed_page = _printed_page_number(page, native_page_label)
    header = f"[Pagina PDF: {page_number}"
    if printed_page is not None:
        header += f"; pagina tipărită: {printed_page}"
    header += "]"

    sections = [header]
    if native_text:
        sections.append(native_text)
    if ocr_text and _normalized_page_text(ocr_text) != _normalized_page_text(native_text):
        if native_text:
            sections.append("[Text vizual detectat prin OCR]\n" + ocr_text)
        else:
            sections.append(ocr_text)

    engines = {str(unit.locator.get("engine") or "liteparse") for unit in native_units}
    engines.add("pp-ocrv5")
    engine = "+".join(sorted(engines))
    locator = _locator(
        page_number,
        engine=engine,
        model=page.model,
        block_type="page",
        width=page.width,
        height=page.height,
        coordinate_space=f"page_composite_{dpi}dpi",
        page_label=str(native_page_label) if native_page_label is not None else None,
        printed_page=printed_page,
        ocr_reasons=reasons,
        ocr_block_count=len(accepted_blocks),
        native_block_count=len(native_units),
    )
    return [TextUnit(text="\n\n".join(sections), locator=locator)]


def _normalized_page_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _printed_page_number(page: OcrPage, native_page_label: object = None) -> int | None:
    label = str(native_page_label or "").strip()
    if _PRINTED_PAGE_RE.fullmatch(label):
        return int(label)
    if not page.height:
        return None

    # Textbooks normally place the printed folio in the bottom margin. Limit
    # the heuristic to that band so exercise numbers elsewhere on the page do
    # not become page metadata.
    candidates: list[tuple[float, float, int]] = []
    for block in page.blocks:
        text = block.text.strip()
        if not _PRINTED_PAGE_RE.fullmatch(text) or block.bbox is None:
            continue
        if block.bbox[1] < page.height * 0.82:
            continue
        confidence = block.confidence if block.confidence is not None else 0.0
        candidates.append((block.bbox[3], confidence, int(text)))
    if not candidates:
        return None
    return max(candidates)[2]


def _locator(page: int, *, engine: str, **values: Any) -> dict[str, object]:
    locator: dict[str, object] = {"page": page, "engine": engine}
    locator.update({key: value for key, value in values.items() if value is not None})
    return locator


def _cell_text(cell: Any) -> str:
    return str(getattr(cell, "text", cell) or "").strip()


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _finite_number(value: Any) -> float | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    converted = float(value)
    return converted if math.isfinite(converted) else None


def _positive_int(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def _valid_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    converted = [_finite_number(item) for item in value]
    if any(item is None for item in converted):
        return None
    bbox = [float(item) for item in converted if item is not None]
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox
