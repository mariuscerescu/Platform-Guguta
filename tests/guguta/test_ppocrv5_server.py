from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image

from scripts import guguta_ppocrv5_server as server


def _png(width: int = 20, height: int = 30) -> bytes:
    output = BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format="PNG")
    return output.getvalue()


def test_predict_normalizes_ppocr_result(monkeypatch: Any) -> None:
    class FakeResult:
        json = {
            "res": {
                "rec_texts": ["Lecția 1", "zgomot"],
                "rec_scores": [0.98, 0.1],
                "rec_boxes": [[10, 20, 19, 29], [1, 1, 2, 2]],
                "rec_polys": [
                    [[10, 20], [19, 20], [19, 29], [10, 29]],
                    [[1, 1], [2, 1], [2, 2], [1, 2]],
                ],
            }
        }

    class FakePipeline:
        inputs: list[str] = []

        def predict(self, path: str) -> list[FakeResult]:
            self.inputs.append(path)
            return [FakeResult()]

    pipeline = FakePipeline()
    monkeypatch.setattr(server, "_pipeline", pipeline)
    payload = server._predict(_png(), ".png")

    assert payload["model"] == (
        "PP-OCRv5_mobile_det+latin_PP-OCRv5_mobile_rec"
    )
    assert payload["markdown"] == "Lecția 1"
    assert payload["width"] == 20
    assert payload["height"] == 30
    assert payload["blocks"] == [
        {
            "label": "text",
            "text": "Lecția 1",
            "bbox": [10.0, 20.0, 19.0, 29.0],
            "polygon": [
                [10.0, 20.0],
                [19.0, 20.0],
                [19.0, 29.0],
                [10.0, 29.0],
            ],
            "order": 1,
            "confidence": 0.98,
        }
    ]


def test_predict_returns_empty_page_when_model_has_no_result(monkeypatch: Any) -> None:
    class FakePipeline:
        def predict(self, _: str) -> list[Any]:
            return []

    monkeypatch.setattr(server, "_pipeline", FakePipeline())
    payload = server._predict(_png(11, 12), ".png")

    assert payload["blocks"] == []
    assert payload["markdown"] == ""
    assert payload["width"] == 11
    assert payload["height"] == 12
