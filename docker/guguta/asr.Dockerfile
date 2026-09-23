# Small launcher image; the large CUDA/NeMo environment stays on the host and
# is mounted read-only, matching the existing private MOSS-TTS deployment.
FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg libsndfile1 \
    && mkdir -p /usr/bin \
    && ln -s /usr/local/bin/python3.12 /usr/bin/python3.12 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
