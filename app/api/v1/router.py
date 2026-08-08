from fastapi import APIRouter

from app.api.auth.routes import router as auth_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.monitoring import router as monitoring_router
from app.api.v1.runs import router as runs_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.schemas import CapabilitiesResponse
from app.config import settings


router = APIRouter(prefix="/api/v1")


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    otp_channels = []
    if settings.email_otp_provider != "disabled":
        otp_channels.append("email")
    if settings.sms_otp_provider != "disabled":
        otp_channels.append("phone")
    return CapabilitiesResponse(
        dual_space_enabled=settings.dual_space_enabled,
        resume_image_upload_enabled=settings.resume_ocr_enabled,
        explain_enabled=settings.evaluation_capability_enabled,
        monitoring_enabled=settings.monitoring_enabled,
        otp_channels=otp_channels,
    )


router.include_router(auth_router)
router.include_router(sessions_router)
router.include_router(runs_router)
router.include_router(feedback_router)
router.include_router(monitoring_router)
