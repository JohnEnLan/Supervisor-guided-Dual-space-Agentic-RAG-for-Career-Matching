from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.pool import close_pool
from app.evaluation.metrics import (
    build_metric_table,
    compare_latent_space_runs,
    compare_retrieval_runs,
    evaluate_explanation_faithfulness,
    evaluate_hard_filter_accuracy,
    evaluate_rankings,
    format_metric_table_markdown,
)
from app.retrieval.hybrid_search import JobCandidate, hybrid_search


def load_eval_inputs(
    queries_path: Path, labels_path: Path, *, limit: int | None = None
) -> list[dict[str, Any]]:
    queries = {row["case_id"]: row for row in _load_jsonl(queries_path)}
    labels = {row["case_id"]: row for row in _load_jsonl(labels_path)}
    missing_labels = sorted(set(queries) - set(labels))
    missing_queries = sorted(set(labels) - set(queries))
    if missing_labels or missing_queries:
        raise ValueError(
            "Eval case_id mismatch: "
            f"missing_labels={missing_labels}, missing_queries={missing_queries}"
        )

    rows = []
    for case_id in sorted(queries):
        merged = dict(queries[case_id])
        merged.update(labels[case_id])
        rows.append(merged)
    return rows[:limit] if limit else rows


def build_offline_report(
    rows: list[dict[str, Any]],
    rankings: dict[str, dict[str, list[str]]],
    *,
    k: int,
) -> dict[str, object]:
    labels = _labels_from_rows(rows)
    baseline = rankings.get("baseline", {})
    with_raptor = rankings.get("with_raptor", baseline)
    with_latent = rankings.get("with_latent", baseline)
    case_notes = {
        row["case_id"]: row.get("qualitative_latent_expectation", "")
        for row in rows
        if row.get("qualitative_latent_expectation")
    }

    return {
        "retrieval": evaluate_rankings(labels, baseline, k=k),
        "raptor_ablation": compare_retrieval_runs(
            labels, baseline, with_raptor, k=k
        ),
        "latent_space_comparison": compare_latent_space_runs(
            labels,
            baseline,
            with_latent,
            k=k,
            case_notes=case_notes,
        ),
        "hard_filter_accuracy": evaluate_hard_filter_accuracy(rows, {}),
        "explanation_faithfulness": evaluate_explanation_faithfulness([]),
    }


def build_offline_metric_table(
    rows: list[dict[str, Any]],
    rankings: dict[str, dict[str, list[str]]],
    *,
    k_values: list[int],
) -> list[dict[str, float | int | str]]:
    return build_metric_table(_labels_from_rows(rows), rankings, k_values=k_values)


def format_report_table(rows: list[dict[str, float | int | str]]) -> str:
    return format_metric_table_markdown(rows)


def load_offline_rankings(path: Path) -> dict[str, dict[str, list[str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("offline rankings must be a JSON object")
    if "metadata" in payload or "rankings" in payload:
        rankings = payload.get("rankings")
        if not isinstance(rankings, dict):
            raise ValueError("wrapped ranking artifact requires a rankings object")
        return rankings
    return payload


async def build_live_report(
    rows: list[dict[str, Any]],
    *,
    k: int,
    include_latent_hint: bool,
) -> dict[str, object]:
    labels = _labels_from_rows(rows)
    baseline_rankings, baseline_candidates = await _run_retrieval(
        rows, k=k, include_raptor=False, include_latent_hint=False
    )
    raptor_rankings, _raptor_candidates = await _run_retrieval(
        rows, k=k, include_raptor=True, include_latent_hint=False
    )
    latent_rankings, _latent_candidates = await _run_retrieval(
        rows, k=k, include_raptor=True, include_latent_hint=include_latent_hint
    )

    explanation_rows = [
        {
            "case_id": case_id,
            "available_evidence_span_ids": [
                evidence_id
                for candidate in candidates
                for evidence_id in candidate.evidence_span_ids
            ],
            "recommended_roles": [
                {
                    "job_id": candidate.job_id,
                    "match_explanation": "Retrieved evidence supports this candidate.",
                    "evidence_span_ids": candidate.evidence_span_ids,
                }
                for candidate in candidates
            ],
        }
        for case_id, candidates in baseline_candidates.items()
    ]
    candidate_metadata = {
        case_id: [_candidate_metadata(candidate) for candidate in candidates]
        for case_id, candidates in baseline_candidates.items()
    }

    case_notes = {
        row["case_id"]: row.get("qualitative_latent_expectation", "")
        for row in rows
        if row.get("qualitative_latent_expectation")
    }
    return {
        "retrieval": evaluate_rankings(labels, baseline_rankings, k=k),
        "raptor_ablation": compare_retrieval_runs(
            labels, baseline_rankings, raptor_rankings, k=k
        ),
        "latent_space_comparison": compare_latent_space_runs(
            labels,
            baseline_rankings,
            latent_rankings,
            k=k,
            case_notes=case_notes,
        ),
        "hard_filter_accuracy": evaluate_hard_filter_accuracy(rows, candidate_metadata),
        "explanation_faithfulness": evaluate_explanation_faithfulness(
            explanation_rows
        ),
        "rankings": {
            "baseline": baseline_rankings,
            "with_raptor": raptor_rankings,
            "with_latent": latent_rankings,
        },
    }


async def _run_retrieval(
    rows: list[dict[str, Any]],
    *,
    k: int,
    include_raptor: bool,
    include_latent_hint: bool,
) -> tuple[dict[str, list[str]], dict[str, list[JobCandidate]]]:
    rankings: dict[str, list[str]] = {}
    candidates_by_case: dict[str, list[JobCandidate]] = {}
    for row in rows:
        query = _query_for_row(row, include_latent_hint=include_latent_hint)
        candidates = await hybrid_search(
            query=query,
            hard_constraints=row.get("hard_constraints") or {},
            soft_prefs=row.get("soft_preferences") or {},
            top_k=k,
            include_raptor=include_raptor,
        )
        case_id = str(row["case_id"])
        rankings[case_id] = [candidate.job_id for candidate in candidates]
        candidates_by_case[case_id] = candidates
    return rankings, candidates_by_case


def _query_for_row(row: dict[str, Any], *, include_latent_hint: bool) -> str:
    query = str(row["query"])
    if include_latent_hint:
        latent = row.get("latent_profile") or {}
        hint = " ".join(str(value) for value in latent.values() if value)
        if hint:
            query = f"{query}\nLatent career profile: {hint}"
    return query


def _candidate_metadata(candidate: JobCandidate) -> dict[str, Any]:
    return {
        "job_id": candidate.job_id,
        "title": candidate.title,
        "company": candidate.company,
        "location": candidate.location,
    }


def _labels_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": row["case_id"],
            "relevant_job_ids": row["relevant_job_ids"],
        }
        for row in rows
    ]


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


async def _main_async(args: argparse.Namespace) -> None:
    try:
        rows = load_eval_inputs(
            args.resume_queries,
            args.relevance_labels,
            limit=args.limit_cases,
        )
        if args.rankings:
            rankings = load_offline_rankings(args.rankings)
            if args.format == "table":
                table = build_offline_metric_table(
                    rows,
                    rankings,
                    k_values=args.table_k,
                )
                print(format_report_table(table))
                return
            report = build_offline_report(rows, rankings, k=args.top_k)
        else:
            report = await build_live_report(
                rows,
                k=args.top_k,
                include_latent_hint=not args.no_latent_hint,
            )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase F evaluation for retrieval, RAPTOR, and latent memory."
    )
    parser.add_argument(
        "--resume-queries",
        type=Path,
        default=Path("data/eval/resume_queries.jsonl"),
    )
    parser.add_argument(
        "--relevance-labels",
        type=Path,
        default=Path("data/eval/relevance_labels.jsonl"),
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--table-k",
        type=int,
        nargs="+",
        default=[1, 3, 5],
        help="K values to include when --format table is used.",
    )
    parser.add_argument("--limit-cases", type=int)
    parser.add_argument(
        "--rankings",
        type=Path,
        help="Optional offline JSON with baseline/with_raptor/with_latent rankings.",
    )
    parser.add_argument(
        "--no-latent-hint",
        action="store_true",
        help="Do not append latent_profile text in the with_latent run.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="json",
        help="Output full JSON report or a Markdown metric table.",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
