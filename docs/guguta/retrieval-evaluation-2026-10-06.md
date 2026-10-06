# Mathematics retrieval evaluation — 2026-10-06

The deployed retrieval improvements were evaluated through the public chat API
against 100 fixed questions from the existing sixth-grade mathematics manual.
Each question used a new independent chat session. The questions, source PDF,
489 indexed chunks, and embeddings were preserved across rounds.

## Configuration

- Chat, query planning, and answer review: `google/gemma-4-31b-it`, via OpenRouter.
- Embedding: `Qwen/Qwen3-Embedding-0.6B`, local, 1024 dimensions.
- Reranking: `Qwen/Qwen3-Reranker-0.6B`, local.
- Original PDF page images and source-based answer review enabled.
- Two concurrent requests; every response reviewed against the source reference.
- Frozen question file SHA-256: `87e9f2e5c62b55a8a72d3396ac4ad7f70670eee3296777e90ec07bc52df9e93d`.

## Complete rounds

| Round | Chat model | Correct | Partial | Failed |
| --- | --- | ---: | ---: | ---: |
| Baseline | Gemma 4 31B | 81 | 8 | 11 |
| Iteration 1 | Gemma 4 31B | 87 | 13 | 0 |
| Iteration 2 | Gemma 4 31B | 93 | 6 | 1 |
| Iteration 3, historical | GPT-5.4 | 97 | 1 | 2 |
| Iteration 5 | Gemma 4 31B | 98 | 2 | 0 |

The GPT-5.4 round is historical and does not establish a Gemma result. The live
model remains Gemma as explicitly required by the operator.

Latest-round metrics: 100/100 completed requests, 100/100 reference-page search
hits, 100/100 responses citing a reference page, and 100/100 citation lists
aligned with visible markers and saved ordinals. Median completion latency:
22.91 seconds. A reference-page hit is not proof that every cited claim is
supported; the manual content review remains separate.

The final audit checked all 100 saved user prompts and assistant responses,
121 persisted citations, source chunk identities/pages, unchanged original
chunks, the chat model and prompt version, and the deployed retrieval code.
Provider-recorded generation plus answer-review cost: USD 0.210744, excluding
query planning.

## Remaining partial responses

- **S009:** the circle/disc distinction and diameter-to-radius conclusion are
  correct, but the explanation derives the diameter relation from the mere
  presence of a statement in a True/False exercise. That page supplies no
  verdict; the deduction as stated is invalid.
- **L023:** both test variants and their fractions are preserved, but one
  sentence about house C loses the information that it is connected to the
  internet and merges two sentences incorrectly. Confirmed against PDF page 143.

L026 retains all three blanks in the proportion; swapping the two sides of an
equality is mathematically equivalent and is accepted. Results from selective
retries were not substituted into the complete-round score.

The full authenticated evaluation artifacts remain outside Git on the server
under `/home/jupyter-marius/retrieval-improvement-2026-10-06/iteration-5-gemma/`.
Authentication state and runtime secrets are excluded from the repository.

Implementation rationale: [ADR-014](../7-DEVELOPMENT/decisions/ADR-014-exact-page-visual-evidence-chat.md).
