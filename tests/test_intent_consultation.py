import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain.intent import IntentConsultInput
from app.state.schema import CareerState, ResumeState, SharedState


def _client() -> TestClient:
    from app.api.v1.router import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_career_state_has_bounded_durable_intent_consultation_fields() -> None:
    career = CareerState()

    assert career.intent_mode is None
    assert career.intent_consulted is False
    assert career.intent_assistant_message == ""
    assert career.intent_directions == []
    assert career.intent_needs_clarification is False
    assert career.intent_clarification_question is None
    assert career.intent_clarification_used == 0
    assert career.consult_transcript == []
    assert career.consult_rounds_used == 0


def test_intent_consultation_fields_round_trip_through_shared_state() -> None:
    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        resume_state=ResumeState(
            original_evidence_spans=[{"span_id": "R1", "text": "Built Python APIs"}]
        ),
        career_state=CareerState(
            intent_mode="explore",
            intent_consulted=True,
            intent_assistant_message="Choose one evidence-backed direction.",
            intent_directions=[
                {
                    "role_family": "data",
                    "title": "Data analyst",
                    "rationale": "Python project evidence",
                    "resume_evidence_span_ids": ["R1"],
                    "primary_gap": "SQL depth",
                    "entry_role": "Junior data analyst",
                }
            ],
        ),
    )

    restored = SharedState.model_validate_json(state.model_dump_json())

    assert restored.career_state.intent_mode == "explore"
    assert restored.career_state.intent_consulted is True
    assert restored.career_state.intent_directions[0]["resume_evidence_span_ids"] == [
        "R1"
    ]


def test_intent_consult_input_forbids_unknown_fields() -> None:
    from app.domain.intent import IntentConsultInput

    with pytest.raises(ValidationError):
        IntentConsultInput.model_validate(
            {
                "mode": "explore",
                "target_roles": [],
                "target_companies": [],
                "company_exclusive": False,
                "model_name": "must-not-be-public",
            }
        )


def test_targeted_consultation_enforces_company_semantics() -> None:
    from app.agents import intent_agent

    agent_type = getattr(intent_agent, "IntentConsultAgent", None)
    assert agent_type is not None
    agent = agent_type(
        IntentConsultInput(
            mode="targeted",
            goal_text="Find platform engineering work",
            target_roles=["Platform Engineer"],
            target_companies=["OpenAI"],
            company_exclusive=True,
        )
    )
    state = SharedState(session_id="session-1", user_id="private-user")

    updated = agent.apply(
        state,
        {
            "assistant_message": "I normalized your target.",
            "current_goal": ["Platform engineering"],
            "long_term_goal": [],
            "hard_constraints": {},
            "soft_preferences": {"preferred_role_clusters": ["engineering"]},
            "avoid_roles": [],
            "directions": [],
            "needs_clarification": False,
        },
    )

    assert updated.career_state.intent_consulted is True
    assert updated.career_state.hard_constraints["companies"] == ["OpenAI"]
    assert updated.career_state.soft_preferences["preferred_companies"] == [
        "OpenAI"
    ]


def test_intent_allow_lists_preserve_company_constraints_and_preferences() -> None:
    from app.agents.intent_agent import (
        _filter_hard_constraints,
        _filter_soft_preferences,
    )

    assert _filter_hard_constraints(
        {"companies": ["OpenAI"], "unsupported_company_rule": True}
    ) == {"companies": ["OpenAI"]}
    assert _filter_soft_preferences(
        {"preferred_companies": ["DeepMind"], "company_weight": 100}
    ) == {"preferred_companies": ["DeepMind"]}


def test_explore_consultation_is_limited_to_three_directions() -> None:
    from app.agents import intent_agent

    agent_type = getattr(intent_agent, "IntentConsultAgent", None)
    assert agent_type is not None
    agent = agent_type(IntentConsultInput(mode="explore"))
    state = SharedState(session_id="session-1", user_id="private-user")
    directions = [
        {
            "role_family": f"family-{index}",
            "title": f"Direction {index}",
            "rationale": "Grounded rationale",
            "resume_evidence_span_ids": ["R1"],
            "primary_gap": "A gap",
            "entry_role": "Entry role",
        }
        for index in range(4)
    ]

    updated = agent.apply(
        state,
        {
            "assistant_message": "Here are three directions.",
            "current_goal": [],
            "long_term_goal": [],
            "hard_constraints": {},
            "soft_preferences": {},
            "avoid_roles": [],
            "directions": directions,
            "needs_clarification": False,
        },
    )

    assert len(updated.career_state.intent_directions) == 3
    assert updated.career_state.intent_consulted is True


@pytest.mark.asyncio
async def test_visible_consultation_rejects_second_clarification_before_llm() -> None:
    from app.agents import intent_agent

    run_visible = getattr(intent_agent, "run_visible_intent_consultation", None)
    assert run_visible is not None
    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        career_state=CareerState(intent_clarification_used=1),
    )

    with pytest.raises(ValueError, match="clarification limit reached"):
        await run_visible(
            state,
            IntentConsultInput(
                mode="targeted",
                clarification_answer="Birmingham only",
            ),
        )


def test_resume_preview_projects_allow_list_evidence(monkeypatch) -> None:
    from app.api.v1 import sessions
    from app.db.state_store import ConsultContext

    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        resume_state=ResumeState(
            normalized_base_resume="full private resume",
            projects=[{"name": "API project", "evidence_span_ids": ["R1"]}],
            original_evidence_spans=[
                {"span_id": "R1", "text": "Built Python APIs", "email": "private@example.com"}
            ],
        ),
    )

    async def context(_session_id: str):
        return ConsultContext(
            state=state,
            status="resume_ready",
            resume_version=1,
            confirmed_resume_version=1,
            resume_upload_generation=1,
        )

    monkeypatch.setattr(sessions, "load_consult_context", context)

    with _client() as client:
        response = client.get("/api/v1/sessions/session-1/resume-preview")

    assert response.status_code == 200
    assert response.json()["evidence"] == [
        {"evidence_span_id": "R1", "content": "Built Python APIs"}
    ]
    assert "private@example.com" not in response.text
    assert "full private resume" not in response.text
