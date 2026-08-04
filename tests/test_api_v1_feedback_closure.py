from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.domain.run import RunStatus


def _feedback_write_result(
    *, feedback_id: int, created: bool = True, **feedback
) -> SimpleNamespace:
    return SimpleNamespace(
        feedback_id=feedback_id,
        created=created,
        feedback={"feedback_id": feedback_id, **feedback},
    )


def _reaction_app() -> FastAPI:
    from app.api.v1.feedback import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def _patch_completed_run(monkeypatch, feedback_module) -> None:
    async def fake_get_run(*, run_id: str):
        assert run_id == "run-1"
        return SimpleNamespace(
            run_id=run_id,
            session_id="session-1",
            status=RunStatus.COMPLETED,
            result_snapshot={"recommended_roles": [{"job_id": "job-1"}]},
        )

    monkeypatch.setattr(feedback_module, "get_run", fake_get_run)


async def _post_reaction(**overrides):
    payload = {
        "job_id": "job-1",
        "outcome": "offer",
        "reason": "strong fit",
        "user_rating": 5,
        "idempotency_key": "reaction-1",
    }
    payload.update(overrides)
    transport = httpx.ASGITransport(app=_reaction_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        return await client.post("/api/v1/runs/run-1/reaction", json=payload)


@pytest.mark.asyncio
async def test_v1_reaction_processes_closure_after_durable_feedback_write(
    monkeypatch,
):
    from app.api.v1 import feedback

    calls = []
    persisted_feedback = {
        "job_id": "job-1",
        "outcome": "offer",
        "reason": "strong fit",
        "user_rating": 5,
        "idempotency_key": "reaction-1",
    }

    async def fake_add_feedback(**kwargs):
        calls.append(("add_feedback", kwargs))
        return _feedback_write_result(feedback_id=10, **persisted_feedback)

    async def fake_process_closure(*, session_id, feedback):
        calls.append(("closure", session_id, feedback))
        return {
            "closure_status": "processed",
            "case_written": True,
            "case": {"case_id": "case-10"},
            "soft_preference_updates": {},
        }

    _patch_completed_run(monkeypatch, feedback)
    monkeypatch.setattr(feedback, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        feedback,
        "process_feedback_closure_for_session",
        fake_process_closure,
        raising=False,
    )

    response = await _post_reaction()

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "run-1",
        "feedback_id": 10,
        "status": "reaction_recorded",
    }
    assert calls == [
        (
            "add_feedback",
            {
                "session_id": "session-1",
                **persisted_feedback,
            },
        ),
        (
            "closure",
            "session-1",
            {"feedback_id": 10, **persisted_feedback},
        ),
    ]


@pytest.mark.asyncio
async def test_v1_reaction_keeps_partial_case_write_out_of_response(
    monkeypatch,
):
    from app.api.v1 import feedback

    closure_calls = []

    async def fake_add_feedback(**kwargs):
        return _feedback_write_result(feedback_id=11, **kwargs)

    async def fake_process_closure(**kwargs):
        closure_calls.append(kwargs)
        return {
            "closure_status": "error",
            "error_code": "similar_case_search_failed",
            "case_written": True,
            "case": {"case_id": "case-11"},
            "soft_preference_updates": {},
        }

    _patch_completed_run(monkeypatch, feedback)
    monkeypatch.setattr(feedback, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        feedback,
        "process_feedback_closure_for_session",
        fake_process_closure,
        raising=False,
    )

    response = await _post_reaction()

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "run-1",
        "feedback_id": 11,
        "status": "reaction_recorded",
    }
    assert closure_calls[0]["session_id"] == "session-1"
    assert closure_calls[0]["feedback"]["feedback_id"] == 11


@pytest.mark.asyncio
async def test_v1_reaction_does_not_reprocess_completed_idempotent_feedback(
    monkeypatch,
):
    from app.api.v1 import feedback

    closure_calls = []

    async def fake_add_feedback(**_kwargs):
        return _feedback_write_result(
            feedback_id=12,
            created=False,
            job_id="job-1",
            outcome="offer",
            reason="strong fit",
            user_rating=5,
            idempotency_key="reaction-1",
            closure_status="processed",
            case_written=True,
            case_id="case-12",
        )

    async def fake_process_closure(**kwargs):
        closure_calls.append(kwargs)
        return {"closure_status": "processed"}

    _patch_completed_run(monkeypatch, feedback)
    monkeypatch.setattr(feedback, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        feedback,
        "process_feedback_closure_for_session",
        fake_process_closure,
        raising=False,
    )

    response = await _post_reaction()

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "run-1",
        "feedback_id": 12,
        "status": "reaction_recorded",
    }
    assert closure_calls == []


@pytest.mark.asyncio
async def test_v1_reaction_retries_failed_closure_with_persisted_payload(
    monkeypatch,
):
    from app.api.v1 import feedback

    persisted_feedback = {
        "feedback_id": 13,
        "job_id": "job-1",
        "outcome": "offer",
        "reason": "strong fit",
        "user_rating": 5,
        "idempotency_key": "reaction-1",
        "closure_status": "error",
        "case_written": False,
        "case_id": None,
        "error_code": "case_upsert_failed",
    }
    closure_calls = []

    async def fake_add_feedback(**_kwargs):
        return SimpleNamespace(
            feedback_id=13,
            created=False,
            feedback=dict(persisted_feedback),
        )

    async def fake_process_closure(*, session_id, feedback):
        closure_calls.append((session_id, feedback))
        return {
            "closure_status": "processed",
            "case_written": True,
            "case": {"case_id": "case-13"},
            "soft_preference_updates": {},
        }

    _patch_completed_run(monkeypatch, feedback)
    monkeypatch.setattr(feedback, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        feedback,
        "process_feedback_closure_for_session",
        fake_process_closure,
        raising=False,
    )

    response = await _post_reaction()

    assert response.status_code == 202
    assert closure_calls == [("session-1", persisted_feedback)]
    assert response.json() == {
        "run_id": "run-1",
        "feedback_id": 13,
        "status": "reaction_recorded",
    }


@pytest.mark.asyncio
async def test_v1_reaction_records_closure_error_after_durable_feedback_write(
    monkeypatch,
):
    from app.api.v1 import feedback

    calls = []
    persisted_feedback = {
        "feedback_id": 14,
        "job_id": "job-1",
        "outcome": "offer",
        "reason": "strong fit",
        "user_rating": 5,
        "idempotency_key": "reaction-1",
    }

    async def fake_add_feedback(**_kwargs):
        calls.append("add_feedback")
        return SimpleNamespace(
            feedback_id=14,
            created=True,
            feedback=dict(persisted_feedback),
        )

    async def fail_process_closure(**_kwargs):
        calls.append("closure")
        raise RuntimeError("private closure failure")

    async def fake_record_error(**kwargs):
        calls.append(("record_error", kwargs))
        return {"closure_status": "error"}

    _patch_completed_run(monkeypatch, feedback)
    monkeypatch.setattr(feedback, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        feedback,
        "process_feedback_closure_for_session",
        fail_process_closure,
        raising=False,
    )
    monkeypatch.setattr(
        feedback,
        "record_feedback_closure_error",
        fake_record_error,
        raising=False,
    )

    response = await _post_reaction()

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "run-1",
        "feedback_id": 14,
        "status": "reaction_recorded",
    }
    assert calls == [
        "add_feedback",
        "closure",
        (
            "record_error",
            {
                "session_id": "session-1",
                "feedback_id": 14,
                "persisted_feedback": persisted_feedback,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_v1_reaction_error_record_preserves_prior_durable_case(
    monkeypatch,
):
    from app.api.v1 import feedback
    from app.memory import feedback_loop
    from app.state.schema import SharedState

    state = SharedState(session_id="session-1", user_id="user-1")
    state.feedback_state.user_feedback = [
        {
            "feedback_id": 15,
            "job_id": "job-1",
            "outcome": "offer",
            "idempotency_key": "reaction-1",
            "closure_status": "error",
            "case_written": True,
            "case_id": "case-durable-15",
            "error_code": "similar_case_search_failed",
        }
    ]

    async def fake_add_feedback(**_kwargs):
        return SimpleNamespace(
            feedback_id=15,
            created=False,
            feedback=dict(state.feedback_state.user_feedback[0]),
        )

    async def fail_process_closure(**_kwargs):
        raise RuntimeError("private retry failure")

    async def fake_mutate_state_atomically(*, session_id, mutator):
        assert session_id == "session-1"
        return mutator(state)

    _patch_completed_run(monkeypatch, feedback)
    monkeypatch.setattr(feedback, "add_feedback", fake_add_feedback)
    monkeypatch.setattr(
        feedback,
        "process_feedback_closure_for_session",
        fail_process_closure,
        raising=False,
    )
    monkeypatch.setattr(
        feedback_loop,
        "mutate_state_atomically",
        fake_mutate_state_atomically,
    )

    response = await _post_reaction()

    assert response.status_code == 202
    assert response.json() == {
        "run_id": "run-1",
        "feedback_id": 15,
        "status": "reaction_recorded",
    }
    persisted = state.feedback_state.user_feedback[0]
    assert persisted["closure_status"] == "error"
    assert persisted["case_written"] is True
    assert persisted["case_id"] == "case-durable-15"
    assert persisted["error_code"] == "feedback_closure_failed"
    assert state.supervisor_log[-1]["case_written"] is True
    assert state.supervisor_log[-1]["case_id"] == "case-durable-15"
    assert "private retry failure" not in str(state.model_dump())
