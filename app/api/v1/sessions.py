from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from app.api.routes import _persist_upload
from app.api.v1.schemas import (
    MatchBriefRequest,
    MatchBriefResponse,
    ResumeAcceptedResponse,
    ResumeConfirmResponse,
    ResumeEducationPreview,
    ResumeExperiencePreview,
    ResumePreviewResponse,
    ResumeProjectPreview,
    SessionCreateRequest,
    SessionResponse,
)
from app.db.run_store import RunConflict, create_run, save_match_brief
from app.db.state_store import (
    confirm_resume,
    get_resume_metadata,
    load_state,
    mark_resume_normalized,
    save_state,
)
from app.domain.match_brief import create_match_brief
from app.normalization.resume_intake import intake_resume
from app.state.schema import SharedState


router = APIRouter()


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(request: SessionCreateRequest) -> SessionResponse:
    session_id = str(uuid.uuid4())
    await save_state(
        SharedState(session_id=session_id, user_id=request.user_id),
        status="awaiting_resume",
    )
    return SessionResponse(session_id=session_id, status="awaiting_resume")


@router.post(
    "/sessions/{session_id}/resume",
    response_model=ResumeAcceptedResponse,
    status_code=202,
)
async def upload_resume(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> ResumeAcceptedResponse:
    state = await load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    resume_path = await _persist_upload(session_id, file)
    await save_state(state, status="resume_queued")
    background_tasks.add_task(
        _normalize_resume,
        session_id=session_id,
        user_id=state.user_id,
        resume_path=resume_path,
    )
    return ResumeAcceptedResponse(session_id=session_id)


@router.get(
    "/sessions/{session_id}/resume-preview",
    response_model=ResumePreviewResponse,
)
async def resume_preview(session_id: str) -> ResumePreviewResponse:
    state = await load_state(session_id)
    metadata = await get_resume_metadata(session_id)
    if state is None or not metadata.get("exists"):
        raise HTTPException(status_code=404, detail="session_id not found")
    version = int(metadata.get("resume_version") or 0)
    if version < 1:
        raise HTTPException(status_code=409, detail="resume is not ready")
    resume = state.resume_state
    return ResumePreviewResponse(
        session_id=session_id,
        resume_version=version,
        confirmed=metadata.get("confirmed_resume_version") == version,
        education=[_education_preview(item) for item in resume.education],
        experience=[_experience_preview(item) for item in resume.experience],
        projects=[_project_preview(item) for item in resume.projects],
        skills=resume.skills,
        resume_quality_issues=resume.resume_quality_issues,
    )


@router.post(
    "/sessions/{session_id}/resume-confirm",
    response_model=ResumeConfirmResponse,
)
async def resume_confirm(session_id: str) -> ResumeConfirmResponse:
    current = await get_resume_metadata(session_id)
    if not current.get("exists"):
        raise HTTPException(status_code=404, detail="session_id not found")
    if int(current.get("resume_version") or 0) < 1:
        raise HTTPException(status_code=409, detail="resume is not ready")
    try:
        metadata = await confirm_resume(session_id=session_id)
    except KeyError:
        raise HTTPException(status_code=409, detail="resume is not ready") from None
    return ResumeConfirmResponse(
        session_id=session_id,
        resume_version=int(metadata["resume_version"]),
        confirmed=True,
        confirmed_at=metadata.get("resume_confirmed_at"),
    )


@router.post(
    "/sessions/{session_id}/match-brief",
    response_model=MatchBriefResponse,
    status_code=201,
)
async def build_match_brief(
    session_id: str, request: MatchBriefRequest
) -> MatchBriefResponse:
    metadata = await get_resume_metadata(session_id)
    if not metadata.get("exists"):
        raise HTTPException(status_code=404, detail="session_id not found")
    version = int(metadata.get("resume_version") or 0)
    if version < 1 or metadata.get("confirmed_resume_version") != version:
        raise HTTPException(status_code=409, detail="resume must be confirmed")

    brief = create_match_brief(
        career_goal=request.career_goal,
        hard_constraints=request.hard_constraints,
        soft_preferences=request.soft_preferences,
        avoid_roles=request.avoid_roles,
        result_count=request.result_count,
        conflicts=request.conflicts,
        needs_clarification=request.needs_clarification,
        clarification_question=request.clarification_question,
        plan_version=1,
    )
    try:
        run = await create_run(session_id=session_id)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await save_match_brief(run_id=run.run_id, brief=brief)
    return MatchBriefResponse(
        run_id=run.run_id,
        session_id=session_id,
        brief=brief,
    )


async def _normalize_resume(
    *, session_id: str, user_id: str, resume_path: Path
) -> None:
    try:
        result = await intake_resume(
            resume_path,
            session_id=session_id,
            user_id=user_id,
            save_to_db=False,
        )
        await save_state(result.state, status="resume_normalized")
        digest = hashlib.sha256(
            result.raw_text.encode("utf-8", errors="ignore")
        ).hexdigest()
        await mark_resume_normalized(session_id=session_id, content_hash=digest)
    except Exception:
        state = await load_state(session_id)
        if state is not None:
            await save_state(state, status="resume_error")


def _education_preview(item: dict) -> ResumeEducationPreview:
    return ResumeEducationPreview(
        institution=_text(item.get("institution")),
        degree=_text(item.get("degree")),
        field=_text(item.get("field")),
        dates=_text(item.get("dates")),
        details=_strings(item.get("details")),
        evidence_span_ids=_strings(item.get("evidence_span_ids")),
    )


def _experience_preview(item: dict) -> ResumeExperiencePreview:
    return ResumeExperiencePreview(
        organization=_text(item.get("organization")),
        title=_text(item.get("title")),
        dates=_text(item.get("dates")),
        location=_text(item.get("location")),
        responsibilities=_strings(item.get("responsibilities")),
        achievements=_strings(item.get("achievements")),
        technologies=_strings(item.get("technologies")),
        evidence_span_ids=_strings(item.get("evidence_span_ids")),
    )


def _project_preview(item: dict) -> ResumeProjectPreview:
    return ResumeProjectPreview(
        name=_text(item.get("name")),
        dates=_text(item.get("dates")),
        summary=_text(item.get("summary")),
        actions=_strings(item.get("actions")),
        technologies=_strings(item.get("technologies")),
        outcomes=_strings(item.get("outcomes")),
        evidence_span_ids=_strings(item.get("evidence_span_ids")),
    )


def _text(value: object) -> str:
    return str(value or "").strip()


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item))]
