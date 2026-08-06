"""Clarification-aware internal views over the immutable base resume."""
from __future__ import annotations

from app.config import settings
from app.state.schema import ResumeState, SharedState


ResumeViewState = ResumeState | SharedState


def effective_resume_text(state: ResumeViewState) -> str:
    """Render the base resume plus confirmed clarification evidence."""
    resume = _resume_state(state)
    base_text = resume.normalized_base_resume
    if not settings.resume_clarify_enabled:
        return base_text

    lines: list[str] = []
    for span in resume.clarification_evidence_spans:
        text = str(span.get("text") or "").strip()
        if not text:
            continue
        span_id = str(span.get("span_id") or span.get("id") or "").strip()
        prefix = f"[{span_id}] " if span_id else ""
        lines.append(f"- {prefix}{text}")

    if not lines:
        return base_text

    section = "Supplementary information (user-confirmed clarifications):\n"
    section += "\n".join(lines)
    if not base_text:
        return section
    separator = "\n" if base_text.endswith("\n") else "\n\n"
    return f"{base_text}{separator}{section}"


def all_resume_evidence_spans(state: ResumeViewState) -> list[dict]:
    """Return the enabled resume-evidence pools in their persisted order."""
    resume = _resume_state(state)
    spans = list(resume.original_evidence_spans)
    if settings.resume_clarify_enabled:
        spans.extend(resume.clarification_evidence_spans)
    return spans


def resume_evidence_ids(state: ResumeViewState) -> set[str]:
    """Collect the evidence IDs allowed for resume-grounded output."""
    ids: set[str] = set()
    for span in all_resume_evidence_spans(state):
        span_id = span.get("span_id") or span.get("id")
        if span_id:
            ids.add(str(span_id))
    return ids


def _resume_state(state: ResumeViewState) -> ResumeState:
    return state.resume_state if isinstance(state, SharedState) else state
