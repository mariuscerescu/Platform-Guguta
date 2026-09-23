# ADR-013: Every PDF page combines native text with visual OCR

- **Status**: Accepted
- **Date**: 2026-09
- **Related**: ADR-011, ADR-012

## Context

Selective OCR was fast, but a page with healthy native text could also contain
words baked into an illustration and therefore never reach OCR. PP-OCRv5 also
returned one unit per detected line, producing hundreds of tiny chunks that
separated printed page and exercise numbers from their content.

## Decision

Render every PDF page and pass it through the private PP-OCRv5 service while
retaining LiteParse native text. Publish one loss-averse composite text unit per
page, store a detected printed-page number in its locator, and repeat page
identity on every chunk derived from a long page. Keep selective mode available
as an explicit configuration fallback, but enable full-page coverage by default.

## Alternatives considered

- Selective OCR only: rejected because it cannot see text inside images on an
  otherwise healthy native page.
- OCR only: rejected because native PDF text is usually exact and preserves
  characters that OCR may confuse.
- PaddleOCR-VL on every page: rejected because of the latency and memory costs
  measured in ADR-012.

## Consequences

- Every rendered page is visually inspected for Romanian/English text and exact
  native text is retained when present.
- Page-level chunks keep folio, exercise labels, and instructions together;
  long chunks retain page identity after splitting.
- OCR work increases for born-digital PDFs, bounded by the compact GPU model;
  operators can set `GUGUTA_PDF_OCR_EVERY_PAGE=false` to restore selective mode.
- This guarantees extraction attempts for visible Latin-script text, not
  semantic interpretation of illustrations, charts, handwriting, or formulas.
