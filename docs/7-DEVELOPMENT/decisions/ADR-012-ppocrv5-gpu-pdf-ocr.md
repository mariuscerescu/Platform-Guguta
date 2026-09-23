# ADR-012: Scanned PDF OCR uses PP-OCRv5 Mobile on GPU

- **Status**: Superseded by ADR-013
- **Date**: 2026-09
- **Related**: ADR-004, ADR-010, ADR-011

## Context

The document VLM selected in ADR-011 required roughly one hour to process a
41-page scanned textbook on CPU and about 63 GiB across ten workers. The two
production T4 GPUs cannot host that 0.9B model safely beside retrieval and TTS,
while scanned textbook retrieval primarily needs accurate text lines, page
numbers and coordinates rather than generative layout reconstruction.

## Decision

Use LiteParse for native PDF text and route pages requiring OCR to a private
PP-OCRv5 service on GPU 1. The service uses `PP-OCRv5_mobile_det` with
`latin_PP-OCRv5_mobile_rec`, which supports Romanian and English, and returns
ordered text lines, confidence scores and bounding boxes. Do not install or
run PaddleOCR-VL. Native complex-layout pages remain on the LiteParse path by
default; scanned, sparse and garbled pages still receive OCR.

## Alternatives considered

- Keep PaddleOCR-VL on CPU: rejected because measured ingestion took hours for
  long textbooks and consumed most host memory.
- Move PaddleOCR-VL to a shared T4: rejected because its VRAM requirement
  conflicts with the resident TTS and retrieval services.
- Tesseract: rejected because the mobile Paddle models were more robust on the
  actual coloured Romanian and English textbooks while remaining compact.

## Consequences

- OCR latency drops from minutes to well under a second per tested page on the
  target GPU, while model storage is measured in tens of megabytes.
- Text lines, printed page numbers, confidence and coordinates remain
  available for page-aware retrieval.
- Complex formulas and table structure are represented as OCR lines rather
  than generative Markdown; retrieval quality must be monitored on math-heavy
  pages.
