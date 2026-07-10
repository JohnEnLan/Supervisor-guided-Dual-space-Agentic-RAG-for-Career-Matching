from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_EVAL_MANIFEST = ROOT / "data/eval/evaluation_manifest.json"

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
    baseline = _select_baseline_rankings(rankings)
    case_notes = {
        row["case_id"]: row.get("qualitative_latent_expectation", "")
        for row in rows
        if row.get("qualitative_latent_expectation")
    }

    report: dict[str, object] = {
        "retrieval": evaluate_rankings(labels, baseline, k=k),
        "raptor_ablation": _not_evaluated(
            "offline artifact does not include with_raptor rankings"
        ),
        "latent_space_comparison": _not_evaluated(
            "offline artifact does not include with_latent rankings"
        ),
        "hard_filter_accuracy": _not_evaluated(
            "offline ranking IDs do not include candidate filter metadata"
        ),
        "explanation_faithfulness": _not_evaluated(
            "offline ranking IDs do not include generated explanations"
        ),
    }
    if "with_raptor" in rankings:
        report["raptor_ablation"] = compare_retrieval_runs(
            labels, baseline, rankings["with_raptor"], k=k
        )
    if "with_latent" in rankings:
        report["latent_space_comparison"] = compare_latent_space_runs(
            labels,
            baseline,
            rankings["with_latent"],
            k=k,
            case_notes=case_notes,
        )
    return report


def build_offline_metric_table(
    rows: list[dict[str, Any]],
    rankings: dict[str, dict[str, list[str]]],
    *,
    k_values: list[int],
) -> list[dict[str, float | int | str]]:
    return build_metric_table(_labels_from_rows(rows), rankings, k_values=k_values)


def format_report_table(rows: list[dict[str, float | int | str]]) -> str:
    return format_metric_table_markdown(rows)


def load_offline_rankings(
    path: Path, *, manifest_path: Path | None = DEFAULT_EVAL_MANIFEST
) -> dict[str, dict[str, list[str]]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("offline rankings must be a JSON object")
    if "metadata" in payload or "rankings" in payload:
        metadata = payload.get("metadata")
        rankings = payload.get("rankings")
        if not isinstance(metadata, dict):
            raise ValueError("wrapped ranking artifact requires a metadata object")
        if not isinstance(rankings, dict):
            raise ValueError("wrapped ranking artifact requires a rankings object")
        if manifest_path is None:
            raise ValueError("wrapped ranking artifact requires a manifest")
        _validate_ranking_artifact(
            artifact_path=path,
            metadata=metadata,
            rankings=rankings,
            manifest_path=manifest_path,
        )
        return rankings
    return payload


def _select_baseline_rankings(
    rankings: dict[str, dict[str, list[str]]],
) -> dict[str, list[str]]:
    for run_name in ("baseline", "offline_lexical_baseline"):
        if run_name in rankings:
            return rankings[run_name]
    if len(rankings) == 1:
        return next(iter(rankings.values()))
    raise ValueError("offline rankings require a baseline run")


def _not_evaluated(reason: str) -> dict[str, str]:
    return {"status": "not_evaluated", "reason": reason}


def _validate_ranking_artifact(
    *,
    artifact_path: Path,
    metadata: dict[str, Any],
    rankings: dict[str, Any],
    manifest_path: Path,
) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("evaluation manifest must be a JSON object")

    required_manifest_fields = {
        "corpus_file",
        "corpus_sha256",
        "corpus_rows",
        "unique_job_ids",
        "query_cases",
        "queries_file",
        "ranking_fixture",
        "ranking_artifact_kind",
        "ranking_method",
        "ranking_run",
        "ranking_top_k",
    }
    missing = sorted(required_manifest_fields - set(manifest))
    if missing:
        raise ValueError(f"evaluation manifest missing fields: {missing}")

    manifest_dir = manifest_path.resolve().parent
    artifact_dir = artifact_path.resolve().parent
    corpus_path = _declared_path(
        manifest["corpus_file"], relative_to=manifest_dir
    )
    queries_path = _declared_path(
        manifest["queries_file"], relative_to=manifest_dir
    )
    expected_artifact_path = _declared_path(
        manifest["ranking_fixture"], relative_to=manifest_dir
    )
    if artifact_path.resolve() != expected_artifact_path.resolve():
        raise ValueError("ranking_fixture does not match the loaded artifact")

    with corpus_path.open(newline="", encoding="utf-8") as handle:
        corpus_rows = list(csv.DictReader(handle))
    corpus_job_ids = [str(row.get("job_id") or "").strip() for row in corpus_rows]
    current_corpus_sha256 = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    query_rows = _load_jsonl(queries_path)
    query_ids = [str(row.get("case_id") or "").strip() for row in query_rows]

    _require_equal(
        "corpus_sha256", current_corpus_sha256, manifest["corpus_sha256"]
    )
    _require_equal("corpus_rows", len(corpus_rows), manifest["corpus_rows"])
    _require_equal(
        "unique_job_ids", len(set(corpus_job_ids)), manifest["unique_job_ids"]
    )
    _require_equal("query_cases", len(query_rows), manifest["query_cases"])

    metadata_expectations = {
        "artifact_kind": manifest["ranking_artifact_kind"],
        "corpus_sha256": manifest["corpus_sha256"],
        "corpus_row_count": manifest["corpus_rows"],
        "query_count": manifest["query_cases"],
        "method": manifest["ranking_method"],
        "top_k": manifest["ranking_top_k"],
    }
    for field, expected in metadata_expectations.items():
        _require_equal(field, metadata.get(field), expected)

    if _declared_path(
        metadata.get("corpus_path", ""), relative_to=artifact_dir
    ) != corpus_path.resolve():
        raise ValueError("corpus_path does not match the evaluation manifest")
    if _declared_path(
        metadata.get("query_path", ""), relative_to=artifact_dir
    ) != queries_path.resolve():
        raise ValueError("query_path does not match the evaluation manifest")

    run_name = str(manifest["ranking_run"])
    if run_name not in rankings:
        raise ValueError(f"ranking_run {run_name!r} is missing from the artifact")
    if not all(corpus_job_ids) or len(corpus_job_ids) != len(set(corpus_job_ids)):
        raise ValueError("current corpus job_id values must be non-empty and unique")
    if not all(query_ids) or len(query_ids) != len(set(query_ids)):
        raise ValueError("current query case_id values must be non-empty and unique")

    expected_case_ids = set(query_ids)
    corpus_id_set = set(corpus_job_ids)
    expected_ranking_length = min(int(manifest["ranking_top_k"]), len(corpus_rows))
    for artifact_run, case_rankings in rankings.items():
        if not isinstance(case_rankings, dict):
            raise ValueError(f"ranking run {artifact_run!r} must be an object")
        if set(case_rankings) != expected_case_ids:
            raise ValueError(
                f"ranking run {artifact_run!r} case IDs do not match current queries"
            )
        for case_id, job_ids in case_rankings.items():
            if not isinstance(job_ids, list):
                raise ValueError(f"ranking {case_id!r} must be a list")
            if len(job_ids) != expected_ranking_length:
                raise ValueError(
                    f"ranking {case_id!r} length does not match ranking_top_k"
                )
            normalized_ids = [str(job_id) for job_id in job_ids]
            if len(normalized_ids) != len(set(normalized_ids)):
                raise ValueError(f"ranking {case_id!r} contains duplicate job IDs")
            if not set(normalized_ids) <= corpus_id_set:
                raise ValueError(f"ranking {case_id!r} contains jobs outside the corpus")


def _declared_path(value: object, *, relative_to: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path.resolve()
    local_path = (relative_to / path).resolve()
    if local_path.exists():
        return local_path
    return (ROOT / path).resolve()


def _require_equal(field: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise ValueError(
            f"{field} mismatch: artifact/current={actual!r}, manifest={expected!r}"
        )


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
            rankings = load_offline_rankings(
                args.rankings,
                manifest_path=args.manifest,
            )
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
        "--manifest",
        type=Path,
        default=DEFAULT_EVAL_MANIFEST,
        help="Manifest used to validate wrapped offline ranking artifacts.",
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
