import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_models import get_db
from database.crud import list_industrial_units, get_industrial_unit
from orchestration.orchestrator import orchestrator

router = APIRouter()


@router.get("")
async def get_industries(zone: str = None, db: AsyncSession = Depends(get_db)):
    units = await list_industrial_units(db, zone=zone)
    result = []
    for u in units:
        evidence = orchestrator.get_unit_evidence(u.id)
        risk_info = evidence.get("risk")
        result.append({
            "unit_id": u.id,
            "name": u.name,
            "zone": u.zone,
            "industry_type": u.industry_type,
            "is_monitored": u.is_monitored,
            "risk_score": u.risk_score,
            "risk_level": u.risk_level,
            "location_lat": u.location_lat,
            "location_lon": u.location_lon,
            "last_assessed_at": u.last_assessed_at.isoformat() if u.last_assessed_at else None,
            "sensor_count": len(json.loads(u.sensor_ids or "[]")),
            "active_breaches": len(evidence.get("breaches", [])),
            "active_anomalies": len(evidence.get("anomalies", [])),
        })
    # Sort by risk score descending
    result.sort(key=lambda x: x["risk_score"], reverse=True)
    return {"count": len(result), "industries": result}


@router.get("/{unit_id}")
async def get_industry_detail(unit_id: str, db: AsyncSession = Depends(get_db)):
    unit = await get_industrial_unit(db, unit_id)
    if not unit:
        raise HTTPException(404, f"Industrial unit '{unit_id}' not found")

    evidence = orchestrator.get_unit_evidence(unit_id)
    risk = evidence.get("risk")
    predictions = evidence.get("predictions", [])
    breaches = evidence.get("breaches", [])
    anomalies = evidence.get("anomalies", [])

    return {
        "unit_id": unit.id,
        "name": unit.name,
        "zone": unit.zone,
        "industry_type": unit.industry_type,
        "is_monitored": unit.is_monitored,
        "risk_score": unit.risk_score,
        "risk_level": unit.risk_level,
        "location": {"lat": unit.location_lat, "lon": unit.location_lon},
        "contact": {"name": unit.contact_name, "email": unit.contact_email},
        "sensors": json.loads(unit.sensor_ids or "[]"),
        "last_assessed_at": unit.last_assessed_at.isoformat() if unit.last_assessed_at else None,
        "current_risk": risk.model_dump() if risk else None,
        "active_threshold_breaches": len(breaches),
        "active_anomalies": len(anomalies),
        "breach_summary": [
            {
                "pollutant": b.pollutant.value,
                "value": b.value,
                "threshold": b.threshold_value,
                "excess_pct": b.excess_pct,
                "status": b.violation_status.value,
            }
            for b in breaches[:5]
        ],
        "predictions_summary": [
            {
                "pollutant": p.pollutant.value,
                "current": p.current_value,
                "predicted_30min": p.predicted_value,
                "trend": p.trend.value,
                "breach_predicted": p.breach_predicted,
                "confidence": p.confidence,
            }
            for p in predictions[:5]
        ],
    }
