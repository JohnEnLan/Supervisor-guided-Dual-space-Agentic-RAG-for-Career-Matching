from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MatchBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    career_goal: str = Field(min_length=10, max_length=2000)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)
    result_count: int = Field(default=5, ge=3, le=10)
    conflicts: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    plan_version: int = Field(ge=1)
    plan_hash: str


def create_match_brief(
    *,
    career_goal: str,
    hard_constraints: dict[str, Any],
    soft_preferences: dict[str, Any],
    avoid_roles: list[str],
    result_count: int,
    plan_version: int,
    conflicts: list[str] | None = None,
    needs_clarification: bool = False,
    clarification_question: str | None = None,
) -> MatchBrief:
    payload = {
        "career_goal": career_goal,
        "hard_constraints": hard_constraints,
        "soft_preferences": soft_preferences,
        "avoid_roles": avoid_roles,
        "result_count": result_count,
        "conflicts": conflicts or [],
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question,
        "plan_version": plan_version,
    }
    return MatchBrief(**payload, plan_hash=compute_plan_hash(payload))


def compute_plan_hash(brief: MatchBrief | dict[str, Any]) -> str:
    payload = (
        brief.model_dump(mode="json", exclude={"plan_hash"})
        if isinstance(brief, MatchBrief)
        else {key: value for key, value in brief.items() if key != "plan_hash"}
    )
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_matches(
    brief: MatchBrief, *, plan_version: int, plan_hash: str
) -> bool:
    return (
        brief.plan_version == plan_version
        and brief.plan_hash == plan_hash
        and compute_plan_hash(brief) == plan_hash
    )
