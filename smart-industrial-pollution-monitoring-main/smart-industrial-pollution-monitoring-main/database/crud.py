"""
CRUD helpers for the database layer.
All public methods are async.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.db_models import (
    AlertDB, AuditLogDB, DataSourceDB, IncidentDB, IndustrialUnitDB,
    PredictionDB, RootCauseDB, SensorMetadataDB, SensorReadingDB,
    SensorReliabilityDB,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _j(obj) -> str:
    return json.dumps(obj, default=str)


def _l(s: str) -> list:
    try:
        return json.loads(s)
    except Exception:
        return []


# ── Industrial units ─────────────────────────────────────────────────────────

async def upsert_industrial_unit(db: AsyncSession, unit: dict) -> None:
    existing = await db.get(IndustrialUnitDB, unit["unit_id"])
    if existing:
        for k, v in unit.items():
            if k == "sensors":
                existing.sensor_ids = _j(v)
            elif k == "metadata":
                existing.metadata_json = _j(v)
            elif hasattr(existing, k):
                setattr(existing, k, v)
    else:
        db.add(IndustrialUnitDB(
            id=unit["unit_id"],
            name=unit["name"],
            zone=unit["zone"],
            industry_type=unit.get("industry_type", ""),
            location_lat=unit.get("location_lat"),
            location_lon=unit.get("location_lon"),
            contact_name=unit.get("contact_name"),
            contact_email=unit.get("contact_email"),
            is_monitored=unit.get("is_monitored", True),
            sensor_ids=_j(unit.get("sensors", [])),
            risk_score=unit.get("risk_score", 0.0),
            risk_level=unit.get("risk_level", "LOW"),
            metadata_json=_j(unit.get("metadata", {})),
        ))
    await db.commit()


async def get_industrial_unit(db: AsyncSession, unit_id: str) -> Optional[IndustrialUnitDB]:
    return await db.get(IndustrialUnitDB, unit_id)


async def list_industrial_units(db: AsyncSession, zone: Optional[str] = None) -> List[IndustrialUnitDB]:
    q = select(IndustrialUnitDB)
    if zone:
        q = q.where(IndustrialUnitDB.zone == zone)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_unit_risk(db: AsyncSession, unit_id: str, score: float, level: str) -> None:
    await db.execute(
        update(IndustrialUnitDB)
        .where(IndustrialUnitDB.id == unit_id)
        .values(risk_score=score, risk_level=level, last_assessed_at=datetime.utcnow())
    )
    await db.commit()


# ── Sensor metadata ───────────────────────────────────────────────────────────

async def upsert_sensor_metadata(db: AsyncSession, s: dict) -> None:
    existing = await db.get(SensorMetadataDB, s["sensor_id"])
    if existing:
        for k, v in s.items():
            if hasattr(existing, k):
                setattr(existing, k, v)
    else:
        db.add(SensorMetadataDB(**{k: v for k, v in s.items() if k != "metadata"}))
    await db.commit()


async def get_sensor_metadata(db: AsyncSession, sensor_id: str) -> Optional[SensorMetadataDB]:
    return await db.get(SensorMetadataDB, sensor_id)


async def list_sensors(db: AsyncSession, unit_id: Optional[str] = None) -> List[SensorMetadataDB]:
    q = select(SensorMetadataDB)
    if unit_id:
        q = q.where(SensorMetadataDB.industrial_unit_id == unit_id)
    result = await db.execute(q)
    return list(result.scalars().all())


async def update_sensor_reliability(
    db: AsyncSession, sensor_id: str, reliability: float, status: str
) -> None:
    await db.execute(
        update(SensorMetadataDB)
        .where(SensorMetadataDB.sensor_id == sensor_id)
        .values(reliability_score=reliability, status=status, last_reading_at=datetime.utcnow())
    )
    await db.commit()


# ── Sensor readings ───────────────────────────────────────────────────────────

async def insert_reading(db: AsyncSession, reading: dict) -> None:
    db.add(SensorReadingDB(
        id=str(reading["id"]),
        sensor_id=reading["sensor_id"],
        industrial_unit_id=reading["industrial_unit_id"],
        zone=reading["zone"],
        pollutant=reading["pollutant"],
        media=reading["media"],
        value=reading["value"],
        unit=reading["unit"],
        timestamp=reading["timestamp"],
        source_type=reading["source_type"],
        source_id=reading["source_id"],
        quality_score=reading.get("quality_score", 1.0),
        is_valid=reading.get("is_valid", True),
        validation_notes=_j(reading.get("validation_notes", [])),
        metadata_json=_j(reading.get("metadata", {})),
    ))
    await db.commit()


async def get_recent_readings(
    db: AsyncSession,
    sensor_id: str,
    limit: int = 100,
    since: Optional[datetime] = None,
) -> List[SensorReadingDB]:
    q = (
        select(SensorReadingDB)
        .where(SensorReadingDB.sensor_id == sensor_id)
        .where(SensorReadingDB.is_valid == True)
    )
    if since:
        q = q.where(SensorReadingDB.timestamp >= since)
    q = q.order_by(desc(SensorReadingDB.timestamp)).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_unit_readings(
    db: AsyncSession,
    unit_id: str,
    pollutant: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: int = 500,
) -> List[SensorReadingDB]:
    q = (
        select(SensorReadingDB)
        .where(SensorReadingDB.industrial_unit_id == unit_id)
        .where(SensorReadingDB.is_valid == True)
    )
    if pollutant:
        q = q.where(SensorReadingDB.pollutant == pollutant)
    if since:
        q = q.where(SensorReadingDB.timestamp >= since)
    q = q.order_by(desc(SensorReadingDB.timestamp)).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Incidents ─────────────────────────────────────────────────────────────────

async def insert_incident(db: AsyncSession, inc: dict) -> None:
    db.add(IncidentDB(
        id=str(inc["id"]),
        industrial_unit_id=inc["industrial_unit_id"],
        zone=inc["zone"],
        status=inc.get("status", "OPEN"),
        severity=inc["severity"],
        title=inc["title"],
        description=inc["description"],
        pollutants_involved=_j(inc.get("pollutants_involved", [])),
        risk_score=inc.get("risk_score", 0.0),
        risk_level=inc.get("risk_level", "LOW"),
        threshold_breaches=_j(inc.get("threshold_breaches", [])),
        anomalies=_j(inc.get("anomalies", [])),
        alerts=_j(inc.get("alerts", [])),
        root_cause_id=inc.get("root_cause_id"),
        granite_summary=inc.get("granite_summary"),
        source_type=inc["source_type"],
    ))
    await db.commit()


async def list_incidents(
    db: AsyncSession,
    unit_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[IncidentDB]:
    q = select(IncidentDB)
    if unit_id:
        q = q.where(IncidentDB.industrial_unit_id == unit_id)
    if status:
        q = q.where(IncidentDB.status == status)
    q = q.order_by(desc(IncidentDB.created_at)).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Alerts ────────────────────────────────────────────────────────────────────

async def insert_alert(db: AsyncSession, alert: dict) -> None:
    db.add(AlertDB(
        id=str(alert["id"]),
        industrial_unit_id=alert["industrial_unit_id"],
        zone=alert["zone"],
        severity=alert["severity"],
        status=alert.get("status", "ACTIVE"),
        title=alert["title"],
        message=alert["message"],
        pollutant=alert.get("pollutant"),
        value=alert.get("value"),
        threshold=alert.get("threshold"),
        risk_score=alert.get("risk_score"),
        risk_level=alert.get("risk_level"),
        source_type=alert["source_type"],
        incident_id=alert.get("incident_id"),
        granite_explanation=alert.get("granite_explanation"),
        evidence=_j(alert.get("evidence", [])),
        actions_taken=_j(alert.get("actions_taken", [])),
        auto_escalated=alert.get("auto_escalated", False),
    ))
    await db.commit()


async def list_alerts(
    db: AsyncSession,
    unit_id: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
) -> List[AlertDB]:
    q = select(AlertDB)
    if unit_id:
        q = q.where(AlertDB.industrial_unit_id == unit_id)
    if status:
        q = q.where(AlertDB.status == status)
    if severity:
        q = q.where(AlertDB.severity == severity)
    q = q.order_by(desc(AlertDB.created_at)).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def acknowledge_alert(db: AsyncSession, alert_id: str) -> None:
    await db.execute(
        update(AlertDB)
        .where(AlertDB.id == alert_id)
        .values(status="ACKNOWLEDGED", acknowledged_at=datetime.utcnow())
    )
    await db.commit()


# ── Predictions ───────────────────────────────────────────────────────────────

async def insert_prediction(db: AsyncSession, pred: dict) -> None:
    db.add(PredictionDB(
        id=str(pred["id"]),
        sensor_id=pred["sensor_id"],
        industrial_unit_id=pred["industrial_unit_id"],
        zone=pred["zone"],
        pollutant=pred["pollutant"],
        current_value=pred["current_value"],
        predicted_value=pred["predicted_value"],
        worst_case_value=pred["worst_case_value"],
        unit=pred["unit"],
        horizon_minutes=pred["horizon_minutes"],
        trend=pred["trend"],
        threshold_value=pred.get("threshold_value"),
        breach_predicted=pred.get("breach_predicted", False),
        breach_eta_minutes=pred.get("breach_eta_minutes"),
        confidence=pred.get("confidence", 1.0),
        uncertainty_pct=pred.get("uncertainty_pct", 0.0),
        model_used=pred.get("model_used", ""),
        evidence=_j(pred.get("evidence", [])),
    ))
    await db.commit()


async def get_latest_predictions(
    db: AsyncSession, unit_id: str, limit: int = 20
) -> List[PredictionDB]:
    q = (
        select(PredictionDB)
        .where(PredictionDB.industrial_unit_id == unit_id)
        .order_by(desc(PredictionDB.created_at))
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Audit logs ────────────────────────────────────────────────────────────────

async def insert_audit_log(db: AsyncSession, entry: dict) -> None:
    db.add(AuditLogDB(
        id=str(entry["id"]),
        event_type=entry["event_type"],
        actor=entry["actor"],
        industrial_unit_id=entry.get("industrial_unit_id"),
        entity_type=entry.get("entity_type"),
        entity_id=entry.get("entity_id"),
        action=entry["action"],
        reason=entry["reason"],
        evidence=_j(entry.get("evidence", [])),
        input_snapshot=_j(entry.get("input_snapshot", {})),
        output_snapshot=_j(entry.get("output_snapshot", {})),
        confidence=entry.get("confidence", 1.0),
        source_type=entry["source_type"],
    ))
    await db.commit()


async def list_audit_logs(
    db: AsyncSession,
    unit_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
) -> List[AuditLogDB]:
    q = select(AuditLogDB)
    if unit_id:
        q = q.where(AuditLogDB.industrial_unit_id == unit_id)
    if event_type:
        q = q.where(AuditLogDB.event_type == event_type)
    q = q.order_by(desc(AuditLogDB.timestamp)).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Data sources ──────────────────────────────────────────────────────────────

async def upsert_data_source(db: AsyncSession, src: dict) -> None:
    existing = await db.get(DataSourceDB, src["source_id"])
    if existing:
        for k, v in src.items():
            if k == "config":
                existing.config_json = _j(v)
            elif hasattr(existing, k):
                setattr(existing, k, v)
    else:
        db.add(DataSourceDB(
            source_id=src["source_id"],
            name=src["name"],
            source_type=src["source_type"],
            industrial_unit_id=src.get("industrial_unit_id"),
            zone=src.get("zone"),
            is_active=src.get("is_active", True),
            quality_score=src.get("quality_score", 1.0),
            config_json=_j(src.get("config", {})),
        ))
    await db.commit()


async def list_data_sources(db: AsyncSession, active_only: bool = True) -> List[DataSourceDB]:
    q = select(DataSourceDB)
    if active_only:
        q = q.where(DataSourceDB.is_active == True)
    result = await db.execute(q)
    return list(result.scalars().all())
