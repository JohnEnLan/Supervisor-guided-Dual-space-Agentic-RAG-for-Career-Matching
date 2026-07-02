import os
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


@pytest.mark.asyncio
async def test_run_pipeline_normalizes_resume_then_searches_with_structured_query(monkeypatch):
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState
    from app.normalization.resume_intake import ResumeIntakeResult
    from scripts import run_week1_pipeline as pipeline

    calls = {}

    async def fake_intake_resume(path, *, session_id, user_id, save_to_db):
        calls["intake"] = {
            "path": path,
            "session_id": session_id,
            "user_id": user_id,
            "save_to_db": save_to_db,
        }
        state = SharedState(
            session_id=session_id,
            user_id=user_id,
            resume_state=ResumeState(
                normalized_base_resume="python data analyst internship query",
                skills=["Python", "SQL"],
                experience=[
                    {
                        "title": "Data Analyst Intern",
                        "responsibilities": ["Built SQL dashboards"],
                    }
                ],
                original_evidence_spans=[{"span_id": "R001", "text": "Python"}],
            ),
        )
        return ResumeIntakeResult(state=state, raw_text="raw", extracted_pages=1)

    async def fake_hybrid_search(query, hard_constraints, soft_prefs, top_k):
        calls["search"] = {
            "query": query,
            "hard_constraints": hard_constraints,
            "soft_prefs": soft_prefs,
            "top_k": top_k,
        }
        return [
            JobCandidate(
                job_id="job-1",
                score=0.91,
                title="Data Analyst Intern",
                company="Example Co",
                location="Birmingham",
                evidence_span_ids=["job-1:skills:1"],
                rrf_score=0.031,
                bm25_score=0.42,
                dense_score=0.88,
                field_bonus=0.06,
                sources=["bm25", "dense"],
            )
        ]

    async def fake_close_pool():
        calls["closed"] = True

    async def fake_save_shared_state(state, status):
        calls["saved_after_retrieval"] = {
            "session_id": state.session_id,
            "status": status,
            "candidate_job_ids": list(state.retrieval_state.candidate_job_ids),
            "ranking_scores": list(state.retrieval_state.ranking_scores),
            "evidence_span_ids": list(state.retrieval_state.evidence_span_ids),
        }

    monkeypatch.setattr(pipeline, "intake_resume", fake_intake_resume)
    monkeypatch.setattr(pipeline, "hybrid_search", fake_hybrid_search)
    monkeypatch.setattr(pipeline, "close_pool", fake_close_pool)
    monkeypatch.setattr(pipeline, "save_shared_state", fake_save_shared_state)

    result = await pipeline.run_pipeline(
        resume_path=Path("resume.pdf"),
        session_id="s1",
        user_id="u1",
        top_k=3,
        hard_constraints={"location": "Birmingham"},
        soft_prefs={"title_keywords": ["analyst"]},
        save_state=True,
    )

    assert calls["intake"]["path"] == Path("resume.pdf")
    assert calls["intake"]["save_to_db"] is True
    assert calls["search"]["hard_constraints"] == {"location": "Birmingham"}
    assert calls["search"]["soft_prefs"] == {"title_keywords": ["analyst"]}
    assert calls["search"]["top_k"] == 3
    assert "Summary: python data analyst internship query" in calls["search"]["query"]
    assert "Skills: Python; SQL" in calls["search"]["query"]
    assert "Experience: Data Analyst Intern" in calls["search"]["query"]
    assert calls["closed"] is True
    assert result.candidates[0].job_id == "job-1"
    assert result.resume_result.state.retrieval_state.candidate_job_ids == ["job-1"]
    assert result.resume_result.state.retrieval_state.ranking_scores == [
        {
            "job_id": "job-1",
            "score": 0.91,
            "rrf_score": 0.031,
            "bm25_score": 0.42,
            "dense_score": 0.88,
            "raptor_score": 0.0,
            "field_bonus": 0.06,
            "sources": ["bm25", "dense"],
            "evidence_span_ids": ["job-1:skills:1"],
        }
    ]
    assert result.resume_result.state.retrieval_state.evidence_span_ids == [
        "job-1:skills:1"
    ]
    assert calls["saved_after_retrieval"] == {
        "session_id": "s1",
        "status": "retrieval_done",
        "candidate_job_ids": ["job-1"],
        "ranking_scores": [
            {
                "job_id": "job-1",
                "score": 0.91,
                "rrf_score": 0.031,
                "bm25_score": 0.42,
                "dense_score": 0.88,
                "raptor_score": 0.0,
                "field_bonus": 0.06,
                "sources": ["bm25", "dense"],
                "evidence_span_ids": ["job-1:skills:1"],
            }
        ],
        "evidence_span_ids": ["job-1:skills:1"],
    }


def test_format_top_k_includes_basic_matching_info():
    from app.retrieval.hybrid_search import JobCandidate
    from app.state.schema import ResumeState, SharedState
    from app.normalization.resume_intake import ResumeIntakeResult
    from scripts import run_week1_pipeline as pipeline

    result = pipeline.Week1PipelineResult(
        resume_result=ResumeIntakeResult(
            state=SharedState(
                session_id="s1",
                user_id="u1",
                resume_state=ResumeState(
                    normalized_base_resume="base resume",
                    skills=["Python"],
                    original_evidence_spans=[{"span_id": "R001", "text": "Python"}],
                ),
            ),
            raw_text="raw",
            extracted_pages=1,
        ),
        candidates=[
            JobCandidate(
                job_id="job-1",
                score=0.91,
                title="Data Analyst Intern",
                company="Example Co",
                location="Birmingham",
                evidence_span_ids=["job-1:skills:1"],
            )
        ],
    )

    rendered = pipeline.format_result(result)

    assert "Top-K matches" in rendered
    assert "job-1" in rendered
    assert "0.910000" in rendered
    assert "Data Analyst Intern" in rendered
    assert "Example Co" in rendered
    assert "job-1:skills:1" in rendered
