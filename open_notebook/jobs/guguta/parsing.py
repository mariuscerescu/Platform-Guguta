"""Text extraction and segmentation for the Guguță pipeline (GHID §6.2).

Extraction returns text units with locators (page for PDF, section index for
plain text). The legacy pypdf path reports a scanned PDF explicitly; production
can replace it with the selective LiteParse + PP-OCRv5 extractor. Chunking
keeps char offsets so citations can point back to the locator.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Optional

from open_notebook.exceptions import OpenNotebookError


class ExtractionError(OpenNotebookError):
    """Extraction failed with a user-presentable reason (mapped to job error)."""


@dataclass(frozen=True)
class TextUnit:
    text: str
    locator: dict[str, object]  # {"page": int} for PDF, {"section": int} for text


@dataclass(frozen=True)
class Chunk:
    text: str
    locator: dict[str, object]
    position: int
    char_start: int
    char_end: int


PDF_SNIFF = b"%PDF-"
ZIP_SNIFF = b"PK\x03\x04"


def detect_kind(data: bytes, declared_ext: Optional[str]) -> str:
    """Real content type detection — client MIME is never trusted (R41)."""
    if data.startswith(PDF_SNIFF):
        return "pdf"
    if data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (
        data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    ):
        return "image"
    if data.startswith(ZIP_SNIFF):
        # OOXML zip containers; distinguish by required entries
        try:
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = zf.namelist()
            if any(n.startswith("word/") for n in names):
                return "docx"
            if any(n.startswith("ppt/") for n in names):
                return "pptx"
        except Exception:
            raise ExtractionError("Arhiva documentului este invalidă.")
        raise ExtractionError("Format zip necunoscut.")
    try:
        data.decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        raise ExtractionError(
            "Tip de fișier neacceptat sau encodare invalidă. Formate MVP: "
            "PDF, DOCX, PPTX, TXT/Markdown, PNG, JPEG și WebP."
        )


def extract_pdf(data: bytes) -> tuple[list[TextUnit], int]:
    """Legacy native-text extraction. Raises for scanned/empty PDFs (A24)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("Parserul PDF nu este disponibil.") from exc
    try:
        reader = PdfReader(io.BytesIO(data))
        page_count = len(reader.pages)
        units: list[TextUnit] = []
        for idx, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                units.append(TextUnit(text=page_text, locator={"page": idx}))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("PDF-ul nu a putut fi citit.") from exc
    if page_count == 0:
        raise ExtractionError("PDF-ul nu conține pagini.")
    usable_chars = sum(len(u.text) for u in units)
    if not units or usable_chars < 20:
        raise ExtractionError(
            "PDF-ul nu conține text utilizabil (probabil scanat). OCR nu este "
            "disponibil momentan; adaugă o versiune cu text sau un alt material."
        )
    return units, page_count


def extract_text(data: bytes) -> tuple[list[TextUnit], Optional[int]]:
    text_value = data.decode("utf-8")
    if not text_value.strip():
        raise ExtractionError("Textul introdus este vid.")
    # split on blank lines to give sections a rough locator
    sections = re.split(r"\n\s*\n", text_value)
    units = [
        TextUnit(text=s.strip(), locator={"section": i})
        for i, s in enumerate(sections, start=1)
        if s.strip()
    ]
    return units, None


def _ooxml_paragraphs(xml_bytes: bytes, run_tag_local: str = "t") -> list[str]:
    """Extract text runs from OOXML document.xml (namespace-agnostic)."""
    import xml.etree.ElementTree as ET

    paragraphs: list[str] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ExtractionError("Documentul OOXML este corupt.") from exc
    for para in root.iter():
        tag = para.tag.rsplit("}", 1)[-1]
        if tag != "p":
            continue
        pieces = [
            (node.text or "")
            for node in para.iter()
            if node.tag.rsplit("}", 1)[-1] == run_tag_local
        ]
        text_value = "".join(pieces).strip()
        if text_value:
            paragraphs.append(text_value)
    return paragraphs


def extract_docx(data: bytes) -> tuple[list[TextUnit], Optional[int]]:
    """DOCX text: one unit per non-empty paragraph, locator = paragraph index."""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except KeyError as exc:
        raise ExtractionError("DOCX invalid: document.xml lipsește.") from exc
    paragraphs = _ooxml_paragraphs(xml_bytes)
    if not paragraphs:
        raise ExtractionError("DOCX-ul nu conține text.")
    units = [
        TextUnit(text=p, locator={"paragraph": i})
        for i, p in enumerate(paragraphs, start=1)
    ]
    return units, len(paragraphs)


def extract_pptx(data: bytes) -> tuple[list[TextUnit], Optional[int]]:
    """PPTX text: one unit per slide, locator = slide number."""
    import io
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            slide_names = sorted(
                (n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.search(r"(\d+)", n).group(1)),  # type: ignore[union-attr]
            )
            units: list[TextUnit] = []
            for idx, name in enumerate(slide_names, start=1):
                pieces = [
                    (node.text or "")
                    for node in ET_iter(zf.read(name))
                    if node.tag.rsplit("}", 1)[-1] == "t"
                ]
                text_value = " ".join(" ".join(pieces).split())
                if text_value:
                    units.append(TextUnit(text=text_value, locator={"slide": idx}))
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError("PPTX invalid.") from exc
    if not units:
        raise ExtractionError("PPTX-ul nu conține text.")
    return units, len(slide_names)


def ET_iter(xml_bytes: bytes):
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_bytes)
    return root.iter()


def extract_units(kind: str, data: bytes) -> tuple[list[TextUnit], Optional[int]]:
    if kind == "pdf":
        return extract_pdf(data)
    if kind == "text":
        return extract_text(data)
    if kind == "docx":
        return extract_docx(data)
    if kind == "pptx":
        return extract_pptx(data)
    raise ExtractionError(
        f"Extracția pentru formatul '{kind}' nu este disponibilă încă."
    )


def segment(
    units: list[TextUnit], *, chunk_size_chars: int = 2000, overlap_chars: int = 200
) -> list[Chunk]:
    """Greedy char-based segmentation honoring unit boundaries per chunk.

    A unit larger than chunk_size is split with overlap; locators are kept.
    """
    if chunk_size_chars < 200 or overlap_chars < 0:
        raise ValueError("parametri de segmentare invalizi")
    if overlap_chars >= chunk_size_chars:
        overlap_chars = chunk_size_chars // 10
    chunks: list[Chunk] = []
    position = 0
    for unit in units:
        text_value = unit.text
        context_prefix = _page_context_prefix(unit.locator)
        start = 0
        n = len(text_value)
        while start < n:
            end = min(start + chunk_size_chars, n)
            piece = text_value[start:end].strip()
            if piece:
                # Composite PDF pages can span several chunks. Repeat their
                # page identity so every chunk remains retrievable by printed
                # page number, not only the first one.
                if context_prefix and not piece.startswith(context_prefix):
                    piece = f"{context_prefix}\n\n{piece}"
                chunks.append(
                    Chunk(
                        text=piece,
                        locator=dict(unit.locator),
                        position=position,
                        char_start=start,
                        char_end=end,
                    )
                )
                position += 1
            if end >= n:
                break
            start = end - overlap_chars
    return chunks


def _page_context_prefix(locator: dict[str, object]) -> str:
    if locator.get("block_type") != "page" or "page" not in locator:
        return ""
    prefix = f"[Pagina PDF: {locator['page']}"
    printed_page = locator.get("printed_page")
    if printed_page is not None:
        prefix += f"; pagina tipărită: {printed_page}"
    return prefix + "]"
