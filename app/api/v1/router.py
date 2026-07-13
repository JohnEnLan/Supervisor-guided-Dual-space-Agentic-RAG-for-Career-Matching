from fastapi import APIRouter

from app.api.v1.feedback import router as feedback_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.runs import router as runs_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.schemas import CapabilitiesResponse
from app.config import settings


router = APIRouter(prefix="/api/v1")


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        dual_space_enabled=settings.dual_space_enabled,
        explain_enabled=settings.evaluation_capability_enabled,
        monitoring_enabled=settings.monitoring_enabled,
    )


router.include_router(sessions_router)
router.include_router(runs_router)
router.include_router(feedback_router)
router.include_router(monitoring_router)
