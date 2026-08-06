from __future__ import annotations

import json

import pytest

from app.state.schema import CareerState, SharedState


def _complete_state(*, targets=None, questions_used: int = 0) -> SharedState:
    return SharedState(
        session_id="session-1",
        user_id="user-1",
        career_state=CareerState(
            current_goal=["Data analyst"],
            hard_constraints={
                "locations": ["Birmingham"],
                "need_visa_sponsor": False,
            },
            soft_preferences={"title_keywords": ["data"]},
            avoid_roles=[],
        ),
        resume_state={
            "clarification_targets": targets or [],
            "questions_used": questions_used,
            "original_evidence_spans": [
                {"span_id": "R001", "text": "Acme 数据接口开发"},
                {"span_id": "R002", "text": "Career RAG 项目"},
            ],
        },
    )


def _targets() -> list[dict]:
    return [
        {
            "target_ref": "experience[0]",
            "field_path": "experience[0]",
            "status": "open",
            "severity": "high",
            "issue": "缺少职责与成果",
            "evidence_span_ids": ["R001"],
        },
        {
            "target_ref": "projects[0]",
            "field_path": "projects[0]",
            "status": "open",
            "severity": "medium",
            "issue": "缺少技术关联",
            "evidence_span_ids": ["R002"],
        },
    ]


def _llm_payload(**overrides) -> str:
    payload = {
        "assistant_reply": "收到，我会按你的原话记录。",
        "next_question": "这个项目具体用了哪些技术？",
        "profile_updates": {},
        "phase_suggestion": "resume_clarify",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_determine_phase_is_slot_first_and_switch_gated(monkeypatch) -> None:
    from app.agents import consult_engine as engine

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(engine.settings, "resume_clarify_max", 2)
    complete = _complete_state(targets=_targets())
    incomplete = _complete_state(targets=_targets())
    incomplete.career_state.hard_constraints.pop("need_visa_sponsor")

    assert engine.determine_phase(incomplete, mode="targeted") == "template"
    assert engine.determine_phase(complete, mode="targeted") == "resume_clarify"
    assert engine.determine_phase(complete, mode="explore") == "resume_clarify"

    complete.resume_state.questions_used = 2
    assert engine.determine_phase(complete, mode="targeted") == "deepen"
    assert engine.determine_phase(complete, mode="explore") == "explore"

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", False)
    complete.resume_state.questions_used = 0
    assert engine.determine_phase(complete, mode="targeted") == "deepen"


def test_clarification_prompt_is_additive_and_disabled_prompt_is_baseline(
    monkeypatch,
) -> None:
    from app.agents import consult_engine as engine

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", False)
    baseline = engine.CONSULT_PROMPT.replace("{phase}", "deepen")
    assert engine.format_consult_prompt("deepen") == baseline
    assert "answer_summary" not in baseline

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", True)
    clarify_prompt = engine.format_consult_prompt("resume_clarify")
    assert '"answer_summary"' in clarify_prompt
    assert '"clarification_action"' in clarify_prompt
    assert "answered | skip_current | skip_remaining" in clarify_prompt
    assert "extractive" in clarify_prompt.casefold()


def test_optional_clarification_fields_never_invalidate_the_core_turn() -> None:
    from app.agents.consult_engine import _ConsultLLMResponse

    parsed = _ConsultLLMResponse.model_validate(
        {
            "assistant_reply": "收到。",
            "next_question": "下一步呢？",
            "profile_updates": {},
            "phase_suggestion": "deepen",
            "answer_summary": ["wrong shape"],
            "clarification_action": "invented_action",
        }
    )

    assert parsed.answer_summary is None
    assert parsed.clarification_action is None


def test_summary_content_tokens_must_be_a_subset_or_fall_back_to_raw() -> None:
    from app.agents.consult_engine import validated_answer_summary

    raw = "我在 Acme 负责 Python API 开发，并把响应时间降低到 200ms。"

    assert validated_answer_summary("负责 Python API 开发", raw) == (
        "负责 Python API 开发"
    )
    assert validated_answer_summary("主导 Go 平台重构", raw) == raw


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("跳过", "skip_current"),
        ("先不补充，下一个", "skip_current"),
        ("剩余全部跳过", "skip_remaining"),
        ("skip all", "skip_remaining"),
    ],
)
def test_skip_whitelist_requires_pending_and_short_residual(message, expected) -> None:
    from app.agents.consult_engine import detect_clarification_skip

    assert detect_clarification_skip(message, has_pending=True) == expected
    assert detect_clarification_skip(message, has_pending=False) is None


def test_skip_whitelist_does_not_override_mixed_substantive_content() -> None:
    from app.agents.consult_engine import detect_clarification_skip

    assert (
        detect_clarification_skip(
            "跳过这个说法，但我实际负责 Python API 开发和性能优化",
            has_pending=True,
        )
        is None
    )


@pytest.mark.asyncio
async def test_pending_answer_uses_t_and_next_question_uses_t_plus_one(
    monkeypatch,
) -> None:
    from app.agents import consult_engine as engine

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(engine.settings, "resume_clarify_max", 2)
    state = _complete_state(targets=_targets(), questions_used=1)
    state.career_state.consult_rounds_used = 1
    state.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 7,
    }
    captured = {}

    async def chat(system, user, **_kwargs):
        captured["system"] = system
        captured["user"] = json.loads(user)
        return _llm_payload(
            answer_summary="负责 Python API 开发",
            clarification_action="answered",
        )

    turn = await engine.run_consult_round(
        state,
        mode="targeted",
        message="我负责 Python API 开发",
        resume_version=7,
        chat=chat,
    )

    clarification = captured["user"]["clarification_context"]
    assert clarification["answer_target"]["target_ref"] == "experience[0]"
    assert clarification["question_target"]["target_ref"] == "projects[0]"
    assert clarification["answer_target"]["evidence"][0]["text"] == (
        "Acme 数据接口开发"
    )
    assert "Current consultation phase: resume_clarify" in captured["system"]
    assert state.resume_state.clarification_targets[0]["status"] == "answered"
    assert state.resume_state.pending_clarification_question == {
        "target_ref": "projects[0]",
        "asked_round": 2,
        "baseline_version": 7,
    }
    assert state.resume_state.questions_used == 2
    assert turn.pending_clarification_at_round_start is True
    assert turn.issued_clarification_question is True
    assert turn.clarification_turn_active is True
    assert turn.clarification_target_refs == ("experience[0]",)
    assert turn.clarification_action == "answered"
    assert turn.clarification_answer_summary == "负责 Python API 开发"


@pytest.mark.asyncio
async def test_skip_remaining_updates_state_before_prompt_and_asks_no_target(
    monkeypatch,
) -> None:
    from app.agents import consult_engine as engine

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(engine.settings, "resume_clarify_max", 2)
    state = _complete_state(targets=_targets(), questions_used=1)
    state.career_state.consult_rounds_used = 1
    state.resume_state.pending_clarification_question = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 7,
    }
    captured = {}

    async def chat(system, user, **_kwargs):
        captured["system"] = system
        captured["user"] = json.loads(user)
        return _llm_payload(
            next_question="接下来更偏好哪类团队？",
            phase_suggestion="deepen",
        )

    turn = await engine.run_consult_round(
        state,
        mode="targeted",
        message="剩余全部跳过",
        resume_version=7,
        chat=chat,
    )

    assert [item["status"] for item in state.resume_state.clarification_targets] == [
        "skipped",
        "skipped",
    ]
    assert state.resume_state.pending_clarification_question is None
    assert state.resume_state.questions_used == 1
    assert captured["user"]["phase"] == "deepen"
    assert "Current consultation phase: deepen" in captured["system"]
    assert "clarification_context" not in captured["user"]
    assert turn.phase == "deepen"
    assert turn.issued_clarification_question is False
    assert turn.clarification_turn_active is True
    assert turn.clarification_action == "skip_remaining"
    assert turn.clarification_target_refs == (
        "experience[0]",
        "projects[0]",
    )


@pytest.mark.asyncio
async def test_failed_optional_extraction_keeps_pending_target_for_retry(
    monkeypatch,
) -> None:
    from app.agents import consult_engine as engine

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", True)
    monkeypatch.setattr(engine.settings, "resume_clarify_max", 2)
    state = _complete_state(targets=_targets(), questions_used=1)
    state.career_state.consult_rounds_used = 1
    pending = {
        "target_ref": "experience[0]",
        "asked_round": 1,
        "baseline_version": 7,
    }
    state.resume_state.pending_clarification_question = dict(pending)

    async def chat(*_args, **_kwargs):
        return _llm_payload(
            answer_summary=["bad"],
            clarification_action="bad",
        )

    turn = await engine.run_consult_round(
        state,
        mode="targeted",
        message="我补充一下",
        resume_version=7,
        chat=chat,
    )

    assert state.resume_state.clarification_targets[0]["status"] == "open"
    assert state.resume_state.pending_clarification_question == pending
    assert state.resume_state.questions_used == 1
    assert turn.clarification_action is None
    assert turn.issued_clarification_question is False


@pytest.mark.asyncio
async def test_switch_off_does_not_enter_clarify_or_touch_feature_a_state(
    monkeypatch,
) -> None:
    from app.agents import consult_engine as engine

    monkeypatch.setattr(engine.settings, "resume_clarify_enabled", False)
    state = _complete_state(targets=_targets(), questions_used=1)
    before = state.resume_state.model_dump()
    calls = 0

    async def chat(system, user, **_kwargs):
        nonlocal calls
        calls += 1
        assert system == engine.CONSULT_PROMPT.replace("{phase}", "deepen")
        assert "clarification_context" not in json.loads(user)
        return _llm_payload(phase_suggestion="deepen")

    turn = await engine.run_consult_round(
        state,
        mode="targeted",
        message="继续",
        chat=chat,
    )

    assert calls == 1
    assert turn.phase == "deepen"
    assert state.resume_state.model_dump() == before
