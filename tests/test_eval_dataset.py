import csv
import json
from pathlib import Path


def test_phase_a_relevance_labels_are_small_and_point_to_sample_jobs():
    dataset_path = Path("data/eval/relevance_labels.jsonl")
    jobs_path = Path("data/jobs/linkedin_postings_50.csv")

    rows = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with jobs_path.open(newline="", encoding="utf-8") as handle:
        sample_job_ids = {row["job_id"] for row in csv.DictReader(handle)}

    assert 10 <= len(rows) <= 20
    assert len({row["case_id"] for row in rows}) == len(rows)

    for row in rows:
        assert row["case_id"].startswith("eval-")
        assert row["query"].strip()
        assert row["relevant_job_ids"]
        assert set(row["relevant_job_ids"]) <= sample_job_ids
        assert row["expected_intent"].strip()


def test_resume_queries_align_with_relevance_labels_and_have_eval_contract():
    queries_path = Path("data/eval/resume_queries.jsonl")
    labels_path = Path("data/eval/relevance_labels.jsonl")

    queries = [
        json.loads(line)
        for line in queries_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    labels = [
        json.loads(line)
        for line in labels_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert {row["case_id"] for row in queries} == {row["case_id"] for row in labels}
    for row in queries:
        assert row["query"].strip()
        assert row["resume_state"]["normalized_base_resume"].strip()
        assert isinstance(row["resume_state"]["skills"], list)
        assert isinstance(row["hard_constraints"], dict)
        assert isinstance(row["soft_preferences"], dict)
        assert row["latent_profile"]["background_type"].strip()
        assert row["qualitative_latent_expectation"].strip()
