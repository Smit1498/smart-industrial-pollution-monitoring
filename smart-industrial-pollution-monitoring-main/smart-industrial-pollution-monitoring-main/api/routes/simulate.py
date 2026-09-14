"""
Simulation control endpoint.
POST /simulate/event  — inject a synthetic pollution event
POST /analyze         — run a one-shot analysis on provided data
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from data_sources.manager import data_source_registry, SimulatedDataSource
from orchestration.orchestrator import orchestrator

router = APIRouter()


class SimulateEventPayload(BaseModel):
    unit_id: str = "VAPI-001"
    event_mode: str = "WARNING"    # NORMAL | WARNING | HIGH_RISK | CRITICAL | RECOVERY
    duration_cycles: int = 5


@router.post("/simulate-event")
async def simulate_event(payload: SimulateEventPayload):
    """
    Set the event mode on the simulated data source for a unit.
    Affects the next N monitoring cycles.
    """
    valid_modes = {"NORMAL", "WARNING", "HIGH_RISK", "CRITICAL", "RECOVERY"}
    if payload.event_mode not in valid_modes:
        raise HTTPException(400, f"event_mode must be one of {valid_modes}")

    source_id = f"sim-{payload.unit_id}"
    source = data_source_registry.get(source_id)
    if source is None:
        raise HTTPException(404, f"No simulated source found for unit '{payload.unit_id}'")
    if not isinstance(source, SimulatedDataSource):
        raise HTTPException(400, "Data source is not a SimulatedDataSource")

    source.set_event_mode(payload.event_mode)
    return {
        "unit_id": payload.unit_id,
        "event_mode": payload.event_mode,
        "note": (
            f"Simulated '{payload.event_mode}' event activated for {payload.unit_id}. "
            "Source type: SIMULATED — not live data."
        ),
    }


class AnalyzePayload(BaseModel):
    sensor_id: str
    industrial_unit_id: str
    zone: str
    pollutant: str
    media: str = "AIR"
    value: float
    unit: str
    source_type: str = "SIMULATED"
    source_id: str = "api_analyze"


@router.post("/analyze")
async def analyze_single(payload: AnalyzePayload):
    """One-shot analysis of a reading without persisting to DB."""
    from data_sources.ingestion import coerce_reading
    from agents.data_quality_agent import data_quality_engine
    from detection.threshold_engine import threshold_engine
    from detection.anomaly_engine import anomaly_engine
    from prediction.prediction_engine import prediction_engine
    from risk.risk_engine import risk_engine
    from app.models import DataSourceType

    raw = payload.model_dump()
    reading = coerce_reading(raw)
    if reading is None:
        raise HTTPException(400, "Invalid reading payload")

    validated, reports = data_quality_engine.validate_batch([reading])
    valid = [r for r in validated if r.is_valid]

    breaches = []
    anomalies = []
    predictions_list = []
    risk_assessment = None

    if valid:
        r = valid[0]
        breaches = threshold_engine.evaluate(r)
        reliability = data_quality_engine.get_sensor_reliability(r.sensor_id)
        anomaly = anomaly_engine.analyze(r, reliability)
        if anomaly:
            anomalies = [anomaly]
        pred = prediction_engine.predict(r, 30)
        if pred:
            predictions_list = [pred]

        risk_assessment = risk_engine.assess(
            unit_id=payload.industrial_unit_id,
            zone=payload.zone,
            threshold_breaches=breaches,
            anomaly_events=anomalies,
            predictions=predictions_list,
            sensor_reliability_avg=reliability,
            source_type=DataSourceType.SIMULATED,
        )

    return {
        "source_type": "SIMULATED",
        "reading": {"sensor_id": payload.sensor_id, "value": payload.value, "unit": payload.unit},
        "quality": reports[0].model_dump() if reports else None,
        "threshold_breaches": len(breaches),
        "anomalies": len(anomalies),
        "risk_score": risk_assessment.risk_score if risk_assessment else 0,
        "risk_level": risk_assessment.risk_level.value if risk_assessment else "UNKNOWN",
        "breach_details": [
            {"pollutant": b.pollutant.value, "excess_pct": b.excess_pct, "status": b.violation_status.value}
            for b in breaches
        ],
        "anomaly_details": [
            {"score": a.anomaly_score, "method": a.method, "confirmed": a.is_confirmed}
            for a in anomalies
        ],
        "prediction": predictions_list[0].model_dump() if predictions_list else None,
    }
