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


def test_build_offline_metric_table_can_be_rendered_as_markdown():
    from scripts.evaluate_system import build_offline_metric_table, format_report_table

    rows = [
        {"case_id": "eval-1", "query": "analyst", "relevant_job_ids": ["job-1"]},
        {"case_id": "eval-2", "query": "engineer", "relevant_job_ids": ["job-3"]},
    ]
    rankings = {
        "baseline": {
            "eval-1": ["job-2", "job-1"],
            "eval-2": ["job-3", "job-4"],
        },
        "with_latent": {
            "eval-1": ["job-1", "job-2"],
            "eval-2": ["job-3", "job-4"],
        },
    }

    table = build_offline_metric_table(rows, rankings, k_values=[1, 2])
    markdown = format_report_table(table)

    assert table
    for row in table:
        assert 0.0 <= row["precision"] <= 1.0
        assert 0.0 <= row["recall"] <= 1.0
        assert 0.0 <= row["mrr"] <= 1.0
        assert 0.0 <= row["ndcg"] <= 1.0

    assert table[0]["run"] == "baseline"
    assert table[-1]["run"] == "with_latent"
    assert "| run | k | cases | precision | recall | mrr | ndcg |" in markdown
    assert "| with_latent | 1 | 2 | 1.000000 | 1.000000 | 1.000000 | 1.000000 |" in markdown
