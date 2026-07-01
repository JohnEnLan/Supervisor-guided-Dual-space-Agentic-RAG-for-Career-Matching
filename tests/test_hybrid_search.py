import os

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


def test_collapse_chunk_hits_keeps_best_job_score_and_evidence_order():
    hits = [
        hs.ChunkHit(job_id="job-1", chunk_id="job-1:weak", score=0.2),
        hs.ChunkHit(job_id="job-2", chunk_id="job-2:only", score=0.5),
        hs.ChunkHit(job_id="job-1", chunk_id="job-1:strong", score=0.9),
    ]

    collapsed = hs._collapse_chunk_hits(hits, max_evidence_per_job=2)

    assert [item.job_id for item in collapsed] == ["job-1", "job-2"]
    assert collapsed[0].score == 0.9
    assert collapsed[0].evidence_span_ids == ["job-1:strong", "job-1:weak"]
    assert collapsed[1].evidence_span_ids == ["job-2:only"]


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
