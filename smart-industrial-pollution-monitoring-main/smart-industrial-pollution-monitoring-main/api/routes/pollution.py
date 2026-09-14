from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_models import get_db
from database.crud import get_unit_readings
from orchestration.orchestrator import orchestrator
from data_sources.ingestion import coerce_reading

router = APIRouter()


@router.get("/current")
async def get_current_pollution(unit_id: Optional[str] = None):
    """Returns the latest readings cached in the orchestrator evidence store."""
    result = {}
    units = [unit_id] if unit_id else list(orchestrator._unit_evidence.keys())
    for uid in units:
        ev = orchestrator.get_unit_evidence(uid)
        readings = ev.get("readings", [])
        latest_by_pollutant = {}
        for r in readings:
            p = r.pollutant.value
            if p not in latest_by_pollutant or r.timestamp > latest_by_pollutant[p].timestamp:
                latest_by_pollutant[p] = r
        result[uid] = {
            "unit_id": uid,
            "readings": [
                {
                    "pollutant": p,
                    "value": r.value,
                    "unit": r.unit,
                    "timestamp": r.timestamp.isoformat(),
                    "source_type": r.source_type.value,
                    "quality_score": r.quality_score,
                    "is_valid": r.is_valid,
                }
                for p, r in latest_by_pollutant.items()
            ],
            "data_freshness": (
                max((r.timestamp for r in readings), default=None)
            ),
        }
        if result[uid]["data_freshness"]:
            result[uid]["data_freshness"] = result[uid]["data_freshness"].isoformat()
    return {"source_type": "LIVE/SIMULATED", "units": result}


@router.get("/history")
async def get_pollution_history(
    unit_id: str,
    pollutant: Optional[str] = None,
    hours: int = Query(default=24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = await get_unit_readings(db, unit_id, pollutant=pollutant, since=since, limit=2000)
    return {
        "unit_id": unit_id,
        "pollutant": pollutant,
        "hours": hours,
        "count": len(rows),
        "source_type": "HISTORICAL",
        "readings": [
            {
                "id": str(r.id),
                "sensor_id": r.sensor_id,
                "pollutant": r.pollutant,
                "value": r.value,
                "unit": r.unit,
                "timestamp": r.timestamp.isoformat(),
                "source_type": r.source_type,
                "quality_score": r.quality_score,
                "is_valid": r.is_valid,
            }
            for r in rows
        ],
    }


class SensorDataPayload(BaseModel):
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: str
    media: str = "AIR"
    value: float
    unit: str
    timestamp: Optional[str] = None
    source_type: str = "LIVE"
    source_id: str = "api_manual"
    metadata: dict = {}


@router.post("/sensor-data")
async def submit_sensor_data(payload: SensorDataPayload):
    """Accept a live sensor reading and process it through the full pipeline."""
    raw = payload.model_dump()
    reading = coerce_reading(raw)
    if reading is None:
        raise HTTPException(400, "Invalid sensor reading — check pollutant name and value")
    await orchestrator.process_manual_reading(reading)
    return {
        "accepted": True,
        "reading_id": str(reading.id),
        "source_type": reading.source_type.value,
        "note": "Reading processed through validation → anomaly → risk pipeline",
    }
