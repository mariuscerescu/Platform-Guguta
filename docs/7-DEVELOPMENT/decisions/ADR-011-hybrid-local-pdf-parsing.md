# ADR-011: PDF ingestion uses LiteParse with selective PaddleOCR-VL

- **Status**: Superseded by ADR-012
- **Date**: 2026-09
- **Related**: ADR-004, ADR-007, ADR-010

## Context

Guguță must ingest both native and scanned Romanian/English PDFs, including
large textbooks with columns, tables and formulas. Running a vision model on
every page wastes GPU time and can introduce OCR errors into perfect native
text, while the existing pypdf-only path cannot index scans or preserve layout.

## Decision

Use pinned LiteParse in the worker for native extraction, layout blocks and
page-complexity signals. Render and send only scanned, sparse, garbled or
structurally complex pages to a private PaddleOCR-VL-1.6 service. Normalize
both paths into page-aware text units carrying parser, block type, reading
order, coordinate space and bounding boxes before chunking and embedding.

## Alternatives considered

- PaddleOCR-VL for every page: rejected because it is slower, consumes GPU for
  native PDFs and can degrade already-correct embedded text.
- LiteParse's simple OCR HTTP adapter: rejected because its text+bbox contract
  discards PaddleOCR-VL table, formula and Markdown structure.
- Keep pypdf and add whole-document OCR fallback: rejected because mixed PDFs
  need page-level routing and better native reading order.

## Consequences

- Scanned and mixed PDFs become searchable without sending pages off-server.
- PaddleOCR-VL remains isolated from the API and serializes inference to bound
  VRAM use; worker retries cover transient service failures.
- The model cache is large and first startup is slow. Operators can disable
  complex-layout routing while retaining OCR for true scans.
