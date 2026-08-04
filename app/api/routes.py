from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.agents.orchestrator import run_persisted_agentic_match_from_session
from app.api.uploads import (
    ALLOWED_RESUME_SUFFIXES,
    MAX_RESUME_UPLOAD_BYTES,
    UPLOAD_CHUNK_BYTES,
    UPLOAD_DIR,
    persist_upload,
)
from app.db.state_store import (
    FeedbackIdempotencyConflict,
    add_feedback,
    load_state,
    load_state_with_status,
    mutate_state_atomically,
    save_state,
)
from app.api.result_projector import project_product_result
from app.memory.feedback_loop import (
    process_feedback_closure_for_session,
    record_feedback_closure_error,
)
from app.memory.feedback import normalize_application_outcome
from app.normalization.resume_intake import intake_resume
from app.retrieval.query_builder import build_resume_retrieval_query
from app.state.schema import SharedState


router = APIRouter()


class MatchRequest(BaseModel):
    session_id: str = Field(min_length=1)
    user_goal_text: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=50)
    include_raptor: bool = False


class FeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1)
    job_id: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    reason: str | None = None
    user_rating: int | None = Field(default=None, ge=1, le=5)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("outcome")
    @classmethod
    def validate_outcome(cls, value: str) -> str:
        return normalize_application_outcome(value)


@router.post("/resume", status_code=202)
async def upload_resume(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    user_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, str]:
    resume_path = await _persist_upload(session_id, file)
    try:
        await save_state(
            SharedState(session_id=session_id, user_id=user_id),
            status="resume_queued",
        )
    except Exception:
        resume_path.unlink(missing_ok=True)
        raise
    background_tasks.add_task(
        _run_resume_task,
        session_id=session_id,
        user_id=user_id,
        resume_path=resume_path,
    )
    return {"session_id": session_id, "status": "resume_queued"}


@router.post("/match", status_code=202)
async def submit_match(
    request: MatchRequest, background_tasks: BackgroundTasks
) -> dict[str, str]:
    state_with_status = await load_state_with_status(request.session_id)
    if state_with_status is None:
        raise HTTPException(status_code=404, detail="session_id not found")

    state, _status = state_with_status
    if not _resume_ready_for_matching(state):
        raise HTTPException(
            status_code=409,
            detail="resume is not ready for matching",
        )

    await mutate_state_atomically(
        session_id=request.session_id,
        mutator=lambda _state: None,
        status="match_queued",
    )
    background_tasks.add_task(
        _run_match_task,
        session_id=request.session_id,
        user_goal_text=request.user_goal_text,
        top_k=request.top_k,
        include_raptor=request.include_raptor,
    )
    return {"session_id": request.session_id, "status": "match_queued"}


@router.get("/status/{session_id}")
async def read_status(session_id: str) -> dict:
    state_with_status = await load_state_with_status(session_id)
    if state_with_status is None:
        raise HTTPException(status_code=404, detail="session_id not found")

    state, status = state_with_status
    response = {
        "session_id": session_id,
        "status": status,
        "result_ready": status == "agentic_done",
    }
    # 公共响应只暴露投影后的产品结果，不返回原始 SharedState。
    if response["result_ready"]:
        response["result"] = project_product_result(state).model_dump(mode="json")
    return response


@router.get("/result/{session_id}")
async def read_result(session_id: str) -> dict:
    state_with_status = await load_state_with_status(session_id)
    if state_with_status is None:
        raise HTTPException(status_code=404, detail="session_id not found")

    state, status = state_with_status
    if status != "agentic_done":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "session result is not ready",
                "recovery": {
                    "action": "poll_status",
                    "status_url": f"/status/{session_id}",
                },
            },
        )
    # 公共响应只暴露投影后的产品结果，不返回原始 SharedState。
    return {
        "session_id": session_id,
        "status": status,
        "result": project_product_result(state).model_dump(mode="json"),
    }


@router.post("/feedback", status_code=202)
async def submit_feedback(request: FeedbackRequest) -> dict:
    try:
        write_result = await add_feedback(
            session_id=request.session_id,
            job_id=request.job_id,
            outcome=request.outcome,
            reason=request.reason,
            user_rating=request.user_rating,
            idempotency_key=request.idempotency_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    except FeedbackIdempotencyConflict:
        raise HTTPException(
            status_code=409,
            detail="idempotency key payload conflict",
        ) from None

    feedback_id = write_result.feedback_id
    feedback = dict(write_result.feedback)
    if not write_result.created and feedback.get("closure_status") in {
        "processed",
        "skipped",
    }:
        return _build_feedback_response(
            session_id=request.session_id,
            feedback_id=feedback_id,
            result={
                "closure_status": feedback["closure_status"],
                "case_written": bool(feedback.get("case_written")),
                "case_id": feedback.get("case_id"),
                "soft_preference_updates": {},
                "error_code": feedback.get("error_code"),
            },
        )

    try:
        result = await process_feedback_closure_for_session(
            session_id=request.session_id,
            feedback=feedback,
        )
    except Exception:
        error_result = await _record_feedback_closure_error(
            session_id=request.session_id,
            feedback_id=feedback_id,
            persisted_feedback=feedback,
        )
        return _build_feedback_response(
            session_id=request.session_id,
            feedback_id=feedback_id,
            result=error_result,
        )

    return _build_feedback_response(
        session_id=request.session_id,
        feedback_id=feedback_id,
        result=result,
    )


def _build_feedback_response(
    *, session_id: str, feedback_id: int, result: dict
) -> dict:
    response = {
        "session_id": session_id,
        "feedback_id": feedback_id,
        "status": "feedback_recorded",
        "closure_status": result.get("closure_status")
        or ("processed" if result["case_written"] else "skipped"),
        "case_written": bool(result["case_written"]),
        "case_id": result.get("case_id")
        or (result.get("case") or {}).get("case_id"),
        "soft_preference_updates": result["soft_preference_updates"],
    }
    if result.get("error_code"):
        response["error_code"] = result["error_code"]
    return response


async def _run_resume_task(*, session_id: str, user_id: str, resume_path: Path) -> None:
    try:
        await mutate_state_atomically(
            session_id=session_id,
            mutator=lambda _state: None,
            status="resume_running",
        )
        result = await intake_resume(
            resume_path,
            session_id=session_id,
            user_id=user_id,
            save_to_db=False,
        )
        resume_state = result.state.resume_state.model_copy(deep=True)
        await mutate_state_atomically(
            session_id=session_id,
            mutator=lambda state: setattr(
                state,
                "resume_state",
                resume_state.model_copy(deep=True),
            ),
            status="resume_ready",
        )
    except Exception as exc:  # pragma: no cover - defensive background safety
        try:
            await _record_background_error(
                session_id=session_id,
                user_id=user_id,
                status="resume_error",
                error=exc,
            )
        except Exception:
            pass
    finally:
        resume_path.unlink(missing_ok=True)


async def _run_match_task(
    *, session_id: str, user_goal_text: str, top_k: int, include_raptor: bool
) -> None:
    state: SharedState | None = None
    try:
        state = await load_state(session_id)
        if state is None:
            raise KeyError(session_id)
        await mutate_state_atomically(
            session_id=session_id,
            mutator=lambda _state: None,
            status="match_running",
        )
        await run_persisted_agentic_match_from_session(
            session_id=session_id,
            user_goal_text=user_goal_text,
            top_k=top_k,
            include_raptor=include_raptor,
        )
    except Exception as exc:  # pragma: no cover - defensive background safety
        try:
            await _record_background_error(
                session_id=session_id,
                user_id=state.user_id if state is not None else "unknown",
                status="match_error",
                error=exc,
            )
        except Exception:
            pass


async def _record_background_error(
    *, session_id: str, user_id: str, status: str, error: Exception
) -> None:
    entry = {
            "stage": "api_background_task",
            "status": status,
            "error_type": type(error).__name__,
            "error_code": "background_task_failed",
        }

    def append_error(state: SharedState) -> None:
        state.supervisor_log.append(deepcopy(entry))

    try:
        await mutate_state_atomically(
            session_id=session_id,
            mutator=append_error,
            status=status,
        )
    except KeyError:
        state = SharedState(session_id=session_id, user_id=user_id)
        state.supervisor_log.append(entry)
        await save_state(state, status=status)


async def _record_feedback_closure_error(
    *,
    session_id: str,
    feedback_id: int,
    persisted_feedback: dict | None = None,
) -> dict:
    return await record_feedback_closure_error(
        session_id=session_id,
        feedback_id=feedback_id,
        persisted_feedback=persisted_feedback,
        mutate_state=mutate_state_atomically,
    )


async def _persist_upload(session_id: str, file: UploadFile) -> Path:
    return await persist_upload(
        session_id,
        file,
        upload_dir=UPLOAD_DIR,
        allowed_suffixes=ALLOWED_RESUME_SUFFIXES,
        max_upload_bytes=MAX_RESUME_UPLOAD_BYTES,
        chunk_bytes=UPLOAD_CHUNK_BYTES,
    )


def _resume_ready_for_matching(state: SharedState) -> bool:
    return bool(build_resume_retrieval_query(state.resume_state).text.strip())
