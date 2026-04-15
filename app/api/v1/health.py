from fastapi import APIRouter
from app.infrastructure.resources import get_app_resources

router = APIRouter()


@router.get("/health")
async def health_check():
    resources = await get_app_resources()
    snapshot = resources.health_snapshot()
    status = "ok" if resources.initialized else "degraded"
    return {
        "status": status,
        "version": "1.0.0",
        "resources": snapshot,
    }
