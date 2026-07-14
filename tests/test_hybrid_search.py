import asyncio
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")

from app.retrieval import hybrid_search as hs


def test_build_hard_filter_query_uses_parameterized_sql():
    sql, params = hs._build_hard_filter_query(
        {
            "location": "London",
            "need_visa_sponsor": True,
            "max_years_exp": 2,
            "role_cluster": "software_engineering",
            "degree_required": "bachelor",
        }
    )

    assert "is_open = TRUE" in sql
    assert "location = $1" in sql
    assert "visa_sponsor = TRUE" in sql
    assert "min_years_exp <= $2" in sql
    assert "role_cluster = $3" in sql
    assert "degree_required = $4" in sql
    assert params == ["London", 2, "software_engineering", "bachelor"]


def test_company_exclusive_filter_is_parameterized_and_case_insensitive():
    sql, params = hs._build_hard_filter_query(
        {"companies": ["OpenAI", "DeepMind"]}
    )

    assert "lower(company) = ANY($1::text[])" in sql
    assert params == [["openai", "deepmind"]]


def test_preferred_company_is_a_soft_ranking_bonus():
    candidates = hs._rerank_candidates(
        fused=[("job-other", 0.03), ("job-target", 0.03)],
        bm25_by_job={"job-other": 0.5, "job-target": 0.5},
        dense_by_job={"job-other": 0.5, "job-target": 0.5},
        evidence_by_job={
            "job-other": ["job-other:skills:1"],
            "job-target": ["job-target:skills:1"],
        },
        metadata_by_job={
            "job-other": {
                "title": "Platform Engineer",
                "company": "Other Co",
                "location": "London",
            },
            "job-target": {
                "title": "Platform Engineer",
                "company": "OpenAI",
                "location": "London",
            },
        },
        soft_prefs={"preferred_companies": ["openai"]},
        top_k=2,
    )

    assert [candidate.job_id for candidate in candidates] == [
        "job-target",
        "job-other",
    ]
    assert candidates[0].score > candidates[1].score


def test_collapse_chunk_hits_keeps_best_job_score_and_evidence_order():
    hits = [
        hs.ChunkHit(
            job_id="job-1",
            chunk_id="job-1:weak",
            score=0.2,
            field="responsibilities",
        ),
        hs.ChunkHit(
            job_id="job-2",
            chunk_id="job-2:only",
            score=0.5,
            field="summary",
        ),
        hs.ChunkHit(
            job_id="job-1",
            chunk_id="job-1:strong",
            score=0.9,
            field="required_skills",
        ),
    ]

    collapsed = hs._collapse_chunk_hits(hits, max_evidence_per_job=2)

    assert [item.job_id for item in collapsed] == ["job-1", "job-2"]
    assert collapsed[0].score == 0.9
    assert collapsed[0].evidence_span_ids == ["job-1:strong", "job-1:weak"]
    assert collapsed[0].evidence_fields == ["required_skills", "responsibilities"]
    assert collapsed[1].evidence_span_ids == ["job-2:only"]
    assert collapsed[1].evidence_fields == ["summary"]


def test_prepare_bm25_tsquery_uses_or_keywords_for_long_resume_query():
    query = (
        "Zhang En has a Bachelor's in Business Administration with Accounting. "
        "Experience includes Meituan corporate strategy research, short video "
        "e-commerce, SPSS analysis, IELTS, and student committee leadership. "
        "Business business business strategy strategy."
    )

    tsquery = hs._prepare_bm25_tsquery(query, max_terms=8)

    assert "|" in tsquery
    assert "&" not in tsquery
    assert "business:*" in tsquery
    assert "strategy:*" in tsquery
    assert tsquery.count("business:*") == 1
    assert len(tsquery.split(" | ")) <= 8


@pytest.mark.asyncio
async def test_bm25_and_dense_overlap_after_hard_filter(monkeypatch) -> None:
    started: set[str] = set()
    both_started = asyncio.Event()

    async def get_pool():
        return object()

    async def hard_filter(_pool, _constraints):
        return {"job-1"}

    async def branch(name: str):
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        await asyncio.sleep(0.1)
        return []

    async def bm25(*_args, **_kwargs):
        return await branch("bm25")

    async def dense(*_args, **_kwargs):
        return await branch("dense")

    monkeypatch.setattr(hs, "get_pool", get_pool)
    monkeypatch.setattr(hs, "_hard_filter_ids", hard_filter)
    monkeypatch.setattr(hs, "_bm25", bm25)
    monkeypatch.setattr(hs, "_dense", dense)

    result = await asyncio.wait_for(
        hs.hybrid_search(
            query="data analyst",
            hard_constraints={"location": "Birmingham"},
            top_k=5,
        ),
        timeout=0.5,
    )
    assert result == []
    assert started == {"bm25", "dense"}


def test_rerank_candidates_promotes_dense_bi_encoder_match():
    candidates = hs._rerank_candidates(
        fused=[("job-1", 0.034), ("job-2", 0.033)],
        bm25_by_job={"job-1": 0.8, "job-2": 0.1},
        dense_by_job={"job-1": 0.1, "job-2": 0.9},
        evidence_by_job={
            "job-1": ["job-1:requirements"],
            "job-2": ["job-2:responsibilities"],
        },
        metadata_by_job={
            "job-1": {"title": "Office Assistant", "company": "A", "location": "NY"},
            "job-2": {"title": "Machine Learning Engineer", "company": "B", "location": "London"},
        },
        soft_prefs={},
        top_k=2,
    )

    assert [candidate.job_id for candidate in candidates] == ["job-2", "job-1"]
    assert candidates[0].score > candidates[1].score
    assert candidates[0].evidence_span_ids == ["job-2:responsibilities"]
    assert candidates[0].rrf_score == 0.033
    assert candidates[0].bm25_score == 0.1
    assert candidates[0].dense_score == 0.9
    assert candidates[0].raptor_score == 0.0
    assert candidates[0].sources == ["bm25", "dense"]


def test_rerank_candidates_applies_field_aware_bonus():
    candidates = hs._rerank_candidates(
        fused=[("job-skills", 0.03), ("job-summary", 0.03)],
        bm25_by_job={"job-skills": 0.5, "job-summary": 0.5},
        dense_by_job={"job-skills": 0.5, "job-summary": 0.5},
        evidence_by_job={
            "job-skills": ["job-skills:required_skills:1"],
            "job-summary": ["job-summary:summary:1"],
        },
        metadata_by_job={
            "job-skills": {
                "title": "Software Engineer",
                "company": "A",
                "location": "London",
            },
            "job-summary": {
                "title": "General Assistant",
                "company": "B",
                "location": "London",
            },
        },
        soft_prefs={},
        top_k=2,
        field_bonus_by_job={"job-skills": 0.06, "job-summary": 0.0},
    )

    assert [candidate.job_id for candidate in candidates] == [
        "job-skills",
        "job-summary",
    ]
    assert candidates[0].field_bonus == 0.06
    assert candidates[0].score > candidates[1].score


def test_rerank_candidates_tracks_raptor_recall_source():
    candidates = hs._rerank_candidates(
        fused=[("job-raptor", 0.04), ("job-dense", 0.03)],
        bm25_by_job={},
        dense_by_job={"job-dense": 0.8},
        raptor_by_job={"job-raptor": 0.9},
        evidence_by_job={
            "job-raptor": ["role:software_engineering"],
            "job-dense": ["job-dense:responsibilities:1"],
        },
        metadata_by_job={
            "job-raptor": {
                "title": "Backend Engineer",
                "company": "A",
                "location": "London",
            },
            "job-dense": {
                "title": "Support Engineer",
                "company": "B",
                "location": "London",
            },
        },
        soft_prefs={},
        top_k=2,
    )

    assert candidates[0].job_id == "job-raptor"
    assert candidates[0].raptor_score == 0.9
    assert candidates[0].sources == ["raptor"]


def test_rerank_candidates_ignores_legacy_case_derived_role_weight():
    candidates = hs._rerank_candidates(
        fused=[("job-generic", 0.03), ("job-case", 0.03)],
        bm25_by_job={"job-generic": 0.5, "job-case": 0.5},
        dense_by_job={"job-generic": 0.5, "job-case": 0.5},
        evidence_by_job={
            "job-generic": ["job-generic:skills:1"],
            "job-case": ["job-case:skills:1"],
        },
        metadata_by_job={
            "job-generic": {
                "title": "General Business Intern",
                "company": "A",
                "location": "Birmingham",
            },
            "job-case": {
                "title": "Data Analyst Intern",
                "company": "B",
                "location": "Birmingham",
            },
        },
        soft_prefs={"case_target_roles": ["Data Analyst"]},
        top_k=2,
    )

    assert [candidate.job_id for candidate in candidates] == [
        "job-generic",
        "job-case",
    ]
    assert candidates[0].score == candidates[1].score
