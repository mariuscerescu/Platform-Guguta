"""Private previews reuse source authorization and never require external viewers."""
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from zipfile import ZipFile

import pytest

from api.routers.guguta_v1 import _source_file_response
from api.services.guguta.sources import SourceNotFound, SourcesService


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["docx", "pptx"])
async def test_office_preview_extracts_text_without_changing_original(kind: str) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as zf:
        if kind == "docx":
            zf.writestr("word/document.xml", '<document><p><r><t>Lecția întâi</t></r></p></document>')
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        else:
            zf.writestr("ppt/slides/slide1.xml", '<slide><t>Lecția întâi</t></slide>')
            mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    original = (archive.getvalue(), mime, f"lecție.{kind}")
    service = SourcesService(MagicMock(), MagicMock())
    service.download = AsyncMock(return_value=original)
    actor, notebook, source = MagicMock(), uuid4(), uuid4()
    data, result_mime, filename = await service.preview(actor, notebook, source)
    service.download.assert_awaited_once_with(actor, notebook, source)
    assert "Lecția întâi" in data.decode()
    assert result_mime == "text/plain"
    assert filename == f"lecție.{kind}"
    assert service.download.return_value == original


@pytest.mark.asyncio
async def test_preview_never_bypasses_download_authorization() -> None:
    service = SourcesService(MagicMock(), MagicMock())
    service.download = AsyncMock(side_effect=SourceNotFound())
    with pytest.raises(SourceNotFound):
        await service.preview(MagicMock(), uuid4(), uuid4())


@pytest.mark.asyncio
async def test_pdf_preview_preserves_exact_file() -> None:
    original = (b"%PDF-1.7\noriginal bytes", "application/pdf", "manual.pdf")
    service = SourcesService(MagicMock(), MagicMock())
    service.download = AsyncMock(return_value=original)
    assert await service.preview(MagicMock(), uuid4(), uuid4()) == original
    preview = _source_file_response(*original, inline=True)
    download = _source_file_response(*original)
    assert preview.headers["content-disposition"].startswith("inline;")
    assert download.headers["content-disposition"].startswith("attachment;")
    assert preview.headers["cache-control"] == "private, no-store"
    assert preview.headers["x-content-type-options"] == "nosniff"
