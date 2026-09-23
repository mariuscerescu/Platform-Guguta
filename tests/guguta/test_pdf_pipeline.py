from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from open_notebook.database.guguta.config import GugutaConfig
from open_notebook.jobs.guguta.parsing import TextUnit, segment
from open_notebook.jobs.guguta.pdf_pipeline import (
    HybridPdfExtractor,
    OcrBlock,
    OcrPage,
    PdfPipelineUnavailable,
    PpOcrClient,
    _complete_page_units,
    _liteparse_units,
    _ocr_reasons,
    _printed_page_number,
)


def test_pdf_pipeline_refuses_remote_ocr_endpoint() -> None:
    with pytest.raises(ValueError, match="local PP-OCRv5 service"):
        GugutaConfig(
            _env_file=None,
            ppocr_base_url="https://ocr.example.com",
        )


def _complexity(*reasons: str, layout_reasons: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        reasons=list(reasons),
        needs_ocr=bool(reasons),
        layout=SimpleNamespace(
            is_complex=bool(layout_reasons),
            reasons=list(layout_reasons),
        ),
    )


def _page(
    number: int,
    text: str,
    *,
    complexity: SimpleNamespace,
    blocks: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        page_num=number,
        page_label=None,
        width=612.0,
        height=792.0,
        text=text,
        markdown=text,
        complexity=complexity,
        blocks=blocks or [],
    )


def test_routing_ignores_illustration_only_but_routes_scan_and_layout() -> None:
    illustration = _page(
        1,
        "Text digital suficient",
        complexity=_complexity("embedded-images"),
    )
    assert _ocr_reasons(illustration, True) == []

    scanned = _page(2, "", complexity=_complexity("scanned", "no-text"))
    assert _ocr_reasons(scanned, True) == ["scanned", "no-text"]

    columns = _page(
        3,
        "Text digital",
        complexity=_complexity(layout_reasons=("multi-column",)),
    )
    assert _ocr_reasons(columns, True) == ["multi-column"]
    assert _ocr_reasons(columns, False) == []


def test_liteparse_units_keep_block_layout_metadata() -> None:
    block = SimpleNamespace(
        kind="heading",
        text="Fotosinteza",
        level=2,
        bbox=SimpleNamespace(x=10.0, y=20.0, width=200.0, height=30.0),
    )
    units = _liteparse_units(
        _page(7, "Fotosinteza", complexity=_complexity(), blocks=[block])
    )
    assert units[0].text == "## Fotosinteza"
    assert units[0].locator == {
        "page": 7,
        "engine": "liteparse",
        "block_type": "heading",
        "block_order": 1,
        "bbox": [10.0, 20.0, 210.0, 50.0],
        "width": 612.0,
        "height": 792.0,
        "coordinate_space": "pdf_points_72dpi",
    }


@pytest.mark.asyncio
async def test_ppocr_client_validates_and_normalizes_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/parse-page"
        return httpx.Response(
            200,
            json={
                "model": "PP-OCRv5_mobile_det+latin_PP-OCRv5_mobile_rec",
                "markdown": "## Lecție",
                "width": 1275,
                "height": 1650,
                "blocks": [
                    {
                        "label": "paragraph_title",
                        "text": "Lecție",
                        "bbox": [10, 20, 400, 80],
                        "order": 1,
                        "confidence": 0.98,
                    },
                    {"label": "text", "text": "Corp", "bbox": [10, 90, 400, 200]},
                ],
            },
        )

    http = httpx.AsyncClient(
        base_url="http://ppocr:8003",
        transport=httpx.MockTransport(handler),
    )
    client = PpOcrClient("http://ppocr:8003", client=http)
    page = await client.parse_page(b"png", page_number=2)
    assert page.model == "PP-OCRv5_mobile_det+latin_PP-OCRv5_mobile_rec"
    assert page.blocks[0].bbox == [10.0, 20.0, 400.0, 80.0]
    assert page.blocks[0].confidence == 0.98
    assert page.blocks[1].order is None
    await http.aclose()


@pytest.mark.asyncio
async def test_ppocr_client_names_timeout_when_exception_has_no_message() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    http = httpx.AsyncClient(
        base_url="http://ppocr:8003",
        transport=httpx.MockTransport(handler),
    )
    client = PpOcrClient("http://ppocr:8003", client=http)

    with pytest.raises(PdfPipelineUnavailable, match="pagina 8: ReadTimeout"):
        await client.parse_page(b"png", page_number=8)

    await http.aclose()


@pytest.mark.asyncio
async def test_hybrid_extractor_replaces_only_routed_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    native_block = SimpleNamespace(
        kind="paragraph",
        text="Text digital despre ecologie.",
        level=None,
        bbox=SimpleNamespace(x=12.0, y=30.0, width=300.0, height=40.0),
    )
    native = SimpleNamespace(
        total_pages=2,
        pages=[
            _page(1, native_block.text, complexity=_complexity(), blocks=[native_block]),
            _page(2, "", complexity=_complexity("scanned", "no-text")),
        ],
    )

    class FakeOcr:
        async def parse_page(self, image: bytes, *, page_number: int):
            assert image == b"page-two"
            assert page_number == 2
            return OcrPage(
                markdown="Text OCR românesc.",
                blocks=[OcrBlock("Text OCR românesc.", "text", [1, 2, 30, 40], 1, 0.99)],
                width=1275,
                height=1650,
                model="PP-OCRv5-mobile-latin",
            )

        async def aclose(self) -> None:
            return None

    extractor = HybridPdfExtractor(  # type: ignore[arg-type]
        FakeOcr(),
        ocr_every_page=False,
    )
    monkeypatch.setattr(extractor, "_parse_native", lambda _: native)
    monkeypatch.setattr(
        extractor,
        "_render_pages",
        lambda _data, pages: [
            SimpleNamespace(page_num=2, image_bytes=b"page-two")
        ]
        if pages == [2]
        else [],
    )

    units, page_count = await extractor.extract(b"%PDF-fake")
    assert page_count == 2
    assert units[0].text == "Text digital despre ecologie."
    assert units[1].text.endswith("Text OCR românesc.")
    assert units[0].locator["engine"] == "liteparse"
    assert units[1].locator["engine"] == "pp-ocrv5"
    assert units[1].locator["ocr_block_count"] == 1
    assert units[1].locator["ocr_reasons"] == ["scanned", "no-text"]


@pytest.mark.asyncio
async def test_full_page_mode_ocr_checks_native_pages_and_keeps_both_texts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_block = SimpleNamespace(
        kind="paragraph",
        text="Text nativ exact.",
        level=None,
        bbox=SimpleNamespace(x=12.0, y=30.0, width=300.0, height=40.0),
    )
    native = SimpleNamespace(
        total_pages=1,
        pages=[
            _page(1, native_block.text, complexity=_complexity(), blocks=[native_block])
        ],
    )

    class FakeOcr:
        async def parse_page(self, image: bytes, *, page_number: int):
            assert image == b"page-one"
            assert page_number == 1
            return OcrPage(
                markdown="Text nativ exact.\nText aflat numai în imagine.",
                blocks=[
                    OcrBlock("Text nativ exact.", "text", [10, 20, 400, 50], 1, 0.99),
                    OcrBlock(
                        "Text aflat numai în imagine.",
                        "text",
                        [10, 60, 500, 100],
                        2,
                        0.98,
                    ),
                ],
                width=1275,
                height=1650,
                model="PP-OCRv5-mobile-latin",
            )

        async def aclose(self) -> None:
            return None

    extractor = HybridPdfExtractor(FakeOcr())  # type: ignore[arg-type]
    monkeypatch.setattr(extractor, "_parse_native", lambda _: native)
    monkeypatch.setattr(
        extractor,
        "_render_pages",
        lambda _data, pages: [
            SimpleNamespace(page_num=1, image_bytes=b"page-one")
        ]
        if pages == [1]
        else [],
    )

    units, page_count = await extractor.extract(b"%PDF-fake")

    assert page_count == 1
    assert len(units) == 1
    assert "Text nativ exact." in units[0].text
    assert "Text aflat numai în imagine." in units[0].text
    assert units[0].locator["ocr_reasons"] == ["full-page-coverage"]
    assert units[0].locator["block_type"] == "page"


def test_complete_page_unit_detects_printed_footer_and_avoids_tiny_chunks() -> None:
    page = OcrPage(
        markdown="4\nSay True or False.\n87",
        blocks=[
            OcrBlock("4", "text", [70, 480, 110, 520], 1, 0.99),
            OcrBlock("Say True or False.", "text", [115, 480, 500, 525], 2, 0.98),
            OcrBlock("87", "text", [880, 1270, 920, 1310], 3, 0.99),
        ],
        width=992,
        height=1403,
        model="PP-OCRv5-mobile-latin",
    )

    units = _complete_page_units(
        [],
        page,
        page_number=39,
        reasons=["full-page-coverage"],
        dpi=120,
    )

    assert _printed_page_number(page) == 87
    assert len(units) == 1
    assert units[0].text.startswith("[Pagina PDF: 39; pagina tipărită: 87]")
    assert "4\nSay True or False.\n87" in units[0].text
    assert units[0].locator["printed_page"] == 87
    assert units[0].locator["ocr_block_count"] == 3


def test_complete_page_unit_retains_native_text_when_ocr_is_empty() -> None:
    native = [
        SimpleNamespace(text="Text nativ păstrat.", locator={"engine": "liteparse"})
    ]
    page = OcrPage(
        markdown="",
        blocks=[],
        width=992,
        height=1403,
        model="PP-OCRv5-mobile-latin",
    )

    units = _complete_page_units(  # type: ignore[arg-type]
        native,
        page,
        page_number=5,
        reasons=["full-page-coverage"],
        dpi=120,
    )

    assert len(units) == 1
    assert "Text nativ păstrat." in units[0].text
    assert units[0].locator["native_block_count"] == 1


def test_page_identity_is_repeated_on_every_large_page_chunk() -> None:
    unit = TextUnit(
        text="[Pagina PDF: 39; pagina tipărită: 87]\n\n" + "text " * 500,
        locator={
            "page": 39,
            "printed_page": 87,
            "block_type": "page",
        },
    )

    chunks = segment([unit], chunk_size_chars=1000, overlap_chars=100)

    assert len(chunks) == 3
    assert all(
        chunk.text.startswith("[Pagina PDF: 39; pagina tipărită: 87]")
        for chunk in chunks
    )


@pytest.mark.asyncio
async def test_hybrid_extractor_limits_parallel_ocr_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = SimpleNamespace(
        total_pages=3,
        pages=[
            _page(number, "", complexity=_complexity("scanned", "no-text"))
            for number in range(1, 4)
        ],
    )

    class FakeOcr:
        active = 0
        max_active = 0

        async def parse_page(self, image: bytes, *, page_number: int):
            assert image == f"page-{page_number}".encode()
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.01)
                text = f"Text OCR pagina {page_number}."
                return OcrPage(
                    markdown=text,
                    blocks=[OcrBlock(text, "text", [1, 2, 30, 40], 1, 0.97)],
                    width=1275,
                    height=1650,
                    model="PP-OCRv5-mobile-latin",
                )
            finally:
                self.active -= 1

        async def aclose(self) -> None:
            return None

    ocr = FakeOcr()
    extractor = HybridPdfExtractor(  # type: ignore[arg-type]
        ocr,
        render_batch_pages=3,
        ocr_concurrency=2,
    )
    monkeypatch.setattr(extractor, "_parse_native", lambda _: native)
    monkeypatch.setattr(
        extractor,
        "_render_pages",
        lambda _data, pages: [
            SimpleNamespace(
                page_num=page_number,
                image_bytes=f"page-{page_number}".encode(),
            )
            for page_number in pages
        ],
    )

    units, page_count = await extractor.extract(b"%PDF-fake")

    assert page_count == 3
    assert ocr.max_active == 2
    assert [unit.text.splitlines()[-1] for unit in units] == [
        "Text OCR pagina 1.",
        "Text OCR pagina 2.",
        "Text OCR pagina 3.",
    ]
