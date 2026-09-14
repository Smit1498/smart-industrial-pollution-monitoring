"""
Monitoring Orchestrator — the central agent loop.

Implements:
  OBSERVE → VALIDATE → ANALYZE → PREDICT → DECIDE → ACT → MONITOR → LEARN

For each sensor batch:
  1.  Ingest raw data
  2.  Validate / quality-check
  3.  Persist valid readings
  4.  Detect threshold breaches
  5.  Detect anomalies
  6.  Generate predictions
  7.  Compute risk scores
  8.  Create incidents and alerts
  9.  Request Granite explanation (async, non-blocking for critical path)
  10. Run root-cause analysis
  11. Write audit log
  12. Adapt monitoring frequency

Bounded autonomy — the orchestrator never:
  - Shuts down facilities
  - Imposes penalties
  - Fabricates data
  - Bypasses security
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.config import get_settings
from app.models import (
    Alert, AlertSeverity, AlertStatus, AnomalyEvent,
    AuditLog, DataSourceType, Incident, IncidentStatus,
    Prediction, RiskAssessment, RiskLevel, SensorReading,
    ThresholdBreachEvent, SystemStatus, ResourceMode,
)
from agents.data_quality_agent import data_quality_engine
from agents.root_cause_agent import root_cause_engine
from data_sources.ingestion import coerce_batch
from data_sources.manager import data_source_registry
from detection.anomaly_engine import anomaly_engine
from detection.threshold_engine import threshold_engine
from prediction.prediction_engine import prediction_engine
from risk.risk_engine import risk_engine
from utils.helpers import get_logger, utcnow

logger = get_logger(__name__)
settings = get_settings()

# ── Lazy import of db / alert / granite to avoid circular deps ────────────────
def _get_db_session():
    from database.db_models import AsyncSessionLocal
    return AsyncSessionLocal()


class MonitoringOrchestrator:
    """
    Central agent loop. One instance per process.
    """

    def __init__(self) -> None:
        self._running = False
        self._status = SystemStatus()
        self._poll_interval = settings.POLL_INTERVAL_SECONDS
        self._unit_registry: Dict[str, Dict[str, Any]] = {}   # unit_id → IndustrialUnit dict
        self._active_incidents: Dict[str, Incident] = {}       # incident_id → Incident
        self._active_alerts: Dict[str, Alert] = {}             # alert_id → Alert
        self._alert_callbacks: List[Any] = []
        # Per-unit recent evidence (for root-cause + audit)
        self._unit_evidence: Dict[str, Dict[str, Any]] = {}

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        logger.info("MonitoringOrchestrator started (poll=%ds)", self._poll_interval)
        asyncio.create_task(self._main_loop())

    async def stop(self) -> None:
        self._running = False
        logger.info("MonitoringOrchestrator stopped")

    def register_unit(self, unit: Dict[str, Any]) -> None:
        self._unit_registry[unit["unit_id"]] = unit

    def register_alert_callback(self, cb) -> None:
        """Register a coroutine callback(alert) for real-time notifications."""
        self._alert_callbacks.append(cb)

    # ── Main loop ──────────────────────────────────────────────────────────────

    async def _main_loop(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:
                logger.error("Orchestrator cycle error: %s", exc, exc_info=True)
            await asyncio.sleep(self._poll_interval)

    # ── Single cycle ──────────────────────────────────────────────────────────

    async def _cycle(self) -> None:
        # ── OBSERVE ────────────────────────────────────────────────────────
        raw_records = await data_source_registry.fetch_all()
        if not raw_records:
            return

        # ── Coerce ─────────────────────────────────────────────────────────
        readings = coerce_batch(raw_records)

        # ── VALIDATE ───────────────────────────────────────────────────────
        validated_readings, quality_reports = data_quality_engine.validate_batch(readings)

        # Persist readings in background
        asyncio.create_task(self._persist_readings(validated_readings))

        # Group valid readings by unit
        by_unit: Dict[str, List[SensorReading]] = {}
        for r in validated_readings:
            if r.is_valid:
                by_unit.setdefault(r.industrial_unit_id, []).append(r)

        # ── Per-unit ANALYZE → PREDICT → DECIDE → ACT ─────────────────────
        for unit_id, unit_readings in by_unit.items():
            await self._process_unit(unit_id, unit_readings)

        # Update system status
        self._update_system_status(validated_readings)

    async def _process_unit(
        self, unit_id: str, readings: List[SensorReading]
    ) -> None:
        unit = self._unit_registry.get(unit_id, {"unit_id": unit_id, "zone": "Unknown",
                                                   "industry_type": "General"})
        zone = unit.get("zone", "Unknown")
        industry_type = unit.get("industry_type", "General")

        # ── ANALYZE: Thresholds ────────────────────────────────────────────
        breaches: List[ThresholdBreachEvent] = []
        for r in readings:
            breaches.extend(threshold_engine.evaluate(r))

        # ── ANALYZE: Anomalies ─────────────────────────────────────────────
        reliability_map = {
            r.sensor_id: data_quality_engine.get_sensor_reliability(r.sensor_id)
            for r in readings
        }
        anomalies: List[AnomalyEvent] = anomaly_engine.analyze_batch(
            readings, reliability_map
        )

        # ── PREDICT ────────────────────────────────────────────────────────
        predictions: List[Prediction] = prediction_engine.predict_batch(readings, 30)

        # ── DECIDE: Risk score ─────────────────────────────────────────────
        avg_reliability = (
            sum(reliability_map.values()) / len(reliability_map)
            if reliability_map else 1.0
        )
        sensor_states = data_quality_engine.all_sensor_states()
        risk = risk_engine.assess(
            unit_id=unit_id,
            zone=zone,
            threshold_breaches=breaches,
            anomaly_events=anomalies,
            predictions=predictions,
            sensor_reliability_avg=avg_reliability,
        )

        # Store evidence for root-cause + queries
        self._unit_evidence[unit_id] = {
            "breaches": breaches,
            "anomalies": anomalies,
            "predictions": predictions,
            "risk": risk,
            "readings": readings[-20:],
        }

        # Persist risk / predictions
        asyncio.create_task(self._persist_risk_and_predictions(unit_id, risk, predictions))

        # ── ACT: Alert & escalation ────────────────────────────────────────
        if breaches or anomalies or risk.risk_score >= 41:
            await self._handle_events(
                unit_id, zone, industry_type, risk, breaches,
                anomalies, predictions, readings, sensor_states
            )

    # ── Event handling ─────────────────────────────────────────────────────────

    async def _handle_events(
        self,
        unit_id: str,
        zone: str,
        industry_type: str,
        risk: RiskAssessment,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        predictions: List[Prediction],
        readings: List[SensorReading],
        sensor_states: Dict[str, Any],
    ) -> None:

        severity = self._risk_to_severity(risk.risk_level)

        # Create or update incident
        incident = await self._upsert_incident(
            unit_id, zone, severity, risk, breaches, anomalies, predictions
        )

        # Generate alert
        alert = self._build_alert(unit_id, zone, severity, risk, breaches, anomalies, incident.id)
        self._active_alerts[str(alert.id)] = alert
        asyncio.create_task(self._persist_alert(alert))

        # Fire callbacks (e.g. WebSocket broadcast)
        for cb in self._alert_callbacks:
            try:
                await cb(alert)
            except Exception:
                pass

        # Audit log
        asyncio.create_task(self._write_audit(
            event_type="RISK_EVENT",
            actor="orchestrator",
            unit_id=unit_id,
            action="ALERT_GENERATED",
            reason=f"Risk={risk.risk_score} ({risk.risk_level.value})",
            evidence=[str(b.id) for b in breaches] + [str(a.id) for a in anomalies],
            confidence=risk.confidence,
        ))

        # Root-cause analysis for ELEVATED+
        if risk.risk_level in (RiskLevel.ELEVATED, RiskLevel.HIGH, RiskLevel.CRITICAL):
            rca = root_cause_engine.analyze(
                incident_id=str(incident.id),
                unit_id=unit_id,
                zone=zone,
                industry_type=industry_type,
                threshold_breaches=breaches,
                anomaly_events=anomalies,
                predictions=predictions,
                recent_readings=readings,
                sensor_states=sensor_states,
            )
            # Request Granite explanation asynchronously (never blocks critical path)
            asyncio.create_task(self._enrich_with_granite(rca, risk, incident))

        # Increase poll frequency for high/critical
        if risk.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            self._poll_interval = max(10, settings.POLL_INTERVAL_SECONDS // 3)
        else:
            self._poll_interval = settings.POLL_INTERVAL_SECONDS

    async def _upsert_incident(
        self,
        unit_id: str,
        zone: str,
        severity: AlertSeverity,
        risk: RiskAssessment,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        predictions: List[Prediction],
    ) -> Incident:
        pollutants = list({b.pollutant for b in breaches} | {a.pollutant for a in anomalies})

        # Check if there's an open incident for this unit
        existing = next(
            (i for i in self._active_incidents.values()
             if i.industrial_unit_id == unit_id and i.status == IncidentStatus.OPEN),
            None
        )
        if existing:
            existing.pollutants_involved = list(set(existing.pollutants_involved) | set(pollutants))
            existing.risk_score = risk.risk_score
            existing.risk_level = risk.risk_level
            existing.updated_at = utcnow()
            return existing

        title = (
            f"{severity.value} pollution event — {zone}"
            if not breaches
            else f"{breaches[0].pollutant.value} threshold breach — {zone}"
        )
        description = self._build_incident_description(risk, breaches, anomalies, predictions)

        incident = Incident(
            id=uuid4(),
            industrial_unit_id=unit_id,
            zone=zone,
            status=IncidentStatus.OPEN,
            severity=severity,
            title=title,
            description=description,
            pollutants_involved=pollutants,
            risk_score=risk.risk_score,
            risk_level=risk.risk_level,
            threshold_breaches=[str(b.id) for b in breaches],
            anomalies=[str(a.id) for a in anomalies],
            source_type=DataSourceType.LIVE,
        )
        self._active_incidents[str(incident.id)] = incident
        asyncio.create_task(self._persist_incident(incident))
        return incident

    def _build_alert(
        self,
        unit_id: str,
        zone: str,
        severity: AlertSeverity,
        risk: RiskAssessment,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        incident_id,
    ) -> Alert:
        top_breach = max(breaches, key=lambda b: b.excess_pct, default=None)
        evidence = [
            f"Risk score: {risk.risk_score:.1f} ({risk.risk_level.value})"
        ]
        if top_breach:
            evidence.append(
                f"Top breach: {top_breach.pollutant.value} = {top_breach.value} "
                f"({top_breach.excess_pct:.1f}% above threshold)"
            )
        evidence += [
            f"Anomalies: {len(anomalies)} detected"
            f" ({sum(1 for a in anomalies if a.is_confirmed)} confirmed)"
        ]

        return Alert(
            id=uuid4(),
            industrial_unit_id=unit_id,
            zone=zone,
            severity=severity,
            status=AlertStatus.ACTIVE,
            title=f"[{severity.value}] Pollution event — {zone}",
            message=self._build_alert_message(risk, breaches, anomalies),
            pollutant=top_breach.pollutant if top_breach else None,
            value=top_breach.value if top_breach else None,
            threshold=top_breach.threshold_value if top_breach else None,
            risk_score=risk.risk_score,
            risk_level=risk.risk_level,
            source_type=DataSourceType.LIVE,
            incident_id=str(incident_id),
            evidence=evidence,
        )

    def _build_alert_message(self, risk, breaches, anomalies) -> str:
        lines = [
            f"Risk Level: {risk.risk_level.value} (Score: {risk.risk_score:.1f}/100)",
        ]
        if breaches:
            lines.append(f"Threshold breaches: {len(breaches)}")
            for b in breaches[:3]:
                lines.append(
                    f"  • {b.pollutant.value}: {b.value} {b.unit} "
                    f"(+{b.excess_pct:.1f}% above {b.threshold_value})"
                )
        if anomalies:
            lines.append(f"Anomalies detected: {len(anomalies)}")
        if risk.dominant_pollutant:
            lines.append(f"Dominant pollutant: {risk.dominant_pollutant.value}")
        lines.append(f"Confidence: {risk.confidence:.0%}")
        return "\n".join(lines)

    def _build_incident_description(self, risk, breaches, anomalies, predictions) -> str:
        parts = [
            f"Pollution incident detected.",
            f"Risk score: {risk.risk_score:.1f} ({risk.risk_level.value}).",
        ]
        if breaches:
            parts.append(
                f"{len(breaches)} regulatory threshold breach(es) detected. "
                f"Status: POTENTIAL_VIOLATION (official confirmation required)."
            )
        if anomalies:
            parts.append(f"{len(anomalies)} anomalous sensor reading(s) detected.")
        if any(p.breach_predicted for p in predictions):
            parts.append("Predictive model forecasts continued deterioration.")
        return " ".join(parts)

    # ── Granite async enrichment (never blocks critical path) ─────────────────

    async def _enrich_with_granite(self, rca, risk, incident) -> None:
        try:
            from ai.granite_client import granite_client
            if not granite_client.is_available():
                return
            explanation = await granite_client.explain_incident(
                risk=risk,
                rca=rca,
                incident=incident,
            )
            if explanation:
                rca.granite_explanation = explanation
                incident.granite_summary = explanation[:500]
        except Exception as exc:
            logger.warning("Granite enrichment failed (non-critical): %s", exc)

    # ── Persist helpers ───────────────────────────────────────────────────────

    async def _persist_readings(self, readings: List[SensorReading]) -> None:
        try:
            async with _get_db_session() as db:
                from database.crud import insert_reading
                for r in readings:
                    await insert_reading(db, r.model_dump())
        except Exception as exc:
            logger.error("Failed to persist readings: %s", exc)

    async def _persist_risk_and_predictions(
        self, unit_id: str, risk: RiskAssessment, predictions: List[Prediction]
    ) -> None:
        try:
            async with _get_db_session() as db:
                from database.crud import update_unit_risk, insert_prediction
                await update_unit_risk(db, unit_id, risk.risk_score, risk.risk_level.value)
                for p in predictions:
                    await insert_prediction(db, p.model_dump())
        except Exception as exc:
            logger.error("Failed to persist risk/predictions: %s", exc)

    async def _persist_incident(self, incident: Incident) -> None:
        try:
            async with _get_db_session() as db:
                from database.crud import insert_incident
                d = incident.model_dump()
                d["pollutants_involved"] = [p.value for p in d["pollutants_involved"]]
                await insert_incident(db, d)
        except Exception as exc:
            logger.error("Failed to persist incident: %s", exc)

    async def _persist_alert(self, alert: Alert) -> None:
        try:
            async with _get_db_session() as db:
                from database.crud import insert_alert
                d = alert.model_dump()
                if d.get("pollutant"):
                    d["pollutant"] = d["pollutant"].value if hasattr(d["pollutant"], "value") else d["pollutant"]
                await insert_alert(db, d)
        except Exception as exc:
            logger.error("Failed to persist alert: %s", exc)

    async def _write_audit(
        self,
        event_type: str,
        actor: str,
        unit_id: str,
        action: str,
        reason: str,
        evidence: List[str],
        confidence: float = 1.0,
    ) -> None:
        try:
            async with _get_db_session() as db:
                from database.crud import insert_audit_log
                log = AuditLog(
                    id=uuid4(),
                    event_type=event_type,
                    actor=actor,
                    industrial_unit_id=unit_id,
                    action=action,
                    reason=reason,
                    evidence=evidence,
                    confidence=confidence,
                    source_type=DataSourceType.LIVE,
                )
                await insert_audit_log(db, log.model_dump())
        except Exception as exc:
            logger.error("Failed to write audit log: %s", exc)

    # ── System status ─────────────────────────────────────────────────────────

    def _update_system_status(self, readings: List[SensorReading]) -> None:
        states = data_quality_engine.all_sensor_states()
        self._status.total_sensors = len(states)
        self._status.online_sensors = sum(
            1 for s in states.values() if s["status"] == "ONLINE"
        )
        self._status.stale_sensors = sum(
            1 for s in states.values() if s["status"] == "STALE"
        )
        self._status.offline_sensors = sum(
            1 for s in states.values() if s["status"] == "OFFLINE"
        )
        self._status.active_incidents = sum(
            1 for i in self._active_incidents.values()
            if i.status == IncidentStatus.OPEN
        )
        self._status.active_alerts = sum(
            1 for a in self._active_alerts.values()
            if a.status == AlertStatus.ACTIVE
        )
        self._status.last_updated = utcnow()

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _risk_to_severity(level: RiskLevel) -> AlertSeverity:
        mapping = {
            RiskLevel.LOW: AlertSeverity.INFO,
            RiskLevel.MODERATE: AlertSeverity.INFO,
            RiskLevel.ELEVATED: AlertSeverity.WARNING,
            RiskLevel.HIGH: AlertSeverity.HIGH,
            RiskLevel.CRITICAL: AlertSeverity.CRITICAL,
        }
        return mapping.get(level, AlertSeverity.WARNING)

    # ── Query helpers (called by API) ─────────────────────────────────────────

    def get_status(self) -> SystemStatus:
        return self._status

    def get_unit_evidence(self, unit_id: str) -> Dict[str, Any]:
        return self._unit_evidence.get(unit_id, {})

    def get_active_alerts(self) -> List[Alert]:
        return list(self._active_alerts.values())

    def get_active_incidents(self) -> List[Incident]:
        return list(self._active_incidents.values())

    async def process_manual_reading(self, reading: SensorReading) -> None:
        """Process a single manually-submitted reading through the full pipeline."""
        validated, _ = data_quality_engine.validate_batch([reading])
        unit_id = reading.industrial_unit_id
        await self._process_unit(unit_id, [r for r in validated if r.is_valid])


# ── Module-level singleton ────────────────────────────────────────────────────
orchestrator = MonitoringOrchestrator()
