"""
Root-Cause Analysis Engine.

Structured hypothesis generation for pollution incidents.
Uses pure Python logic + historical data analysis.
Granite is called asynchronously to enrich explanations
AFTER deterministic findings are ready.

Never presents an unverified cause as fact.
Returns structured evidence sets: observed / supporting / contradicting.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.models import (
    AnomalyEvent, PollutantType, Prediction, RootCauseAnalysis,
    SensorReading, ThresholdBreachEvent, TrendDirection,
)
from utils.helpers import get_logger, utcnow

logger = get_logger(__name__)

# ── Industry-pollutant association knowledge base ─────────────────────────────
# Kept minimal and factual; NOT a legal finding.
_INDUSTRY_POLLUTANTS: Dict[str, List[str]] = {
    "Chemical":     ["SO2", "NO2", "H2S", "NH3", "VOC", "COD", "BOD"],
    "Textile":      ["COD", "BOD", "TSS", "pH", "HeavyMetals"],
    "Pharma":       ["COD", "BOD", "VOC", "TSS"],
    "Dye":          ["COD", "BOD", "TSS", "pH", "Turbidity"],
    "Fertilizer":   ["NH3", "NO2", "SO2", "CO2"],
    "Steel":        ["SO2", "NO2", "CO", "PM2.5", "PM10"],
    "Cement":       ["PM2.5", "PM10", "SO2", "NO2"],
    "Petrochemical":["SO2", "NO2", "H2S", "VOC", "CO"],
    "General":      ["PM2.5", "PM10", "SO2", "NO2", "CO"],
}

# ── Correlated pollutant pairs (if A rises, B often rises too) ────────────────
_CORRELATED_PAIRS: List[tuple] = [
    ("SO2", "NO2"),
    ("PM2.5", "PM10"),
    ("COD", "BOD"),
    ("TSS", "Turbidity"),
    ("NH3", "H2S"),
    ("CO", "CO2"),
]


class RootCauseEngine:
    """
    Deterministic root-cause analyser.
    Granite enrichment is requested asynchronously by the orchestrator.
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    def analyze(
        self,
        incident_id: str,
        unit_id: str,
        zone: str,
        industry_type: str,
        threshold_breaches: List[ThresholdBreachEvent],
        anomaly_events: List[AnomalyEvent],
        predictions: List[Prediction],
        recent_readings: List[SensorReading],
        sensor_states: Optional[Dict[str, Any]] = None,
    ) -> RootCauseAnalysis:
        """
        Build a structured root-cause analysis.
        """
        observed = self._build_observed_evidence(
            threshold_breaches, anomaly_events, predictions, recent_readings
        )
        causes = self._hypothesize_causes(
            industry_type, threshold_breaches, anomaly_events,
            recent_readings, sensor_states or {}
        )
        supporting = self._build_supporting_evidence(
            threshold_breaches, anomaly_events, predictions, recent_readings
        )
        contradicting = self._build_contradicting_evidence(
            threshold_breaches, anomaly_events, sensor_states or {}
        )
        additional = self._additional_data_needed(
            threshold_breaches, anomaly_events, sensor_states or {}
        )
        confidence = self._estimate_confidence(
            threshold_breaches, anomaly_events, causes
        )

        return RootCauseAnalysis(
            id=uuid4(),
            incident_id=incident_id,
            industrial_unit_id=unit_id,
            zone=zone,
            observed_evidence=observed,
            possible_causes=causes,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            confidence=confidence,
            additional_data_required=additional,
            granite_explanation=None,  # populated asynchronously
            created_at=utcnow(),
        )

    # ── Evidence builders ─────────────────────────────────────────────────────

    def _build_observed_evidence(
        self,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        predictions: List[Prediction],
        readings: List[SensorReading],
    ) -> List[str]:
        evidence: List[str] = []

        for b in breaches:
            evidence.append(
                f"Threshold breach: {b.pollutant.value} = {b.value} {b.unit}"
                f" (threshold {b.threshold_value}, excess {b.excess_pct:.1f}%)"
            )
        for a in anomalies:
            evidence.append(
                f"Anomaly detected: {a.pollutant.value} = {a.value} {a.unit}"
                f" (score={a.anomaly_score:.2f}, method={a.method})"
            )
        for p in predictions:
            if p.breach_predicted:
                evidence.append(
                    f"Predicted breach: {p.pollutant.value} expected {p.predicted_value}"
                    f" {p.unit} in {p.horizon_minutes} min"
                )
        if readings:
            latest = max(readings, key=lambda r: r.timestamp, default=None)
            if latest:
                evidence.append(
                    f"Latest sensor reading: {latest.pollutant.value} = {latest.value}"
                    f" {latest.unit} at {latest.timestamp.isoformat()}"
                )
        return evidence

    def _hypothesize_causes(
        self,
        industry_type: str,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        readings: List[SensorReading],
        sensor_states: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        causes: List[Dict[str, Any]] = []
        raised_pollutants = list({
            b.pollutant.value for b in breaches
        } | {a.pollutant.value for a in anomalies})

        # ── 1. Industry-type match ────────────────────────────────────────
        industry_norm = industry_type.strip().capitalize()
        known_pollutants = _INDUSTRY_POLLUTANTS.get(
            industry_norm, _INDUSTRY_POLLUTANTS["General"]
        )
        matched = [p for p in raised_pollutants if p in known_pollutants]
        if matched:
            causes.append({
                "hypothesis": f"Process-related emission from {industry_type} operation",
                "matched_pollutants": matched,
                "confidence": "MODERATE",
                "note": "Observed pollutants are consistent with industry type. Not a confirmed finding.",
            })

        # ── 2. Correlated pollutant pairs ─────────────────────────────────
        for a, b in _CORRELATED_PAIRS:
            if a in raised_pollutants and b in raised_pollutants:
                causes.append({
                    "hypothesis": f"Combined {a}+{b} elevation suggests common source",
                    "matched_pollutants": [a, b],
                    "confidence": "LOW-MODERATE",
                    "note": "Co-elevation may indicate a single emission event.",
                })

        # ── 3. Sensor health check ────────────────────────────────────────
        unreliable = [
            sid for sid, s in sensor_states.items()
            if s.get("reliability_score", 1.0) < 0.5
        ]
        if unreliable:
            causes.append({
                "hypothesis": "Sensor malfunction contributing to false anomaly",
                "matched_pollutants": [],
                "confidence": "LOW",
                "note": f"Sensors with low reliability: {unreliable}. Verify readings physically.",
            })

        # ── 4. Rapid ramp pattern ─────────────────────────────────────────
        rapid_rises = [
            b for b in breaches if b.excess_pct > 50
        ]
        if rapid_rises:
            causes.append({
                "hypothesis": "Acute emission event (spill, equipment failure, or process upset)",
                "matched_pollutants": [b.pollutant.value for b in rapid_rises],
                "confidence": "MODERATE",
                "note": f"Excess >50% above threshold observed. Suggests sudden event.",
            })

        if not causes:
            causes.append({
                "hypothesis": "Cause undetermined — insufficient evidence",
                "matched_pollutants": raised_pollutants,
                "confidence": "VERY_LOW",
                "note": "Additional inspection and data collection recommended.",
            })

        return causes

    def _build_supporting_evidence(
        self,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        predictions: List[Prediction],
        readings: List[SensorReading],
    ) -> List[str]:
        support: List[str] = []
        if len(breaches) > 1:
            support.append(f"Multiple threshold breaches ({len(breaches)}) across parameters")
        confirmed_anomalies = [a for a in anomalies if a.is_confirmed]
        if confirmed_anomalies:
            support.append(
                f"{len(confirmed_anomalies)} cross-sensor confirmed anomalies"
            )
        breach_preds = [p for p in predictions if p.breach_predicted]
        if breach_preds:
            support.append(f"Predictive model forecasts {len(breach_preds)} future breach(es)")
        return support

    def _build_contradicting_evidence(
        self,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        sensor_states: Dict[str, Any],
    ) -> List[str]:
        contra: List[str] = []
        low_quality = [
            b for b in breaches if b.quality_score < 0.6
        ]
        if low_quality:
            contra.append(
                f"{len(low_quality)} breach reading(s) have low quality score (<0.6) — "
                "may reflect sensor issues rather than real pollution"
            )
        unconfirmed = [a for a in anomalies if not a.is_confirmed]
        if unconfirmed:
            contra.append(
                f"{len(unconfirmed)} anomaly(s) not cross-sensor confirmed — "
                "could be isolated sensor noise"
            )
        return contra

    def _additional_data_needed(
        self,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        sensor_states: Dict[str, Any],
    ) -> List[str]:
        needed: List[str] = []
        needed.append("Meteorological data (wind speed/direction) to assess dispersion")
        needed.append("CCTV/inspection log from facility for the breach period")
        if any(b.pollutant.value in ["H2S", "NH3", "VOC"] for b in breaches):
            needed.append("Stack emission data from process chimneys")
        if any(b.pollutant.value in ["COD", "BOD", "TSS"] for b in breaches):
            needed.append("Effluent Treatment Plant (ETP) operation log")
        unreliable = [sid for sid, s in sensor_states.items() if s.get("reliability_score", 1.0) < 0.6]
        if unreliable:
            needed.append(f"Physical calibration check for sensors: {unreliable}")
        return needed

    def _estimate_confidence(
        self,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
        causes: List[Dict[str, Any]],
    ) -> float:
        base = 0.3
        if breaches:
            avg_q = sum(b.quality_score for b in breaches) / len(breaches)
            base += 0.2 * avg_q
        confirmed = sum(1 for a in anomalies if a.is_confirmed)
        base += min(0.2, confirmed * 0.05)
        high_conf_causes = sum(1 for c in causes if c["confidence"] in ("MODERATE", "HIGH"))
        base += min(0.2, high_conf_causes * 0.1)
        return round(min(0.85, base), 3)


# Module-level singleton
root_cause_engine = RootCauseEngine()
