from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.agents.orchestrator import run_persisted_agentic_match_from_session
from app.db.state_store import (
    add_feedback,
    load_state,
    load_state_with_status,
    mutate_state_atomically,
    save_state,
)
from app.memory.feedback_loop import process_feedback_closure_for_session
from app.memory.feedback import normalize_application_outcome
from app.normalization.resume_intake import intake_resume
from app.retrieval.query_builder import build_resume_retrieval_query
from app.state.schema import SharedState


router = APIRouter()
UPLOAD_DIR = Path("data/resumes/uploads")
ALLOWED_RESUME_SUFFIXES = {".pdf", ".docx", ".txt"}


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
    await save_state(
        SharedState(session_id=session_id, user_id=user_id),
        status="resume_queued",
    )
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

    await save_state(state, status="match_queued")
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
    if response["result_ready"]:
        response["state"] = state.model_dump(mode="json")
    return response


@router.get("/result/{session_id}")
async def read_result(session_id: str) -> dict:
    state_with_status = await load_state_with_status(session_id)
    if state_with_status is None:
        raise HTTPException(status_code=404, detail="session_id not found")

    state, status = state_with_status
    return {
        "session_id": session_id,
        "status": status,
        "state": state.model_dump(mode="json"),
    }


@router.post("/feedback", status_code=202)
async def submit_feedback(request: FeedbackRequest) -> dict:
    try:
        feedback_id = await add_feedback(
            session_id=request.session_id,
            job_id=request.job_id,
            outcome=request.outcome,
            reason=request.reason,
            user_rating=request.user_rating,
            idempotency_key=request.idempotency_key,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None

    feedback = {
        "feedback_id": feedback_id,
        "job_id": request.job_id,
        "outcome": request.outcome,
        "reason": request.reason,
        "user_rating": request.user_rating,
        "idempotency_key": request.idempotency_key,
    }
    try:
        result = await process_feedback_closure_for_session(
            session_id=request.session_id,
            feedback=feedback,
        )
    except Exception:
        await _record_feedback_closure_error(
            session_id=request.session_id,
            feedback_id=feedback_id,
        )
        return {
            "session_id": request.session_id,
            "feedback_id": feedback_id,
            "status": "feedback_recorded",
            "closure_status": "error",
            "case_written": False,
            "case_id": None,
            "soft_preference_updates": {},
            "error_code": "feedback_closure_failed",
        }

    response = {
        "session_id": request.session_id,
        "feedback_id": feedback_id,
        "status": "feedback_recorded",
        "closure_status": result.get("closure_status")
        or ("processed" if result["case_written"] else "skipped"),
        "case_written": bool(result["case_written"]),
        "case_id": (result.get("case") or {}).get("case_id"),
        "soft_preference_updates": result["soft_preference_updates"],
    }
    if result.get("error_code"):
        response["error_code"] = result["error_code"]
    return response


async def _run_resume_task(*, session_id: str, user_id: str, resume_path: Path) -> None:
    await save_state(
        SharedState(session_id=session_id, user_id=user_id),
        status="resume_running",
    )
    try:
        result = await intake_resume(
            resume_path,
            session_id=session_id,
            user_id=user_id,
            save_to_db=True,
        )
        await save_state(result.state, status="resume_ready")
    except Exception as exc:  # pragma: no cover - defensive background safety
        await _record_background_error(
            session_id=session_id,
            user_id=user_id,
            status="resume_error",
            error=exc,
        )


async def _run_match_task(
    *, session_id: str, user_goal_text: str, top_k: int, include_raptor: bool
) -> None:
    state = await load_state(session_id)
    if state is None:
        return

    await save_state(state, status="match_running")
    try:
        await run_persisted_agentic_match_from_session(
            session_id=session_id,
            user_goal_text=user_goal_text,
            top_k=top_k,
            include_raptor=include_raptor,
        )
    except Exception as exc:  # pragma: no cover - defensive background safety
        await _record_background_error(
            session_id=session_id,
            user_id=state.user_id,
            status="match_error",
            error=exc,
        )


async def _record_background_error(
    *, session_id: str, user_id: str, status: str, error: Exception
) -> None:
    state = await load_state(session_id) or SharedState(
        session_id=session_id,
        user_id=user_id,
    )
    state.supervisor_log.append(
        {
            "stage": "api_background_task",
            "status": status,
            "error_type": type(error).__name__,
            "error_code": "background_task_failed",
        }
    )
    await save_state(state, status=status)


async def _record_feedback_closure_error(
    *, session_id: str, feedback_id: int
) -> None:
    try:
        def append_error_log(state: SharedState) -> None:
            for entry in state.feedback_state.user_feedback:
                if str(entry.get("feedback_id")) == str(feedback_id):
                    entry["closure_status"] = "error"
                    entry["case_written"] = False
                    entry["case_id"] = None
                    entry["error_code"] = "feedback_closure_failed"
                    break
            state.supervisor_log.append(
                {
                    "stage": "feedback_closure_error",
                    "feedback_id": feedback_id,
                    "error_code": "feedback_closure_failed",
                }
            )

        await mutate_state_atomically(
            session_id=session_id,
            mutator=append_error_log,
        )
    except Exception:
        return


async def _persist_upload(session_id: str, file: UploadFile) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_RESUME_SUFFIXES:
        suffix = ".txt"

    path = UPLOAD_DIR / f"{_safe_id(session_id)}{suffix}"
    content = await file.read()
    path.write_bytes(content)
    await file.close()
    return path


def _safe_id(raw: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return safe[:120] or "session"


def _resume_ready_for_matching(state: SharedState) -> bool:
    return bool(build_resume_retrieval_query(state.resume_state).text.strip())
