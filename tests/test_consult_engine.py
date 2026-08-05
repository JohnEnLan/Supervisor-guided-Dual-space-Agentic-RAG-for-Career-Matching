from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.state.schema import CareerState, SharedState


def _complete_career(**overrides) -> CareerState:
    payload = {
        "current_goal": ["Data analyst"],
        "hard_constraints": {
            "locations": ["Birmingham"],
            "need_visa_sponsor": False,
        },
        "soft_preferences": {
            "preferred_role_clusters": ["analytics"],
            "title_keywords": ["data"],
        },
        "avoid_roles": ["Sales"],
    }
    payload.update(overrides)
    return CareerState(**payload)


def test_career_state_adds_consult_defaults_and_loads_old_snapshot() -> None:
    career = CareerState()
    old_snapshot = SharedState.model_validate(
        {"session_id": "session-old", "user_id": "legacy-user"}
    )

    assert career.consult_transcript == []
    assert career.consult_rounds_used == 0
    assert old_snapshot.career_state.consult_transcript == []
    assert old_snapshot.career_state.consult_rounds_used == 0
    assert old_snapshot.career_state.intent_clarification_used == 0


def test_consult_phase_progression_is_deterministic() -> None:
    from app.agents.consult_engine import determine_phase

    assert determine_phase(CareerState(), mode="targeted") == "template"
    assert (
        determine_phase(
            _complete_career(
                soft_preferences={"title_keywords": ["data"]},
                avoid_roles=[],
            ),
            mode="targeted",
        )
        == "deepen"
    )
    assert determine_phase(_complete_career(), mode="targeted") == "explore"


def test_explore_mode_enters_explore_once_required_slots_are_full() -> None:
    from app.agents.consult_engine import determine_phase

    thin_profile = _complete_career(soft_preferences={}, avoid_roles=[])

    assert determine_phase(thin_profile, mode="targeted") == "deepen"
    assert determine_phase(thin_profile, mode="explore") == "explore"


def test_remote_true_satisfies_location_slot_and_completeness_formula() -> None:
    from app.agents.consult_engine import calculate_completeness, can_finalize

    career = CareerState(
        current_goal=["Platform engineer"],
        hard_constraints={"remote": True, "need_visa_sponsor": True},
        soft_preferences={
            "title_keywords": ["platform"],
            "preferred_role_clusters": ["engineering"],
        },
    )

    assert can_finalize(career) is True
    assert calculate_completeness(career) == pytest.approx(0.8)


def test_invalid_required_constraint_types_do_not_complete_profile() -> None:
    from app.agents.consult_engine import can_finalize

    career = CareerState(
        current_goal=["Platform engineer"],
        hard_constraints={
            "locations": {"city": "London"},
            "need_visa_sponsor": "unknown",
        },
    )

    assert can_finalize(career) is False


def test_completeness_caps_soft_preferences_at_four_items() -> None:
    from app.agents.consult_engine import calculate_completeness

    career = CareerState(
        current_goal=["Analyst"],
        hard_constraints={"locations": ["London"]},
        soft_preferences={f"preference_{index}": index for index in range(6)},
    )

    assert calculate_completeness(career) == pytest.approx(0.8)


def test_consult_prompt_keeps_fixed_contract_and_phase_placeholder() -> None:
    from app.agents.consult_engine import CONSULT_PROMPT, format_consult_prompt

    assert CONSULT_PROMPT.startswith("PHASE_C2_CONSULT_ADVISOR\n")
    assert "Current consultation phase: {phase}" in CONSULT_PROMPT
    assert "Ask exactly ONE heuristic question per turn" in CONSULT_PROMPT
    assert "question max 80 Chinese characters" in CONSULT_PROMPT
    assert "Never invent facts about the user" in CONSULT_PROMPT
    assert '"assistant_reply"' in CONSULT_PROMPT
    assert '"next_question"' in CONSULT_PROMPT
    assert '"profile_updates"' in CONSULT_PROMPT
    assert '"phase_suggestion"' in CONSULT_PROMPT
    assert "Current consultation phase: deepen" in format_consult_prompt("deepen")


def test_consult_context_contains_profile_and_only_latest_four_rounds() -> None:
    from app.agents.consult_engine import build_consult_user_prompt

    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        career_state=_complete_career(
            consult_transcript=[
                {
                    "round": index,
                    "user_message": f"answer-{index}",
                    "assistant_reply": f"reply-{index}",
                    "next_question": f"question-{index}",
                    "phase": "template",
                }
                for index in range(1, 7)
            ]
        ),
    )

    serialized = build_consult_user_prompt(
        state,
        message="x" * 2100,
        phase="deepen",
        max_chars=10_000,
    )
    payload = json.loads(serialized)

    assert payload["phase"] == "deepen"
    assert len(payload["user_message"]) == 2000
    assert [item["round"] for item in payload["recent_transcript"]] == [3, 4, 5, 6]
    assert payload["profile_summary"]["current_goal"] == ["Data analyst"]
    assert "private-user" not in serialized


@pytest.mark.asyncio
async def test_remembered_profile_is_labeled_and_not_silently_merged() -> None:
    from app.agents.consult_engine import run_consult_round

    remembered = {
        "current_goal": ["Data analyst"],
        "hard_constraints": {
            "locations": ["London"],
            "need_visa_sponsor": True,
        },
    }
    captured = {}

    async def chat(_system: str, user: str, **_kwargs) -> str:
        captured.update(json.loads(user))
        return json.dumps(
            {
                "assistant_reply": "我找到了你上次确认过的求职画像。",
                "next_question": "这些目标和约束现在仍然适用吗？",
                "profile_updates": remembered,
                "phase_suggestion": "template",
            },
            ensure_ascii=False,
        )

    state = SharedState(session_id="session-1", user_id="private-user")
    await run_consult_round(
        state,
        mode="targeted",
        message="开始咨询",
        remembered_profile=remembered,
        chat=chat,
    )

    assert captured["remembered_profile_draft"] == {
        "source": "user_profiles",
        "requires_confirmation": True,
        "profile": remembered,
    }
    assert state.career_state.current_goal == []
    assert state.career_state.hard_constraints == {}
    assert state.career_state.consult_rounds_used == 1


def test_invalid_remembered_profile_field_is_ignored_without_losing_draft() -> None:
    from app.agents.consult_engine import build_consult_user_prompt

    state = SharedState(session_id="session-1", user_id="private-user")
    serialized = build_consult_user_prompt(
        state,
        message="开始咨询",
        phase="template",
        remembered_profile={
            "hard_constraints": {
                "locations": ["London"],
                "max_years_exp": "many",
            }
        },
        max_chars=10_000,
    )

    remembered = json.loads(serialized)["remembered_profile_draft"]["profile"]
    assert remembered == {"hard_constraints": {"locations": ["London"]}}


@pytest.mark.asyncio
async def test_successful_consult_round_filters_merges_and_records_once() -> None:
    from app.agents.consult_engine import run_consult_round

    captured = {}

    async def chat(system: str, user: str, **kwargs) -> str:
        captured.update(system=system, user=user, kwargs=kwargs)
        return json.dumps(
            {
                "assistant_reply": "我理解你希望继续做数据相关工作。",
                "next_question": "地点和远程办公之间，你更看重哪一个？",
                "profile_updates": {
                    "current_goal": ["Analytics engineer"],
                    "long_term_goal": ["长期转向数据平台负责人"],
                    "hard_constraints": {
                        "locations": ["London"],
                        "need_visa_sponsor": True,
                        "remote": True,
                        "unsupported_salary_rule": 999,
                    },
                    "soft_preferences": {
                        "title_keywords": ["analytics"],
                        "unsupported_weight": 100,
                    },
                    "avoid_roles": ["Sales"],
                    "invented_top_level": ["drop me"],
                },
                "phase_suggestion": "explore",
            },
            ensure_ascii=False,
        )

    state = SharedState(
        session_id="session-1",
        user_id="private-user",
        career_state=CareerState(
            current_goal=["Data analyst"],
            soft_preferences={"preferred_locations": ["Birmingham"]},
        ),
    )

    result = await run_consult_round(
        state,
        mode="targeted",
        message="我的长期目标是转向数据平台负责人。",
        chat=chat,
    )

    assert result.phase == "template"
    assert state.career_state.consult_rounds_used == 1
    assert state.career_state.intent_clarification_used == 1
    assert state.career_state.intent_consulted is False
    assert state.career_state.current_goal == ["Data analyst", "Analytics engineer"]
    assert state.career_state.long_term_goal == ["长期转向数据平台负责人"]
    assert state.career_state.hard_constraints == {
        "locations": ["London"],
        "need_visa_sponsor": True,
        "remote": True,
    }
    assert state.career_state.soft_preferences == {
        "preferred_locations": ["Birmingham"],
        "title_keywords": ["analytics"],
    }
    assert state.career_state.avoid_roles == ["Sales"]
    assert state.career_state.consult_transcript == [
        {
            "round": 1,
            "user_message": "我的长期目标是转向数据平台负责人。",
            "assistant_reply": "我理解你希望继续做数据相关工作。",
            "next_question": "地点和远程办公之间，你更看重哪一个？",
            "phase": "template",
        }
    ]
    assert captured["kwargs"] == {"json_mode": True}
    assert "Current consultation phase: template" in captured["system"]


@pytest.mark.asyncio
async def test_invalid_llm_response_does_not_consume_a_round() -> None:
    from app.agents.consult_engine import ConsultResponseError, run_consult_round

    async def invalid_chat(*_args, **_kwargs) -> str:
        return "not-json"

    state = SharedState(session_id="session-1", user_id="private-user")

    with pytest.raises(ConsultResponseError):
        await run_consult_round(
            state,
            mode="targeted",
            message="我想做数据分析。",
            chat=invalid_chat,
        )

    assert state.career_state.consult_rounds_used == 0
    assert state.career_state.consult_transcript == []


@pytest.mark.asyncio
async def test_invalid_profile_update_does_not_partially_mutate_profile() -> None:
    from app.agents.consult_engine import ConsultResponseError, run_consult_round

    async def invalid_chat(*_args, **_kwargs) -> str:
        return json.dumps(
            {
                "assistant_reply": "我理解你的方向。",
                "next_question": "你希望在哪里工作？",
                "profile_updates": {
                    "current_goal": ["Data analyst"],
                    "hard_constraints": {"max_years_exp": "not-a-number"},
                },
                "phase_suggestion": "template",
            },
            ensure_ascii=False,
        )

    state = SharedState(session_id="session-1", user_id="private-user")

    with pytest.raises(ConsultResponseError):
        await run_consult_round(
            state,
            mode="targeted",
            message="我想做数据分析。",
            chat=invalid_chat,
        )

    assert state.career_state.current_goal == []
    assert state.career_state.hard_constraints == {}
    assert state.career_state.consult_rounds_used == 0
    assert state.career_state.consult_transcript == []


@pytest.mark.asyncio
async def test_non_boolean_visa_update_is_rejected_without_consuming_round() -> None:
    from app.agents.consult_engine import ConsultResponseError, run_consult_round

    async def invalid_chat(*_args, **_kwargs) -> str:
        return json.dumps(
            {
                "assistant_reply": "我理解你的方向。",
                "next_question": "你需要签证担保吗？",
                "profile_updates": {
                    "hard_constraints": {"need_visa_sponsor": "unknown"}
                },
                "phase_suggestion": "template",
            },
            ensure_ascii=False,
        )

    state = SharedState(session_id="session-1", user_id="private-user")

    with pytest.raises(ConsultResponseError):
        await run_consult_round(
            state,
            mode="targeted",
            message="我还没有说明签证情况。",
            chat=invalid_chat,
        )

    assert state.career_state.hard_constraints == {}
    assert state.career_state.consult_rounds_used == 0


@pytest.mark.asyncio
async def test_consult_round_limit_defaults_to_eight_and_can_reach_hard_cap() -> None:
    from app.agents.consult_engine import ConsultRoundLimitReached, run_consult_round

    calls = 0

    async def chat(*_args, **_kwargs) -> str:
        nonlocal calls
        calls += 1
        return json.dumps(
            {
                "assistant_reply": "收到。",
                "next_question": "你最看重哪项选择标准？",
                "profile_updates": {},
                "phase_suggestion": "deepen",
            },
            ensure_ascii=False,
        )

    exhausted = SharedState(
        session_id="session-8",
        user_id="private-user",
        career_state=CareerState(consult_rounds_used=8),
    )
    with pytest.raises(ConsultRoundLimitReached):
        await run_consult_round(
            exhausted,
            mode="targeted",
            message="继续",
            chat=chat,
        )
    assert calls == 0

    capped = SharedState(
        session_id="session-15",
        user_id="private-user",
        career_state=CareerState(consult_rounds_used=14),
    )
    await run_consult_round(
        capped,
        mode="explore",
        message="继续",
        max_rounds=15,
        chat=chat,
    )
    assert capped.career_state.consult_rounds_used == 15
    with pytest.raises(ConsultRoundLimitReached):
        await run_consult_round(
            capped,
            mode="explore",
            message="再继续",
            max_rounds=15,
            chat=chat,
        )


def test_max_consult_rounds_config_defaults_to_eight_and_hard_caps_at_fifteen() -> None:
    from app.config import Settings

    assert Settings().max_consult_rounds == 8
    assert Settings(max_consult_rounds=15).max_consult_rounds == 15
    with pytest.raises(ValidationError):
        Settings(max_consult_rounds=16)
