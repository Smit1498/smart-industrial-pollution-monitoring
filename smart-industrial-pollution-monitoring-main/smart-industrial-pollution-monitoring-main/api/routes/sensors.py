from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_models import get_db
from database.crud import list_sensors, get_sensor_metadata
from agents.data_quality_agent import data_quality_engine

router = APIRouter()


@router.get("")
async def get_sensors(unit_id: str = None, db: AsyncSession = Depends(get_db)):
    sensors = await list_sensors(db, unit_id=unit_id)
    states = data_quality_engine.all_sensor_states()
    result = []
    for s in sensors:
        state = states.get(s.sensor_id, {})
        result.append({
            "sensor_id": s.sensor_id,
            "industrial_unit_id": s.industrial_unit_id,
            "zone": s.zone,
            "pollutant": s.pollutant,
            "media": s.media,
            "unit": s.unit,
            "reliability_score": state.get("reliability_score", s.reliability_score),
            "status": state.get("status", s.status),
            "last_seen": state.get("last_seen", s.last_reading_at.isoformat() if s.last_reading_at else None),
            "is_stale": state.get("is_stale", False),
            "is_frozen": state.get("is_frozen", False),
            "consecutive_issues": state.get("consecutive_issues", 0),
        })
    return {"count": len(result), "sensors": result}
