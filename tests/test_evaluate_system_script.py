import json
from pathlib import Path


def test_load_eval_inputs_joins_queries_and_labels(tmp_path):
    from scripts.evaluate_system import load_eval_inputs

    queries_path = tmp_path / "resume_queries.jsonl"
    labels_path = tmp_path / "relevance_labels.jsonl"
    queries_path.write_text(
        json.dumps(
            {
                "case_id": "eval-1",
                "query": "analyst",
                "hard_constraints": {"locations": ["London"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    labels_path.write_text(
        json.dumps({"case_id": "eval-1", "relevant_job_ids": ["job-1"]}) + "\n",
        encoding="utf-8",
    )

    rows = load_eval_inputs(queries_path, labels_path)

    assert rows == [
        {
            "case_id": "eval-1",
            "query": "analyst",
            "hard_constraints": {"locations": ["London"]},
            "relevant_job_ids": ["job-1"],
        }
    ]


def test_build_offline_report_includes_required_phase_f_sections():
    from scripts.evaluate_system import build_offline_report

    rows = [
        {
            "case_id": "eval-1",
            "query": "analyst",
            "relevant_job_ids": ["job-1"],
            "hard_constraints": {"locations": ["London"]},
            "qualitative_latent_expectation": "Memory should prefer analytics roles.",
        }
    ]
    rankings = {
        "baseline": {"eval-1": ["job-2", "job-1"]},
        "with_raptor": {"eval-1": ["job-1", "job-2"]},
        "with_latent": {"eval-1": ["job-1", "job-2"]},
    }

    report = build_offline_report(rows, rankings, k=2)

    assert set(report) == {
        "retrieval",
        "raptor_ablation",
        "latent_space_comparison",
        "hard_filter_accuracy",
        "explanation_faithfulness",
    }
    assert report["raptor_ablation"]["delta"]["mrr@2"] > 0
