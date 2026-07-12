from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(PublicModel):
    evidence_span_id: str
    field: str | None = None
    content: str


class RecommendationResult(PublicModel):
    job_id: str
    title: str | None = None
    company: str | None = None
    location: str | None = None
    tier: Literal["now_fit", "stretch_fit", "bridge_role"]
    concise_explanation: str
    why_this_match: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    resume_evidence: list[EvidenceItem] = Field(default_factory=list)
    source_url: str | None = None
    listing_kind: Literal["source_url", "dataset_only"] = "dataset_only"


class ResumeAdvice(PublicModel):
    section: str
    suggestion: str
    evidence_span_ids: list[str] = Field(default_factory=list)


class SkillGap(PublicModel):
    skill: str
    gap: str = ""
    priority: Literal["low", "medium", "high", ""] = ""
    evidence_span_ids: list[str] = Field(default_factory=list)


class CareerPathItem(PublicModel):
    horizon: Literal["short", "medium", "long"]
    action: str
    evidence_span_ids: list[str] = Field(default_factory=list)


class ProductResult(PublicModel):
    summary: str
    recommended_roles: list[RecommendationResult] = Field(default_factory=list)
    resume_strategy: list[ResumeAdvice] = Field(default_factory=list)
    skill_gaps: list[SkillGap] = Field(default_factory=list)
    career_path: list[CareerPathItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
