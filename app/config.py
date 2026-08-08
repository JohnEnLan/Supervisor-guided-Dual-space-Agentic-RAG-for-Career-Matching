"""集中配置。默认读取 .env，测试可显式关闭 dotenv 加载。"""
import os
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _configured_env_file() -> str | None:
    configured = os.environ.get("CAREER_RAG_ENV_FILE")
    if configured is None:
        return ".env"
    return configured or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_configured_env_file(),
        extra="ignore",
    )

    database_url: str
    db_pool_min: int = 2
    db_pool_max: int = 10

    app_env: Literal["development", "test", "production"] = "development"
    auth_secret_key: str = "development-only-auth-secret-key-change-me"
    otp_pepper: str = "development-only-otp-pepper-change-me"
    auth_session_ttl_days: int = Field(default=7, ge=1, le=30)
    email_otp_provider: Literal["console", "smtp", "disabled"] = "console"
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_start_tls: bool = True
    sms_otp_provider: Literal["console", "disabled"] = "console"
    auth_enforced: bool = False
    # 跨机器 http 演示时置 true：改发无 __Host- 前缀、无 Secure 的会话 Cookie。
    # 仅限 development/test；production 启动校验会拒绝。
    auth_cookie_insecure: bool = False
    monitoring_admin_mode: bool = False
    demo_corpus_enabled: bool = False
    # 每账号会话（对话）额度；超出返回 402 由前端弹付费墙
    session_quota_per_user: int = Field(default=3, ge=1)

    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_fast: str = "deepseek-chat"
    deepseek_model_pro: str = "deepseek-reasoner"

    qwen_api_key: str
    # 必须与语料 embedding 指纹一致（W5 演示语料按 text-embedding-v4 构建）。
    # 在线服务启动不做查询模型×语料指纹交叉校验，配错会静默劣化召回；
    # 导入流程（import_cnuk_demo）有指纹强校验、配错会直接报错。
    qwen_embed_model: str = "text-embedding-v4"
    embed_dim: int = 1024  # 必须与 schema.sql 里的 vector(N) 一致

    # RAPTOR 检索通道（岗位/角色摘要节点树）：产品主链 plan 的 run 级快照来源。
    # 消融实测与 Cross 同开为最优组合（docs/validation/2026-08-06）。
    raptor_enabled: bool = False
    rerank_enabled: bool = False
    rerank_model: Literal["gte-rerank-v2"] = "gte-rerank-v2"
    rerank_endpoint: str | None = None
    rerank_top_n: int = Field(default=20, ge=1, le=200)
    rerank_timeout_seconds: float = Field(default=5, gt=0)
    rerank_max_concurrency: int = Field(default=4, ge=1)
    rerank_doc_max_chars: int = Field(default=1500, ge=100, le=4000)
    rerank_query_max_chars: int = Field(default=600, ge=100, le=4000)

    llm_max_concurrency: int = Field(default=5, ge=1)
    llm_user_prompt_max_chars: int = Field(default=60_000, ge=1_000)
    embed_max_concurrency: int = Field(default=8, ge=1)

    dual_space_enabled: bool = True
    implicit_min_cases: int = 3
    implicit_max_weight: float = 0.30
    implicit_case_top_k: int = 20

    evaluation_capability_enabled: bool = False
    monitoring_enabled: bool = False
    langgraph_orchestrator_enabled: bool = True
    run_stale_after_seconds: int = Field(default=900, ge=1)
    checkpoint_sweep_interval_seconds: int = Field(default=3600, ge=0)

    max_clarification_loops: int = 1
    max_consult_rounds: int = Field(default=8, ge=1, le=15)
    resume_clarify_enabled: bool = False
    resume_clarify_max: int = Field(default=2, ge=1, le=5)
    # v3 B2：每会话解析（LLM 归一化）次数上限；上传/预览零成本不计额
    resume_parse_limit: int = Field(default=3, ge=1, le=10)
    # v3 B4：视觉 OCR 兜底（R1 主线功能，默认开；false=B4 前逐字节等价，
    # 供回退与对照测试）。上传阶段零 VL 调用——只在确认解析后的任务内，
    # 对低文本 PDF 页/图片简历触发（方案 §4）。
    resume_ocr_enabled: bool = True
    qwen_vl_model: str = "qwen-vl-ocr"
    vl_max_concurrency: int = Field(default=2, ge=1)
    resume_ocr_page_min_chars: int = Field(default=50, ge=0)
    resume_ocr_max_pages: int = Field(default=6, ge=1)
    resume_ocr_max_pixels: int = Field(default=4_000_000, ge=100_000)
    resume_ocr_render_scale: float = Field(default=2.0, gt=0)
    # 解码防炸：显式尺寸乘积检查（不依赖 Pillow MAX_IMAGE_PIXELS——其超限
    # 默认仅告警、超两倍才抛错）
    resume_ocr_max_image_pixels_decode: int = Field(
        default=40_000_000, ge=1_000_000
    )
    # v3 B5：管理员邮箱白名单（逗号分隔）。空串=无管理员（require_admin
    # fail-closed 恒 403）。解析规范见 parse_admin_emails。
    admin_emails: str = ""
    consult_coach_enabled: bool = False
    consult_coach_max: int = Field(default=3, ge=1, le=5)
    max_reretrieval_loops: int = 1
    max_repair_loops: int = 1


def parse_admin_emails(raw: str) -> frozenset[str]:
    """B5 白名单解析规范（方案 §5.2 逐字）：逗号分隔、trim、casefold、
    去重；空串/纯分隔符 → 空集（require_admin fail-closed）。"""
    return frozenset(
        item.strip().casefold()
        for item in raw.split(",")
        if item.strip()
    )


def validate_runtime_security(
    runtime_settings: Settings,
    *,
    active_demo_corpus: bool = False,
) -> None:
    if runtime_settings.app_env != "production":
        return
    if not runtime_settings.auth_enforced:
        raise RuntimeError("AUTH_ENFORCED must be true in production")
    if runtime_settings.auth_cookie_insecure:
        raise RuntimeError(
            "AUTH_COOKIE_INSECURE is a demo-only switch and is forbidden "
            "in production"
        )
    if (
        len(runtime_settings.auth_secret_key.encode("utf-8")) < 32
        or runtime_settings.auth_secret_key.startswith("development-only-")
    ):
        raise RuntimeError("AUTH_SECRET_KEY must be at least 32 bytes")
    if (
        len(runtime_settings.otp_pepper.encode("utf-8")) < 32
        or runtime_settings.otp_pepper.startswith("development-only-")
    ):
        raise RuntimeError("OTP_PEPPER must be at least 32 bytes")
    otp_providers = {
        runtime_settings.email_otp_provider,
        runtime_settings.sms_otp_provider,
    }
    if otp_providers == {"disabled"}:
        raise RuntimeError("at least one OTP provider must be enabled")
    if "console" in otp_providers:
        raise RuntimeError("console OTP providers are forbidden in production")
    if runtime_settings.email_otp_provider == "smtp" and not (
        runtime_settings.smtp_host and runtime_settings.smtp_from_email
    ):
        raise RuntimeError(
            "SMTP_HOST and SMTP_FROM_EMAIL are required when the email OTP "
            "provider is smtp in production"
        )
    if (
        runtime_settings.monitoring_enabled
        and not runtime_settings.monitoring_admin_mode
    ):
        raise RuntimeError(
            "MONITORING_ADMIN_MODE is required when monitoring is enabled "
            "in production"
        )
    if active_demo_corpus and not runtime_settings.demo_corpus_enabled:
        raise RuntimeError(
            "DEMO_CORPUS_ENABLED must be true when production has active "
            "demo_synthetic jobs"
        )


settings = Settings()  # 全局唯一实例
