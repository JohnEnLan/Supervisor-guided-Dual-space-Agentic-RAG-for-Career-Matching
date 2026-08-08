"""Qwen VL OCR 异步客户端（DashScope，OpenAI 兼容接口）。

v3 B4 视觉 OCR 兜底：
- 只在确认解析后的后台任务内调用（上传阶段零 VL 成本，方案 §4 边界）。
- Semaphore 限流（VL_MAX_CONCURRENCY，默认 2）。
- 输入为任务内已编码好的 JPEG 字节（光栅化/再编码由调用方经
  asyncio.to_thread 卸载——宪法裁决允许的阻塞卸载例外）；本模块只负责
  base64 封包与 API 调用，不做任何图像处理。
"""
import asyncio
import base64

from openai import AsyncOpenAI

from app.config import settings

# 与 qwen_embed 同一 DashScope OpenAI 兼容 endpoint。
# timeout/max_retries 写死（B4 方案三轮 Codex 裁定）：J1 熔断语义承诺
# "成本放大上界=1 次调用"——SDK 默认 max_retries=2 会让一次逻辑调用变
# 3 次传输尝试、且 60s 超时罩不住整个逻辑调用，必须归零重试。
_VL_TIMEOUT_SECONDS = 60.0
_client = AsyncOpenAI(
    api_key=settings.qwen_api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    timeout=_VL_TIMEOUT_SECONDS,
    max_retries=0,
)

_sem = asyncio.Semaphore(settings.vl_max_concurrency)

# qwen-vl-ocr 为 OCR 专用模型：官方用法固定文本指令，模型输出图内全部文字
_OCR_INSTRUCTION = "Read all the text in the image."


async def ocr_image_jpeg(jpeg_bytes: bytes) -> str:
    """对单张 JPEG 图片做 OCR，返回识别出的全部文本（失败向上抛，由任务

    的统一 except 兜底走 resume_error——图片路径如此；PDF 路径由调用点
    捕获熔断（方案偏差备案 #2）。"""
    async with _sem:
        # base64 编码在 Semaphore 内（Codex 一轮 m3）：并发内存峰值随
        # 并发闸受限，而非只限网络段
        encoded = base64.b64encode(jpeg_bytes).decode("ascii")
        response = await _client.chat.completions.create(
            model=settings.qwen_vl_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{encoded}"
                            },
                        },
                        {"type": "text", "text": _OCR_INSTRUCTION},
                    ],
                }
            ],
        )
    return (response.choices[0].message.content or "").strip()
