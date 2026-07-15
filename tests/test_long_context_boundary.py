from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_llm_boundary_compacts_large_json_without_breaking_structure(
    monkeypatch,
) -> None:
    from app.llm import deepseek

    captured: dict = {}

    class FakeMessage:
        content = '{"ok": true}'

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(deepseek, "_client", FakeClient())
    monkeypatch.setattr(deepseek.settings, "llm_user_prompt_max_chars", 2_000)
    prompt = json.dumps(
        {
            "normalized_base_resume": "真实项目证据" * 40_000,
            "skills": ["Python", "SQL"],
            "career_state": {"hard_constraints": {"location": "Birmingham"}},
        },
        ensure_ascii=False,
    )

    result = await deepseek.chat("system", prompt, json_mode=True)

    sent = captured["messages"][1]["content"]
    decoded = json.loads(sent)
    assert result == '{"ok": true}'
    assert len(sent) <= 2_000
    assert decoded["_context_budget"]["truncated"] is True
    assert decoded["_context_budget"]["original_chars"] == len(prompt)
    assert decoded["skills"] == ["Python", "SQL"]
    assert decoded["career_state"]["hard_constraints"]["location"] == "Birmingham"
    assert "[truncated" in decoded["normalized_base_resume"]


def test_context_budget_wraps_large_plain_text_as_valid_json() -> None:
    from app.llm.context_budget import fit_user_prompt_to_budget

    bounded = fit_user_prompt_to_budget("evidence " * 10_000, max_chars=1_000)

    decoded = json.loads(bounded)
    assert len(bounded) <= 1_000
    assert decoded["_context_budget"]["truncated"] is True
    assert decoded["payload_preview"].startswith("evidence evidence")
