from __future__ import annotations

import pytest

from app.agents.matching_agent import _write_retrieval_state
from app.agents.supervisor_harness import record_supervisor_checkpoint
from app.api.result_projector import project_product_result
from app.retrieval.hybrid_search import JobCandidate, _fetch_job_metadata
from app.state.schema import SharedState


def _demo_state(*, marker=True) -> SharedState:
    state = SharedState(session_id="demo-session", user_id="demo-user")
    state.retrieval_state.candidate_job_ids = ["demo-job"]
    state.retrieval_state.ranking_scores = [
        {
            "job_id": "demo-job",
            "source_tag": "linkedin_ml_cnuk_demo_v1",
            "demo_synthetic": marker,
            "country_code": "CN",
            "evidence_spans": [
                {
                    "evidence_span_id": "demo-job:raw_jd:1",
                    "field": "raw_jd",
                    "content": "Synthetic demo company context plus source JD evidence.",
                }
            ],
        }
    ]
    state.strategy_state.recommended_roles = [
        {
            "job_id": "demo-job",
            "tier": "now_fit",
            "match_explanation": "Evidence-backed match.",
            "evidence_span_ids": ["demo-job:raw_jd:1"],
        }
    ]
    return state


def test_candidate_metadata_reaches_public_recommendation_without_llm_copy() -> None:
    state = SharedState(session_id="demo-session", user_id="demo-user")
    _write_retrieval_state(
        state,
        [
            JobCandidate(
                job_id="demo-job",
                score=0.9,
                evidence_span_ids=["demo-job:raw_jd:1"],
                evidence_spans=[
                    {
                        "evidence_span_id": "demo-job:raw_jd:1",
                        "field": "raw_jd",
                        "content": "JD evidence",
                    }
                ],
                demo_synthetic=True,
                country_code="UK",
                source_tag="linkedin_ml_cnuk_demo_v1",
            )
        ],
    )
    state.strategy_state.recommended_roles = [
        {
            "job_id": "demo-job",
            "tier": "stretch_fit",
            "match_explanation": "Evidence-backed match.",
            "evidence_span_ids": ["demo-job:raw_jd:1"],
        }
    ]

    role = project_product_result(state).recommended_roles[0]

    assert role.demo_synthetic is True
    assert role.country_code == "UK"


def test_publication_gate_rejects_demo_corpus_role_missing_marker() -> None:
    state = _demo_state(marker=None)
    result = record_supervisor_checkpoint(
        state,
        checkpoint="publication_gate",
        verification={},
    )

    assert "demo_marker_missing" in result["issue_codes"]
    assert result["metrics"]["publishable_recommendation_count"] == 0
    projected = project_product_result(state)
    assert projected.recommended_roles == []
    assert "demo_marker_missing:demo-job" in projected.warnings


def test_publication_gate_accepts_marked_demo_corpus_role() -> None:
    result = record_supervisor_checkpoint(
        _demo_state(marker=True),
        checkpoint="publication_gate",
        verification={},
    )

    assert "demo_marker_missing" not in result["issue_codes"]
    assert result["metrics"]["publishable_recommendation_count"] == 1


@pytest.mark.asyncio
async def test_job_metadata_select_fetches_demo_columns() -> None:
    class Connection:
        async def fetch(self, sql, *_args):
            assert "demo_synthetic" in sql
            assert "country_code" in sql
            assert "source_tag" in sql
            return [
                {
                    "job_id": "demo-job",
                    "demo_synthetic": True,
                    "country_code": "CN",
                    "source_tag": "linkedin_ml_cnuk_demo_v1",
                }
            ]

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *_args):
            return None

    class Pool:
        def acquire(self):
            return Acquire()

    result = await _fetch_job_metadata(Pool(), ["demo-job"])

    assert result["demo-job"]["demo_synthetic"] is True
    assert result["demo-job"]["country_code"] == "CN"
