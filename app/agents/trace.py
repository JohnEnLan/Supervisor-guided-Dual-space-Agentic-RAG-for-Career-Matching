from __future__ import annotations

from typing import Any

from app.state.schema import SharedState


def build_public_explain(
    state: SharedState,
    *,
    evaluation_enabled: bool,
    implicit_max_weight: float = 0.30,
    stage_durations_ms: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    """Build an examiner trace from an explicit allow-list of public fields."""
    if not evaluation_enabled:
        return None

    rows = list(state.retrieval_state.ranking_scores)
    explicit_ranks = _score_ranks(rows, "explicit_score")
    implicit_ranks = _score_ranks(rows, "implicit_score")
    rank_trace = []
    for final_rank, row in enumerate(
        rows, start=1
    ):
        evidence = row.get("implicit_evidence") or []
        case_ids = [
            str(item.get("case_id"))
            for item in evidence
            if isinstance(item, dict) and item.get("case_id")
        ]
        case_evidence = [
            {
                "case_id": str(item["case_id"]),
                "highest_stage": str(item.get("highest_stage") or "unknown"),
                "confidence": _optional_float(
                    item.get("confidence", item.get("source_confidence"))
                ),
            }
            for item in evidence
            if isinstance(item, dict) and item.get("case_id")
        ]
        rank_trace.append(
            {
                "job_id": str(row.get("job_id") or ""),
                "final_rank": final_rank,
                "explicit_rank": _optional_int(row.get("explicit_rank"))
                or explicit_ranks.get(str(row.get("job_id") or "")),
                "implicit_rank": _optional_int(row.get("implicit_rank"))
                or implicit_ranks.get(str(row.get("job_id") or "")),
                "explicit_score": _optional_float(row.get("explicit_score")),
                "implicit_score": _optional_float(row.get("implicit_score")),
                "implicit_confidence": _optional_float(
                    row.get("implicit_confidence")
                ),
                "implicit_weight": round(
                    float(implicit_max_weight)
                    * float(row.get("implicit_confidence") or 0.0),
                    6,
                ),
                "case_ids": case_ids,
                "case_evidence": case_evidence,
            }
        )

    recovery_events = []
    for event in state.supervisor_log:
        if event.get("stage") not in {
            "clarification_loop",
            "reretrieval_loop",
            "repair_loop",
        }:
            continue
        recovery_events.append(
            {
                "stage": str(event["stage"]),
                "reason": str(event.get("reason") or "bounded_recovery"),
                "attempt": int(event.get("loop_used") or 1),
                "max_attempts": int(event.get("max_loops") or 1),
            }
        )

    durations = dict(stage_durations_ms or {})
    if not durations:
        durations = {
            str(event["stage_name"]): int(event["duration_ms"])
            for event in state.supervisor_log
            if event.get("stage") == "public_stage_duration"
            and event.get("stage_name")
            and event.get("duration_ms") is not None
        }

    return {
        "rank_trace": rank_trace,
        "fusion": {"implicit_max_weight": float(implicit_max_weight)},
        "stage_durations_ms": durations,
        "recovery_events": recovery_events,
    }


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _score_ranks(rows: list[dict[str, Any]], score_key: str) -> dict[str, int]:
    scored = [
        (str(row.get("job_id") or ""), float(row.get(score_key) or 0.0))
        for row in rows
        if row.get("job_id") and row.get(score_key) is not None
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return {job_id: rank for rank, (job_id, _score) in enumerate(scored, start=1)}
