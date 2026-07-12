from __future__ import annotations

import pytest

from app.config import settings
from app.retrieval.hybrid_search import JobCandidate
from app.state.schema import ResumeState


def test_implicit_query_text_uses_only_allow_listed_career_fields() -> None:
    from app.retrieval.implicit_search import build_implicit_query_text

    resume = ResumeState(
        education=[
            {
                "school": "University of Birmingham",
                "degree": "MSc",
                "major": "Data Science",
                "student_id": "12345678",
            }
        ],
        experience=[
            {
                "company": "Acme Analytics",
                "title": "Data Analyst Intern",
                "description": "Contact alice@example.com or +44 7700 900123",
            }
        ],
        projects=[
            {
                "name": "Demand Forecasting",
                "technologies": ["Python", "Pandas"],
                "description": "Portfolio https://example.com/alice",
            }
        ],
        skills=["SQL", "Python"],
        normalized_base_resume=(
            "Alice Zhang alice@example.com +44 7700 900123 full private resume"
        ),
        original_evidence_spans=[
            {"evidence_span_id": "resume-1", "text": "Alice Zhang private evidence"}
        ],
    )

    text = build_implicit_query_text(resume)

    assert "University of Birmingham" in text
    assert "Data Analyst Intern" in text
    assert "Acme Analytics" in text
    assert "Demand Forecasting" in text
    assert "Pandas" in text
    assert "SQL" in text
    assert "Alice Zhang" not in text
    assert "alice@example.com" not in text
    assert "7700" not in text
    assert "12345678" not in text
    assert "private evidence" not in text
    assert "https://" not in text


def test_implicit_query_text_is_deterministic_and_deduplicated() -> None:
    from app.retrieval.implicit_search import build_implicit_query_text

    resume = ResumeState(skills=["Python", "Python", " SQL "])

    first = build_implicit_query_text(resume)
    second = build_implicit_query_text(resume)

    assert first == second
    assert first.count("Python") == 1
    assert "SQL" in first


@pytest.mark.asyncio
async def test_case_search_uses_existing_embedding_and_public_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.memory import case_base

    class Connection:
        def __init__(self) -> None:
            self.sql = ""
            self.args: tuple[object, ...] = ()

        async def fetch(self, sql: str, *args: object):
            self.sql = sql
            self.args = args
            return [
                {
                    "case_id": "case-1",
                    "resume_payload": {"skills": ["SQL"]},
                    "similarity": 0.88,
                    "outcome_id": "outcome-1",
                    "job_id": "job-1",
                    "company": "Acme",
                    "role_family": "data",
                    "explicit_match_score": 0.8,
                    "highest_stage": "interview",
                    "final_status": "active",
                    "source_confidence": 1.0,
                }
            ]

    class Acquire:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        async def __aenter__(self) -> Connection:
            return self.connection

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class Pool:
        def __init__(self, connection: Connection) -> None:
            self.connection = connection

        def acquire(self) -> Acquire:
            return Acquire(self.connection)

    connection = Connection()

    async def fake_get_pool() -> Pool:
        return Pool(connection)

    monkeypatch.setattr(case_base, "get_pool", fake_get_pool)
    embedding = [0.01] * settings.embed_dim

    rows = await case_base.search_similar_resume_cases_by_embedding(
        embedding, top_k=3
    )

    assert "FROM anonymous_resume_cases" in connection.sql
    assert "JOIN case_job_outcomes" in connection.sql
    assert connection.args[1] == 3
    assert rows[0]["case_id"] == "case-1"
    assert rows[0]["similarity"] == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_case_search_rejects_embedding_dimension_mismatch() -> None:
    from app.memory.case_base import search_similar_resume_cases_by_embedding

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        await search_similar_resume_cases_by_embedding([0.1], top_k=3)


def test_implicit_score_uses_similarity_stage_and_explicit_relation() -> None:
    from app.retrieval.implicit_search import aggregate_implicit_evidence

    rows = [
        {
            "case_id": "case-1",
            "similarity": 0.9,
            "job_id": "job-1",
            "company": "Acme",
            "role_family": "data",
            "explicit_match_score": 0.8,
            "highest_stage": "offer",
            "final_status": "active",
            "source_confidence": 1.0,
        },
        {
            "case_id": "case-2",
            "similarity": 0.8,
            "job_id": "job-1",
            "company": "Acme",
            "role_family": "data",
            "explicit_match_score": 0.7,
            "highest_stage": "screen_passed",
            "final_status": "active",
            "source_confidence": 1.0,
        },
    ]

    evidence = aggregate_implicit_evidence(rows, candidate_job_id="job-1")

    expected = (0.9 * 0.9 * 0.8 + 0.8 * 0.4 * 0.7) / (0.9 + 0.8)
    assert evidence.score == pytest.approx(expected)
    assert evidence.confidence == pytest.approx(2 / settings.implicit_min_cases)
    assert evidence.effective_case_count == 2
    assert [row["case_id"] for row in evidence.supporting_cases] == [
        "case-1",
        "case-2",
    ]


def test_early_rejection_has_no_positive_implicit_score() -> None:
    from app.retrieval.implicit_search import aggregate_implicit_evidence

    evidence = aggregate_implicit_evidence(
        [
            {
                "case_id": "case-rejected",
                "similarity": 0.95,
                "job_id": "job-1",
                "company": "Acme",
                "role_family": "data",
                "explicit_match_score": 1.0,
                "highest_stage": "screen_passed",
                "final_status": "rejected",
                "source_confidence": 1.0,
            }
        ],
        candidate_job_id="job-1",
    )

    assert evidence.score == 0.0


@pytest.mark.asyncio
async def test_implicit_search_matches_exact_job_before_company_role_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.retrieval import implicit_search

    candidates = [
        JobCandidate(
            job_id="job-1",
            score=0.9,
            evidence_span_ids=["jd-1"],
            company="Acme",
            role_cluster="data",
        ),
        JobCandidate(
            job_id="job-2",
            score=0.8,
            evidence_span_ids=["jd-2"],
            company="Acme",
            role_cluster="engineering",
        ),
    ]
    rows = [
        {
            "case_id": "exact",
            "similarity": 0.9,
            "job_id": "job-1",
            "company": "Other",
            "role_family": "other",
            "explicit_match_score": 0.8,
            "highest_stage": "offer",
            "final_status": "active",
            "source_confidence": 1.0,
        },
        {
            "case_id": "fallback",
            "similarity": 0.8,
            "job_id": "closed-job",
            "company": "Acme",
            "role_family": "data",
            "explicit_match_score": 0.7,
            "highest_stage": "interview",
            "final_status": "active",
            "source_confidence": 1.0,
        },
        {
            "case_id": "company-only",
            "similarity": 1.0,
            "job_id": "closed-job-2",
            "company": "Acme",
            "role_family": "marketing",
            "explicit_match_score": 1.0,
            "highest_stage": "joined",
            "final_status": "joined",
            "source_confidence": 1.0,
        },
    ]

    async def fake_embed_one(text: str) -> list[float]:
        assert text == "privacy safe resume"
        return [0.01] * settings.embed_dim

    async def fake_case_search(embedding: list[float], *, top_k: int):
        assert len(embedding) == settings.embed_dim
        assert top_k == 20
        return rows

    monkeypatch.setattr(implicit_search, "embed_one", fake_embed_one)
    monkeypatch.setattr(
        implicit_search.case_base,
        "search_similar_resume_cases_by_embedding",
        fake_case_search,
    )

    result = await implicit_search.search_implicit_evidence(
        anonymized_resume_text="privacy safe resume",
        candidates=candidates,
    )

    assert set(result) == {"job-1"}
    assert [row["case_id"] for row in result["job-1"].supporting_cases] == [
        "exact",
        "fallback",
    ]


@pytest.mark.asyncio
async def test_implicit_search_returns_empty_for_empty_query_or_candidates() -> None:
    from app.retrieval.implicit_search import search_implicit_evidence

    assert (
        await search_implicit_evidence(
            anonymized_resume_text="", candidates=[]
        )
        == {}
    )
