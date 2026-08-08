from __future__ import annotations

from io import BytesIO
import math

from PIL import Image, ImageOps

from app.config import settings


_MAX_OCR_BASE64_BYTES = 10 * 1024 * 1024


def _encode_jpeg(image: Image.Image, quality: int) -> bytes:
    output = BytesIO()
    image.save(output, format="JPEG", quality=quality)
    return output.getvalue()


def _base64_encoded_size(raw_size: int) -> int:
    return 4 * math.ceil(raw_size / 3)


def validate_image_header(raw: bytes) -> tuple[int, int]:
    """Validate the image container and reject dimensions above the decode gate."""
    with Image.open(BytesIO(raw)) as image:
        width, height = image.size
        if width * height > settings.resume_ocr_max_image_pixels_decode:
            raise ValueError("resume image exceeds decode pixel limit")
        image.verify()
    return width, height


def prepare_image_jpeg(raw: bytes) -> bytes:
    """Convert an uploaded resume image to an RGB JPEG for OCR."""
    validate_image_header(raw)
    with Image.open(BytesIO(raw)) as image:
        if image.format == "JPEG":
            width, height = image.size
            scale = min(
                1.0,
                math.sqrt(settings.resume_ocr_max_pixels / (width * height)),
            )
            image.draft(
                "RGB",
                (max(1, int(width * scale)), max(1, int(height * scale))),
            )
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        scale = min(
            1.0,
            math.sqrt(settings.resume_ocr_max_pixels / (width * height)),
        )
        if scale < 1.0:
            image = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.Resampling.LANCZOS,
            )
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and "transparency" in image.info
        ):
            rgba = image.convert("RGBA")
            prepared = Image.new("RGB", rgba.size, "white")
            prepared.paste(rgba, mask=rgba.getchannel("A"))
        else:
            prepared = image.convert("RGB")
        jpeg = _encode_jpeg(prepared, 70)
        if _base64_encoded_size(len(jpeg)) <= _MAX_OCR_BASE64_BYTES:
            return jpeg
        jpeg = _encode_jpeg(prepared, 50)
        if _base64_encoded_size(len(jpeg)) > _MAX_OCR_BASE64_BYTES:
            raise ValueError("resume image exceeds OCR base64 payload limit")
        return jpeg
