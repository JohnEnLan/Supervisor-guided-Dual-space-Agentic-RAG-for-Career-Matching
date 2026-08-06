from __future__ import annotations

import json

import pytest

from app.config import settings
from app.state.schema import ResumeState, SharedState


def _resume_state(*, with_clarification: bool) -> ResumeState:
    return ResumeState(
        normalized_base_resume="Base resume text.\n",
        original_evidence_spans=[
            {"span_id": "R001", "text": "Built a reporting dashboard."}
        ],
        clarification_evidence_spans=(
            [
                {
                    "span_id": "C001",
                    "text": "Led the Python API delivery.",
                    "source": "user_clarification",
                }
            ]
            if with_clarification
            else []
        ),
    )


def _shared_state(*, with_clarification: bool = True) -> SharedState:
    return SharedState(
        session_id="session-b5c",
        user_id="user-b5c",
        resume_state=_resume_state(with_clarification=with_clarification),
    )


def test_resume_view_helpers_merge_user_confirmed_clarifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.state.resume_view import (
        all_resume_evidence_spans,
        effective_resume_text,
        resume_evidence_ids,
    )

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    state = _shared_state()

    text = effective_resume_text(state.resume_state)
    spans = all_resume_evidence_spans(state)

    assert text.startswith(state.resume_state.normalized_base_resume)
    assert "Supplementary information" in text
    assert "C001" in text
    assert "Led the Python API delivery." in text
    assert spans == [
        *state.resume_state.original_evidence_spans,
        *state.resume_state.clarification_evidence_spans,
    ]
    assert resume_evidence_ids(state) == {"R001", "C001"}


def test_resume_view_helpers_are_exact_identity_without_clarification_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.state.resume_view import (
        all_resume_evidence_spans,
        effective_resume_text,
        resume_evidence_ids,
    )

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    state = _shared_state(with_clarification=False)

    assert effective_resume_text(state) == "Base resume text.\n"
    assert all_resume_evidence_spans(state) == [
        {"span_id": "R001", "text": "Built a reporting dashboard."}
    ]
    assert resume_evidence_ids(state) == {"R001"}


def test_resume_view_helpers_ignore_stale_clarifications_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.state.resume_view import (
        all_resume_evidence_spans,
        effective_resume_text,
        resume_evidence_ids,
    )

    monkeypatch.setattr(settings, "resume_clarify_enabled", False)
    state = _shared_state()

    assert effective_resume_text(state) == "Base resume text.\n"
    assert all_resume_evidence_spans(state) == [
        {"span_id": "R001", "text": "Built a reporting dashboard."}
    ]
    assert resume_evidence_ids(state) == {"R001"}


def test_matching_agent_prompt_uses_effective_resume_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.matching_agent import MatchingAgent

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)

    payload = json.loads(MatchingAgent([]).build_user_prompt(_shared_state()))

    assert payload["resume"]["effective_resume_text"].startswith(
        "Base resume text.\n"
    )
    assert "Led the Python API delivery." in payload["resume"][
        "effective_resume_text"
    ]


@pytest.mark.asyncio
async def test_candidate_explanation_payload_uses_effective_resume_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.matching_agent import _explain_candidate_match
    from app.retrieval.hybrid_search import JobCandidate

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    captured: dict[str, object] = {}

    async def fake_chat(_system: str, user: str, **_kwargs: object) -> str:
        captured.update(json.loads(user))
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": "job-1",
                        "tier": "now_fit",
                        "match_explanation": "Supported match.",
                        "evidence_span_ids": ["job-1:skills:1"],
                    }
                ]
            }
        )

    candidate = JobCandidate(
        job_id="job-1",
        score=0.9,
        evidence_span_ids=["job-1:skills:1"],
        evidence_spans=[
            {
                "evidence_span_id": "job-1:skills:1",
                "field": "skills",
                "content": "Python required.",
            }
        ],
    )

    await _explain_candidate_match(
        _shared_state(), candidate, {}, chat_fn=fake_chat
    )

    resume_payload = captured["resume"]
    assert isinstance(resume_payload, dict)
    assert "Led the Python API delivery." in resume_payload["effective_resume_text"]


def test_supervisor_payloads_consume_effective_resume_and_merged_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.supervisor import _final_payload, _planning_payload

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    state = _shared_state()

    planning = json.loads(_planning_payload(state, "Data roles", 5, False))
    final = json.loads(_final_payload(state))

    assert "Led the Python API delivery." in planning["resume_summary"]
    assert final["resume_evidence_span_ids"] == ["C001", "R001"]


def test_strategy_context_and_whitelist_accept_clarification_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.strategy_agent import StrategyAgent, _filter_resume_revision_plan

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)
    state = _shared_state()

    prompt = json.loads(StrategyAgent().build_user_prompt(state))
    kept, dropped = _filter_resume_revision_plan(
        state,
        [
            {
                "section": "experience",
                "suggestion": "Describe the confirmed API ownership.",
                "evidence_span_ids": ["C001"],
            }
        ],
    )

    assert "Led the Python API delivery." in prompt["resume_state"][
        "effective_resume_text"
    ]
    assert prompt["resume_state"]["resume_evidence_spans"][-1]["source"] == (
        "user_clarification"
    )
    assert prompt["evidence_contract"]["resume_evidence_span_ids"] == [
        "C001",
        "R001",
    ]
    assert kept[0]["evidence_span_ids"] == ["C001"]
    assert dropped == 0


def test_base_collector_delegates_to_clarification_aware_whitelist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agents.base import resume_evidence_ids

    monkeypatch.setattr(settings, "resume_clarify_enabled", True)

    assert resume_evidence_ids(_shared_state()) == {"R001", "C001"}


def test_strategy_and_supervisor_prompts_name_the_full_resume_evidence_contract() -> None:
    from app.agents.strategy_agent import StrategyAgent
    from app.agents.supervisor import FINAL_PROMPT

    required = (
        "resume evidence and user-confirmed clarifications (source-tagged) only"
    )

    assert required in StrategyAgent.system_prompt
    assert required in FINAL_PROMPT
    assert "original resume evidence only" not in StrategyAgent.system_prompt
    assert "original resume evidence" not in FINAL_PROMPT
