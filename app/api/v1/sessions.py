from __future__ import annotations

import asyncio
import hashlib
import logging
import time
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
from app.api.uploads import read_resume_upload
from app.api.v1.schemas import (
    ClarificationProgress,
    ConsultBriefDraftResponse,
    ConsultRequest,
    ConsultResponse,
    ConsultStateResponse,
    MatchBriefRequest,
    MatchBriefResponse,
    ResumeAcceptedResponse,
    ResumeConfirmRequest,
    ResumeConfirmResponse,
    ResumeEducationPreview,
    ResumeEvidencePreview,
    ResumeExperiencePreview,
    ResumeParseRequest,
    ResumePreviewResponse,
    ResumeProgressEvent,
    ResumeProgressResponse,
    ResumeProjectPreview,
    ResumeLifecycleConflictResponse,
    ResumeUploadedResponse,
    ResumeUploadRejectedResponse,
    ResumeVersionRequiredResponse,
    RequestValidationErrorResponse,
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
from app.agents.consult_coach import (
    CoachAttemptOutcome,
    CoachReservationConflict,
    evaluate_consult_l1,
    finalize_coach_reservation,
    merge_coach_reservations,
    merge_consult_transcript,
    reserve_coach_attempt,
    run_consult_coach,
)
from app.db.run_store import RunConflict, create_run, save_match_brief
from app.config import settings
from app.db.state_store import (
    MutationOutcome,
    ResumeLifecycleConflict,
    TerminalEvent,
    accept_resume_upload,
    begin_resume_parse,
    clear_resume_upload_content,
    confirm_resume,
    create_owned_session_with_quota,
    get_pending_resume_upload,
    get_resume_metadata,
    load_consult_context,
    load_intake_progress,
    load_state,
    mutate_state_atomically,
    mark_resume_error,
    record_intake_progress,
    refund_parse_count,
    save_normalized_resume,
    save_state,
)
from app.domain.match_brief import create_match_brief
from app.normalization.resume_intake import (
    build_evidence_spans,
    extract_resume_text_from_bytes,
    normalize_resume_text,
)
from app.state.schema import ResumeState, SharedState


logger = logging.getLogger(__name__)


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


class _ResumeChangedConflict(ValueError):
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
    session_id = str(uuid.uuid4())
    resolved_user_id = user.user_id if user is not None else session_id
    state = SharedState(session_id=session_id, user_id=resolved_user_id)
    if user is not None:
        created = await create_owned_session_with_quota(
            state,
            owner_user_id=user.user_id,
            quota=settings.session_quota_per_user,
        )
        if not created:
            raise HTTPException(
                status_code=402, detail="session_quota_exceeded"
            )
    else:
        await save_state(
            state,
            status="awaiting_resume",
            owner_user_id=None,
        )
    return SessionResponse(session_id=session_id, status="awaiting_resume")


# B2：ocr_suggested 路由提示阈值（B4 引入 RESUME_OCR_* 配置前的常量）
_OCR_SUGGEST_MIN_CHARS = 150
_TEXT_PREVIEW_CHARS = 600


def _upload_response(
    session_id: str,
    *,
    generation: int,
    filename: str,
    extracted_text: str,
    pages: int,
    chars: int,
    ocr_suggested: bool,
    parses_used: int,
) -> ResumeUploadedResponse:
    return ResumeUploadedResponse(
        session_id=session_id,
        generation=generation,
        filename=filename,
        pages=pages,
        chars=chars,
        # 先对全文脱敏再截断：600 字边界穿过电话/邮箱时不得泄漏半截 token
        text_preview=_redact_contact_text(extracted_text)[:_TEXT_PREVIEW_CHARS],
        parses_used=parses_used,
        parses_limit=settings.resume_parse_limit,
        ocr_suggested=ocr_suggested,
    )


@router.post(
    "/sessions/{session_id}/resume",
    response_model=ResumeUploadedResponse,
    responses={
        413: {"description": "resume file exceeds upload size limit"},
        415: {"model": ResumeUploadRejectedResponse},
        # 422 = anyOf(稳定 detail 契约, FastAPI 默认校验数组形态)——multipart
        # 缺失/非法走后者，与 resume-confirm 的加性契约模式一致。
        422: {"model": ResumeUploadRejectedResponse | RequestValidationErrorResponse},
    },
    dependencies=[Depends(require_owned_session)],
)
async def upload_resume(
    session_id: str,
    file: UploadFile = File(...),
) -> ResumeUploadedResponse:
    """B2 上传确认流：存库 + 本地提取（零 LLM），等待用户「确认解析」。"""
    filename, suffix, content = await read_resume_upload(file)
    try:
        extracted_text, pages = await asyncio.to_thread(
            extract_resume_text_from_bytes, content, suffix
        )
    except Exception:
        # 损坏/不可解析：不入库、不占 generation、不扣额度。
        # 完整堆栈落日志——解析器自身的程序性缺陷不允许被 422 静默吞没。
        logger.warning(
            "resume extraction failed for %s (%s)", session_id, suffix, exc_info=True
        )
        raise HTTPException(status_code=422, detail="unreadable_file") from None
    chars = len(extracted_text)
    ocr_suggested = chars < _OCR_SUGGEST_MIN_CHARS
    try:
        accepted = await accept_resume_upload(
            session_id=session_id,
            filename=filename,
            suffix=suffix,
            content=content,
            extracted_text=extracted_text,
            pages=pages,
            chars=chars,
            ocr_suggested=ocr_suggested,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    return _upload_response(
        session_id,
        generation=int(accepted["resume_upload_generation"]),
        filename=filename,
        extracted_text=extracted_text,
        pages=pages,
        chars=chars,
        ocr_suggested=ocr_suggested,
        parses_used=int(accepted["resume_parse_count"]),
    )


@router.get(
    "/sessions/{session_id}/resume-upload",
    response_model=ResumeUploadedResponse,
    dependencies=[Depends(require_owned_session)],
)
async def pending_resume_upload(session_id: str) -> ResumeUploadedResponse:
    """刷新恢复：仅 resume_uploaded 态返回待解析上传元数据，否则 404。"""
    pending = await get_pending_resume_upload(session_id=session_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="no pending resume upload")
    return _upload_response(
        session_id,
        generation=int(pending["generation"]),
        filename=str(pending["filename"]),
        extracted_text=str(pending["extracted_text"] or ""),
        pages=int(pending["pages"]),
        chars=int(pending["chars"]),
        ocr_suggested=bool(pending["ocr_suggested"]),
        parses_used=int(pending["resume_parse_count"]),
    )


@router.get(
    "/sessions/{session_id}/resume-progress",
    response_model=ResumeProgressResponse,
    dependencies=[Depends(require_owned_session)],
)
async def resume_progress(session_id: str) -> ResumeProgressResponse:
    """B3 解析进度轮询：当前代全量事件（ORDER BY seq，≤100 行无需游标）。
    done = 已离开 resume_queued——ready/error/uploaded 全部停轮询，覆盖
    "解析中重传"交错（重传后新代为 resume_uploaded → done=true 回落确认卡）。"""
    progress = await load_intake_progress(session_id=session_id)
    if progress is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    return ResumeProgressResponse(
        generation=progress["generation"],
        status=progress["status"],
        events=[
            ResumeProgressEvent(
                seq=int(event["seq"]),
                step=str(event["step"]),
                text=str(event["text"]),
                elapsed_ms=int(event["elapsed_ms"]),
                created_at=event["created_at"],
            )
            for event in progress["events"]
        ],
        done=progress["status"] != "resume_queued",
    )


@router.post(
    "/sessions/{session_id}/resume/parse",
    response_model=ResumeAcceptedResponse,
    status_code=202,
    responses={409: {"model": ResumeLifecycleConflictResponse}},
    dependencies=[Depends(require_owned_session)],
)
async def parse_resume(
    session_id: str,
    request: ResumeParseRequest,
    background_tasks: BackgroundTasks,
) -> ResumeAcceptedResponse:
    """确认解析（LLM 成本发生点）：CAS 扣一次解析额度并入队后台归一化。"""
    try:
        started = await begin_resume_parse(
            session_id=session_id,
            generation=request.generation,
            max_parses=settings.resume_parse_limit,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    except ResumeLifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from None
    background_tasks.add_task(
        _normalize_resume,
        session_id=session_id,
        user_id=str(started["owner_user_id"] or session_id),
        raw_text=str(started["extracted_text"] or ""),
        suffix=str(started["suffix"] or ""),
        content=bytes(started["content"] or b""),
        expected_generation=request.generation,
    )
    return ResumeAcceptedResponse(session_id=session_id)


@router.get(
    "/sessions/{session_id}/resume-preview",
    response_model=ResumePreviewResponse,
    responses={409: {"model": ResumeLifecycleConflictResponse}},
    dependencies=[Depends(require_owned_session)],
)
async def resume_preview(session_id: str) -> ResumePreviewResponse:
    context = await load_consult_context(session_id)
    if context is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    if context.status == "resume_uploaded":
        raise HTTPException(status_code=409, detail="resume_unparsed")
    if context.status == "resume_queued":
        raise HTTPException(status_code=409, detail="resume_processing")
    if context.status == "resume_error":
        raise HTTPException(status_code=409, detail="resume_error")
    version = context.resume_version
    if version < 1:
        # 从未上传过简历的新会话：必须与"归一化中"可区分，前端据此展示
        # 上传入口而非处理中 spinner（审计二轮阻断项修复）。
        raise HTTPException(status_code=409, detail="resume_missing")
    resume = context.state.resume_state
    return ResumePreviewResponse(
        session_id=session_id,
        resume_version=version,
        confirmed=context.confirmed_resume_version == version,
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
    responses={
        409: {"model": ResumeLifecycleConflictResponse},
        # 422 = anyOf(必填 detail 稳定契约, 默认校验数组形态)——运行时两种
        # 形状并存，契约必须加性保留而非替换（审计三轮修正）。
        422: {"model": ResumeVersionRequiredResponse | RequestValidationErrorResponse},
    },
    dependencies=[Depends(require_owned_session)],
)
async def resume_confirm(
    session_id: str,
    request: ResumeConfirmRequest | None = None,
) -> ResumeConfirmResponse:
    # Feature-A's client version CAS is intentionally scoped to the resume
    # clarification switch. With the switch off, legacy no-body confirmation
    # and all 00/01 runtime behavior remain equivalent to the baseline.
    if settings.resume_clarify_enabled and (
        request is None or request.expected_resume_version is None
    ):
        raise HTTPException(
            status_code=422,
            detail="expected_resume_version_required",
        )
    expected_resume_version = (
        request.expected_resume_version
        if settings.resume_clarify_enabled and request is not None
        else None
    )
    try:
        metadata = await confirm_resume(
            session_id=session_id,
            expected_resume_version=expected_resume_version,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    except ResumeLifecycleConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from None
    return ResumeConfirmResponse(
        session_id=session_id,
        resume_version=int(metadata["resume_version"]),
        confirmed=True,
        confirmed_at=metadata.get("resume_confirmed_at"),
    )


@router.get(
    "/sessions/{session_id}/consult",
    response_model=ConsultStateResponse,
    response_model_exclude_unset=True,
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
        phase=determine_phase(state, mode=mode),
        completeness=calculate_completeness(career),
        can_finalize=can_finalize(career),
        clarification_progress=_clarification_progress(state),
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
    turn, persisted = await _execute_consult_round(
        session_id=session_id,
        mode=request.mode,
        message=request.message,
        expected_round=request.expected_round,
        status="intent_consulting",
        user_id=user.user_id if user is not None else None,
    )
    # Select the public DTO fields explicitly. ConsultTurn also carries private
    # Feature-A CAS facts that must never leak into OpenAPI responses.
    return ConsultResponse(
        assistant_reply=turn.assistant_reply,
        next_question=turn.next_question,
        phase=turn.phase,
        completeness=turn.completeness,
        can_finalize=turn.can_finalize,
        round=turn.round,
        profile_draft=turn.profile_draft,
        clarification_progress=_clarification_progress(persisted),
    )


@router.post(
    "/sessions/{session_id}/consult/finalize",
    response_model=ConsultBriefDraftResponse,
    dependencies=[Depends(require_owned_session)],
)
async def finalize_consultation(
    session_id: str,
) -> ConsultBriefDraftResponse:
    # B2 无条件生命周期保护（与 clarify flag 解耦）：uploaded/queued 两个
    # 新流程状态在任何开关组合下都不得进入 LLM/finalize 路径；resume_error
    # 与 confirmed 契约仍按 Feature A 的 flag 门控（基线行为不变）。
    context = await load_consult_context(session_id)
    if context is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    if context.status == "resume_uploaded":
        raise HTTPException(status_code=409, detail="resume_unparsed")
    if context.status == "resume_queued":
        raise HTTPException(status_code=409, detail="resume_processing")
    if settings.resume_clarify_enabled:
        # The confirmed-resume/generation contract is scoped to Feature A;
        # when disabled the legacy read-only finalize path below stays intact.
        if context.status == "resume_error":
            raise HTTPException(status_code=409, detail="resume_error")
        if (
            context.resume_version < 1
            or context.confirmed_resume_version != context.resume_version
        ):
            raise HTTPException(status_code=409, detail="resume_processing")
        if not _pending_baseline_matches_version(
            context.state.resume_state,
            context.resume_version,
        ):
            raise HTTPException(status_code=409, detail="resume_changed")

        def finalize_and_skip(
            latest: SharedState,
            current_resume_version: int,
            current_resume_upload_generation: int,
            _current_status: str = "",
        ) -> dict:
            if (
                current_resume_version != context.resume_version
                or current_resume_upload_generation
                != context.resume_upload_generation
            ):
                raise _ResumeChangedConflict(session_id)
            if not can_finalize(latest.career_state):
                raise ConsultError("consultation profile is incomplete")
            _skip_remaining_clarification_targets(latest.resume_state)
            return build_brief_draft(latest.career_state)

        try:
            draft = await mutate_state_atomically(
                session_id=session_id,
                mutator=finalize_and_skip,
            )
        except ConsultError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except _ResumeChangedConflict:
            raise HTTPException(status_code=409, detail="resume_changed") from None
        except KeyError:
            raise HTTPException(status_code=404, detail="session_id not found") from None
        return ConsultBriefDraftResponse.model_validate(draft)

    try:
        draft = build_brief_draft(context.state.career_state)
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
    expected_generation = int(metadata.get("resume_upload_generation") or 0)

    def persist_match_brief(
        state: SharedState,
        current_resume_version: int = 0,
        current_resume_upload_generation: int = 0,
        _current_status: str = "",
    ) -> dict:
        # B2：generation 比对无条件生效（flag-off 下并发重传也不得把新生命
        # 周期覆盖成 match_brief_approved）；version 比对维持 Feature A 门控
        # （保 test_api_v1 既有 fixture 基线，方案 §1.2 写死的口径）。
        if current_resume_upload_generation != expected_generation:
            raise _ResumeChangedConflict(session_id)
        if settings.resume_clarify_enabled and (
            current_resume_version != version
        ):
            raise _ResumeChangedConflict(session_id)
        if settings.resume_clarify_enabled:
            _skip_remaining_clarification_targets(state.resume_state)
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
    except _ResumeChangedConflict:
        raise HTTPException(status_code=409, detail="resume_changed") from None
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
    expected_resume_version: int | None = None
    expected_resume_upload_generation: int | None = None
    # B2：读路径统一走 context loader（flag-off 也要拿到 generation 供落库
    # 保护比对）；uploaded/queued 两个新流程状态无条件拦截，不进 LLM。
    context = await load_consult_context(session_id)
    if context is None:
        raise HTTPException(status_code=404, detail="session_id not found")
    if context.status == "resume_uploaded":
        raise HTTPException(status_code=409, detail="resume_unparsed")
    if context.status == "resume_queued":
        raise HTTPException(status_code=409, detail="resume_processing")
    loaded_generation = context.resume_upload_generation
    state = context.state
    if settings.resume_clarify_enabled:
        # Feature-A lifecycle checks apply only while clarification is on;
        # keeping this branch scoped preserves the 00/01 baseline behavior.
        if context.status == "resume_error":
            raise HTTPException(status_code=409, detail="resume_error")
        if (
            context.resume_version < 1
            or context.confirmed_resume_version != context.resume_version
        ):
            raise HTTPException(status_code=409, detail="resume_processing")
        if not _pending_baseline_matches_version(
            context.state.resume_state,
            context.resume_version,
        ):
            raise HTTPException(status_code=409, detail="resume_changed")
        expected_resume_version = context.resume_version
        expected_resume_upload_generation = loaded_generation
    if state.career_state.consult_rounds_used != expected_round:
        raise HTTPException(status_code=409, detail="consultation round conflict")
    if state.career_state.intent_consulted:
        raise HTTPException(status_code=409, detail="consultation round conflict")

    working = state.model_copy(deep=True)
    clarification_snapshot = _clarification_cas_snapshot(state.resume_state)
    pending_at_round_start = deepcopy(
        state.resume_state.pending_clarification_question
    )
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
        if settings.resume_clarify_enabled:
            consult_kwargs["resume_version"] = int(expected_resume_version or 0)
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

    def persist_turn(
        latest: SharedState,
        current_resume_version: int = 0,
        current_resume_upload_generation: int = 0,
        current_status: str = "",
    ) -> SharedState | MutationOutcome:
        completeness_before = calculate_completeness(latest.career_state)
        if settings.resume_clarify_enabled and (
            current_resume_version != expected_resume_version
            or current_resume_upload_generation
            != expected_resume_upload_generation
        ):
            raise _ResumeChangedConflict(expected_round)
        if settings.resume_clarify_enabled and not _pending_baseline_matches_version(
            latest.resume_state,
            current_resume_version,
        ):
            raise _ResumeChangedConflict(expected_round)
        if (
            latest.career_state.consult_rounds_used != expected_round
            or latest.career_state.intent_consulted
        ):
            raise _ConsultRoundConflict(expected_round)
        if settings.resume_clarify_enabled and (
            _clarification_cas_snapshot(latest.resume_state)
            != clarification_snapshot
        ):
            # Finalize/match-brief may have terminalized the pending target while
            # the LLM was outside the lock. Never revive that target or pending.
            raise _ConsultRoundConflict(expected_round)
        # B2 无条件落库保护（行锁内判定；flag-on 的失配已在上方 raise，此
        # 分支实际覆盖 flag-off）：LLM 等待期间发生重传/确认解析 → 本轮只
        # 追加 transcript，不覆盖 status、不合并旧代 resume_state。
        if (
            current_resume_upload_generation != loaded_generation
            or current_status in {"resume_uploaded", "resume_queued"}
        ):
            latest.career_state.consult_transcript = merge_consult_transcript(
                latest.career_state.consult_transcript,
                working.career_state.consult_transcript,
            )
            return MutationOutcome(
                result=latest.model_copy(deep=True),
                status_override=None,
            )
        for field_name in _INTENT_CAREER_FIELDS:
            if field_name == "consult_transcript":
                latest.career_state.consult_transcript = merge_consult_transcript(
                    latest.career_state.consult_transcript,
                    working.career_state.consult_transcript,
                )
                continue
            setattr(
                latest.career_state,
                field_name,
                deepcopy(getattr(working.career_state, field_name)),
            )
        if settings.resume_clarify_enabled:
            _merge_feature_a_resume_state(
                latest.resume_state,
                working.resume_state,
            )
            _record_clarification_turn(
                latest.resume_state,
                turn=turn,
                pending_at_round_start=pending_at_round_start,
                raw_answer=str(message).strip()[:2000],
            )
        if settings.consult_coach_enabled:
            # The working copy may predate CAS2 from the preceding round. Merge
            # attempts monotonically before evaluating this turn so terminal
            # reservations can never be overwritten by stale "reserved" data.
            latest.coach_reservations = merge_coach_reservations(
                latest.coach_reservations,
                working.coach_reservations,
            )
            progress = _clarification_progress(latest).model_dump()
            l1_facts = evaluate_consult_l1(
                latest,
                round_number=turn.round,
                phase=turn.phase,
                completeness_before=completeness_before,
                completeness=calculate_completeness(latest.career_state),
                can_finalize=turn.can_finalize,
                clarification_turn_active=turn.clarification_turn_active,
                clarification_progress=progress,
                coach_max=settings.consult_coach_max,
            )
            reserve_coach_attempt(
                latest,
                l1_facts,
                coach_max=settings.consult_coach_max,
            )
            latest.supervisor_log.append(deepcopy(l1_facts))
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
    except _ResumeChangedConflict:
        raise HTTPException(status_code=409, detail="resume_changed") from None
    except KeyError:
        raise HTTPException(status_code=404, detail="session_id not found") from None
    if settings.consult_coach_enabled:
        reservation = _reserved_coach_attempt_for_round(persisted, turn.round)
        if reservation is not None:
            l1_facts = _consult_l1_for_round(persisted, turn.round)
            try:
                outcome = await run_consult_coach(
                    persisted,
                    reservation=reservation,
                    l1_facts=l1_facts,
                )
            except asyncio.CancelledError:
                # CAS1 already burned the reservation. Cancellation must remain
                # observable to the server and must not release or retry it.
                raise
            except Exception:
                # Defensive fail-open boundary around the coach adapter itself;
                # ordinary transport/parse/timeout failures are already mapped
                # inside run_consult_coach.
                outcome = CoachAttemptOutcome(
                    status="unavailable",
                    error_code="service",
                )

            def persist_coach_outcome(
                latest: SharedState,
                _current_resume_version: int = 0,
                _current_resume_upload_generation: int = 0,
                _current_status: str = "",
            ) -> SharedState:
                # CAS2 deliberately has no rounds_used equality check. It acts
                # on the newest locked state and accepts later consultation
                # rounds as long as the reservation identity still matches.
                finalize_coach_reservation(
                    latest,
                    round_number=int(reservation["round"]),
                    trigger=str(reservation["trigger"]),
                    coach_attempt_id=str(reservation.get("coach_attempt_id") or ""),
                    status=outcome.status,
                    note=outcome.note,
                    error_code=outcome.error_code,
                )
                return latest.model_copy(deep=True)

            try:
                persisted = await mutate_state_atomically(
                    session_id=session_id,
                    mutator=persist_coach_outcome,
                    status=None,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # CAS1 has already committed the user turn and burned this
                # reservation. CAS2 is advisory, so persistence races or store
                # failures must not turn a successful consultation into an error.
                logger.warning(
                    "coach CAS2 persistence failed",
                    exc_info=True,
                    extra={
                        "session_id": session_id,
                        "coach_attempt_id": reservation.get("coach_attempt_id"),
                    },
                )
    return turn, persisted


def _reserved_coach_attempt_for_round(
    state: SharedState,
    round_number: int,
) -> dict | None:
    for reservation in state.coach_reservations:
        if (
            isinstance(reservation, dict)
            and int(reservation.get("round") or 0) == int(round_number)
            and reservation.get("status") == "reserved"
        ):
            return deepcopy(reservation)
    return None


def _consult_l1_for_round(state: SharedState, round_number: int) -> dict:
    for entry in reversed(state.supervisor_log):
        if (
            isinstance(entry, dict)
            and entry.get("stage") == "consult_coach_l1"
            and int(entry.get("round") or 0) == int(round_number)
        ):
            return deepcopy(entry)
    raise CoachReservationConflict("coach L1 facts not found")


def _clarification_progress(state: SharedState) -> ClarificationProgress:
    if not settings.resume_clarify_enabled:
        return ClarificationProgress()
    targets = [
        target
        for target in state.resume_state.clarification_targets
        if isinstance(target, dict)
    ]
    return ClarificationProgress(
        answered=sum(target.get("status") == "answered" for target in targets),
        skipped=sum(target.get("status") == "skipped" for target in targets),
        total=len(targets),
        questions_used=state.resume_state.questions_used,
    )


def _clarification_cas_snapshot(resume: ResumeState) -> tuple:
    target_states = tuple(
        (
            str(target.get("target_ref") or ""),
            str(target.get("status") or ""),
        )
        for target in resume.clarification_targets
        if isinstance(target, dict)
    )
    pending = resume.pending_clarification_question
    pending_identity = (
        (
            str(pending.get("target_ref") or ""),
            int(pending.get("asked_round") or 0),
        )
        if isinstance(pending, dict)
        else None
    )
    return target_states, pending_identity, int(resume.questions_used)


def _pending_baseline_matches_version(
    resume: ResumeState,
    resume_version: int,
) -> bool:
    pending = resume.pending_clarification_question
    if not isinstance(pending, dict):
        return True
    try:
        return int(pending.get("baseline_version")) == int(resume_version)
    except (TypeError, ValueError):
        return False


def _merge_feature_a_resume_state(
    latest: ResumeState,
    incoming: ResumeState,
) -> None:
    """Merge only Feature-A fields; composite identities are explicit."""
    latest.clarification_targets = deepcopy(incoming.clarification_targets)
    latest.pending_clarification_question = deepcopy(
        incoming.pending_clarification_question
    )
    latest.questions_used = incoming.questions_used
    latest.clarification_evidence_spans = _merge_feature_a_entries(
        latest.clarification_evidence_spans,
        incoming.clarification_evidence_spans,
        identity=lambda item: str(item.get("span_id") or "") or None,
    )
    latest.clarifications = _merge_feature_a_entries(
        latest.clarifications,
        incoming.clarifications,
        identity=lambda item: (
            str(item.get("target_ref") or ""),
            int(item.get("round") or 0),
        ),
    )


def _merge_feature_a_entries(
    latest: list[dict],
    incoming: list[dict],
    *,
    identity,
) -> list[dict]:
    merged = [deepcopy(item) for item in latest if isinstance(item, dict)]
    identities = {identity(item) for item in merged}
    for item in incoming:
        if not isinstance(item, dict):
            continue
        item_identity = identity(item)
        if item_identity in identities:
            continue
        identities.add(item_identity)
        merged.append(deepcopy(item))
    return merged


def _record_clarification_turn(
    resume: ResumeState,
    *,
    turn,
    pending_at_round_start: dict | None,
    raw_answer: str,
) -> None:
    action = getattr(turn, "clarification_action", None)
    target_refs = tuple(getattr(turn, "clarification_target_refs", ()) or ())
    if (
        action not in {"answered", "skip_current", "skip_remaining"}
        or not isinstance(pending_at_round_start, dict)
        or not target_refs
    ):
        return
    anchored_ref = str(pending_at_round_start.get("target_ref") or "")
    if anchored_ref not in target_refs:
        return
    round_number = int(getattr(turn, "round", 0) or 0)

    if action == "answered":
        if _clarification_record_exists(resume, anchored_ref, round_number):
            return
        if not raw_answer:
            return
        span_id = _next_clarification_span_id(resume)
        resume.clarification_evidence_spans.append(
            {
                "span_id": span_id,
                "page": None,
                "text": raw_answer,
                "source": "user_clarification",
            }
        )
        summary_value = getattr(turn, "clarification_answer_summary", None)
        summary = str(summary_value).strip() if summary_value is not None else None
        resume.clarifications.append(
            {
                "target_ref": anchored_ref,
                "answer_summary": summary or None,
                "span_id": span_id,
                "round": round_number,
                "action": action,
            }
        )
        return

    for target_ref in target_refs:
        target_ref = str(target_ref)
        if not target_ref or _clarification_record_exists(
            resume, target_ref, round_number
        ):
            continue
        resume.clarifications.append(
            {
                "target_ref": target_ref,
                "answer_summary": "",
                "span_id": None,
                "round": round_number,
                "action": action,
            }
        )


def _clarification_record_exists(
    resume: ResumeState,
    target_ref: str,
    round_number: int,
) -> bool:
    return any(
        isinstance(item, dict)
        and str(item.get("target_ref") or "") == target_ref
        and int(item.get("round") or 0) == round_number
        for item in resume.clarifications
    )


def _next_clarification_span_id(resume: ResumeState) -> str:
    used = {
        int(match.group(1))
        for item in resume.clarification_evidence_spans
        if isinstance(item, dict)
        and (match := re.fullmatch(r"C(\d+)", str(item.get("span_id") or "")))
    }
    sequence = 1
    while sequence in used:
        sequence += 1
    return f"C{sequence:03d}"


def _skip_remaining_clarification_targets(resume: ResumeState) -> None:
    for target in resume.clarification_targets:
        if isinstance(target, dict) and target.get("status") == "open":
            target["status"] = "skipped"
    resume.pending_clarification_question = None


class _IntakeNarrator:
    """B3 小意解析叙事发射器：任务内单调分配非终态 seq（每代单任务，由
    begin_resume_parse 的 CAS 保证，无并发分配者）；写失败只告警——
    叙事是旁路，绝不允许影响解析主流程。"""

    def __init__(self, session_id: str, generation: int) -> None:
        self._session_id = session_id
        self._generation = generation
        self._seq = 0
        self._started = time.monotonic()

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def elapsed_text(self) -> str:
        return f"{self.elapsed_ms() / 1000:.1f} 秒"

    async def emit(self, step: str, text: str) -> None:
        if self._seq >= 99:
            return  # 协议上界：非终态 seq 1..99，终态固定 100
        self._seq += 1
        try:
            await record_intake_progress(
                session_id=self._session_id,
                generation=self._generation,
                seq=self._seq,
                step=step,
                text=text,
                elapsed_ms=self.elapsed_ms(),
                first=self._seq == 1,
            )
        except Exception:
            logger.warning(
                "intake progress write failed for %s", self._session_id,
                exc_info=True,
            )


async def _normalize_resume(
    *,
    session_id: str,
    user_id: str,
    raw_text: str,
    suffix: str = "",
    content: bytes = b"",
    expected_generation: int,
) -> None:
    """B2 确认解析后台任务：输入为上传时已提取的文本与原始字节（字节随
    begin_resume_parse 事务取出并入内存，任何并发重传都影响不到本任务；
    B2 只消费 raw_text，suffix/content 为 B4 视觉 OCR 兜底预留的输入契约）。
    返还位于唯一的 except 分支且本函数是 begin 后的唯一任务体——
    "每任务至多一次返还"由该唯一调用点保证；external_started 与
    normalizing 进度阶段同点置位——之前失败返还额度（用户没花到钱），
    之后不返。B3：终态事件经 terminal_event 随 save/mark 的 CAS 事务写入，
    CAS 未命中（解析中重传换代）则零事件。
    """
    del suffix, content  # B4 起用于低文本 OCR 路由；B2 契约先行贯通
    narrator = _IntakeNarrator(session_id, expected_generation)
    external_started = False
    try:
        await narrator.emit("received", "收到！我现在就把你的简历完整读一遍～")
        if not raw_text.strip():
            raise ValueError("empty resume text")
        evidence_spans = build_evidence_spans(raw_text)
        if not evidence_spans:
            raise ValueError("no usable evidence spans")
        await narrator.emit(
            "extracted",
            f"读完啦！我从简历里整理出 {len(evidence_spans)} 条原文片段，"
            "每一条后面都会当作证据来用。",
        )
        external_started = True
        await narrator.emit(
            "normalizing",
            "正在把这些经历梳理成结构化档案——这一步最花心思，稍等我一下…",
        )
        resume_state = await normalize_resume_text(raw_text, evidence_spans)
        await narrator.emit(
            "validated",
            "梳理完成！我逐条核对过：档案里的每个条目都能对回你的简历原文，"
            "绝不无中生有。",
        )
        digest = hashlib.sha256(
            raw_text.encode("utf-8", errors="ignore")
        ).hexdigest()
        await save_normalized_resume(
            session_id=session_id,
            resume_state=resume_state,
            content_hash=digest,
            expected_generation=expected_generation,
            terminal_event=TerminalEvent(
                step="done",
                text=(
                    f"档案生成完毕，用时 {narrator.elapsed_text()}。"
                    "来看看整理结果吧！"
                ),
                elapsed_ms=narrator.elapsed_ms(),
            ),
        )
    except Exception:
        try:
            if not external_started:
                await refund_parse_count(session_id=session_id)
            await mark_resume_error(
                session_id=session_id,
                expected_generation=expected_generation,
                terminal_event=TerminalEvent(
                    step="error",
                    text=(
                        f"抱歉，这次解析中途出了点问题（用时 "
                        f"{narrator.elapsed_text()}）。别担心，你可以再试一次，"
                        "或换一份文件重新上传～"
                    ),
                    elapsed_ms=narrator.elapsed_ms(),
                ),
            )
        except Exception:
            logger.exception("resume error bookkeeping failed for %s", session_id)
    finally:
        try:
            await clear_resume_upload_content(
                session_id=session_id, generation=expected_generation
            )
        except Exception:
            logger.exception("resume upload cleanup failed for %s", session_id)


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
