import csv
import json
from pathlib import Path


def test_relevance_labels_are_bound_to_the_full_linkedin_corpus():
    dataset_path = Path("data/eval/relevance_labels.jsonl")
    jobs_path = Path("data/jobs/linkedin_postings_1000.csv")
    original_sample_path = Path("data/jobs/linkedin_postings_50.csv")
    manifest_path = Path("data/eval/evaluation_manifest.json")

    labels = [
        json.loads(line)
        for line in dataset_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with jobs_path.open(newline="", encoding="utf-8") as handle:
        job_rows = list(csv.DictReader(handle))
    with original_sample_path.open(newline="", encoding="utf-8") as handle:
        original_50_ids = {row["job_id"] for row in csv.DictReader(handle)}

    job_ids = {row["job_id"] for row in job_rows}
    assert len(job_rows) == 1000
    assert len(job_ids) == 1000
    assert len(labels) == 15
    assert len({row["case_id"] for row in labels}) == len(labels)
    assert all(
        row["annotation_scope"] == "linkedin_1000_title_description_review"
        for row in labels
    )
    assert all(set(row["relevant_job_ids"]) <= job_ids for row in labels)
    assert sum(
        bool(set(row["relevant_job_ids"]) - original_50_ids) for row in labels
    ) >= 10

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["corpus_file"] == str(jobs_path).replace("\\", "/")
    assert manifest["corpus_rows"] == len(job_rows)
    assert manifest["unique_job_ids"] == len(job_ids)
    assert manifest["query_cases"] == len(labels)
    assert manifest["labels_file"] == str(dataset_path).replace("\\", "/")

    for row in labels:
        assert row["case_id"].startswith("eval-")
        assert row["query"].strip()
        assert row["relevant_job_ids"]
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
