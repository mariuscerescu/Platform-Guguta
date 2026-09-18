# ADR-008: Source-grounded chat with multi-query retrieval

## Status

Accepted — 2026-09-18

## Context

The chat previously retrieved with the literal user question and, when no
chunk matched, allowed the language model to answer from general knowledge.
That made follow-up questions harder to retrieve and blurred the boundary
between notebook evidence and model memory.

## Decision

Chat uses this pipeline:

1. load conversation history from the notebook's current context revision;
2. ask the configured chat model for two to four short retrieval perspectives;
3. retrieve each perspective only over selected, ready, authorized sources;
4. combine candidates with reciprocal-rank fusion and rerank once against the
   original question;
5. synthesize from the resulting evidence and validate citation indices before
   persistence.

The original user question is always included as a fallback query. If planning
fails, chat continues with that query. If evidence is absent or insufficient,
the assistant abstains and suggests a useful next step; it does not fill the
gap from model memory. Conversation history resolves follow-ups but is not
treated as evidence. Source disagreement must remain visible.

## Consequences

- Complex and follow-up questions gain recall across several perspectives.
- Selected-source isolation and citation validation remain unchanged.
- Grounded answers require one additional small model completion for planning.
- Empty or irrelevant notebooks return a useful evidence-gap response rather
  than a general-knowledge answer.
