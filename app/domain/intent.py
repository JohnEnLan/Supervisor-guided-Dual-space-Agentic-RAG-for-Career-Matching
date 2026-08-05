from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IntentConsultInput(IntentModel):
    mode: Literal["targeted", "explore"]
    goal_text: str | None = Field(default=None, max_length=2000)
    target_roles: list[str] = Field(default_factory=list, max_length=10)
    target_companies: list[str] = Field(default_factory=list, max_length=10)
    company_exclusive: bool = False
    clarification_answer: str | None = Field(default=None, max_length=1000)


class CareerDirection(IntentModel):
    role_family: str = Field(min_length=1)
    title: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    resume_evidence_span_ids: list[str] = Field(default_factory=list)
    primary_gap: str = ""
    entry_role: str = ""
