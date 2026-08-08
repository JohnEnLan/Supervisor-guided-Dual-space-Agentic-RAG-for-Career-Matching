"""B4 模块一：VL OCR 客户端与配置（v3 方案 §4）。

真实模型名/参数的线上冒烟另行执行（方案"首日真实冒烟"条款）；本文件
钉死：配置默认值与边界、payload 结构（data URL + 固定指令）、Semaphore
并发上限、异常不吞（由任务统一 except 兜底）。
"""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


def _settings(**overrides):
    from app.config import Settings

    return Settings(
        _env_file=None,
        database_url="postgresql://test",
        deepseek_api_key="test",
        qwen_api_key="test",
        **overrides,
    )


def test_ocr_config_defaults_match_plan_section_4() -> None:
    config = _settings()
    assert config.resume_ocr_enabled is True
    assert config.qwen_vl_model == "qwen-vl-ocr"
    assert config.vl_max_concurrency == 2
    assert config.resume_ocr_page_min_chars == 50
    assert config.resume_ocr_max_pages == 6
    assert config.resume_ocr_max_pixels == 4_000_000
    assert config.resume_ocr_render_scale == 2.0
    assert config.resume_ocr_max_image_pixels_decode == 40_000_000


def test_vl_client_pins_timeout_and_zero_retries() -> None:
    """O15（Codex 三轮 Major）：J1 熔断承诺"成本放大上界=1 次调用"依赖
    SDK 不自作主张重试——timeout=60s 且 max_retries=0 双断言钉死。"""
    from app.llm import qwen_vl

    assert qwen_vl._VL_TIMEOUT_SECONDS == 60.0
    assert qwen_vl._client.timeout == 60.0
    assert qwen_vl._client.max_retries == 0


def test_ocr_config_rejects_out_of_range_values() -> None:
    for invalid in ({"vl_max_concurrency": 0}, {"resume_ocr_max_pages": 0},
                    {"resume_ocr_render_scale": 0}):
        with pytest.raises(ValidationError):
            _settings(**invalid)


@pytest.mark.asyncio
async def test_ocr_image_jpeg_sends_data_url_and_fixed_instruction(
    monkeypatch,
) -> None:
    from app.llm import qwen_vl

    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        message = SimpleNamespace(content="  识别出的简历文本  ")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(
        qwen_vl._client.chat.completions, "create", fake_create
    )

    text = await qwen_vl.ocr_image_jpeg(b"\xff\xd8fake-jpeg")

    assert text == "识别出的简历文本"
    assert captured["model"] == qwen_vl.settings.qwen_vl_model
    (message,) = captured["messages"]
    assert message["role"] == "user"
    image_part, text_part = message["content"]
    expected_b64 = base64.b64encode(b"\xff\xd8fake-jpeg").decode("ascii")
    assert image_part["image_url"]["url"] == (
        f"data:image/jpeg;base64,{expected_b64}"
    )
    assert text_part["text"] == "Read all the text in the image."


@pytest.mark.asyncio
async def test_ocr_semaphore_caps_concurrent_calls(monkeypatch) -> None:
    from app.llm import qwen_vl

    active = 0
    peak = 0
    release = asyncio.Event()

    async def slow_create(**_kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await release.wait()
        active -= 1
        message = SimpleNamespace(content="text")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(
        qwen_vl._client.chat.completions, "create", slow_create
    )

    tasks = [
        asyncio.create_task(qwen_vl.ocr_image_jpeg(b"jpeg")) for _ in range(5)
    ]
    await asyncio.sleep(0.05)
    assert peak <= qwen_vl.settings.vl_max_concurrency
    release.set()
    await asyncio.gather(*tasks)
    assert peak == qwen_vl.settings.vl_max_concurrency


@pytest.mark.asyncio
async def test_ocr_propagates_api_errors_without_swallowing(
    monkeypatch,
) -> None:
    from app.llm import qwen_vl

    async def failing_create(**_kwargs):
        raise RuntimeError("vl api down")

    monkeypatch.setattr(
        qwen_vl._client.chat.completions, "create", failing_create
    )

    with pytest.raises(RuntimeError, match="vl api down"):
        await qwen_vl.ocr_image_jpeg(b"jpeg")
