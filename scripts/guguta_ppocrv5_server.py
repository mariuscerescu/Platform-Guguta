"""Private PP-OCRv5 Mobile GPU service for Guguță.

The service extracts Romanian and English text lines plus bounding boxes from
rendered PDF pages. It deliberately exposes the same small page contract used
by the ingestion worker while keeping Paddle and CUDA out of the API image.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from PIL import Image

PIPELINE_VERSION = "PP-OCRv5"
DETECTION_MODEL = "PP-OCRv5_mobile_det"
RECOGNITION_MODEL = "latin_PP-OCRv5_mobile_rec"
MODEL_NAME = f"{DETECTION_MODEL}+{RECOGNITION_MODEL}"
DEVICE = os.environ.get("PPOCR_DEVICE", "gpu:0")
MAX_IMAGE_MIB = int(os.environ.get("PPOCR_MAX_IMAGE_MIB", "25"))
MAX_IMAGE_BYTES = MAX_IMAGE_MIB * 1024 * 1024
MIN_CONFIDENCE = float(os.environ.get("PPOCR_MIN_CONFIDENCE", "0.35"))

_pipeline: Any | None = None
_inference_lock: asyncio.Lock | None = None
logger = logging.getLogger("guguta.ppocrv5")


def _load_pipeline() -> Any:
    from paddleocr import PaddleOCR

    return PaddleOCR(
        device=DEVICE,
        text_detection_model_name=DETECTION_MODEL,
        text_recognition_model_name=RECOGNITION_MODEL,
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_textline_orientation=True,
        text_rec_score_thresh=MIN_CONFIDENCE,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _pipeline, _inference_lock
    _pipeline = await asyncio.to_thread(_load_pipeline)
    _inference_lock = asyncio.Lock()
    yield
    _pipeline = None
    _inference_lock = None


app = FastAPI(
    title="Guguta PP-OCRv5",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="modelul se încarcă")
    return {
        "status": "ready",
        "model": MODEL_NAME,
        "pipeline": PIPELINE_VERSION,
        "device": DEVICE,
    }


@app.post("/v1/parse-page")
async def parse_page(
    file: UploadFile = File(...),
    page_number: int = Form(..., ge=1),
) -> dict[str, Any]:
    if _pipeline is None or _inference_lock is None:
        raise HTTPException(status_code=503, detail="model indisponibil")
    content_type = (file.content_type or "").lower()
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=415, detail="format imagine neacceptat")
    image = await file.read(MAX_IMAGE_BYTES + 1)
    if not image:
        raise HTTPException(status_code=422, detail="imagine vidă")
    if len(image) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"imaginea depășește limita de {MAX_IMAGE_MIB} MiB",
        )

    suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[
        content_type
    ]
    try:
        logger.info("OCR page %s started", page_number)
        async with _inference_lock:
            payload = await asyncio.to_thread(_predict, image, suffix)
        logger.info("OCR page %s completed", page_number)
    except Exception as exc:
        logger.exception("OCR page %s failed", page_number)
        raise HTTPException(
            status_code=500,
            detail=f"PP-OCRv5 nu a putut procesa pagina {page_number}",
        ) from exc
    payload["page"] = page_number
    return payload


def _predict(image: bytes, suffix: str) -> dict[str, Any]:
    assert _pipeline is not None
    with Image.open(BytesIO(image)) as opened:
        width, height = opened.size

    with tempfile.TemporaryDirectory(prefix="guguta-ocr-") as directory:
        path = Path(directory) / f"page{suffix}"
        path.write_bytes(image)
        results = _pipeline.predict(str(path))

    if not results:
        return _empty_payload(width, height)

    result = results[0]
    raw_json = result.json
    raw = raw_json.get("res", raw_json) if isinstance(raw_json, dict) else {}
    if not isinstance(raw, dict):
        return _empty_payload(width, height)

    texts = _as_list(raw.get("rec_texts"))
    scores = _as_list(raw.get("rec_scores"))
    boxes = _as_list(raw.get("rec_boxes"))
    polygons = _as_list(raw.get("rec_polys"))
    blocks: list[dict[str, Any]] = []
    for index, value in enumerate(texts):
        text = str(value or "").strip()
        score = _number(scores[index]) if index < len(scores) else None
        if not text or (score is not None and score < MIN_CONFIDENCE):
            continue
        bbox = _bbox(boxes[index]) if index < len(boxes) else None
        polygon = _polygon(polygons[index]) if index < len(polygons) else None
        if bbox is None and polygon:
            bbox = _bbox_from_polygon(polygon)
        blocks.append(
            {
                "label": "text",
                "text": text,
                "bbox": bbox,
                "polygon": polygon,
                "order": len(blocks) + 1,
                "confidence": score,
            }
        )

    return {
        "model": MODEL_NAME,
        "pipeline_version": PIPELINE_VERSION,
        "markdown": "\n\n".join(block["text"] for block in blocks),
        "blocks": blocks,
        "width": width,
        "height": height,
    }


def _empty_payload(width: int, height: int) -> dict[str, Any]:
    return {
        "model": MODEL_NAME,
        "pipeline_version": PIPELINE_VERSION,
        "markdown": "",
        "blocks": [],
        "width": width,
        "height": height,
    }


def _as_list(value: Any) -> list[Any]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    return list(value) if isinstance(value, (list, tuple)) else []


def _number(value: Any) -> float | None:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _bbox(value: Any) -> list[float] | None:
    items = _as_list(value)
    if len(items) != 4:
        return None
    numbers = [_number(item) for item in items]
    if any(number is None for number in numbers):
        return None
    result = [float(number) for number in numbers if number is not None]
    if result[2] <= result[0] or result[3] <= result[1]:
        return None
    return result


def _polygon(value: Any) -> list[list[float]] | None:
    points = _as_list(value)
    polygon: list[list[float]] = []
    for point in points:
        pair = _as_list(point)
        if len(pair) != 2:
            return None
        numbers = [_number(item) for item in pair]
        if any(number is None for number in numbers):
            return None
        polygon.append([float(number) for number in numbers if number is not None])
    return polygon or None


def _bbox_from_polygon(polygon: list[list[float]]) -> list[float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return [min(xs), min(ys), max(xs), max(ys)]
