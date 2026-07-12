from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HiringStage(StrEnum):
    APPLIED = "applied"
    SCREEN_PASSED = "screen_passed"
    OA_PASSED = "oa_passed"
    INTERVIEW = "interview"
    OFFER = "offer"
    JOINED = "joined"

    @property
    def weight(self) -> float:
        return {
            HiringStage.APPLIED: 0.0,
            HiringStage.SCREEN_PASSED: 0.4,
            HiringStage.OA_PASSED: 0.55,
            HiringStage.INTERVIEW: 0.7,
            HiringStage.OFFER: 0.9,
            HiringStage.JOINED: 1.0,
        }[self]


class FinalStatus(StrEnum):
    ACTIVE = "active"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    OFFER_DECLINED = "offer_declined"
    JOINED = "joined"


class AnonymousResumeCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    resume_payload: dict[str, Any]
    embedding_text: str


class CaseJobOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_id: str
    case_id: str
    job_id: str | None = None
    company: str
    role_family: str
    explicit_match_score: float = Field(ge=0.0, le=1.0)
    highest_stage: HiringStage
    final_status: FinalStatus
    source_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ImplicitEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    effective_case_count: int = Field(ge=0)
    supporting_cases: list[dict[str, Any]] = Field(default_factory=list)
