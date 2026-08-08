from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.match_brief import MatchBrief
from app.domain.results import ProductResult


class PublicDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilitiesResponse(PublicDTO):
    api_version: Literal["v1"] = "v1"
    dual_space_enabled: bool
    explain_enabled: bool
    monitoring_enabled: bool
    execution_durability: Literal["process_local"] = "process_local"
    # 可用的 OTP 登录通道；配置为 disabled 的通道不出现在列表里，
    # 前端据此隐藏对应登录 tab
    otp_channels: list[Literal["email", "phone"]] = Field(default_factory=list)


class OtpRequest(PublicDTO):
    channel: Literal["email", "phone"]
    target: str = Field(min_length=3, max_length=320)


class OtpRequestAccepted(PublicDTO):
    status: Literal["otp_accepted"] = "otp_accepted"


class OtpVerifyRequest(PublicDTO):
    channel: Literal["email", "phone"]
    target: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^\d{6}$")


class MeResponse(PublicDTO):
    user_id: str
    display_name: str | None = None
    avatar_url: str | None = None
    status: str
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None = None


class ProfilePatchRequest(PublicDTO):
    profile: dict[str, Any]


class ProfileResponse(PublicDTO):
    profile: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime


class MeSessionResponse(PublicDTO):
    session_id: str
    status: str
    updated_at: datetime


class MeSessionsResponse(PublicDTO):
    sessions: list[MeSessionResponse] = Field(default_factory=list)
    page: int
    page_size: int
    has_more: bool


class SessionCreateRequest(PublicDTO):
    pass


class SessionResponse(PublicDTO):
    session_id: str
    status: str


class ResumeAcceptedResponse(PublicDTO):
    session_id: str
    status: Literal["resume_queued"] = "resume_queued"


class ResumeUploadedResponse(PublicDTO):
    """B2 上传确认流：上传即本地提取（零 LLM），等待用户确认解析。"""

    session_id: str
    status: Literal["resume_uploaded"] = "resume_uploaded"
    generation: int
    filename: str
    pages: int
    chars: int
    text_preview: str
    parses_used: int
    parses_limit: int
    ocr_suggested: bool


class ResumeParseRequest(PublicDTO):
    # 必须回传预览所得 generation：旧标签页解析未预览的新代 → 409 resume_changed
    generation: int


class ResumeProgressEvent(PublicDTO):
    """B3 小意解析叙事：单条进度事件（非终态 seq 1..99，终态 done/error=100）。"""

    seq: int
    step: str
    text: str
    elapsed_ms: int
    created_at: datetime


class ResumeProgressResponse(PublicDTO):
    """B3 解析进度轮询契约：events 恒为当前代全量（ORDER BY seq，协议上界
    ≤100 行）；从未上传 → generation=null + events=[]；done = 已离开
    resume_queued（ready/error/uploaded 全部停轮询，覆盖解析中重传交错）。"""

    generation: int | None
    status: str
    events: list[ResumeProgressEvent] = Field(default_factory=list)
    done: bool


class ResumeConfirmRequest(PublicDTO):
    expected_resume_version: int | None = None


class ResumeLifecycleConflictResponse(PublicDTO):
    # resume_missing = 会话从未上传过简历（与"归一化中"必须可区分，否则新
    # 会话会被前端当成处理中而失去上传入口——审计二轮阻断项）
    # resume_unparsed = 已上传未确认解析（B2）；resume_parse_limit = 解析
    # 次数额度用尽（B2，防烧钱限额）
    detail: Literal[
        "resume_changed",
        "resume_processing",
        "resume_error",
        "resume_missing",
        "resume_unparsed",
        "resume_parse_limit",
    ]


class ResumeUploadRejectedResponse(PublicDTO):
    # 415 = 非白名单后缀；422 = 文件损坏/无法解析（不入库、不占 generation）
    detail: Literal["unsupported_file_type", "unreadable_file"]


class ResumeVersionRequiredResponse(PublicDTO):
    detail: Literal["expected_resume_version_required"]


class ValidationErrorItem(BaseModel):
    """FastAPI/Pydantic 默认校验错误条目的契约镜像（宽容额外键）。"""

    model_config = ConfigDict(extra="allow")

    loc: list[str | int] = Field(default_factory=list)
    msg: str = ""
    type: str = ""


class RequestValidationErrorResponse(BaseModel):
    """默认 422 数组形态——与自定义必填 detail 组成 anyOf，保证契约加性。"""

    model_config = ConfigDict(extra="allow")

    detail: list[ValidationErrorItem] = Field(default_factory=list)


class ResumeEducationPreview(PublicDTO):
    institution: str = ""
    degree: str = ""
    field: str = ""
    dates: str = ""
    details: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)


class ResumeExperiencePreview(PublicDTO):
    organization: str = ""
    title: str = ""
    dates: str = ""
    location: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)


class ResumeProjectPreview(PublicDTO):
    name: str = ""
    dates: str = ""
    summary: str = ""
    actions: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)
    evidence_span_ids: list[str] = Field(default_factory=list)


class ResumeEvidencePreview(PublicDTO):
    evidence_span_id: str
    content: str


class ResumePreviewResponse(PublicDTO):
    session_id: str
    resume_version: int
    confirmed: bool
    education: list[ResumeEducationPreview] = Field(default_factory=list)
    experience: list[ResumeExperiencePreview] = Field(default_factory=list)
    projects: list[ResumeProjectPreview] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    resume_quality_issues: list[str] = Field(default_factory=list)
    evidence: list[ResumeEvidencePreview] = Field(default_factory=list)


class ResumeConfirmResponse(PublicDTO):
    session_id: str
    resume_version: int
    confirmed: bool
    confirmed_at: datetime | None = None


class ConsultProfileDraft(PublicDTO):
    current_goal: list[str] = Field(default_factory=list)
    long_term_goal: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)


class ClarificationProgress(PublicDTO):
    answered: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    questions_used: int = Field(default=0, ge=0)


class SupervisorNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["coach"]
    trigger: Literal["deepen_entry", "stagnation", "finalizable"]
    text: str = Field(min_length=1, max_length=300)
    verdict: Literal["pass", "advise"]
    coach_attempt_id: str = Field(min_length=1)


class ConsultTranscriptEntry(PublicDTO):
    round: int = Field(ge=1)
    user_message: str = Field(max_length=2000)
    assistant_reply: str = Field(max_length=120)
    next_question: str = Field(max_length=80)
    phase: Literal["template", "resume_clarify", "deepen", "explore"]
    supervisor_notes: list[SupervisorNote] = Field(default_factory=list)


class ConsultRequest(PublicDTO):
    mode: Literal["targeted", "explore"]
    message: str = Field(min_length=1, max_length=2000)
    expected_round: int = Field(ge=0)

    @field_validator("message")
    @classmethod
    def strip_nonempty_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("consultation message must not be blank")
        return stripped


class ConsultResponse(PublicDTO):
    assistant_reply: str = Field(min_length=1, max_length=120)
    next_question: str = Field(min_length=1, max_length=80)
    phase: Literal["template", "resume_clarify", "deepen", "explore"]
    completeness: float = Field(ge=0, le=1)
    can_finalize: bool
    round: int = Field(ge=1)
    profile_draft: ConsultProfileDraft
    clarification_progress: ClarificationProgress = Field(
        default_factory=ClarificationProgress
    )


class ConsultStateResponse(PublicDTO):
    transcript: list[ConsultTranscriptEntry] = Field(default_factory=list)
    profile_draft: ConsultProfileDraft
    round: int = Field(ge=0)
    phase: Literal["template", "resume_clarify", "deepen", "explore"]
    completeness: float = Field(ge=0, le=1)
    can_finalize: bool
    clarification_progress: ClarificationProgress = Field(
        default_factory=ClarificationProgress
    )


class ConsultBriefDraftResponse(PublicDTO):
    career_goal: str
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)
    result_count: int = Field(default=5, ge=3, le=10)


class MatchBriefRequest(PublicDTO):
    career_goal: str = Field(min_length=10, max_length=2000)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)
    result_count: int = Field(default=5, ge=3, le=10)
    conflicts: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None


class MatchBriefResponse(PublicDTO):
    run_id: str
    session_id: str
    brief: MatchBrief


class ExecuteRunRequest(PublicDTO):
    plan_version: int = Field(ge=1)
    plan_hash: str = Field(min_length=64, max_length=64)


class RunStatusResponse(PublicDTO):
    run_id: str
    session_id: str
    status: str
    stage: str | None = None
    result_ready: bool
    warning_codes: list[str] = Field(default_factory=list)
    error_code: str | None = None
    execution_durability: str
    retry_after_ms: int | None = None
    completed_stages: list[str] = Field(default_factory=list)
    total_stages: int = 7
    plan_version: int
    plan_hash: str | None = None
    updated_at: datetime


class ConversationMessageResponse(PublicDTO):
    seq: int = Field(ge=1)
    persona: Literal["intent_consultant", "job_scout", "strategist", "pm"]
    display_name: str
    kind: Literal[
        "intro",
        "brief",
        "progress",
        "checkpoint",
        "recovery",
        "result",
        "warning",
        "error",
    ]
    text: str
    stage: str


class RunConversationResponse(PublicDTO):
    run_id: str
    status: str
    stage: str | None = None
    next_poll_ms: int | None = None
    messages: list[ConversationMessageResponse] = Field(default_factory=list)


class RunResultResponse(PublicDTO):
    run_id: str
    status: str
    result: ProductResult


class CaseEvidenceResponse(PublicDTO):
    case_id: str
    highest_stage: str
    confidence: float | None = None


class RankTraceResponse(PublicDTO):
    job_id: str
    final_rank: int
    explicit_rank: int | None = None
    implicit_rank: int | None = None
    explicit_score: float | None = None
    implicit_score: float | None = None
    implicit_confidence: float | None = None
    implicit_weight: float
    case_ids: list[str] = Field(default_factory=list)
    case_evidence: list[CaseEvidenceResponse] = Field(default_factory=list)


class FusionResponse(PublicDTO):
    implicit_max_weight: float


class RecoveryEventResponse(PublicDTO):
    stage: str
    reason: str
    attempt: int
    max_attempts: int


class RunExplainResponse(PublicDTO):
    run_id: str
    rank_trace: list[RankTraceResponse] = Field(default_factory=list)
    fusion: FusionResponse
    stage_durations_ms: dict[str, int] = Field(default_factory=dict)
    recovery_events: list[RecoveryEventResponse] = Field(default_factory=list)


class StageLatencyResponse(PublicDTO):
    stage: str
    p50_ms: int | None = None
    p95_ms: int | None = None


class MonitoringOverviewResponse(PublicDTO):
    window_hours: int
    generated_at: datetime
    total_runs: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    completion_rate: float
    warning_rate: float
    failure_rate: float
    duration_p50_ms: int | None = None
    duration_p95_ms: int | None = None
    stage_latencies: list[StageLatencyResponse] = Field(default_factory=list)
    average_recommendation_count: float
    jd_evidence_coverage_rate: float
    implicit_usage_rate: float
    reordered_run_count: int


class RecentRunResponse(PublicDTO):
    run_id: str
    status: str
    stage: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    recommendation_count: int = 0
    warning_codes: list[str] = Field(default_factory=list)
    error_code: str | None = None


class RecentRunsResponse(PublicDTO):
    window_hours: int
    generated_at: datetime
    runs: list[RecentRunResponse] = Field(default_factory=list)


class ReactionRequest(PublicDTO):
    job_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    reason: str | None = None
    user_rating: int | None = Field(default=None, ge=1, le=5)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class ReactionResponse(PublicDTO):
    run_id: str
    feedback_id: int
    status: Literal["reaction_recorded"] = "reaction_recorded"
