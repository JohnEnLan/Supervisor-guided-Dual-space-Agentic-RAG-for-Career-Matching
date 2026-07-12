from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.db.pool import get_pool
from app.llm.qwen_embed import embed_one


PII_PATTERNS = [
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\+?\d[\s().-]*){8,}\b"),
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\b(linkedin|github)\.com/\S+", re.IGNORECASE),
]
CASE_PREFERENCE_KEYS = frozenset({"case_target_roles", "case_bridge_roles"})
# Learned case hints are a small ranking signal, not an unbounded user profile.
CASE_PREFERENCE_MAX_ITEMS = 10


class CareerCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    background_type: str
    target_role: str
    successful_resume_features: list[str] = Field(default_factory=list)
    missing_skills_before: list[str] = Field(default_factory=list)
    application_outcome: str
    recommended_bridge_roles: list[str] = Field(default_factory=list)

    def validate_anonymous(self) -> "CareerCase":
        payload = self.model_dump(mode="json")
        for key, value in payload.items():
            if contains_pii(value):
                raise ValueError(f"career case field {key!r} contains PII")
        return self


def contains_pii(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(contains_pii(item) for item in value)
    if isinstance(value, dict):
        return any(contains_pii(item) for item in value.values())
    text = str(value)
    return any(pattern.search(text) for pattern in PII_PATTERNS)


def build_case_embedding_text(case: CareerCase) -> str:
    case.validate_anonymous()
    return "\n".join(
        [
            f"Background type: {case.background_type}",
            f"Target role: {case.target_role}",
            "Successful resume features: "
            + "; ".join(case.successful_resume_features),
            "Missing skills before: " + "; ".join(case.missing_skills_before),
            f"Application outcome: {case.application_outcome}",
            "Recommended bridge roles: " + "; ".join(case.recommended_bridge_roles),
        ]
    )


def merge_case_soft_preferences(
    base_soft_prefs: dict[str, Any],
    case_updates: dict[str, list[str]],
) -> dict[str, Any]:
    merged = {
        key: list(value) if isinstance(value, list) else value
        for key, value in base_soft_prefs.items()
    }
    for key in CASE_PREFERENCE_KEYS:
        existing = merged.get(key)
        if isinstance(existing, list):
            merged[key] = _deduplicated_text(existing)[:CASE_PREFERENCE_MAX_ITEMS]

    for key, values in case_updates.items():
        if key not in CASE_PREFERENCE_KEYS or not isinstance(values, list):
            continue
        existing = merged.get(key)
        merged[key] = list(existing) if isinstance(existing, list) else []
        for value in values:
            text = str(value).strip() if value is not None else ""
            if text and text not in merged[key]:
                merged[key].append(text)
            if len(merged[key]) >= CASE_PREFERENCE_MAX_ITEMS:
                break
    return merged


def normalize_case_soft_preferences(preferences: dict[str, Any]) -> dict[str, list[str]]:
    return {
        key: _deduplicated_text(values)[:CASE_PREFERENCE_MAX_ITEMS]
        for key, values in preferences.items()
        if key in CASE_PREFERENCE_KEYS and isinstance(values, list)
    }


def _deduplicated_text(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text and text not in normalized:
            normalized.append(text)
    return normalized


async def upsert_career_case(
    case: CareerCase,
    *,
    embedding: list[float] | None = None,
    embed_if_missing: bool = True,
) -> None:
    case.validate_anonymous()
    if embedding is None and embed_if_missing:
        embedding = await embed_one(build_case_embedding_text(case))
    if embedding is not None and len(embedding) != settings.embed_dim:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(embedding)}, "
            f"expected {settings.embed_dim}"
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO career_cases (
                case_id, background_type, target_role, successful_resume_features,
                missing_skills_before, application_outcome, recommended_bridge_roles,
                embedding
            )
            VALUES ($1, $2, $3, $4::text[], $5::text[], $6, $7::text[], $8::vector)
            ON CONFLICT (case_id) DO UPDATE SET
                background_type = EXCLUDED.background_type,
                target_role = EXCLUDED.target_role,
                successful_resume_features = EXCLUDED.successful_resume_features,
                missing_skills_before = EXCLUDED.missing_skills_before,
                application_outcome = EXCLUDED.application_outcome,
                recommended_bridge_roles = EXCLUDED.recommended_bridge_roles,
                embedding = EXCLUDED.embedding
            """,
            case.case_id,
            case.background_type,
            case.target_role,
            case.successful_resume_features,
            case.missing_skills_before,
            case.application_outcome,
            case.recommended_bridge_roles,
            _to_vector_literal(embedding) if embedding is not None else None,
        )


async def search_similar_cases(query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    query_embedding = await embed_one(query)
    if len(query_embedding) != settings.embed_dim:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(query_embedding)}, "
            f"expected {settings.embed_dim}"
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                case_id,
                background_type,
                target_role,
                successful_resume_features,
                missing_skills_before,
                application_outcome,
                recommended_bridge_roles,
                1 - (embedding <=> $1::vector) AS score
            FROM career_cases
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            _to_vector_literal(query_embedding),
            top_k,
        )
    return [_case_row_to_dict(row) for row in rows]


async def search_similar_resume_cases_by_embedding(
    query_embedding: list[float], *, top_k: int = 20
) -> list[dict[str, Any]]:
    if len(query_embedding) != settings.embed_dim:
        raise ValueError(
            f"Embedding dimension mismatch: got {len(query_embedding)}, "
            f"expected {settings.embed_dim}"
        )
    if top_k <= 0:
        return []

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.case_id,
                c.resume_payload,
                1 - (c.embedding <=> $1::vector) AS similarity,
                o.outcome_id,
                o.job_id,
                o.company,
                o.role_family,
                o.explicit_match_score,
                o.highest_stage,
                o.final_status,
                o.source_confidence
            FROM anonymous_resume_cases AS c
            JOIN case_job_outcomes AS o ON o.case_id = c.case_id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            _to_vector_literal(query_embedding),
            top_k,
        )
    return [_anonymous_case_row_to_dict(row) for row in rows]


async def list_career_cases(*, limit: int = 20) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT case_id, background_type, target_role, successful_resume_features,
                   missing_skills_before, application_outcome, recommended_bridge_roles
            FROM career_cases
            ORDER BY case_id
            LIMIT $1
            """,
            limit,
        )
    return [_case_row_to_dict(row) for row in rows]


def _case_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "background_type": row["background_type"],
        "target_role": row["target_role"],
        "successful_resume_features": list(row["successful_resume_features"] or []),
        "missing_skills_before": list(row["missing_skills_before"] or []),
        "application_outcome": row["application_outcome"],
        "recommended_bridge_roles": list(row["recommended_bridge_roles"] or []),
        "score": float(row["score"]) if "score" in row else None,
    }


def _anonymous_case_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "case_id": str(row["case_id"]),
        "resume_payload": row["resume_payload"],
        "similarity": float(row["similarity"]),
        "outcome_id": str(row["outcome_id"]),
        "job_id": str(row["job_id"]) if row["job_id"] is not None else None,
        "company": str(row["company"]),
        "role_family": str(row["role_family"]),
        "explicit_match_score": float(row["explicit_match_score"]),
        "highest_stage": str(row["highest_stage"]),
        "final_status": str(row["final_status"]),
        "source_confidence": float(row["source_confidence"]),
    }


def _to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in values) + "]"
