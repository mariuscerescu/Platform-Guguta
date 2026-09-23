# ADR-009: Romanian speech recognition runs as a private local service

- **Status**: Accepted
- **Date**: 2026-09
- **Related**: ADR-002, ADR-007

## Context

Guguță needs Romanian voice dictation in the notebook prompt. The selected
Parakeet 110M checkpoint uses NVIDIA NeMo and CUDA, whose runtime is much
larger than the FastAPI application and is not available from a hosted
inference provider. Browser recordings also require media normalization before
the model can process them.

## Decision

Run `gabrielpirlo/Sped_ParakeetRomanian_110M_TDT-CTC` in a dedicated,
GPU-backed service on the private Docker network. The authenticated Guguță API
validates and size-limits audio, then proxies it to that service; browsers
never address the model service directly. The NeMo runtime remains outside the
application image, while the model cache is a persistent private volume.

## Alternatives considered

- Install NeMo in the API image: rejected because it couples API availability,
  build size, CUDA dependencies, and model memory.
- Send audio to a hosted provider: rejected because this checkpoint has no
  inference-provider deployment and voice data should remain self-hosted.
- Run inference in the browser: rejected because NeMo/CUDA and the checkpoint
  are not suitable for browser delivery.

## Consequences

- API and frontend images remain small and can restart independently of ASR.
- Voice recordings stay on the host's private infrastructure.
- Deployment now requires a compatible NVIDIA GPU and an isolated NeMo runtime.
- ASR failure disables dictation but does not make notebook chat unavailable.
