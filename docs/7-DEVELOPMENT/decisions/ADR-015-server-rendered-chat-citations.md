# ADR-015: Server-rendered citations and independent review retries

- **Status**: Accepted
- **Date**: 2026-10-06
- **Related**: ADR-008, ADR-014 (replaces its model response citation contract)

## Context

A live Gemma evaluation rejected a response twice because its inline citation
markers disagreed with its source list. The reviewer also received dense display
ordinals alongside original fragment identifiers. A malformed review discarded
the valid draft and restarted generation.

## Decision

The OpenRouter chat adapter requests one document containing paragraphs with
`text` and `source_ids`. Source identifiers are restricted to the authorized
retrieval context in both the JSON schema and server validation. Generation and
review use the same canonical document; inline fragment labels are discarded as
presentation noise, and ordinary bracketed mathematical text is preserved.
Only after validation and optional review does the server render dense citation
ordinals in first-use order and return the existing `ChatAnswer` API contract.

Each stage may retry its own malformed completion once, with the same configured
model. A failed review never restarts generation or publishes an unreviewed draft.
Logs identify stage, attempt and a content-free reason. Usage includes all
completions that return valid usage metadata, including rejected attempts.
Requests require provider support for the supplied structured-output parameters.

## Alternatives considered

- More prompt reminders or whole-response retries retain duplicate citation state.
- Publishing the draft after failed review would bypass the enabled quality step.
- The old inline-marker response formats retain the failure mode and are rejected
  by this adapter. Saved chat history and other adapters remain compatible.

## Consequences

No database migration or frontend response change is required. Citation formatting
is deterministic; source existence is validated, but factual support still needs
the source-based review and evaluation. Upstream availability and truncation can
still produce controlled errors. Retries add bounded cost and latency.
