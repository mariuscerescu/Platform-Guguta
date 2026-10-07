"""Validate and normalize private raster images, excluding EXIF/GPS metadata."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from open_notebook.jobs.guguta.parsing import ExtractionError


def normalize_image(
    data: bytes, *, max_pixels: int = 20_000_000, max_dimension: int = 8000
) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if (
                    image.format not in ("PNG", "JPEG", "WEBP")
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise ExtractionError(
                        "Sunt acceptate imagini statice PNG, JPEG și WebP."
                    )
                width, height = image.size
                if width * height > max_pixels or max(width, height) > max_dimension:
                    raise ExtractionError(
                        f"Imaginea depășește limita de {max_pixels // 1_000_000} megapixeli "
                        f"sau {max_dimension} pixeli pe latură. Redimensionează imaginea."
                    )
                image.load()
                mode = (
                    "RGBA"
                    if "A" in image.getbands() or "transparency" in image.info
                    else "RGB"
                )
                normalized = ImageOps.exif_transpose(image).convert(mode)
                normalized.info.clear()
                output = io.BytesIO()
                normalized.save(output, format="PNG")
                return output.getvalue()
    except ExtractionError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise ExtractionError("Imaginea este invalidă sau prea mare.") from None


def render_image(
    data: bytes, region: tuple[float, float, float, float] | None = None
) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        if region is not None:
            width, height = image.size
            image = image.crop(
                (
                    int(region[0] * width),
                    int(region[1] * height),
                    max(1, int(region[2] * width)),
                    max(1, int(region[3] * height)),
                )
            )
        image.thumbnail((2048, 2048))
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
