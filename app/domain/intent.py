from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.state.schema import SharedState


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


class IntentConsultationProjection(IntentModel):
    session_id: str
    mode: Literal["targeted", "explore"]
    assistant_message: str
    current_goal: list[str] = Field(default_factory=list)
    long_term_goal: list[str] = Field(default_factory=list)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    soft_preferences: dict[str, Any] = Field(default_factory=dict)
    avoid_roles: list[str] = Field(default_factory=list)
    directions: list[CareerDirection] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    clarification_used: int = Field(default=0, ge=0, le=1)


def project_intent_consultation(
    state: SharedState,
) -> IntentConsultationProjection:
    mode = state.career_state.intent_mode
    if mode is None:
        raise ValueError("intent consultation is not available")

    allowed_evidence_ids = {
        str(span_id)
        for span in state.resume_state.original_evidence_spans
        if (span_id := span.get("span_id") or span.get("id"))
    }
    directions: list[CareerDirection] = []
    for raw_direction in state.career_state.intent_directions[:3]:
        if not isinstance(raw_direction, dict):
            continue
        payload = dict(raw_direction)
        payload["resume_evidence_span_ids"] = [
            str(span_id)
            for span_id in payload.get("resume_evidence_span_ids") or []
            if str(span_id) in allowed_evidence_ids
        ]
        try:
            directions.append(CareerDirection.model_validate(payload))
        except ValidationError:
            continue

    return IntentConsultationProjection(
        session_id=state.session_id,
        mode=mode,
        assistant_message=state.career_state.intent_assistant_message,
        current_goal=[str(value) for value in state.career_state.current_goal],
        long_term_goal=[str(value) for value in state.career_state.long_term_goal],
        hard_constraints=dict(state.career_state.hard_constraints),
        soft_preferences=dict(state.career_state.soft_preferences),
        avoid_roles=[str(value) for value in state.career_state.avoid_roles],
        directions=directions,
        needs_clarification=state.career_state.intent_needs_clarification,
        clarification_question=state.career_state.intent_clarification_question,
        clarification_used=state.career_state.intent_clarification_used,
    )
