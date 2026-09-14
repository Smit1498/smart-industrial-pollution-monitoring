"""
SQLAlchemy async ORM models + database initialisation.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index, Integer,
    String, Text, func, text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# ── Engine / session factory ─────────────────────────────────────────────────

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_db() -> AsyncSession:  # FastAPI dependency
    async with AsyncSessionLocal() as session:
        yield session


# ── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── ORM models ───────────────────────────────────────────────────────────────

class IndustrialUnitDB(Base):
    __tablename__ = "industrial_units"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    zone = Column(String, nullable=False, index=True)
    industry_type = Column(String)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    contact_name = Column(String, nullable=True)
    contact_email = Column(String, nullable=True)
    is_monitored = Column(Boolean, default=True, index=True)
    sensor_ids = Column(Text, default="[]")      # JSON array
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String, default="LOW")
    last_assessed_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SensorMetadataDB(Base):
    __tablename__ = "sensor_metadata"

    sensor_id = Column(String, primary_key=True)
    industrial_unit_id = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=False, index=True)
    pollutant = Column(String, nullable=False, index=True)
    media = Column(String, nullable=False)
    unit = Column(String, nullable=False)
    location_lat = Column(Float, nullable=True)
    location_lon = Column(Float, nullable=True)
    manufacturer = Column(String, nullable=True)
    calibration_date = Column(DateTime, nullable=True)
    reliability_score = Column(Float, default=1.0)
    status = Column(String, default="ONLINE", index=True)
    last_reading_at = Column(DateTime, nullable=True)
    notes = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


class SensorReadingDB(Base):
    __tablename__ = "sensor_readings"

    id = Column(String, primary_key=True)
    sensor_id = Column(String, nullable=False, index=True)
    industrial_unit_id = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=False, index=True)
    pollutant = Column(String, nullable=False, index=True)
    media = Column(String, nullable=False)
    value = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    source_type = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=False)
    quality_score = Column(Float, default=1.0)
    is_valid = Column(Boolean, default=True, index=True)
    validation_notes = Column(Text, default="[]")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("ix_readings_unit_time", "industrial_unit_id", "timestamp"),
        Index("ix_readings_sensor_time", "sensor_id", "timestamp"),
        Index("ix_readings_pollutant_time", "pollutant", "timestamp"),
    )


class IncidentDB(Base):
    __tablename__ = "incidents"

    id = Column(String, primary_key=True)
    industrial_unit_id = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=False, index=True)
    status = Column(String, default="OPEN", index=True)
    severity = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    pollutants_involved = Column(Text, default="[]")
    risk_score = Column(Float, default=0.0)
    risk_level = Column(String, default="LOW")
    threshold_breaches = Column(Text, default="[]")
    anomalies = Column(Text, default="[]")
    alerts = Column(Text, default="[]")
    root_cause_id = Column(String, nullable=True)
    granite_summary = Column(Text, nullable=True)
    human_notes = Column(Text, default="")
    source_type = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime, nullable=True)


class AlertDB(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True)
    industrial_unit_id = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True)
    status = Column(String, default="ACTIVE", index=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    pollutant = Column(String, nullable=True)
    value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    risk_level = Column(String, nullable=True)
    source_type = Column(String, nullable=False)
    incident_id = Column(String, nullable=True, index=True)
    granite_explanation = Column(Text, nullable=True)
    evidence = Column(Text, default="[]")
    actions_taken = Column(Text, default="[]")
    auto_escalated = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)


class PredictionDB(Base):
    __tablename__ = "predictions"

    id = Column(String, primary_key=True)
    sensor_id = Column(String, nullable=False, index=True)
    industrial_unit_id = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=False)
    pollutant = Column(String, nullable=False, index=True)
    current_value = Column(Float, nullable=False)
    predicted_value = Column(Float, nullable=False)
    worst_case_value = Column(Float, nullable=False)
    unit = Column(String, nullable=False)
    horizon_minutes = Column(Integer, nullable=False)
    trend = Column(String, nullable=False)
    threshold_value = Column(Float, nullable=True)
    breach_predicted = Column(Boolean, default=False, index=True)
    breach_eta_minutes = Column(Integer, nullable=True)
    confidence = Column(Float, default=1.0)
    uncertainty_pct = Column(Float, default=0.0)
    model_used = Column(String, default="")
    evidence = Column(Text, default="[]")
    created_at = Column(DateTime, server_default=func.now(), index=True)


class RootCauseDB(Base):
    __tablename__ = "root_cause_analyses"

    id = Column(String, primary_key=True)
    incident_id = Column(String, nullable=False, index=True)
    industrial_unit_id = Column(String, nullable=False, index=True)
    zone = Column(String, nullable=False)
    observed_evidence = Column(Text, default="[]")
    possible_causes = Column(Text, default="[]")
    supporting_evidence = Column(Text, default="[]")
    contradicting_evidence = Column(Text, default="[]")
    confidence = Column(Float, default=0.0)
    additional_data_required = Column(Text, default="[]")
    granite_explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AuditLogDB(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True)
    event_type = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False)
    industrial_unit_id = Column(String, nullable=True, index=True)
    entity_type = Column(String, nullable=True)
    entity_id = Column(String, nullable=True)
    action = Column(String, nullable=False)
    reason = Column(Text, nullable=False)
    evidence = Column(Text, default="[]")
    input_snapshot = Column(Text, default="{}")
    output_snapshot = Column(Text, default="{}")
    confidence = Column(Float, default=1.0)
    source_type = Column(String, nullable=False)
    timestamp = Column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )


class DataSourceDB(Base):
    __tablename__ = "data_sources"

    source_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    source_type = Column(String, nullable=False)    # REST, MQTT, CSV, etc.
    industrial_unit_id = Column(String, nullable=True, index=True)
    zone = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    quality_score = Column(Float, default=1.0)
    last_success_at = Column(DateTime, nullable=True)
    last_failure_at = Column(DateTime, nullable=True)
    failure_count = Column(Integer, default=0)
    config_json = Column(Text, default="{}")
    created_at = Column(DateTime, server_default=func.now())


class SensorReliabilityDB(Base):
    __tablename__ = "sensor_reliability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sensor_id = Column(String, nullable=False, index=True)
    recorded_at = Column(DateTime, server_default=func.now(), index=True)
    reliability_score = Column(Float, nullable=False)
    quality_score = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    issues = Column(Text, default="[]")


# ── Init ─────────────────────────────────────────────────────────────────────

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
