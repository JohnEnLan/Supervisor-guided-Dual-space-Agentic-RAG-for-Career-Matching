from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

from PIL import Image
import pytest
from pypdf import PdfWriter
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.normalization import image_prep
from app.normalization.image_prep import prepare_image_jpeg, validate_image_header
from app.normalization.resume_intake import ResumeIntakeUserError
from app.state.schema import ResumeState


def _image_bytes(image: Image.Image, image_format: str, **save_kwargs) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format=image_format, **save_kwargs)
    return buffer.getvalue()


def test_o2_prepare_image_jpeg_flattens_rgba_transparency_to_white() -> None:
    image = Image.new("RGBA", (64, 64), (255, 0, 0, 0))
    image.paste((0, 0, 0, 255), (32, 0, 64, 64))

    jpeg = prepare_image_jpeg(_image_bytes(image, "PNG"), ".png")

    with Image.open(BytesIO(jpeg)) as prepared:
        assert prepared.format == "JPEG"
        assert prepared.mode == "RGB"
        assert all(channel >= 245 for channel in prepared.getpixel((8, 32)))


def test_o2_prepare_image_jpeg_applies_exif_orientation_before_encoding() -> None:
    image = Image.new("RGB", (20, 40), "navy")
    exif = Image.Exif()
    exif[274] = 6
    raw = _image_bytes(image, "JPEG", exif=exif)

    jpeg = prepare_image_jpeg(raw, ".jpg")

    with Image.open(BytesIO(jpeg)) as prepared:
        assert prepared.size == (40, 20)


def test_o2_prepare_image_jpeg_accepts_palette_cmyk_and_multiframe_webp() -> None:
    palette = Image.new("P", (32, 32), 0)
    palette.putpalette([255, 0, 0, 0, 0, 0] + [0, 0, 0] * 254)
    palette.info["transparency"] = 0
    cmyk = Image.new("CMYK", (32, 32), (0, 255, 255, 0))
    frame_one = Image.new("RGB", (32, 32), "red")
    frame_two = Image.new("RGB", (32, 32), "blue")

    webp_buffer = BytesIO()
    frame_one.save(
        webp_buffer,
        format="WEBP",
        save_all=True,
        append_images=[frame_two],
        duration=100,
        loop=0,
    )
    webp_raw = webp_buffer.getvalue()

    palette_raw = _image_bytes(palette, "PNG", transparency=0)
    with Image.open(
        BytesIO(prepare_image_jpeg(palette_raw, ".png"))
    ) as prepared_palette:
        assert all(
            channel >= 245 for channel in prepared_palette.getpixel((16, 16))
        )
    with Image.open(
        BytesIO(prepare_image_jpeg(webp_raw, ".webp"))
    ) as prepared_webp:
        red, _green, blue = prepared_webp.getpixel((16, 16))
        assert red > blue

    for raw, suffix in (
        (palette_raw, ".png"),
        (_image_bytes(cmyk, "JPEG"), ".jpeg"),
        (webp_raw, ".webp"),
    ):
        with Image.open(BytesIO(prepare_image_jpeg(raw, suffix))) as prepared:
            assert prepared.format == "JPEG"
            assert prepared.mode == "RGB"


def test_o3_validate_image_header_rejects_malformed_and_truncated_images() -> None:
    valid = _image_bytes(Image.new("RGB", (32, 32), "white"), "PNG")
    validate_image_header(valid, ".png")

    for raw in (b"not-an-image", valid[:-12]):
        with pytest.raises(Exception):
            validate_image_header(raw, ".png")


def test_codexM1_image_format_must_match_declared_suffix() -> None:
    """整批终审 Codex M1：改名图片（真实容器 ≠ 后缀）必须拒绝——
    GIF/BMP 等白名单之外的解码器不得被伪装后缀带进管线。"""
    png_raw = _image_bytes(Image.new("RGB", (16, 16), "white"), "PNG")
    gif_raw = _image_bytes(Image.new("P", (16, 16)), "GIF")

    # PNG 改名 .jpg / GIF 伪装 .png：一律格式失配拒绝
    with pytest.raises(ValueError, match="does not match"):
        validate_image_header(png_raw, ".jpg")
    with pytest.raises(ValueError, match="does not match"):
        validate_image_header(gif_raw, ".png")
    with pytest.raises(ValueError, match="does not match"):
        prepare_image_jpeg(gif_raw, ".webp")
    # 非白名单后缀直接拒绝
    with pytest.raises(ValueError, match="unsupported"):
        validate_image_header(png_raw, ".gif")
    # 正身通过
    assert validate_image_header(png_raw, ".png") == (16, 16)


def test_o12_decode_gate_is_strict_and_output_is_resized_to_pixel_limit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        image_prep.settings, "resume_ocr_max_image_pixels_decode", 100
    )
    monkeypatch.setattr(image_prep.settings, "resume_ocr_max_pixels", 16)
    exact = _image_bytes(Image.new("RGB", (10, 10), "white"), "PNG")
    over = _image_bytes(Image.new("RGB", (10, 11), "white"), "PNG")

    assert validate_image_header(exact, ".png") == (10, 10)
    with pytest.raises(ValueError, match="decode pixel limit"):
        validate_image_header(over, ".png")

    with Image.open(BytesIO(prepare_image_jpeg(exact, ".png"))) as prepared:
        assert prepared.width * prepared.height <= 16


def test_o12_literal_40m_decode_boundary_accepts_exact_and_rejects_over(
    monkeypatch,
) -> None:
    exact = _image_bytes(Image.new("1", (8_000, 5_000)), "PNG")
    over = _image_bytes(Image.new("1", (8_001, 5_000)), "PNG")

    assert validate_image_header(exact, ".png") == (8_000, 5_000)
    with pytest.raises(ValueError, match="decode pixel limit"):
        validate_image_header(over, ".png")

    # 整批终审 Codex m2：8001×5000=40_005_000 不是恰 40M+1——用降一位的
    # 闸值让同一张 40_000_000 像素图被拒，精确钉死严格 ">" 边界语义
    monkeypatch.setattr(
        image_prep.settings,
        "resume_ocr_max_image_pixels_decode",
        39_999_999,
    )
    with pytest.raises(ValueError, match="decode pixel limit"):
        validate_image_header(exact, ".png")


def test_v1_2_q70_payload_at_base64_limit_is_encoded_once(monkeypatch) -> None:
    calls: list[int] = []
    max_raw_bytes = 3 * ((10 * 1024 * 1024) // 4)

    def fake_encode(_image: Image.Image, quality: int) -> bytes:
        calls.append(quality)
        return b"x" * max_raw_bytes

    monkeypatch.setattr(image_prep, "_encode_jpeg", fake_encode)
    raw = _image_bytes(Image.new("RGB", (8, 8), "white"), "PNG")

    assert len(prepare_image_jpeg(raw, ".png")) == max_raw_bytes
    assert calls == [70]


def test_v1_3_q70_payload_over_limit_reencodes_once_at_q50(monkeypatch) -> None:
    calls: list[int] = []
    max_raw_bytes = 3 * ((10 * 1024 * 1024) // 4)

    def fake_encode(_image: Image.Image, quality: int) -> bytes:
        calls.append(quality)
        return b"x" * (max_raw_bytes + 1) if quality == 70 else b"q50"

    monkeypatch.setattr(image_prep, "_encode_jpeg", fake_encode)
    raw = _image_bytes(Image.new("RGB", (8, 8), "white"), "PNG")

    assert prepare_image_jpeg(raw, ".png") == b"q50"
    assert calls == [70, 50]


def test_o12_q50_payload_over_limit_is_rejected_after_two_encodes(
    monkeypatch,
) -> None:
    calls: list[int] = []
    max_raw_bytes = 3 * ((10 * 1024 * 1024) // 4)

    def fake_encode(_image: Image.Image, quality: int) -> bytes:
        calls.append(quality)
        return b"x" * (max_raw_bytes + 1)

    monkeypatch.setattr(image_prep, "_encode_jpeg", fake_encode)
    raw = _image_bytes(Image.new("RGB", (8, 8), "white"), "PNG")

    with pytest.raises(ValueError, match="base64 payload limit"):
        prepare_image_jpeg(raw, ".png")
    assert calls == [70, 50]


def test_docx_empty_text_error_preserves_user_message() -> None:
    message = "这份 DOCX 里我没能读到文字，转成 PDF 或图片再传一次就好啦～"

    error = ResumeIntakeUserError(message)

    assert isinstance(error, ValueError)
    assert str(error) == message
    assert error.user_message == message


def _install_normalization_sinks(monkeypatch, sessions):
    record = SimpleNamespace(
        events=[],
        refunds=[],
        marks=[],
        saves=[],
        cleanups=[],
        normalized_texts=[],
        span_counts=[],
    )

    async def record_progress(**kwargs):
        record.events.append(kwargs)

    async def refund(*, session_id: str):
        record.refunds.append(session_id)

    async def mark_error(**kwargs):
        record.marks.append(kwargs)
        return True

    async def save(**kwargs):
        record.saves.append(kwargs)
        return {"resume_version": 1}

    async def cleanup(**kwargs):
        record.cleanups.append(kwargs)

    async def normalize(raw_text, spans):
        record.normalized_texts.append(raw_text)
        record.span_counts.append(len(spans))
        return ResumeState(skills=["Python"])

    monkeypatch.setattr(sessions, "record_intake_progress", record_progress)
    monkeypatch.setattr(sessions, "refund_parse_count", refund)
    monkeypatch.setattr(sessions, "mark_resume_error", mark_error)
    monkeypatch.setattr(sessions, "save_normalized_resume", save)
    monkeypatch.setattr(sessions, "clear_resume_upload_content", cleanup)
    monkeypatch.setattr(sessions, "normalize_resume_text", normalize)
    return record


@pytest.mark.asyncio
async def test_image_resume_ocr_runs_after_confirmation_and_normalizes_text(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    ocr_inputs: list[bytes] = []

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        ocr_inputs.append(jpeg)
        return "OCR resume text with enough evidence"

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr, raising=False)
    raw_image = _image_bytes(Image.new("RGB", (64, 64), "white"), "PNG")

    await sessions._normalize_resume(
        session_id="image-session",
        user_id="user-1",
        raw_text="",
        suffix=".png",
        content=raw_image,
        expected_generation=3,
    )

    assert len(ocr_inputs) == 1
    assert ocr_inputs[0].startswith(b"\xff\xd8")
    assert record.normalized_texts == ["OCR resume text with enough evidence"]
    assert len(record.saves) == 1
    assert record.marks == []
    assert record.refunds == []
    assert any("视觉识别" in event["text"] for event in record.events)


@pytest.mark.asyncio
async def test_v1_2_q70_bytes_are_sent_to_exactly_one_vl_call(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    encode_qualities: list[int] = []
    vl_payloads: list[bytes] = []

    def encode(_image: Image.Image, quality: int) -> bytes:
        encode_qualities.append(quality)
        return b"q70-payload"

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        vl_payloads.append(jpeg)
        return "OCR evidence from q70 payload"

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(image_prep, "_encode_jpeg", encode)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)
    raw_image = _image_bytes(Image.new("RGB", (32, 32), "white"), "PNG")

    await sessions._normalize_resume(
        session_id="q70-session",
        user_id="user-1",
        raw_text="",
        suffix=".png",
        content=raw_image,
        expected_generation=18,
    )

    assert encode_qualities == [70]
    assert vl_payloads == [b"q70-payload"]
    assert len(record.saves) == 1


@pytest.mark.asyncio
async def test_v1_3_q50_bytes_are_sent_to_exactly_one_vl_call(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    encode_qualities: list[int] = []
    vl_payloads: list[bytes] = []

    def encode(_image: Image.Image, quality: int) -> bytes:
        encode_qualities.append(quality)
        return b"over" if quality == 70 else b"fit"

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        vl_payloads.append(jpeg)
        return "OCR evidence from q50 payload"

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(image_prep, "_MAX_OCR_BASE64_BYTES", 4)
    monkeypatch.setattr(image_prep, "_encode_jpeg", encode)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)
    raw_image = _image_bytes(Image.new("RGB", (32, 32), "white"), "PNG")

    await sessions._normalize_resume(
        session_id="q50-session",
        user_id="user-1",
        raw_text="",
        suffix=".png",
        content=raw_image,
        expected_generation=19,
    )

    assert encode_qualities == [70, 50]
    assert vl_payloads == [b"fit"]
    assert len(record.saves) == 1


@pytest.mark.asyncio
async def test_o12_pdf_double_over_skips_vl_and_preserves_native_text(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    pdf_buffer = BytesIO()
    writer.write(pdf_buffer)
    native_text = "native tiny evidence"
    encode_qualities: list[int] = []
    vl_payloads: list[bytes] = []

    def encode(_image: Image.Image, quality: int) -> bytes:
        encode_qualities.append(quality)
        return b"over"

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        vl_payloads.append(jpeg)
        return "unreachable"

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(image_prep, "_MAX_OCR_BASE64_BYTES", 4)
    monkeypatch.setattr(image_prep, "_encode_jpeg", encode)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([(1, native_text)], 1),
    )
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="pdf-double-over-session",
        user_id="user-1",
        raw_text=f"[Page 1]\n{native_text}",
        suffix=".pdf",
        content=pdf_buffer.getvalue(),
        expected_generation=20,
    )

    assert encode_qualities == [70, 50]
    assert vl_payloads == []
    assert record.normalized_texts == [f"[Page 1]\n{native_text}"]
    assert record.refunds == []
    assert len(record.saves) == 1


@pytest.mark.asyncio
async def test_empty_docx_uses_actionable_user_error_and_refunds(monkeypatch) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)

    await sessions._normalize_resume(
        session_id="docx-session",
        user_id="user-1",
        raw_text="",
        suffix=".docx",
        content=b"docx-bytes",
        expected_generation=4,
    )

    assert record.refunds == ["docx-session"]
    assert record.normalized_texts == []
    assert record.marks[0]["terminal_event"].text == (
        "这份 DOCX 里我没能读到文字，转成 PDF 或图片再传一次就好啦～"
    )


@pytest.mark.asyncio
async def test_o5_pdf_vl_exception_fuses_remaining_pages_and_keeps_prior_ocr(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    native_text = "Native experience evidence " * 4
    pages = [(1, ""), (2, ""), (3, ""), (4, native_text)]
    vl_pages: list[int] = []

    def extract(_content: bytes, _suffix: str):
        return list(pages), 4

    def render(_content: bytes, page_number: int) -> bytes:
        return f"jpeg-{page_number}".encode()

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        page_number = int(jpeg.decode().rsplit("-", 1)[1])
        vl_pages.append(page_number)
        if page_number == 2:
            raise TimeoutError("VL timeout")
        return "OCR evidence from page one"

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "extract_resume_pages_from_bytes", extract)
    monkeypatch.setattr(sessions, "_render_pdf_page_jpeg", render, raising=False)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="pdf-session",
        user_id="user-1",
        raw_text=f"[Page 4]\n{native_text}",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=5,
    )

    assert vl_pages == [1, 2]
    assert "[Page 1]\nOCR evidence from page one" in record.normalized_texts[0]
    assert f"[Page 4]\n{native_text.strip()}" in record.normalized_texts[0]
    summaries = [
        event
        for event in record.events
        if event["step"] == "ocr" and "档案可能不完整" in event["text"]
    ]
    assert len(summaries) == 1
    assert "视觉识别中断" in summaries[0]["text"]
    # 整批终审 Codex m2：钉死精确口径——当前失败页也计入"未识别"
    # （3 候选、第 2 页失败于 index 1 → 2 页未识别）
    assert "2 页未识别" in summaries[0]["text"]
    assert record.refunds == []
    assert len(record.saves) == 1


@pytest.mark.asyncio
async def test_o1_pure_scan_local_failures_refund_once_without_start_event(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    ocr_calls: list[bytes] = []

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([(1, ""), (2, "")], 2),
    )
    monkeypatch.setattr(
        sessions,
        "_render_pdf_page_jpeg",
        lambda _content, _page: (_ for _ in ()).throw(OSError("render failed")),
    )

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        ocr_calls.append(jpeg)
        return "unreachable"

    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="scan-session",
        user_id="user-1",
        raw_text="",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=6,
    )

    assert ocr_calls == []
    assert record.refunds == ["scan-session"]
    assert len(record.marks) == 1
    assert record.saves == []
    assert not any("我用视觉识别" in event["text"] for event in record.events)
    summaries = [event for event in record.events if event["step"] == "ocr"]
    assert len(summaries) == 1
    assert "档案可能不完整" in summaries[0]["text"]


@pytest.mark.asyncio
async def test_o1b_mixed_pdf_local_failures_continue_to_normalization_without_refund(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    native_text = "Reliable native evidence " * 4
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([(1, native_text), (2, "")], 2),
    )
    monkeypatch.setattr(
        sessions,
        "_render_pdf_page_jpeg",
        lambda _content, _page: (_ for _ in ()).throw(OSError("render failed")),
    )

    await sessions._normalize_resume(
        session_id="mixed-session",
        user_id="user-1",
        raw_text=f"[Page 1]\n{native_text}",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=7,
    )

    assert record.normalized_texts == [f"[Page 1]\n{native_text.strip()}"]
    assert len(record.saves) == 1
    assert record.marks == []
    assert record.refunds == []
    assert len([event for event in record.events if event["step"] == "ocr"]) == 1


@pytest.mark.asyncio
async def test_o4_local_page_failure_skips_only_that_page(monkeypatch) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    ocr_pages: list[int] = []
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([(1, ""), (2, "")], 2),
    )

    def render(_content: bytes, page_number: int) -> bytes:
        if page_number == 1:
            raise OSError("page render failed")
        return str(page_number).encode()

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        page_number = int(jpeg)
        ocr_pages.append(page_number)
        return "Recovered evidence on page two"

    monkeypatch.setattr(sessions, "_render_pdf_page_jpeg", render)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="page-skip-session",
        user_id="user-1",
        raw_text="",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=8,
    )

    assert ocr_pages == [2]
    assert record.normalized_texts == ["[Page 2]\nRecovered evidence on page two"]
    assert len(record.saves) == 1
    assert len(
        [
            event
            for event in record.events
            if event["step"] == "ocr" and "档案可能不完整" in event["text"]
        ]
    ) == 1


@pytest.mark.asyncio
async def test_o8_empty_pdf_ocr_preserves_native_page_text(monkeypatch) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([(1, "native tiny evidence")], 1),
    )
    monkeypatch.setattr(
        sessions, "_render_pdf_page_jpeg", lambda _content, _page: b"jpeg"
    )

    async def empty_ocr(_jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        return "   \n "

    monkeypatch.setattr(sessions, "ocr_image_jpeg", empty_ocr)

    await sessions._normalize_resume(
        session_id="empty-ocr-session",
        user_id="user-1",
        raw_text="[Page 1]\nnative tiny evidence",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=9,
    )

    assert record.normalized_texts == ["[Page 1]\nnative tiny evidence"]
    assert len(record.saves) == 1
    assert record.refunds == []
    assert len(
        [
            event
            for event in record.events
            if event["step"] == "ocr" and "档案可能不完整" in event["text"]
        ]
    ) == 1


@pytest.mark.asyncio
async def test_o9_empty_image_ocr_marks_error_without_refund(monkeypatch) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)

    async def empty_ocr(_jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        return " \n "

    monkeypatch.setattr(sessions, "ocr_image_jpeg", empty_ocr)
    raw_image = _image_bytes(Image.new("RGB", (32, 32), "white"), "PNG")

    await sessions._normalize_resume(
        session_id="empty-image-session",
        user_id="user-1",
        raw_text="",
        suffix=".png",
        content=raw_image,
        expected_generation=10,
    )

    assert len(record.marks) == 1
    assert record.saves == []
    assert record.refunds == []
    assert record.cleanups == [
        {"session_id": "empty-image-session", "generation": 10}
    ]


@pytest.mark.asyncio
async def test_o10_zero_page_pdf_marks_error_and_refunds_without_vl(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    vl_calls: list[bytes] = []
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([], 0),
    )

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        vl_calls.append(jpeg)
        return "unreachable"

    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="zero-page-session",
        user_id="user-1",
        raw_text="",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=11,
    )

    assert vl_calls == []
    assert record.refunds == ["zero-page-session"]
    assert len(record.marks) == 1
    assert record.saves == []


@pytest.mark.asyncio
async def test_o12_image_prepare_failure_refunds_once_before_any_vl_call(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    vl_calls: list[bytes] = []
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "prepare_image_jpeg",
        lambda _raw: (_ for _ in ()).throw(ValueError("too large")),
    )

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        vl_calls.append(jpeg)
        return "unreachable"

    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="large-image-session",
        user_id="user-1",
        raw_text="",
        suffix=".png",
        content=b"image-bytes",
        expected_generation=12,
    )

    assert vl_calls == []
    assert record.refunds == ["large-image-session"]
    assert len(record.marks) == 1
    assert record.cleanups == [
        {"session_id": "large-image-session", "generation": 12}
    ]


@pytest.mark.asyncio
async def test_o13_max_pages_counts_low_text_pages_not_physical_positions(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    pages: list[tuple[int, str]] = []
    low_page_numbers: list[int] = []
    for page_number in range(1, 17):
        if page_number % 2:
            pages.append((page_number, "tiny"))
            low_page_numbers.append(page_number)
        else:
            pages.append((page_number, f"Native evidence page {page_number} " * 4))
    rendered_pages: list[int] = []
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_ocr_max_pages", 6)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: (list(pages), len(pages)),
    )

    def render(_content: bytes, page_number: int) -> bytes:
        rendered_pages.append(page_number)
        return str(page_number).encode()

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        return f"OCR evidence page {int(jpeg)}"

    monkeypatch.setattr(sessions, "_render_pdf_page_jpeg", render)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="interleaved-session",
        user_id="user-1",
        raw_text="pre-extracted text",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=13,
    )

    assert rendered_pages == low_page_numbers[:6]
    summaries = [
        event
        for event in record.events
        if event["step"] == "ocr" and "档案可能不完整" in event["text"]
    ]
    assert len(summaries) == 1
    assert "2 页超出本次视觉识别上限" in summaries[0]["text"]
    assert len(record.saves) == 1


@pytest.mark.asyncio
async def test_o13_skip_and_truncation_emit_one_combined_summary(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_ocr_max_pages", 2)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: (
            [(1, ""), (2, ""), (3, ""), (4, "")],
            4,
        ),
    )

    def render(_content: bytes, page_number: int) -> bytes:
        if page_number == 1:
            raise OSError("render failed")
        return str(page_number).encode()

    async def ocr(_jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        return "Recovered evidence"

    monkeypatch.setattr(sessions, "_render_pdf_page_jpeg", render)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="combined-summary-session",
        user_id="user-1",
        raw_text="",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=15,
    )

    summaries = [
        event
        for event in record.events
        if event["step"] == "ocr" and "档案可能不完整" in event["text"]
    ]
    assert len(summaries) == 1
    assert "1 页图像准备失败" in summaries[0]["text"]
    assert "2 页超出本次视觉识别上限" in summaries[0]["text"]


@pytest.mark.asyncio
async def test_v1_13_cancelled_vl_call_is_not_caught_as_pipeline_failure(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: ([(1, "")], 1),
    )
    monkeypatch.setattr(
        sessions, "_render_pdf_page_jpeg", lambda _content, _page: b"jpeg"
    )

    async def cancelled(_jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        raise asyncio.CancelledError()

    monkeypatch.setattr(sessions, "ocr_image_jpeg", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await sessions._normalize_resume(
            session_id="cancelled-session",
            user_id="user-1",
            raw_text="",
            suffix=".pdf",
            content=b"pdf-bytes",
            expected_generation=16,
        )

    assert record.marks == []
    assert record.refunds == []
    assert record.cleanups == [
        {"session_id": "cancelled-session", "generation": 16}
    ]


@pytest.mark.asyncio
async def test_v1_9_flag_false_preserves_legacy_error_copy_and_zero_vl(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)

    async def forbidden_ocr(_jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        raise AssertionError("disabled OCR must not call VL")

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", False)
    monkeypatch.setattr(sessions, "ocr_image_jpeg", forbidden_ocr)

    await sessions._normalize_resume(
        session_id="disabled-session",
        user_id="user-1",
        raw_text="",
        suffix=".png",
        content=b"ignored-image",
        expected_generation=17,
    )

    assert record.refunds == ["disabled-session"]
    assert "（用时 " in record.marks[0]["terminal_event"].text


@pytest.mark.asyncio
async def test_o11_six_long_ocr_pages_cap_evidence_at_120_spans(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    record = _install_normalization_sinks(monkeypatch, sessions)
    pages = [(page_number, "") for page_number in range(1, 7)]
    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions.settings, "resume_ocr_max_pages", 6)
    monkeypatch.setattr(
        sessions,
        "extract_resume_pages_from_bytes",
        lambda _content, _suffix: (list(pages), len(pages)),
    )
    monkeypatch.setattr(
        sessions,
        "_render_pdf_page_jpeg",
        lambda _content, page_number: str(page_number).encode(),
    )

    async def ocr(jpeg: bytes, *, on_attempt=None) -> str:
        if on_attempt is not None:
            on_attempt()
        page_number = int(jpeg)
        return "\n".join(
            f"- page {page_number} evidence line {line_number} with detail"
            for line_number in range(30)
        )

    monkeypatch.setattr(sessions, "ocr_image_jpeg", ocr)

    await sessions._normalize_resume(
        session_id="long-ocr-session",
        user_id="user-1",
        raw_text="",
        suffix=".pdf",
        content=b"pdf-bytes",
        expected_generation=14,
    )

    assert record.span_counts == [120]
    assert len(record.saves) == 1


def test_v1_7_giant_pdf_media_box_render_converges_to_pixel_limit(
    monkeypatch,
) -> None:
    from app.api.v1 import sessions

    writer = PdfWriter()
    writer.add_blank_page(width=10_000, height=10_000)
    pdf_buffer = BytesIO()
    writer.write(pdf_buffer)
    monkeypatch.setattr(sessions.settings, "resume_ocr_max_pixels", 4_000_000)
    monkeypatch.setattr(sessions.settings, "resume_ocr_render_scale", 2.0)

    jpeg = sessions._render_pdf_page_jpeg(pdf_buffer.getvalue(), 1)

    with Image.open(BytesIO(jpeg)) as rendered:
        assert rendered.width * rendered.height <= 4_000_000


@pytest.mark.asyncio
async def test_o6_image_upload_whitelist_tracks_ocr_capability(monkeypatch) -> None:
    from app.api import uploads

    raw = _image_bytes(Image.new("RGB", (8, 8), "white"), "PNG")
    monkeypatch.setattr(uploads.settings, "resume_ocr_enabled", False, raising=False)
    disabled_file = UploadFile(filename="resume.png", file=BytesIO(raw))

    with pytest.raises(Exception) as excinfo:
        await uploads.read_resume_upload(disabled_file)
    assert excinfo.value.status_code == 415

    monkeypatch.setattr(uploads.settings, "resume_ocr_enabled", True, raising=False)
    enabled_file = UploadFile(filename="resume.png", file=BytesIO(raw))

    filename, suffix, content = await uploads.read_resume_upload(enabled_file)
    assert (filename, suffix, content) == ("resume.png", ".png", raw)


@pytest.mark.asyncio
async def test_o7_image_upload_post_and_get_share_fixed_preview(monkeypatch) -> None:
    from app.api.v1 import sessions

    raw = _image_bytes(Image.new("RGB", (32, 32), "white"), "PNG")
    accepted_calls: list[dict] = []

    async def accept(**kwargs):
        accepted_calls.append(kwargs)
        return {"resume_upload_generation": 2, "resume_parse_count": 0}

    async def pending(*, session_id: str):
        assert session_id == "image-upload-session"
        return {
            "generation": 2,
            "filename": "resume.png",
            "suffix": ".png",
            "extracted_text": "",
            "pages": 1,
            "chars": 0,
            "ocr_suggested": True,
            "resume_parse_count": 0,
        }

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "accept_resume_upload", accept)
    monkeypatch.setattr(sessions, "get_pending_resume_upload", pending)

    posted = await sessions.upload_resume(
        "image-upload-session",
        UploadFile(filename="resume.png", file=BytesIO(raw)),
    )
    refreshed = await sessions.pending_resume_upload("image-upload-session")

    # 方案 §4/§M2c 钉死文案：成本提示（分钱），不是时间提示
    preview = "图片简历，确认解析后将进行视觉识别（约几分钱）"
    assert posted.text_preview == preview
    assert refreshed.text_preview == preview
    assert accepted_calls[0]["extracted_text"] == ""
    assert accepted_calls[0]["pages"] == 1
    assert accepted_calls[0]["chars"] == 0
    assert accepted_calls[0]["ocr_suggested"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["disguised", "truncated"])
async def test_o3_unreadable_image_uploads_return_422_without_persistence(
    monkeypatch,
    kind: str,
) -> None:
    from app.api.v1 import sessions

    valid = _image_bytes(Image.new("RGB", (32, 32), "white"), "PNG")
    raw = b"plain text disguised as png" if kind == "disguised" else valid[:-12]

    async def forbidden_accept(**_kwargs):
        raise AssertionError("invalid image must not be persisted")

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "accept_resume_upload", forbidden_accept)

    with pytest.raises(HTTPException) as excinfo:
        await sessions.upload_resume(
            "invalid-image-session",
            UploadFile(filename="resume.png", file=BytesIO(raw)),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "unreadable_file"


@pytest.mark.asyncio
async def test_o3_decompression_bomb_upload_maps_to_422(monkeypatch) -> None:
    from app.api.v1 import sessions

    async def forbidden_accept(**_kwargs):
        raise AssertionError("invalid image must not be persisted")

    def bomb(_raw: bytes):
        raise Image.DecompressionBombError("178M pixels")

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    monkeypatch.setattr(sessions, "validate_image_header", bomb)
    monkeypatch.setattr(sessions, "accept_resume_upload", forbidden_accept)

    with pytest.raises(HTTPException) as excinfo:
        await sessions.upload_resume(
            "bomb-session",
            UploadFile(filename="resume.png", file=BytesIO(b"image-header")),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "unreadable_file"


@pytest.mark.asyncio
async def test_o10_zero_page_pdf_upload_returns_422(monkeypatch) -> None:
    from app.api.v1 import sessions

    writer = PdfWriter()
    pdf_buffer = BytesIO()
    writer.write(pdf_buffer)

    async def forbidden_accept(**_kwargs):
        raise AssertionError("zero-page PDF must not be persisted")

    monkeypatch.setattr(sessions, "accept_resume_upload", forbidden_accept)

    with pytest.raises(HTTPException) as excinfo:
        await sessions.upload_resume(
            "zero-page-upload-session",
            UploadFile(filename="resume.pdf", file=BytesIO(pdf_buffer.getvalue())),
        )

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail == "unreadable_file"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_o14_capabilities_exposes_image_upload_state(
    monkeypatch,
    enabled: bool,
) -> None:
    from app.api.v1 import router as router_module

    monkeypatch.setattr(router_module.settings, "resume_ocr_enabled", enabled)

    response = await router_module.capabilities()

    assert response.resume_image_upload_enabled is enabled


@pytest.mark.asyncio
async def test_codexM4_parse_rejects_grandfathered_image_before_quota(
    monkeypatch,
) -> None:
    """整批终审 Codex M4：OCR 开启期上传的图片、关掉开关后确认解析——
    必须在扣额度之前 409 resume_ocr_disabled（begin 不得被调用）。"""
    from fastapi import BackgroundTasks

    from app.api.v1 import sessions
    from app.api.v1.schemas import ResumeParseRequest

    async def pending(*, session_id: str):
        return {
            "generation": 3,
            "filename": "resume.png",
            "suffix": ".png",
            "extracted_text": "",
            "pages": 1,
            "chars": 0,
            "ocr_suggested": True,
            "resume_parse_count": 1,
        }

    async def forbidden_begin(**_kwargs):
        raise AssertionError("must reject before the quota CAS")

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", False)
    monkeypatch.setattr(sessions, "get_pending_resume_upload", pending)
    monkeypatch.setattr(sessions, "begin_resume_parse", forbidden_begin)

    with pytest.raises(HTTPException) as excinfo:
        await sessions.parse_resume(
            "grandfather-session",
            ResumeParseRequest(generation=3),
            BackgroundTasks(),
        )
    assert excinfo.value.status_code == 409
    assert excinfo.value.detail == "resume_ocr_disabled"


def test_codexM4_image_preview_falls_back_when_ocr_disabled(monkeypatch) -> None:
    """flag 关闭后固定视觉识别 preview 不得再出现（GET 恢复同层）。"""
    from app.api.v1 import sessions

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", False)
    response = sessions._upload_response(
        "grandfather-session",
        generation=3,
        filename="resume.png",
        suffix=".png",
        extracted_text="",
        pages=1,
        chars=0,
        ocr_suggested=True,
        parses_used=1,
    )
    assert response.text_preview == ""

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    enabled = sessions._upload_response(
        "grandfather-session",
        generation=3,
        filename="resume.png",
        suffix=".png",
        extracted_text="",
        pages=1,
        chars=0,
        ocr_suggested=True,
        parses_used=1,
    )
    assert "视觉识别" in enabled.text_preview


@pytest.mark.asyncio
async def test_codexM4_zero_page_pdf_upload_gate_tracks_flag(monkeypatch) -> None:
    """0 页 PDF 上传 422 随开关（flag=false 逐字节回到 B4 前行为：接受
    入库，解析期报错返还）。"""
    from app.api.v1 import sessions

    writer = PdfWriter()
    empty_buffer = BytesIO()
    writer.write(empty_buffer)
    raw = empty_buffer.getvalue()
    accepted: list[dict] = []

    async def accept(**kwargs):
        accepted.append(kwargs)
        return {"resume_upload_generation": 1, "resume_parse_count": 0}

    monkeypatch.setattr(sessions, "accept_resume_upload", accept)

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", True)
    with pytest.raises(HTTPException) as excinfo:
        await sessions.upload_resume(
            "zero-page-session",
            UploadFile(filename="resume.pdf", file=BytesIO(raw)),
        )
    assert excinfo.value.status_code == 422
    assert accepted == []

    monkeypatch.setattr(sessions.settings, "resume_ocr_enabled", False)
    response = await sessions.upload_resume(
        "zero-page-session",
        UploadFile(filename="resume.pdf", file=BytesIO(raw)),
    )
    assert response.pages == 0
    assert len(accepted) == 1
