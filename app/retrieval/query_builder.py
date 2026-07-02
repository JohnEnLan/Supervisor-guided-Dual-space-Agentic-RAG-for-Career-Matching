from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any

from app.state.schema import ResumeState


@dataclass(frozen=True)
class ResumeRetrievalQuery:
    text: str
    field_texts: dict[str, str] = dataclass_field(default_factory=dict)


FIELD_LABELS = {
    "summary": "Summary",
    "skills": "Skills",
    "experience": "Experience",
    "projects": "Projects",
}

DICT_VALUE_ORDER = (
    "title",
    "role",
    "company",
    "organization",
    "name",
    "description",
    "summary",
    "responsibilities",
    "achievements",
    "skills",
    "tools",
    "outcomes",
)


def build_resume_retrieval_query(resume_state: ResumeState) -> ResumeRetrievalQuery:
    field_texts = {
        "summary": _clean_text(resume_state.normalized_base_resume),
        "skills": _join_unique(resume_state.skills, max_chars=800),
        "experience": _join_unique(
            _flatten_values(resume_state.experience), max_chars=1800
        ),
        "projects": _join_unique(_flatten_values(resume_state.projects), max_chars=1200),
    }

    parts = [
        f"{FIELD_LABELS[field]}: {text}"
        for field, text in field_texts.items()
        if text
    ]
    return ResumeRetrievalQuery(text="\n".join(parts), field_texts=field_texts)


def _flatten_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float, bool)):
        return [str(value)]
    if isinstance(value, list):
        flattened: list[str] = []
        for item in value:
            flattened.extend(_flatten_values(item))
        return flattened
    if isinstance(value, dict):
        flattened = []
        seen_keys = set()
        for key in DICT_VALUE_ORDER:
            if key in value:
                flattened.extend(_flatten_values(value[key]))
                seen_keys.add(key)
        for key, item in value.items():
            if key not in seen_keys:
                flattened.extend(_flatten_values(item))
        return flattened
    return [str(value)]


def _join_unique(values: list[Any], *, max_chars: int) -> str:
    fragments: list[str] = []
    seen: set[str] = set()
    total = 0

    for value in values:
        text = _clean_text(str(value))
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        next_total = total + len(text) + (2 if fragments else 0)
        if next_total > max_chars:
            break
        seen.add(key)
        fragments.append(text)
        total = next_total

    return "; ".join(fragments)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
