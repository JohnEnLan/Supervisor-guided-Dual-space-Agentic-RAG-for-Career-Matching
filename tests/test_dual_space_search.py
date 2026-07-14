from __future__ import annotations

import asyncio
from time import perf_counter

import pytest

from app.retrieval.hybrid_search import JobCandidate


def _candidate(job_id: str, score: float, *, company: str = "Acme") -> JobCandidate:
    return JobCandidate(
        job_id=job_id,
        score=score,
        explicit_score=score,
        evidence_span_ids=[f"jd-{job_id}"],
        company=company,
        role_cluster="data",
        sources=["dense"],
    )


def _outcome(case_id: str, job_id: str, *, similarity: float = 1.0) -> dict:
    return {
        "case_id": case_id,
        "similarity": similarity,
        "job_id": job_id,
        "company": "Acme",
        "role_family": "data",
        "explicit_match_score": 1.0,
        "highest_stage": "joined",
        "final_status": "joined",
        "source_confidence": 1.0,
    }


def test_retrieval_package_exports_dual_space_search() -> None:
    from app.retrieval import dual_space_search

    assert callable(dual_space_search)


@pytest.mark.asyncio
async def test_cold_start_preserves_explicit_order_and_scores() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    explicit = [_candidate("job-1", 0.9), _candidate("job-2", 0.8)]

    async def explicit_search(**kwargs):
        return explicit

    async def implicit_rows_search(**kwargs):
        return []

    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL analyst internship",
        hard_constraints={},
        soft_prefs={},
        top_k=2,
        explicit_search=explicit_search,
        implicit_rows_search=implicit_rows_search,
    )

    assert [row.job_id for row in result] == ["job-1", "job-2"]
    assert [row.score for row in result] == [0.9, 0.8]
    assert result[0] is explicit[0]


@pytest.mark.asyncio
async def test_disabled_implicit_path_preserves_explicit_results() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    explicit = [_candidate("job-1", 0.9), _candidate("job-2", 0.8)]

    async def explicit_search(**kwargs):
        return explicit

    async def implicit_rows_search(**kwargs):
        raise AssertionError("implicit search must not run when disabled")

    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL analyst internship",
        hard_constraints={},
        soft_prefs={},
        top_k=2,
        implicit_enabled=False,
        explicit_search=explicit_search,
        implicit_rows_search=implicit_rows_search,
    )

    assert result == explicit


@pytest.mark.asyncio
async def test_confident_implicit_evidence_can_rerank_explicit_candidates() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    async def explicit_search(**kwargs):
        return [_candidate("job-1", 0.9), _candidate("job-2", 0.88)]

    async def implicit_rows_search(**kwargs):
        return [
            _outcome("case-1", "job-2"),
            _outcome("case-2", "job-2"),
            _outcome("case-3", "job-2"),
        ]

    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL analyst internship",
        hard_constraints={},
        soft_prefs={},
        top_k=2,
        explicit_search=explicit_search,
        implicit_rows_search=implicit_rows_search,
    )

    assert [row.job_id for row in result] == ["job-2", "job-1"]
    assert result[0].implicit_score == 1.0
    assert result[0].implicit_confidence == 1.0
    assert "implicit_case" in result[0].sources
    assert len(result[0].implicit_evidence) == 3
    assert result[0].implicit_evidence[0]["highest_stage"] == "joined"


@pytest.mark.asyncio
async def test_implicit_rows_cannot_introduce_a_filtered_job() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    async def explicit_search(**kwargs):
        return [_candidate("job-visible", 0.7)]

    async def implicit_rows_search(**kwargs):
        return [
            _outcome("case-hidden-1", "job-hidden"),
            _outcome("case-hidden-2", "job-hidden"),
            _outcome("case-hidden-3", "job-hidden"),
        ]

    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL analyst internship",
        hard_constraints={"location": "Birmingham"},
        soft_prefs={},
        top_k=5,
        explicit_search=explicit_search,
        implicit_rows_search=implicit_rows_search,
    )

    assert [row.job_id for row in result] == ["job-visible"]


@pytest.mark.asyncio
async def test_explicit_and_implicit_io_start_concurrently() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    started: set[str] = set()
    both_started = asyncio.Event()

    async def rendezvous(name: str) -> None:
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        await asyncio.sleep(0.1)

    async def explicit_search(**kwargs):
        await rendezvous("explicit")
        return [_candidate("job-1", 0.9)]

    async def implicit_rows_search(**kwargs):
        await rendezvous("implicit")
        return []

    started_at = perf_counter()
    result = await asyncio.wait_for(
        dual_space_search(
            query="data analyst",
            anonymized_resume_text="SQL analyst internship",
            hard_constraints={},
            soft_prefs={},
            top_k=1,
            explicit_search=explicit_search,
            implicit_rows_search=implicit_rows_search,
        ),
        timeout=0.5,
    )
    elapsed = perf_counter() - started_at

    assert started == {"explicit", "implicit"}
    assert result[0].job_id == "job-1"
    assert elapsed < 0.18


@pytest.mark.asyncio
async def test_implicit_failure_falls_back_to_explicit_results() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    explicit = [_candidate("job-1", 0.9)]

    async def explicit_search(**kwargs):
        return explicit

    async def implicit_rows_search(**kwargs):
        raise RuntimeError("private provider detail")

    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL analyst internship",
        hard_constraints={},
        soft_prefs={},
        top_k=1,
        explicit_search=explicit_search,
        implicit_rows_search=implicit_rows_search,
    )

    assert result == explicit


@pytest.mark.asyncio
async def test_implicit_cancellation_propagates() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    async def explicit_search(**kwargs):
        return [_candidate("job-1", 0.9)]

    async def implicit_rows_search(**kwargs):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await dual_space_search(
            query="data analyst",
            anonymized_resume_text="SQL analyst internship",
            hard_constraints={},
            soft_prefs={},
            top_k=1,
            explicit_search=explicit_search,
            implicit_rows_search=implicit_rows_search,
        )


@pytest.mark.asyncio
async def test_explicit_failure_is_not_hidden_by_implicit_results() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    async def explicit_search(**kwargs):
        raise RuntimeError("explicit retrieval failed")

    async def implicit_rows_search(**kwargs):
        return [_outcome("case-1", "job-1")]

    with pytest.raises(RuntimeError, match="explicit retrieval failed"):
        await dual_space_search(
            query="data analyst",
            anonymized_resume_text="SQL analyst internship",
            hard_constraints={},
            soft_prefs={},
            top_k=1,
            explicit_search=explicit_search,
            implicit_rows_search=implicit_rows_search,
        )
