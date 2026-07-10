from __future__ import annotations

import math
from typing import Mapping, Sequence


MetricRow = Mapping[str, object]
Rankings = Mapping[str, Sequence[str]]
MetricTableRow = dict[str, float | int | str]


def evaluate_rankings(
    labels: Sequence[MetricRow], rankings: Rankings, *, k: int
) -> dict[str, float | int]:
    if k <= 0:
        raise ValueError("k must be positive")

    precision_values = []
    recall_values = []
    mrr_values = []
    ndcg_values = []

    for label in labels:
        case_id = str(label["case_id"])
        relevant = {str(job_id) for job_id in label["relevant_job_ids"]}
        predicted = _unique_ranked_ids(rankings.get(case_id, []))[:k]

        precision_values.append(_precision_at_k(predicted, relevant, k))
        recall_values.append(_recall_at_k(predicted, relevant))
        mrr_values.append(_mrr_at_k(predicted, relevant))
        ndcg_values.append(_ndcg_at_k(predicted, relevant, k))

    return {
        "cases": len(labels),
        f"precision@{k}": _mean(precision_values),
        f"recall@{k}": _mean(recall_values),
        f"mrr@{k}": _mean(mrr_values),
        f"ndcg@{k}": _mean(ndcg_values),
    }


def compare_retrieval_runs(
    labels: Sequence[MetricRow],
    no_raptor_rankings: Rankings,
    with_raptor_rankings: Rankings,
    *,
    k: int,
) -> dict[str, object]:
    no_raptor = evaluate_rankings(labels, no_raptor_rankings, k=k)
    with_raptor = evaluate_rankings(labels, with_raptor_rankings, k=k)
    delta = {
        key: round(float(with_raptor[key]) - float(no_raptor[key]), 6)
        for key in no_raptor
        if key != "cases"
    }
    return {
        "k": k,
        "no_raptor": no_raptor,
        "with_raptor": with_raptor,
        "delta": delta,
    }


def build_metric_table(
    labels: Sequence[MetricRow],
    rankings_by_run: Mapping[str, Rankings],
    *,
    k_values: Sequence[int],
) -> list[MetricTableRow]:
    table: list[MetricTableRow] = []
    for run_name, rankings in rankings_by_run.items():
        for k in k_values:
            metrics = evaluate_rankings(labels, rankings, k=k)
            table.append(
                {
                    "run": run_name,
                    "k": k,
                    "cases": int(metrics["cases"]),
                    "precision": float(metrics[f"precision@{k}"]),
                    "recall": float(metrics[f"recall@{k}"]),
                    "mrr": float(metrics[f"mrr@{k}"]),
                    "ndcg": float(metrics[f"ndcg@{k}"]),
                }
            )
    return table


def format_metric_table_markdown(rows: Sequence[MetricTableRow]) -> str:
    headers = ["run", "k", "cases", "precision", "recall", "mrr", "ndcg"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_format_table_cell(row.get(header, "")) for header in headers)
            + " |"
        )
    return "\n".join(lines)


def compare_latent_space_runs(
    labels: Sequence[MetricRow],
    no_latent_rankings: Rankings,
    with_latent_rankings: Rankings,
    *,
    k: int,
    case_notes: Mapping[str, str] | None = None,
) -> dict[str, object]:
    no_latent = evaluate_rankings(labels, no_latent_rankings, k=k)
    with_latent = evaluate_rankings(labels, with_latent_rankings, k=k)
    delta = {
        key: round(float(with_latent[key]) - float(no_latent[key]), 6)
        for key in no_latent
        if key != "cases"
    }
    qualitative_counts = {"improved": 0, "regressed": 0, "unchanged": 0}
    for label in labels:
        case_id = str(label["case_id"])
        relevant = {str(job_id) for job_id in label["relevant_job_ids"]}
        before_rank = _first_relevant_rank(no_latent_rankings.get(case_id, []), relevant)
        after_rank = _first_relevant_rank(with_latent_rankings.get(case_id, []), relevant)
        if after_rank < before_rank:
            qualitative_counts["improved"] += 1
        elif after_rank > before_rank:
            qualitative_counts["regressed"] += 1
        else:
            qualitative_counts["unchanged"] += 1

    return {
        "k": k,
        "no_latent": no_latent,
        "with_latent": with_latent,
        "delta": delta,
        "qualitative_counts": qualitative_counts,
        "case_notes": dict(case_notes or {}),
    }


def evaluate_hard_filter_accuracy(
    cases: Sequence[MetricRow], candidates_by_case: Mapping[str, Sequence[Mapping[str, object]]]
) -> dict[str, float | int]:
    checked = 0
    passed = 0
    for case in cases:
        case_id = str(case["case_id"])
        hard_constraints = _as_dict(case.get("hard_constraints"))
        if not hard_constraints:
            continue
        for candidate in candidates_by_case.get(case_id, []):
            checked += 1
            if _candidate_satisfies_hard_constraints(candidate, hard_constraints):
                passed += 1
    return {
        "checked_candidates": checked,
        "hard_filter_passed": passed,
        "hard_filter_accuracy": round(passed / checked, 6) if checked else 1.0,
    }


def evaluate_explanation_faithfulness(
    rows: Sequence[Mapping[str, object]]
) -> dict[str, float | int]:
    checked = 0
    faithful = 0
    for row in rows:
        available = {str(item) for item in row.get("available_evidence_span_ids", [])}
        for role in row.get("recommended_roles", []):
            if not isinstance(role, Mapping):
                continue
            checked += 1
            evidence_ids = {str(item) for item in role.get("evidence_span_ids", [])}
            explanation = str(role.get("match_explanation") or "").strip()
            if explanation and evidence_ids and evidence_ids <= available:
                faithful += 1
    return {
        "checked_explanations": checked,
        "faithful_explanations": faithful,
        "explanation_faithfulness": round(faithful / checked, 6) if checked else 1.0,
    }


def _precision_at_k(predicted: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for job_id in predicted[:k] if job_id in relevant)
    return hits / k


def _unique_ranked_ids(values: Sequence[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def _recall_at_k(predicted: Sequence[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    hits = sum(1 for job_id in predicted if job_id in relevant)
    return hits / len(relevant)


def _mrr_at_k(predicted: Sequence[str], relevant: set[str]) -> float:
    for index, job_id in enumerate(predicted, start=1):
        if job_id in relevant:
            return 1.0 / index
    return 0.0


def _ndcg_at_k(predicted: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    dcg = 0.0
    for index, job_id in enumerate(predicted[:k], start=1):
        if job_id in relevant:
            dcg += 1.0 / math.log2(index + 1)

    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 6)


def _format_table_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _candidate_satisfies_hard_constraints(
    candidate: Mapping[str, object], hard_constraints: Mapping[str, object]
) -> bool:
    locations = {str(item) for item in hard_constraints.get("locations", [])}
    if hard_constraints.get("location"):
        locations.add(str(hard_constraints["location"]))
    if locations and str(candidate.get("location")) not in locations:
        return False

    if hard_constraints.get("need_visa_sponsor") is True:
        if candidate.get("visa_sponsor") is not True:
            return False

    max_years = hard_constraints.get("max_years_exp")
    if max_years is not None:
        candidate_years = candidate.get("min_years_exp")
        if candidate_years is not None and int(candidate_years) > int(max_years):
            return False

    role_clusters = {str(item) for item in hard_constraints.get("role_clusters", [])}
    if hard_constraints.get("role_cluster"):
        role_clusters.add(str(hard_constraints["role_cluster"]))
    if role_clusters and str(candidate.get("role_cluster")) not in role_clusters:
        return False

    degree_required = hard_constraints.get("degree_required")
    if degree_required and str(candidate.get("degree_required")) != str(degree_required):
        return False

    return True


def _first_relevant_rank(predicted: Sequence[str], relevant: set[str]) -> int:
    for index, job_id in enumerate(_unique_ranked_ids(predicted), start=1):
        if str(job_id) in relevant:
            return index
    return 1_000_000


def _as_dict(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
