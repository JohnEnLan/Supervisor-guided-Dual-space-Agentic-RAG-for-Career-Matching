import csv
import hashlib
import json
from pathlib import Path


def _job_ids(path: Path) -> set[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["job_id"] for row in csv.DictReader(handle)}


def test_lexical_ranking_fixture_covers_the_declared_1000_job_universe():
    corpus_path = Path("data/jobs/linkedin_postings_1000.csv")
    old_sample_path = Path("data/jobs/linkedin_postings_50.csv")
    fixture_path = Path("data/eval/offline_lexical_rankings_1000.json")
    artifact = json.loads(fixture_path.read_text(encoding="utf-8"))

    corpus_ids = _job_ids(corpus_path)
    old_sample_ids = _job_ids(old_sample_path)
    metadata = artifact["metadata"]
    rankings = artifact["rankings"]["offline_lexical_baseline"]

    assert metadata == {
        "artifact_kind": "offline_lexical_baseline",
        "label": "Offline lexical baseline (not live hybrid-system performance)",
        "corpus_path": "data/jobs/linkedin_postings_1000.csv",
        "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
        "corpus_row_count": 1000,
        "query_path": "data/eval/resume_queries.jsonl",
        "query_count": 15,
        "method": "deterministic_weighted_token_overlap_v1",
        "top_k": 20,
    }
    assert len(corpus_ids) == 1000
    assert len(rankings) == 15
    assert all(len(job_ids) == 20 for job_ids in rankings.values())
    assert all(set(job_ids) <= corpus_ids for job_ids in rankings.values())
    assert any(
        set(job_ids) - old_sample_ids
        for job_ids in rankings.values()
    )


def test_lexical_ranking_generation_is_deterministic():
    from scripts.generate_lexical_rankings import generate_lexical_ranking_artifact

    kwargs = {
        "corpus_path": Path("data/jobs/linkedin_postings_1000.csv"),
        "queries_path": Path("data/eval/resume_queries.jsonl"),
        "top_k": 20,
    }
    first = generate_lexical_ranking_artifact(**kwargs)
    second = generate_lexical_ranking_artifact(**kwargs)

    assert first == second
    assert first["metadata"]["corpus_row_count"] == 1000
    assert first["metadata"]["query_count"] == 15


def test_lexical_ranking_script_has_no_live_retrieval_dependencies():
    script = Path("scripts/generate_lexical_rankings.py").read_text(encoding="utf-8")

    forbidden = ["hybrid_search", "asyncpg", "qwen", "deepseek", "openai"]
    assert all(name not in script.casefold() for name in forbidden)
