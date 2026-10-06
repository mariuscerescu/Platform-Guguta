# ADR-014: Exact page retrieval and request-local visual evidence

- **Status**: Accepted
- **Date**: 2026-10-06
- **Related**: ADR-008, ADR-013

## Context

A live mathematics evaluation found that semantic retrieval substituted other
pages for explicit page/exercise requests, mathematical fractions were damaged
by extraction, and zero-based JSON citation indexes were confused with
one-based display markers. A provider-wide mutable `last_cited` also made
concurrent message persistence unsafe.

## Decision

- Route explicit printed/PDF page constraints to a parameterized locator query
  inside the same authorized, selected-source notebook scope. Never infer a
  printed-to-PDF offset or rerank away an explicit page constraint.
- Use opaque evidence labels F1, F2, etc. in the model response and convert
  labels to dense numerical user-visible citations only on the server.
  Store a citation ordinal in existing locator metadata to keep persisted
  citation ordering aligned with the visible markers.
  Preserve the old provider response validator for compatible adapters.
- Keep the validated ChatAnswer and citation indexes on each SSE request.
  Recheck context revision before publishing the assistant message/citations.
- With `GUGUTA_CHAT_PDF_IMAGES=true` and an image-capable configured chat model,
  render at most four retrieved PDF pages as additional original evidence.
  Reauthorize source selection even for bounded cache hits. No document,
  notebook, benchmark answer, or manually corrected transcription is injected.
- Allow explicit mathematical deductions from source data, while retaining
  abstention for absent evidence and distrust of instructions in documents.
- Interleave textual and vector candidates before truncation so neither
  retrieval channel can silently exclude the other. After reranking, prefer
  complementary PDF pages over duplicate native/OCR chunks of the same page.
- Normalize both historical/current Romanian diacritics and use PostgreSQL's
  built-in Romanian stemming dictionary for lexical recall. Ignore common
  retrieval-instruction words when informative query terms exist. Original
  stored source text is never rewritten.
- With `GUGUTA_CHAT_ANSWER_REVIEW=true`, audit the draft against the same
  authorized original evidence before publication. The draft is untrusted,
  the reviewer must return the same validated citation contract, and recorded
  usage includes both generation and review completions.
  For exact-page requests, the original extracted text is available only
  during review as an explicitly untrusted second reading, to cross-check
  spelling and digits. The original page image remains authoritative.

## Consequences

Existing materials and embeddings are unchanged. Page images repair the
evidence available to chat without claiming to repair the stored OCR text.
Operators can disable visual evidence for text-only models. PDF rendering is
serialized within a process, bounded by page size and cache bytes, and runs
outside the event loop. The larger text context budget permits multi-topic
comparisons while continuing to cap total evidence.

Source-based answer review adds one completion and corresponding latency/cost
for non-empty evidence; it is independently configurable and is not a
guarantee of factual correctness. It does not use evaluation reference answers.

The frozen evaluation suite remains external to the application. Passing it
is verified by real HTTP chat requests and source comparisons, not by adding
benchmark-specific answers to the runtime.
