# ADR-016: Bounded LangGraph agent for notebook page inspection

- **Status**: Accepted
- **Date**: 2026-10-06
- **Related**: ADR-008, ADR-014, ADR-015

## Context

A follow-up about the number of clocks lost the image from the previously
cited exercise. Query rewriting alone does not preserve the page as an exact
evidence target. OCR and text embeddings also do not necessarily describe
illustrations, and fixed retrieval cannot request another view after seeing
the first result.

## Decision

With `GUGUTA_CHAT_AGENT_ENABLED=true`, use a request-local asynchronous
LangGraph graph to decide and execute read-only notebook inspection tools.
LangChain Core defines and validates tool arguments. The graph receives the
already configured Guguță provider from the application factory; it does not
provision a legacy model, access SurrealDB or create SQLite checkpoints.
The existing OpenRouter adapter supplies native function calls, using the
configured model and requiring upstream support for the tool parameters.

Tools are `list_sources`, `search_pages`, `open_page`, `load_image` and
`crop_image`. Actor and notebook identifiers are server-bound and absent from
model-controlled tool arguments. Source selection, readiness, material version
and RLS are checked on every page access, crop and subsequent model invocation.
Tools accept source IDs and evidence labels rather than paths or URLs.

Recent citations from the current context revision restore the most recent
page references. They are locator hints: original pages are reopened before
use. Assistant history is never treated as image evidence. An explicit page
in the current question takes priority over prior references. Printed and PDF
page numbering remain distinct; offsets are never guessed.

Image evidence includes original pixels and source/page identity. Cropping
re-renders the original PDF at higher resolution, uses normalized coordinates
from the top-left of the full page, and preserves the parent citation. A page
without indexed text can have a source/page citation with a null chunk ID.

Defaults bound execution to four decision rounds, eight tool calls, six
images, sixteen evidence fragments and 24,000 text characters. Duplicate tool
requests receive a recoverable result rather than executing repeatedly.
The chat's overall timeout cancels the graph and outbound requests. Graph
state, tool artifacts and accounting are local to each invocation; concurrent
sessions never share an active page or mutable citation state.

After evidence acquisition, the existing grounded generation and optional
review run against the accumulated original evidence. Agent prose is discarded.
Server-rendered citations and the revision recheck still govern publication.
Usage accounting includes tool-selection completions and final generation/review.
Logs expose tool names/status and aggregate counts, never pixels or source text.

## Configuration

- `GUGUTA_CHAT_AGENT_ENABLED`: opt-in, default false.
- `GUGUTA_CHAT_AGENT_MAX_ROUNDS`: 1–6, default 4.
- `GUGUTA_CHAT_AGENT_MAX_TOOL_CALLS`: 1–12, default 8.
- `GUGUTA_CHAT_AGENT_MAX_IMAGES`: 1–8, default 6.
- `GUGUTA_CHAT_PDF_IMAGES=true`: enables image loading and cropping; otherwise
  the agent retains source listing, text search and page text inspection.

## Consequences and limits

This iteration reuses lexical/vector text search and adds adaptive original
page inspection. `search_pages` is not a visual embedding index. Global visual
page discovery (ColPali/ColQwen or similar) is a separate indexing change that
requires evaluation on the manuals. Embedded figure extraction and image-file
uploads are also separate ingestion work; image IDs currently reference page
evidence. Model vision can still miscount, so correctness is evaluated on
original page images rather than claimed from tool availability.

No schema migration or frontend API change is required. Disable the flag to
restore the fixed retrieval path. Runtime images include pinned LangGraph and
LangChain Core dependencies. A read-only live smoke script checks an existing
authorized session without saving new messages or changing its materials.
