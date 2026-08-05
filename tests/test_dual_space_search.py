from __future__ import annotations

import asyncio
from dataclasses import replace

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


def test_effective_explicit_score_preserves_optional_three_state_semantics() -> None:
    from app.retrieval.hybrid_search import effective_explicit_score

    unset = JobCandidate(job_id="unset", score=0.7, evidence_span_ids=[])
    zero = JobCandidate(
        job_id="zero",
        score=0.7,
        explicit_score=0.0,
        evidence_span_ids=[],
    )
    positive = JobCandidate(
        job_id="positive",
        score=0.7,
        explicit_score=0.4,
        evidence_span_ids=[],
    )

    assert effective_explicit_score(unset) == 0.7
    assert effective_explicit_score(zero) == 0.0
    assert effective_explicit_score(positive) == 0.4


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
async def test_legal_zero_explicit_score_does_not_fall_back_during_fusion() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    async def explicit_search(**kwargs):
        return [
            JobCandidate(
                job_id="job-zero",
                score=0.8,
                explicit_score=0.0,
                evidence_span_ids=["jd-job-zero"],
                company="Acme",
                role_cluster="data",
            )
        ]

    async def implicit_rows_search(**kwargs):
        return [
            _outcome(f"case-{index}", "job-zero")
            for index in range(3)
        ]

    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL analyst internship",
        hard_constraints={},
        soft_prefs={},
        top_k=1,
        explicit_search=explicit_search,
        implicit_rows_search=implicit_rows_search,
    )

    assert result[0].explicit_score == 0.0
    assert result[0].score == 0.3


@pytest.mark.asyncio
async def test_cross_rank_breaks_full_score_tie_before_job_id() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    candidates = [
        replace(_candidate("job-z", 0.8), cross_rank=0),
        replace(_candidate("job-a", 0.8), cross_rank=1),
    ]

    async def explicit_search(**kwargs):
        return candidates

    async def implicit_rows_search(**kwargs):
        return [
            _outcome(f"z-{index}", "job-z") for index in range(3)
        ] + [
            _outcome(f"a-{index}", "job-a") for index in range(3)
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

    assert [candidate.job_id for candidate in result] == ["job-z", "job-a"]


@pytest.mark.asyncio
async def test_missing_cross_rank_retains_job_id_tie_breaker() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    candidates = [_candidate("job-z", 0.8), _candidate("job-a", 0.8)]

    async def explicit_search(**kwargs):
        return candidates

    async def implicit_rows_search(**kwargs):
        return [
            _outcome(f"z-{index}", "job-z") for index in range(3)
        ] + [
            _outcome(f"a-{index}", "job-a") for index in range(3)
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

    assert [candidate.job_id for candidate in result] == ["job-a", "job-z"]


@pytest.mark.asyncio
async def test_existing_clamp_asymmetry_is_preserved_for_partial_implicit_hits() -> None:
    from app.retrieval.dual_space_search import dual_space_search

    async def explicit_search(**kwargs):
        return [_candidate("job-hit", 1.2), _candidate("job-no-hit", 1.1)]

    async def implicit_rows_search(**kwargs):
        return [
            _outcome(f"case-{index}", "job-hit") for index in range(3)
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

    assert [candidate.job_id for candidate in result] == [
        "job-no-hit",
        "job-hit",
    ]
    assert result[0].score == 1.1
    assert result[1].score == 1.0


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
    assert started == {"explicit", "implicit"}
    assert result[0].job_id == "job-1"


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
