from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from database.db_models import get_db
from database.crud import list_data_sources, upsert_data_source
from data_sources.manager import data_source_registry

router = APIRouter()


@router.get("")
async def get_data_sources(db: AsyncSession = Depends(get_db)):
    live = data_source_registry.status()
    db_sources = await list_data_sources(db, active_only=False)
    return {
        "live_sources": live,
        "registered_count": len(live),
        "db_sources": [
            {
                "source_id": s.source_id,
                "name": s.name,
                "source_type": s.source_type,
                "is_active": s.is_active,
                "quality_score": s.quality_score,
                "last_success_at": s.last_success_at.isoformat() if s.last_success_at else None,
                "last_failure_at": s.last_failure_at.isoformat() if s.last_failure_at else None,
                "failure_count": s.failure_count,
            }
            for s in db_sources
        ],
    }


class DataSourcePayload(BaseModel):
    source_id: str
    name: str
    source_type: str
    industrial_unit_id: Optional[str] = None
    zone: Optional[str] = None
    config: dict = {}


@router.post("")
async def register_data_source(
    payload: DataSourcePayload,
    db: AsyncSession = Depends(get_db),
):
    await upsert_data_source(db, payload.model_dump())
    return {"registered": True, "source_id": payload.source_id}
