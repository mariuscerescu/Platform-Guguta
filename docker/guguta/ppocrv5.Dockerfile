# Private PP-OCRv5 Mobile GPU runtime. The model cache is mounted separately
# so release images stay reproducible and model downloads survive rebuilds.
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04@sha256:46cb48a4abfbc40c836fe57bc05a07101b6458fffc63bbdfd6a50db98c9358bd

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
    PADDLE_PDX_CACHE_HOME=/models/paddlex \
    PPOCR_DEVICE=gpu:0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 python3-pip libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Paddle's CUDA 12.6 build matches the host runtime. Only OCR dependencies are
# installed; the former document-VLM and Transformers runtime are absent.
RUN python3 -m pip install --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/ \
        "paddlepaddle-gpu==3.2.1" \
    && python3 -m pip install \
        "paddleocr==3.6.0" \
        "paddlex[ocr-core]==3.6.1" \
        "fastapi>=0.115,<1" \
        "uvicorn[standard]>=0.30,<1" \
        "python-multipart>=0.0.20,<0.1"

RUN useradd --create-home --uid 10003 ppocr \
    && mkdir -p /srv /models \
    && chown -R ppocr:ppocr /srv /models

COPY --chown=ppocr:ppocr scripts/guguta_ppocrv5_server.py /srv/guguta_ppocrv5_server.py

USER ppocr
WORKDIR /srv
EXPOSE 8003

CMD ["python3", "-m", "uvicorn", "guguta_ppocrv5_server:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "1"]
