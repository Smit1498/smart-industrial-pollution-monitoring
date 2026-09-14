from fastapi import APIRouter
from app.config import get_settings
from orchestration.orchestrator import orchestrator
from ai.granite_client import granite_client

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health():
    status = orchestrator.get_status()
    return {
        "status": "healthy" if status.healthy else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "resource_mode": settings.RESOURCE_MODE,
        "granite_available": granite_client.is_available(),
        "system": {
            "total_sensors": status.total_sensors,
            "online_sensors": status.online_sensors,
            "stale_sensors": status.stale_sensors,
            "offline_sensors": status.offline_sensors,
            "active_incidents": status.active_incidents,
            "active_alerts": status.active_alerts,
        },
        "granite": granite_client.status(),
        "last_updated": status.last_updated.isoformat(),
        "degraded_components": status.degraded_components,
    }
