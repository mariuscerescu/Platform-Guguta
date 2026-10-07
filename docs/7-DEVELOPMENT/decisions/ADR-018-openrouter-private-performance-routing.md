# ADR-018: OpenRouter privacy and performance routing

- **Status**: Accepted
- **Date**: 2026-10-07
- **Related**: ADR-016, ADR-017; [runtime configuration](../../guguta/OPENROUTER_CONFIDENTIALITATE_RUTARE_2026-10-07.md)

## Context

The default OpenRouter routing favours price. Preventing training alone does
not exclude providers that retain inputs for monitoring. Chat, agent tools and
Studio generation share the same HTTP client in the API and worker.

## Decision

The shared client enforces `provider.zdr=true` and `data_collection="deny"`
on every request and retry, overriding caller attempts to weaken privacy.
Requests fail when no compatible endpoint is available, without changing the
model or relaxing restrictions. `X-OpenRouter-Cache: false` disables response
caching. Only the three existing API paths are permitted; redirects are refused
and upstream error messages are replaced with locally defined safe text.

Short planning/tool/retrieval calls sort by latency; generation and review sort
by throughput. Configurable soft preferences default to at most 3 seconds
latency and at least 50 tokens/second, without excluding slower ZDR endpoints.
Capability requirements for tools and structured responses remain intact.

## Alternatives considered

- Training opt-out alone does not meet the retention requirement.
- Price-weighted routing does not prioritize response speed.
- A fixed provider list would become stale and reduce compatible availability.

## Consequences

Providers without eligible endpoints cannot serve requests. ZDR is a declared
provider policy and allows temporary in-memory prompt caching; it cannot prove
absence of all retention or guarantee 100% security. Account-level input/output
logging and OpenRouter use of inputs/outputs must remain disabled separately.
Usage metadata is still retained by OpenRouter. Configuration, tests and
primary documentation links are recorded in the runtime guide.
