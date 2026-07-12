from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import ReactionRequest, ReactionResponse
from app.db.run_store import get_run
from app.db.state_store import (
    FeedbackIdempotencyConflict,
    add_feedback,
)
from app.domain.run import RunStatus


router = APIRouter()


@router.post(
    "/runs/{run_id}/reaction",
    response_model=ReactionResponse,
    status_code=202,
)
async def add_run_reaction(
    run_id: str, request: ReactionRequest
) -> ReactionResponse:
    run = await get_run(run_id=run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_id not found")
    if run.status not in {
        RunStatus.COMPLETED,
        RunStatus.COMPLETED_WITH_WARNINGS,
    }:
        raise HTTPException(status_code=409, detail="run result is not ready")
    recommended_job_ids = {
        str(role.get("job_id"))
        for role in (run.result_snapshot or {}).get("recommended_roles", [])
        if isinstance(role, dict) and role.get("job_id")
    }
    if request.job_id not in recommended_job_ids:
        raise HTTPException(
            status_code=422, detail="job_id is not in this run result"
        )
    try:
        result = await add_feedback(
            session_id=run.session_id,
            job_id=request.job_id,
            outcome=request.outcome,
            reason=request.reason,
            user_rating=request.user_rating,
            idempotency_key=request.idempotency_key,
        )
    except FeedbackIdempotencyConflict:
        raise HTTPException(
            status_code=409, detail="idempotency key payload conflict"
        ) from None
    return ReactionResponse(run_id=run_id, feedback_id=result.feedback_id)
