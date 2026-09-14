import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_models import get_db
from database.crud import list_alerts, acknowledge_alert
from agents.alert_agent import alert_agent
from orchestration.orchestrator import orchestrator

router = APIRouter()


@router.get("")
async def get_alerts(
    unit_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_alerts(db, unit_id=unit_id, status=status, severity=severity, limit=limit)
    # Also include in-memory active alerts
    in_memory = [
        a for a in orchestrator.get_active_alerts()
        if (unit_id is None or a.industrial_unit_id == unit_id)
        and (status is None or a.status.value == status)
        and (severity is None or a.severity.value == severity)
    ]
    in_memory_ids = {str(a.id) for a in in_memory}

    db_alerts = [
        {
            "id": str(r.id),
            "industrial_unit_id": r.industrial_unit_id,
            "zone": r.zone,
            "severity": r.severity,
            "status": r.status,
            "title": r.title,
            "message": r.message,
            "pollutant": r.pollutant,
            "value": r.value,
            "threshold": r.threshold,
            "risk_score": r.risk_score,
            "risk_level": r.risk_level,
            "evidence": json.loads(r.evidence or "[]"),
            "granite_explanation": r.granite_explanation,
            "auto_escalated": r.auto_escalated,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "acknowledged_at": r.acknowledged_at.isoformat() if r.acknowledged_at else None,
            "source_type": r.source_type,
        }
        for r in rows
        if str(r.id) not in in_memory_ids
    ]
    mem_alerts = [
        {
            "id": str(a.id),
            "industrial_unit_id": a.industrial_unit_id,
            "zone": a.zone,
            "severity": a.severity.value,
            "status": a.status.value,
            "title": a.title,
            "message": a.message,
            "pollutant": a.pollutant.value if a.pollutant else None,
            "value": a.value,
            "threshold": a.threshold,
            "risk_score": a.risk_score,
            "risk_level": a.risk_level.value if a.risk_level else None,
            "evidence": a.evidence,
            "granite_explanation": a.granite_explanation,
            "auto_escalated": a.auto_escalated,
            "created_at": a.created_at.isoformat(),
            "source_type": a.source_type.value if hasattr(a.source_type, "value") else str(a.source_type),
        }
        for a in in_memory
    ]
    all_alerts = mem_alerts + db_alerts
    return {"count": len(all_alerts), "alerts": all_alerts}


@router.post("/{alert_id}/acknowledge")
async def acknowledge(alert_id: str, db: AsyncSession = Depends(get_db)):
    await acknowledge_alert(db, alert_id)
    # Update in-memory
    if alert_id in orchestrator._active_alerts:
        from app.models import AlertStatus
        from utils.helpers import utcnow
        orchestrator._active_alerts[alert_id].status = AlertStatus.ACKNOWLEDGED
        orchestrator._active_alerts[alert_id].acknowledged_at = utcnow()
    return {"acknowledged": True, "alert_id": alert_id}


class TestAlertPayload(BaseModel):
    unit_id: str = "VAPI-001"
    zone: str = "Vapi"


@router.post("/test")
async def test_alert(payload: TestAlertPayload):
    """Fire a test alert to verify all alert channels."""
    alert = await alert_agent.test_alert(payload.unit_id, payload.zone)
    return {"test_alert_sent": True, "alert_id": str(alert.id)}
