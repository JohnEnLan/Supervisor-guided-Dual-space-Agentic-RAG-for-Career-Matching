from __future__ import annotations

import hashlib
import uuid
from copy import deepcopy
from pathlib import Path
import re

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)

from app.api.auth.deps import optional_current_user, require_owned_session
from app.api.auth.routes import load_profile, merge_profile
from app.api.auth.sessions import AuthedUser
from app.api.uploads import persist_upload
from app.api.v1.schemas import (
    ConsultBriefDraftResponse,
    ConsultRequest,
    ConsultResponse,
    ConsultStateResponse,
    MatchBriefRequest,
    MatchBriefResponse,
    ResumeAcceptedResponse,
    ResumeConfirmResponse,
    ResumeEducationPreview,
    ResumeEvidencePreview,
    ResumeExperiencePreview,
    ResumePreviewResponse,
    ResumeProjectPreview,
    SessionCreateRequest,
    SessionResponse,
)
from app.agents.consult_engine import (
    ConsultError,
    ConsultResponseError,
    ConsultRoundLimitReached,
    build_brief_draft,
    calculate_completeness,
    can_finalize,
    determine_phase,
    profile_draft,
    run_consult_round,
)
from app.db.run_store import RunConflict, create_run, save_match_brief
from app.config import settings
from app.db.state_store import (
    confirm_resume,
    count_owned_sessions,
    get_resume_metadata,
    load_state,
    mutate_state_atomically,
    save_normalized_resume,
    save_state,
)
from app.domain.match_brief import create_match_brief
from app.normalization.resume_intake import intake_resume
from app.state.schema import SharedState


router = APIRouter()
_INTENT_CAREER_FIELDS = (
    "current_goal",
    "long_term_goal",
    "hard_constraints",
    "soft_preferences",
    "avoid_roles",
    "intent_mode",
    "intent_consulted",
    "intent_assistant_message",
    "intent_directions",
    "intent_needs_clarification",
    "intent_clarification_question",
    "intent_clarification_used",
    "consult_transcript",
    "consult_rounds_used",
)


class _ConsultRoundConflict(ValueError):
    pass


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=201,
    responses={402: {"description": "session quota exhausted"}},
)
async def create_session(
    user: Annotated[
        AuthedUser | None,
        Depends(optional_current_user),
    ],
    request: SessionCreateRequest | None = None,
) -> SessionResponse:
    # 每账号会话额度（默认 3）：超额返回 402，前端展示付费墙弹窗。
    # 兼容模式的匿名会话不计额度（仅 development/test 存在）。
    if user is not None:
        owned = await count_owned_sessions(user.user_id)
        if owned >= settings.session_quota_per_user:
            raise HTTPException(
                status_code=402, detail="session_quota_exceeded"
            )
    session_id = str(uuid.uuid4())
    resolved_user_id = user.user_id if user is not None else session_id
    await save_state(
        SharedState(session_id=session_id, user_id=resolved_user_id),
        status="awaiting_resume",
        owner_user_id=user.user_id if user is not None else None,
    )
    return SessionResponse(session_id=session_id, status="awaiting_resume")


@router.post(
    "/sessions/{session_id}/resume",
    response_model=ResumeAcceptedResponse,
    status_code=202,
    dependencies=[Depends(require_owned_session)],
)
async def upload_resume(
    session_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> ResumeAcceptedResponse:
    state = await load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    resume_path = await persist_upload(session_id, file)
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
    dependencies=[Depends(require_owned_session)],
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
        evidence=_resume_evidence_preview(resume),
    )


@router.post(
    "/sessions/{session_id}/resume-confirm",
    response_model=ResumeConfirmResponse,
    dependencies=[Depends(require_owned_session)],
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


@router.get(
    "/sessions/{session_id}/consult",
    response_model=ConsultStateResponse,
    dependencies=[Depends(require_owned_session)],
)
async def get_consultation(session_id: str) -> ConsultStateResponse:
    state = await load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    career = state.career_state
    mode = career.intent_mode or "targeted"
    return ConsultStateResponse(
        transcript=career.consult_transcript,
        profile_draft=profile_draft(career),
        round=career.consult_rounds_used,
        phase=determine_phase(career, mode=mode),
        completeness=calculate_completeness(career),
        can_finalize=can_finalize(career),
    )


@router.post(
    "/sessions/{session_id}/consult",
    response_model=ConsultResponse,
    dependencies=[Depends(require_owned_session)],
)
async def continue_consultation(
    session_id: str,
    request: ConsultRequest,
    user: Annotated[AuthedUser | None, Depends(optional_current_user)],
) -> ConsultResponse:
    turn, _persisted = await _execute_consult_round(
        session_id=session_id,
        mode=request.mode,
        message=request.message,
        expected_round=request.expected_round,
        status="intent_consulting",
        user_id=user.user_id if user is not None else None,
    )
    return ConsultResponse.model_validate(turn.__dict__)


@router.post(
    "/sessions/{session_id}/consult/finalize",
    response_model=ConsultBriefDraftResponse,
    dependencies=[Depends(require_owned_session)],
)
async def finalize_consultation(
    session_id: str,
) -> ConsultBriefDraftResponse:
    state = await load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    try:
        draft = build_brief_draft(state.career_state)
    except ConsultError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return ConsultBriefDraftResponse.model_validate(draft)


@router.post(
    "/sessions/{session_id}/match-brief",
    response_model=MatchBriefResponse,
    status_code=201,
    dependencies=[Depends(require_owned_session)],
)
async def build_match_brief(
    session_id: str,
    request: MatchBriefRequest,
    user: Annotated[AuthedUser | None, Depends(optional_current_user)],
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
    def persist_match_brief(state: SharedState) -> dict:
        state.career_state.current_goal = [request.career_goal]
        state.career_state.hard_constraints = dict(request.hard_constraints)
        state.career_state.soft_preferences = dict(request.soft_preferences)
        state.career_state.avoid_roles = list(request.avoid_roles)
        state.career_state.intent_consulted = True
        return profile_draft(state.career_state)

    try:
        confirmed_profile = await mutate_state_atomically(
            session_id=session_id,
            mutator=persist_match_brief,
            status="match_brief_approved",
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    try:
        run = await create_run(session_id=session_id)
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await save_match_brief(run_id=run.run_id, brief=brief)
    if user is not None:
        await merge_profile(user.user_id, confirmed_profile)
    return MatchBriefResponse(
        run_id=run.run_id,
        session_id=session_id,
        brief=brief,
    )


async def _execute_consult_round(
    *,
    session_id: str,
    mode: str,
    message: str,
    expected_round: int,
    status: str | None,
    user_id: str | None = None,
):
    state = await load_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    if state.career_state.consult_rounds_used != expected_round:
        raise HTTPException(status_code=409, detail="consultation round conflict")
    if state.career_state.intent_consulted:
        raise HTTPException(status_code=409, detail="consultation round conflict")

    working = state.model_copy(deep=True)
    remembered_profile = None
    if user_id is not None and expected_round == 0:
        stored_profile = await load_profile(user_id)
        if stored_profile is not None and isinstance(
            stored_profile.get("profile"), dict
        ):
            remembered_profile = dict(stored_profile["profile"])
    try:
        consult_kwargs = {}
        if remembered_profile:
            consult_kwargs["remembered_profile"] = remembered_profile
        turn = await run_consult_round(
            working,
            mode=mode,
            message=message,
            **consult_kwargs,
        )
    except ConsultRoundLimitReached as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except ConsultResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None

    persisted_status = status or (
        "intent_consulted" if turn.can_finalize else "intent_clarification"
    )

    def persist_turn(latest: SharedState) -> SharedState:
        if (
            latest.career_state.consult_rounds_used != expected_round
            or latest.career_state.intent_consulted
        ):
            raise _ConsultRoundConflict(expected_round)
        for field_name in _INTENT_CAREER_FIELDS:
            setattr(
                latest.career_state,
                field_name,
                deepcopy(getattr(working.career_state, field_name)),
            )
        return latest.model_copy(deep=True)

    try:
        persisted = await mutate_state_atomically(
            session_id=session_id,
            mutator=persist_turn,
            status=persisted_status,
        )
    except _ConsultRoundConflict:
        raise HTTPException(
            status_code=409,
            detail="consultation round conflict",
        ) from None
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    return turn, persisted


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
        digest = hashlib.sha256(
            result.raw_text.encode("utf-8", errors="ignore")
        ).hexdigest()
        await save_normalized_resume(
            session_id=session_id,
            resume_state=result.state.resume_state,
            content_hash=digest,
        )
    except Exception:
        try:
            await mutate_state_atomically(
                session_id=session_id,
                mutator=lambda _state: None,
                status="resume_error",
            )
        except KeyError:
            pass
    finally:
        resume_path.unlink(missing_ok=True)


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


def _resume_evidence_preview(resume) -> list[ResumeEvidencePreview]:
    referenced_ids: set[str] = set()
    for section in (resume.education, resume.experience, resume.projects):
        for item in section:
            if isinstance(item, dict):
                referenced_ids.update(_strings(item.get("evidence_span_ids")))

    evidence: list[ResumeEvidencePreview] = []
    for span in resume.original_evidence_spans:
        if not isinstance(span, dict):
            continue
        span_id = _text(span.get("span_id") or span.get("id"))
        content = _redact_contact_text(_text(span.get("text")))
        if span_id in referenced_ids and content:
            evidence.append(
                ResumeEvidencePreview(
                    evidence_span_id=span_id,
                    content=content,
                )
            )
    return evidence


def _redact_contact_text(text: str) -> str:
    text = re.sub(
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        "[email hidden]",
        text,
        flags=re.IGNORECASE,
    )

    def redact_phone(match: re.Match[str]) -> str:
        candidate = match.group(0)
        if re.fullmatch(
            r"(?:19|20)\d{2}\s*[-–—]\s*(?:19|20)\d{2}",
            candidate.strip(),
        ):
            return candidate
        return "[phone hidden]"

    return re.sub(
        r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)",
        redact_phone,
        text,
    )
