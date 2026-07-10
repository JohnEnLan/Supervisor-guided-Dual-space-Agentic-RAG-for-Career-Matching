import json
import subprocess
import sys
from pathlib import Path

import pytest


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


def test_load_offline_rankings_accepts_plain_legacy_and_rejects_unbound_wrapped(
    tmp_path,
):
    from scripts.evaluate_system import load_offline_rankings

    rankings = {"offline_lexical_baseline": {"eval-1": ["job-1"]}}
    wrapped_path = tmp_path / "wrapped.json"
    plain_path = tmp_path / "plain.json"
    wrapped_path.write_text(
        json.dumps({"metadata": {"method": "lexical"}, "rankings": rankings}),
        encoding="utf-8",
    )
    plain_path.write_text(json.dumps(rankings), encoding="utf-8")

    with pytest.raises(ValueError, match="ranking_fixture"):
        load_offline_rankings(wrapped_path)
    assert load_offline_rankings(plain_path) == rankings


def test_committed_offline_artifact_json_report_uses_its_single_run():
    result = subprocess.run(
        [
            sys.executable,
            "scripts/evaluate_system.py",
            "--rankings",
            "data/eval/offline_lexical_rankings_1000.json",
            "--top-k",
            "5",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    report = json.loads(result.stdout)

    assert report["retrieval"]["precision@5"] == pytest.approx(0.4)
    assert report["retrieval"]["recall@5"] == pytest.approx(0.250001, abs=1e-6)
    assert report["retrieval"]["mrr@5"] == pytest.approx(0.7)
    assert report["retrieval"]["ndcg@5"] == pytest.approx(0.447162, abs=1e-6)
    assert report["raptor_ablation"]["status"] == "not_evaluated"
    assert report["latent_space_comparison"]["status"] == "not_evaluated"
    assert report["hard_filter_accuracy"]["status"] == "not_evaluated"
    assert report["explanation_faithfulness"]["status"] == "not_evaluated"


@pytest.mark.parametrize(
    ("metadata_field", "invalid_value"),
    [
        ("corpus_sha256", "0" * 64),
        ("corpus_row_count", 999),
        ("query_count", 14),
        ("method", "different_method"),
    ],
)
def test_load_offline_rankings_rejects_manifest_binding_mismatch(
    tmp_path, metadata_field, invalid_value
):
    from scripts.evaluate_system import load_offline_rankings
    from scripts.generate_lexical_rankings import (
        METHOD,
        RUN_NAME,
        generate_lexical_ranking_artifact,
    )

    corpus_path = tmp_path / "jobs.csv"
    queries_path = tmp_path / "queries.jsonl"
    rankings_path = tmp_path / "rankings.json"
    manifest_path = tmp_path / "manifest.json"
    corpus_path.write_text(
        "job_id,title,skills_desc,description\njob-1,Data Analyst,SQL,data analysis\n",
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps({"case_id": "eval-1", "query": "data analyst"}) + "\n",
        encoding="utf-8",
    )
    artifact = generate_lexical_ranking_artifact(
        corpus_path=corpus_path,
        queries_path=queries_path,
        top_k=1,
    )
    artifact["metadata"][metadata_field] = invalid_value
    rankings_path.write_text(json.dumps(artifact), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "corpus_file": str(corpus_path),
                "corpus_sha256": generate_lexical_ranking_artifact(
                    corpus_path=corpus_path,
                    queries_path=queries_path,
                    top_k=1,
                )["metadata"]["corpus_sha256"],
                "corpus_rows": 1,
                "unique_job_ids": 1,
                "query_cases": 1,
                "queries_file": str(queries_path),
                "ranking_fixture": str(rankings_path),
                "ranking_artifact_kind": "offline_lexical_baseline",
                "ranking_method": METHOD,
                "ranking_run": RUN_NAME,
                "ranking_top_k": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=metadata_field):
        load_offline_rankings(rankings_path, manifest_path=manifest_path)


def test_load_offline_rankings_resolves_bundle_paths_from_manifest_directory(
    tmp_path,
):
    from scripts.evaluate_system import load_offline_rankings
    from scripts.generate_lexical_rankings import (
        METHOD,
        RUN_NAME,
        generate_lexical_ranking_artifact,
    )

    bundle_path = tmp_path / "portable-eval"
    bundle_path.mkdir()
    corpus_path = bundle_path / "jobs.csv"
    queries_path = bundle_path / "queries.jsonl"
    rankings_path = bundle_path / "rankings.json"
    manifest_path = bundle_path / "manifest.json"
    corpus_path.write_text(
        "job_id,title,skills_desc,description\njob-1,Data Analyst,SQL,data analysis\n",
        encoding="utf-8",
    )
    queries_path.write_text(
        json.dumps({"case_id": "eval-1", "query": "data analyst"}) + "\n",
        encoding="utf-8",
    )
    artifact = generate_lexical_ranking_artifact(
        corpus_path=corpus_path,
        queries_path=queries_path,
        top_k=1,
    )
    artifact["metadata"]["corpus_path"] = "jobs.csv"
    artifact["metadata"]["query_path"] = "queries.jsonl"
    rankings_path.write_text(json.dumps(artifact), encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                "corpus_file": "jobs.csv",
                "corpus_sha256": artifact["metadata"]["corpus_sha256"],
                "corpus_rows": 1,
                "unique_job_ids": 1,
                "query_cases": 1,
                "queries_file": "queries.jsonl",
                "ranking_fixture": "rankings.json",
                "ranking_artifact_kind": "offline_lexical_baseline",
                "ranking_method": METHOD,
                "ranking_run": RUN_NAME,
                "ranking_top_k": 1,
            }
        ),
        encoding="utf-8",
    )

    assert load_offline_rankings(
        rankings_path,
        manifest_path=manifest_path,
    ) == artifact["rankings"]
