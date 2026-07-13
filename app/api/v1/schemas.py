from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.match_brief import MatchBrief
from app.domain.results import ProductResult


class PublicDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilitiesResponse(PublicDTO):
    api_version: Literal["v1"] = "v1"
    dual_space_enabled: bool
    explain_enabled: bool
    execution_durability: Literal["process_local"] = "process_local"


class SessionCreateRequest(PublicDTO):
    user_id: str = Field(min_length=1, max_length=200)


class SessionResponse(PublicDTO):
    session_id: str
    status: str


class ResumeAcceptedResponse(PublicDTO):
    session_id: str
    status: Literal["resume_queued"] = "resume_queued"


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


class IntentConsultRequest(PublicDTO):
    mode: Literal["targeted", "explore"]
    goal_text: str | None = Field(default=None, max_length=2000)
    target_roles: list[str] = Field(default_factory=list, max_length=10)
    target_companies: list[str] = Field(default_factory=list, max_length=10)
    company_exclusive: bool = False
    clarification_answer: str | None = Field(default=None, max_length=1000)


class CareerDirectionResponse(PublicDTO):
    role_family: str
    title: str
    rationale: str
    resume_evidence_span_ids: list[str] = Field(default_factory=list)
    primary_gap: str = ""
    entry_role: str = ""


class IntentConsultResponse(PublicDTO):
    session_id: str
    mode: Literal["targeted", "explore"]
    assistant_message: str
    current_goal: list[str] = Field(default_factory=list)
    long_term_goal: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)
    directions: list[CareerDirectionResponse] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_used: int = Field(default=0, ge=0, le=1)


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
    updated_at: datetime


class RunResultResponse(PublicDTO):
    run_id: str
    status: str
    result: ProductResult


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
