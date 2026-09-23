# ADR-010: Multilingual retrieval runs on private local Qwen models

- **Status**: Accepted
- **Date**: 2026-09
- **Related**: ADR-007, ADR-008, PDR-002

## Context

Guguță needs strong Romanian and cross-lingual retrieval without sending
source passages to an external embedding or reranking provider. The server has
an NVIDIA T4 with enough spare memory for the 0.6B Qwen retrieval pair, while
larger variants would compete with ASR and TTS workloads.

## Decision

Run pinned revisions of `Qwen/Qwen3-Embedding-0.6B` and
`Qwen/Qwen3-Reranker-0.6B` in one GPU-backed service on the private Docker
network. Use 1024-dimensional normalized document vectors and the Qwen
retrieval instruction only on queries. Reindex into an inactive embedding
space and activate it atomically only after every existing chunk is present.

## Alternatives considered

- Continue using OpenRouter retrieval: rejected for source privacy, network
  dependency, and variable provider availability.
- Deploy the 4B/8B Qwen variants: rejected because their marginal retrieval
  gain does not justify T4 memory contention and latency on this server.
- Install both models in API and worker images: rejected because it couples
  web availability and image builds to CUDA inference dependencies.

## Consequences

- Source text used for embedding and reranking remains on the server.
- OpenRouter remains in use only for chat generation.
- The service requires CUDA and about 2.5 GB of persistent model weights, plus
  runtime GPU memory.
- Changing either model revision or vector dimension requires a new atomic
  reindex; old embedding spaces remain available for rollback.
