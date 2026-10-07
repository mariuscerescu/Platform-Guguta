# ADR-020: Current message attachments take priority

Date: 2026-10-07 · Status: Accepted · Refines: ADR-019

## Context

“Help me understand the attached material” must target that message's files.
Automatically preloaded notebook images and old citations previously competed
with a new DOCX as indistinguishable evidence, allowing an answer about the
wrong material.

## Decision

Validated attachment IDs establish the primary sources. The server labels
chunks as `current_attachment`, `chat_attachment` (earlier conversation files),
or `notebook`. Retrieval tools, the generator and independent review receive
these labels. Source contents remain untrusted, irrespective of priority.

Seed up to eight indexed chunks per file, interleaving files' opening excerpts.
Current files precede older files before rendering and context budgeting.
Do not automatically reopen old citations when fresh attachments are present,
or preload notebook images when conversation attachments are available.
Selected materials remain accessible through tools and relevant search results,
including explicit comparisons. Original pixels override OCR within the same
source. Existing authorization and context/tool limits remain enforced.

## Alternatives considered

- Ordering alone provides no source identity and leaves old images distracting.
- Excluding notebook materials entirely prevents useful supplemental explanations.

## Consequences

The model can distinguish the question's subject from supporting materials.
Initial excerpts are partial; search can retrieve further content. No schema
migration or retention-policy change is needed. Tests cover real DOCX ingestion
beside a notebook image, old citations, streaming, follow-ups, tight budgets,
source labels in tools, and generation/review payloads.
