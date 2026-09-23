# Small launcher image. CUDA/PyTorch/Transformers live in the host runtime
# mounted read-only, so rebuilding the Guguță API never redownloads gigabytes.
FROM python:3.12-slim@sha256:d764629ce0ddd8c71fd371e9901efb324a95789d2315a47db7e4d27e78f1b0e9

RUN mkdir -p /usr/bin \
    && ln -s /usr/local/bin/python3.12 /usr/bin/python3.12

WORKDIR /srv
