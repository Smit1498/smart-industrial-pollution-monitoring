"""
Core domain types shared across the entire system.

Every measurement / event carries a DataSourceType so downstream
components always know whether they are working with live, historical,
simulated, or predicted data.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════
# Enums
# ═══════════════════════════════════════════════════════════════════════════

class DataSourceType(str, Enum):
    LIVE = "LIVE"
    HISTORICAL = "HISTORICAL"
    SIMULATED = "SIMULATED"
    PREDICTED = "PREDICTED"


class ResourceMode(str, Enum):
    NORMAL = "NORMAL"
    LOW_RESOURCE = "LOW_RESOURCE"
    EMERGENCY = "EMERGENCY"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class SensorStatus(str, Enum):
    ONLINE = "ONLINE"
    STALE = "STALE"
    FROZEN = "FROZEN"
    OFFLINE = "OFFLINE"
    UNRELIABLE = "UNRELIABLE"


class PollutantType(str, Enum):
    # Air pollutants
    PM25 = "PM2.5"
    PM10 = "PM10"
    SO2 = "SO2"
    NO2 = "NO2"
    CO = "CO"
    CO2 = "CO2"
    VOC = "VOC"
    NH3 = "NH3"
    H2S = "H2S"
    O3 = "O3"
    # Water pollutants
    PH = "pH"
    BOD = "BOD"
    COD = "COD"
    TSS = "TSS"
    DO = "DO"          # Dissolved Oxygen
    WATER_TEMP = "WaterTemp"
    CONDUCTIVITY = "Conductivity"
    TURBIDITY = "Turbidity"
    HEAVY_METALS = "HeavyMetals"


class MediaType(str, Enum):
    AIR = "AIR"
    WATER = "WATER"


class TrendDirection(str, Enum):
    RAPIDLY_INCREASING = "RAPIDLY_INCREASING"
    INCREASING = "INCREASING"
    STABLE = "STABLE"
    DECREASING = "DECREASING"
    RAPIDLY_DECREASING = "RAPIDLY_DECREASING"
    UNKNOWN = "UNKNOWN"


class ViolationStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    POTENTIAL_VIOLATION = "POTENTIAL_VIOLATION"      # evidence incomplete
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"      # only with official evidence
    WARNING_ZONE = "WARNING_ZONE"                    # approaching threshold


# ═══════════════════════════════════════════════════════════════════════════
# Core measurement types
# ═══════════════════════════════════════════════════════════════════════════

class SensorReading(BaseModel):
    """A single sensor reading — the fundamental unit of data."""
    id: UUID = Field(default_factory=uuid4)
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: PollutantType
    media: MediaType
    value: float
    unit: str
    timestamp: datetime
    source_type: DataSourceType
    source_id: str                         # which data-source produced this
    raw_value: Optional[float] = None      # before unit conversion
    quality_score: float = 1.0             # 0.0–1.0, set by data-quality agent
    is_valid: bool = True
    validation_notes: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SensorMetadata(BaseModel):
    """Static description of a sensor."""
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: PollutantType
    media: MediaType
    unit: str
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    manufacturer: Optional[str] = None
    calibration_date: Optional[datetime] = None
    reliability_score: float = 1.0         # updated by data-quality agent
    status: SensorStatus = SensorStatus.ONLINE
    last_reading_at: Optional[datetime] = None
    notes: str = ""


class IndustrialUnit(BaseModel):
    """An industrial facility being monitored."""
    unit_id: str
    name: str
    zone: str
    industry_type: str                     # e.g. "Chemical", "Textile", "Pharma"
    location_lat: Optional[float] = None
    location_lon: Optional[float] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    is_monitored: bool = True
    sensors: List[str] = Field(default_factory=list)   # sensor_ids
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    last_assessed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DataQualityReport(BaseModel):
    """Quality assessment for a batch of readings from one source."""
    source_id: str
    sensor_id: Optional[str] = None
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
    total_records: int = 0
    valid_records: int = 0
    issues: List[str] = Field(default_factory=list)
    quality_score: float = 1.0             # 0.0–1.0
    sensor_reliability_score: float = 1.0
    is_stale: bool = False
    is_frozen: bool = False
    has_impossible_values: bool = False
    has_future_timestamps: bool = False
    has_duplicates: bool = False
    notes: str = ""


class ThresholdBreachEvent(BaseModel):
    """Fired when a reading crosses a regulatory threshold."""
    id: UUID = Field(default_factory=uuid4)
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: PollutantType
    value: float
    unit: str
    threshold_value: float
    threshold_type: str                    # "hourly_limit", "daily_limit", etc.
    excess_pct: float                      # how many % above threshold
    violation_status: ViolationStatus
    source_type: DataSourceType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    quality_score: float = 1.0


class AnomalyEvent(BaseModel):
    """Anomaly detected by the anomaly-detection engine."""
    id: UUID = Field(default_factory=uuid4)
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: PollutantType
    value: float
    unit: str
    anomaly_score: float                   # 0.0–1.0
    method: str                            # "zscore", "isolation_forest", etc.
    zscore: Optional[float] = None
    ewma_deviation: Optional[float] = None
    is_confirmed: bool = False             # cross-sensor confirmation
    source_type: DataSourceType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)


class RiskAssessment(BaseModel):
    """System/AI risk score for an industrial unit at a point in time."""
    id: UUID = Field(default_factory=uuid4)
    industrial_unit_id: str
    zone: str
    risk_score: float                      # 0–100
    risk_level: RiskLevel
    contributing_factors: List[Dict[str, Any]] = Field(default_factory=list)
    dominant_pollutant: Optional[PollutantType] = None
    threshold_breaches: int = 0
    anomaly_count: int = 0
    sensor_reliability_avg: float = 1.0
    prediction_risk_boost: float = 0.0
    confidence: float = 1.0
    assessed_at: datetime = Field(default_factory=datetime.utcnow)
    source_type: DataSourceType = DataSourceType.LIVE


class Prediction(BaseModel):
    """Future-value prediction for a pollutant."""
    id: UUID = Field(default_factory=uuid4)
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: PollutantType
    current_value: float
    predicted_value: float
    worst_case_value: float
    unit: str
    horizon_minutes: int
    trend: TrendDirection
    threshold_value: Optional[float] = None
    breach_predicted: bool = False
    breach_eta_minutes: Optional[int] = None
    confidence: float = 1.0
    uncertainty_pct: float = 0.0
    model_used: str = ""
    evidence: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source_type: DataSourceType = DataSourceType.PREDICTED


class RootCauseAnalysis(BaseModel):
    """Structured root-cause analysis for an incident."""
    id: UUID = Field(default_factory=uuid4)
    incident_id: str
    industrial_unit_id: str
    zone: str
    observed_evidence: List[str] = Field(default_factory=list)
    possible_causes: List[Dict[str, Any]] = Field(default_factory=list)
    supporting_evidence: List[str] = Field(default_factory=list)
    contradicting_evidence: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    additional_data_required: List[str] = Field(default_factory=list)
    granite_explanation: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Alert(BaseModel):
    """An alert generated by the system."""
    id: UUID = Field(default_factory=uuid4)
    industrial_unit_id: str
    zone: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.ACTIVE
    title: str
    message: str
    pollutant: Optional[PollutantType] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    risk_score: Optional[float] = None
    risk_level: Optional[RiskLevel] = None
    source_type: DataSourceType
    incident_id: Optional[str] = None
    granite_explanation: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)
    actions_taken: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    auto_escalated: bool = False


class Incident(BaseModel):
    """A pollution incident aggregating related events."""
    id: UUID = Field(default_factory=uuid4)
    industrial_unit_id: str
    zone: str
    status: IncidentStatus = IncidentStatus.OPEN
    severity: AlertSeverity
    title: str
    description: str
    pollutants_involved: List[PollutantType] = Field(default_factory=list)
    risk_score: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    threshold_breaches: List[str] = Field(default_factory=list)
    anomalies: List[str] = Field(default_factory=list)
    alerts: List[str] = Field(default_factory=list)
    root_cause_id: Optional[str] = None
    granite_summary: Optional[str] = None
    human_notes: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    source_type: DataSourceType


class AuditLog(BaseModel):
    """Immutable record of every significant system decision."""
    id: UUID = Field(default_factory=uuid4)
    event_type: str
    actor: str                             # agent / user / system
    industrial_unit_id: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    action: str
    reason: str
    evidence: List[str] = Field(default_factory=list)
    input_snapshot: Dict[str, Any] = Field(default_factory=dict)
    output_snapshot: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    source_type: DataSourceType
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SystemStatus(BaseModel):
    """Overall health of the monitoring system."""
    healthy: bool = True
    resource_mode: ResourceMode = ResourceMode.NORMAL
    degraded_components: List[str] = Field(default_factory=list)
    granite_available: bool = True
    ml_available: bool = True
    database_available: bool = True
    total_sensors: int = 0
    online_sensors: int = 0
    stale_sensors: int = 0
    offline_sensors: int = 0
    active_incidents: int = 0
    active_alerts: int = 0
    last_updated: datetime = Field(default_factory=datetime.utcnow)
