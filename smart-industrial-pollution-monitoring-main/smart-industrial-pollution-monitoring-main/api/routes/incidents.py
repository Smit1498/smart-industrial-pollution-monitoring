import json
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_models import get_db
from database.crud import list_incidents
from orchestration.orchestrator import orchestrator

router = APIRouter()


@router.get("")
async def get_incidents(
    unit_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_incidents(db, unit_id=unit_id, status=status, limit=limit)
    # Also include in-memory active incidents
    in_memory = [
        i for i in orchestrator.get_active_incidents()
        if (unit_id is None or i.industrial_unit_id == unit_id)
        and (status is None or i.status.value == status)
    ]
    in_memory_ids = {str(i.id) for i in in_memory}

    db_incidents = [
        {
            "id": str(r.id),
            "industrial_unit_id": r.industrial_unit_id,
            "zone": r.zone,
            "status": r.status,
            "severity": r.severity,
            "title": r.title,
            "description": r.description,
            "pollutants_involved": json.loads(r.pollutants_involved or "[]"),
            "risk_score": r.risk_score,
            "risk_level": r.risk_level,
            "threshold_breaches": json.loads(r.threshold_breaches or "[]"),
            "granite_summary": r.granite_summary,
            "source_type": r.source_type,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        }
        for r in rows
        if str(r.id) not in in_memory_ids
    ]

    mem_incidents = [
        {
            "id": str(i.id),
            "industrial_unit_id": i.industrial_unit_id,
            "zone": i.zone,
            "status": i.status.value,
            "severity": i.severity.value,
            "title": i.title,
            "description": i.description,
            "pollutants_involved": [p.value for p in i.pollutants_involved],
            "risk_score": i.risk_score,
            "risk_level": i.risk_level.value,
            "granite_summary": i.granite_summary,
            "source_type": i.source_type.value,
            "created_at": i.created_at.isoformat(),
        }
        for i in in_memory
    ]

    all_incidents = mem_incidents + db_incidents
    return {"count": len(all_incidents), "incidents": all_incidents}
