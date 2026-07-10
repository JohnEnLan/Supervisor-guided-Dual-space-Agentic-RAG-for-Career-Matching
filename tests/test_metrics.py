from app.evaluation.metrics import (
    build_metric_table,
    compare_latent_space_runs,
    compare_retrieval_runs,
    evaluate_explanation_faithfulness,
    evaluate_hard_filter_accuracy,
    evaluate_rankings,
    format_metric_table_markdown,
)


def test_evaluate_rankings_computes_top_k_metrics():
    labels = [
        {"case_id": "eval-1", "relevant_job_ids": ["a", "b"]},
        {"case_id": "eval-2", "relevant_job_ids": ["d"]},
    ]
    rankings = {
        "eval-1": ["x", "a", "b"],
        "eval-2": ["d", "z"],
    }

    metrics = evaluate_rankings(labels, rankings, k=2)

    assert metrics["cases"] == 2
    assert metrics["precision@2"] == 0.5
    assert metrics["recall@2"] == 0.75
    assert metrics["mrr@2"] == 0.75
    assert 0.0 < metrics["ndcg@2"] <= 1.0


def test_evaluate_rankings_deduplicates_predictions_before_k():
    labels = [{"case_id": "eval-1", "relevant_job_ids": ["a"]}]
    rankings = {"eval-1": ["a", "a"]}

    metrics = evaluate_rankings(labels, rankings, k=2)

    assert metrics == {
        "cases": 1,
        "precision@2": 0.5,
        "recall@2": 1.0,
        "mrr@2": 1.0,
        "ndcg@2": 1.0,
    }


def test_compare_retrieval_runs_reports_no_raptor_vs_with_raptor_delta():
    labels = [
        {"case_id": "eval-1", "relevant_job_ids": ["a"]},
        {"case_id": "eval-2", "relevant_job_ids": ["d"]},
    ]
    no_raptor = {
        "eval-1": ["x", "a"],
        "eval-2": ["z", "y"],
    }
    with_raptor = {
        "eval-1": ["a", "x"],
        "eval-2": ["d", "z"],
    }

    comparison = compare_retrieval_runs(labels, no_raptor, with_raptor, k=2)

    assert comparison["k"] == 2
    assert comparison["with_raptor"]["recall@2"] > comparison["no_raptor"]["recall@2"]
    assert comparison["delta"]["mrr@2"] > 0


def test_evaluate_hard_filter_accuracy_checks_candidate_metadata():
    cases = [
        {
            "case_id": "eval-1",
            "hard_constraints": {"locations": ["London"], "max_years_exp": 2},
        },
        {
            "case_id": "eval-2",
            "hard_constraints": {"need_visa_sponsor": True},
        },
    ]
    candidates = {
        "eval-1": [
            {"job_id": "a", "location": "London", "min_years_exp": 1},
            {"job_id": "b", "location": "Paris", "min_years_exp": 1},
        ],
        "eval-2": [
            {"job_id": "c", "visa_sponsor": True},
            {"job_id": "d", "visa_sponsor": False},
        ],
    }

    metrics = evaluate_hard_filter_accuracy(cases, candidates)

    assert metrics == {
        "checked_candidates": 4,
        "hard_filter_passed": 2,
        "hard_filter_accuracy": 0.5,
    }


def test_evaluate_explanation_faithfulness_requires_known_evidence_ids():
    rows = [
        {
            "case_id": "eval-1",
            "available_evidence_span_ids": ["job-1:skills:1", "job-1:resp:2"],
            "recommended_roles": [
                {
                    "job_id": "job-1",
                    "match_explanation": "Python skills match.",
                    "evidence_span_ids": ["job-1:skills:1"],
                }
            ],
        },
        {
            "case_id": "eval-2",
            "available_evidence_span_ids": ["job-2:skills:1"],
            "recommended_roles": [
                {
                    "job_id": "job-2",
                    "match_explanation": "Unsupported claim.",
                    "evidence_span_ids": ["missing"],
                }
            ],
        },
    ]

    metrics = evaluate_explanation_faithfulness(rows)

    assert metrics == {
        "checked_explanations": 2,
        "faithful_explanations": 1,
        "explanation_faithfulness": 0.5,
    }


def test_compare_latent_space_runs_reports_metric_delta_and_qualitative_counts():
    labels = [
        {"case_id": "eval-1", "relevant_job_ids": ["a"]},
        {"case_id": "eval-2", "relevant_job_ids": ["d"]},
        {"case_id": "eval-3", "relevant_job_ids": ["g"]},
    ]
    no_latent = {
        "eval-1": ["x", "a"],
        "eval-2": ["d", "z"],
        "eval-3": ["g", "h"],
    }
    with_latent = {
        "eval-1": ["a", "x"],
        "eval-2": ["z", "d"],
        "eval-3": ["g", "h"],
    }

    comparison = compare_latent_space_runs(
        labels,
        no_latent,
        with_latent,
        k=2,
        case_notes={
            "eval-1": "Latent memory promoted analyst trajectory.",
            "eval-2": "Latent preference over-weighted adjacent role.",
        },
    )

    assert comparison["k"] == 2
    assert comparison["qualitative_counts"] == {
        "improved": 1,
        "regressed": 1,
        "unchanged": 1,
    }
    assert comparison["case_notes"]["eval-1"].startswith("Latent memory")


def test_latent_qualitative_rank_comparison_ignores_duplicate_ids():
    labels = [{"case_id": "eval-1", "relevant_job_ids": ["a"]}]
    no_latent = {"eval-1": ["x", "x", "a"]}
    with_latent = {"eval-1": ["x", "a"]}

    comparison = compare_latent_space_runs(
        labels,
        no_latent,
        with_latent,
        k=3,
    )

    assert comparison["no_latent"]["mrr@3"] == 0.5
    assert comparison["with_latent"]["mrr@3"] == 0.5
    assert comparison["qualitative_counts"] == {
        "improved": 0,
        "regressed": 0,
        "unchanged": 1,
    }


def test_build_metric_table_reports_multiple_runs_and_k_values():
    labels = [
        {"case_id": "eval-1", "relevant_job_ids": ["a"]},
        {"case_id": "eval-2", "relevant_job_ids": ["d"]},
    ]
    rankings_by_run = {
        "baseline": {
            "eval-1": ["x", "a"],
            "eval-2": ["d", "z"],
        },
        "with_latent": {
            "eval-1": ["a", "x"],
            "eval-2": ["d", "z"],
        },
    }

    table = build_metric_table(labels, rankings_by_run, k_values=[1, 2])

    assert table == [
        {
            "run": "baseline",
            "k": 1,
            "cases": 2,
            "precision": 0.5,
            "recall": 0.5,
            "mrr": 0.5,
            "ndcg": 0.5,
        },
        {
            "run": "baseline",
            "k": 2,
            "cases": 2,
            "precision": 0.5,
            "recall": 1.0,
            "mrr": 0.75,
            "ndcg": 0.815465,
        },
        {
            "run": "with_latent",
            "k": 1,
            "cases": 2,
            "precision": 1.0,
            "recall": 1.0,
            "mrr": 1.0,
            "ndcg": 1.0,
        },
        {
            "run": "with_latent",
            "k": 2,
            "cases": 2,
            "precision": 0.5,
            "recall": 1.0,
            "mrr": 1.0,
            "ndcg": 1.0,
        },
    ]

    markdown = format_metric_table_markdown(table)

    assert "| run | k | cases | precision | recall | mrr | ndcg |" in markdown
    assert "| with_latent | 1 | 2 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |" in markdown
