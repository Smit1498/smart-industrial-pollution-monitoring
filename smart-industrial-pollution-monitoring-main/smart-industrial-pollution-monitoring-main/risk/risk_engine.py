"""
Risk Assessment Engine.

Computes a 0–100 AI/System Risk Score for an industrial unit by
combining multiple evidence signals.  The algorithm is purely
deterministic Python — no LLM involvement.

Score composition (configurable weights):
  - Threshold breach severity      : 35 pts
  - Anomaly evidence               : 20 pts
  - Duration / persistence         : 15 pts
  - Prediction risk                :  10 pts
  - Pollutant hazard class         :  10 pts
  - Sensor / source reliability     : -10 pts (penalty for low quality)
  - Multi-pollutant confirmation    :  10 pts bonus

Classification:
  0–20  : LOW
  21–40 : MODERATE
  41–60 : ELEVATED
  61–80 : HIGH
  81–100: CRITICAL
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.config import get_settings
from app.models import (
    AnomalyEvent, DataSourceType, PollutantType,
    Prediction, RiskAssessment, RiskLevel,
    ThresholdBreachEvent,
)
from utils.helpers import get_logger, utcnow

logger = get_logger(__name__)
settings = get_settings()

_HAZARD_WEIGHTS: Dict[str, float] = {
    "CRITICAL": 1.0,
    "HIGH":     0.75,
    "MEDIUM":   0.5,
    "LOW":      0.25,
}

_POLLUTANT_HAZARD: Dict[str, str] = {
    "H2S":         "CRITICAL",
    "HeavyMetals": "CRITICAL",
    "SO2":         "HIGH",
    "NO2":         "HIGH",
    "CO":          "HIGH",
    "NH3":         "HIGH",
    "O3":          "HIGH",
    "VOC":         "HIGH",
    "BOD":         "HIGH",
    "COD":         "HIGH",
    "PM2.5":       "MEDIUM",
    "PM10":        "MEDIUM",
    "CO2":         "LOW",
    "TSS":         "MEDIUM",
    "DO":          "HIGH",
    "WaterTemp":   "MEDIUM",
    "Conductivity":"MEDIUM",
    "Turbidity":   "MEDIUM",
    "pH":          "MEDIUM",
}


def _risk_level(score: float) -> RiskLevel:
    if score <= settings.RISK_LOW_MAX:
        return RiskLevel.LOW
    if score <= settings.RISK_MODERATE_MAX:
        return RiskLevel.MODERATE
    if score <= settings.RISK_ELEVATED_MAX:
        return RiskLevel.ELEVATED
    if score <= settings.RISK_HIGH_MAX:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


class RiskEngine:
    """
    Deterministic risk scoring engine.
    One instance per process (stateful: tracks duration of active events).
    """

    def __init__(self) -> None:
        # Track when a unit first entered elevated risk
        self._elevated_since: Dict[str, Optional[datetime]] = {}
        # Track per-unit rolling max scores for persistence
        self._recent_scores: Dict[str, List[float]] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def assess(
        self,
        unit_id: str,
        zone: str,
        threshold_breaches: List[ThresholdBreachEvent],
        anomaly_events: List[AnomalyEvent],
        predictions: List[Prediction],
        sensor_reliability_avg: float = 1.0,
        source_type: DataSourceType = DataSourceType.LIVE,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        """
        Compute the current risk score for unit_id.
        """
        score = 0.0
        factors: List[Dict[str, Any]] = []

        # ── 1. Threshold breach severity (max 35 pts) ─────────────────────
        breach_pts, breach_factors = self._score_breaches(threshold_breaches)
        score += breach_pts
        factors.extend(breach_factors)

        # ── 2. Anomaly evidence (max 20 pts) ──────────────────────────────
        anomaly_pts, anomaly_factors = self._score_anomalies(anomaly_events)
        score += anomaly_pts
        factors.extend(anomaly_factors)

        # ── 3. Prediction risk boost (max 10 pts) ─────────────────────────
        pred_pts, pred_factors = self._score_predictions(predictions)
        score += pred_pts
        factors.extend(pred_factors)

        # ── 4. Pollutant hazard class bonus (max 10 pts) ──────────────────
        all_pollutants = (
            [b.pollutant for b in threshold_breaches]
            + [a.pollutant for a in anomaly_events]
        )
        hazard_pts, hazard_factors = self._score_hazard(all_pollutants)
        score += hazard_pts
        factors.extend(hazard_factors)

        # ── 5. Multi-pollutant confirmation bonus (max 10 pts) ────────────
        unique_pollutants = set(p.value for p in all_pollutants)
        if len(unique_pollutants) >= 3:
            score += 10
            factors.append({"component": "multi_pollutant", "pts": 10,
                             "detail": f"{len(unique_pollutants)} pollutants elevated"})
        elif len(unique_pollutants) == 2:
            score += 5
            factors.append({"component": "multi_pollutant", "pts": 5,
                             "detail": "2 pollutants elevated"})

        # ── 6. Duration / persistence bonus (max 15 pts) ──────────────────
        persist_pts = self._persistence_bonus(unit_id, score)
        score += persist_pts
        if persist_pts:
            factors.append({"component": "persistence", "pts": persist_pts,
                             "detail": "Sustained elevated condition"})

        # ── 7. Sensor/source reliability penalty (up to -10 pts) ──────────
        if sensor_reliability_avg < 0.8:
            penalty = round((0.8 - sensor_reliability_avg) * 50, 1)
            # Apply penalty but also reduce confidence
            score -= penalty
            factors.append({"component": "reliability_penalty", "pts": -penalty,
                             "detail": f"Avg sensor reliability={sensor_reliability_avg:.2f}"})

        score = round(max(0.0, min(100.0, score)), 2)
        level = _risk_level(score)

        # Update persistence tracking
        self._update_persistence(unit_id, score)

        # Dominant pollutant
        dominant = self._dominant_pollutant(threshold_breaches, anomaly_events)

        # Confidence — reduced when sensor reliability is low
        confidence = round(min(1.0, max(0.3, sensor_reliability_avg)), 3)

        return RiskAssessment(
            id=uuid4(),
            industrial_unit_id=unit_id,
            zone=zone,
            risk_score=score,
            risk_level=level,
            contributing_factors=factors,
            dominant_pollutant=dominant,
            threshold_breaches=len(threshold_breaches),
            anomaly_count=len(anomaly_events),
            sensor_reliability_avg=round(sensor_reliability_avg, 3),
            prediction_risk_boost=pred_pts,
            confidence=confidence,
            assessed_at=utcnow(),
            source_type=source_type,
        )

    # ── Scoring sub-components ────────────────────────────────────────────────

    def _score_breaches(
        self, breaches: List[ThresholdBreachEvent]
    ) -> tuple[float, List[Dict[str, Any]]]:
        if not breaches:
            return 0.0, []
        max_excess = max(b.excess_pct for b in breaches)
        pts = min(35.0, max_excess * 0.3 + len(breaches) * 2)
        return round(pts, 2), [
            {
                "component": "threshold_breach",
                "pts": round(pts, 2),
                "detail": f"{len(breaches)} breaches, max excess={max_excess:.1f}%",
            }
        ]

    def _score_anomalies(
        self, events: List[AnomalyEvent]
    ) -> tuple[float, List[Dict[str, Any]]]:
        if not events:
            return 0.0, []
        avg_score = sum(e.anomaly_score for e in events) / len(events)
        confirmed = sum(1 for e in events if e.is_confirmed)
        pts = min(20.0, avg_score * 15 + confirmed * 2)
        return round(pts, 2), [
            {
                "component": "anomaly",
                "pts": round(pts, 2),
                "detail": f"{len(events)} anomalies ({confirmed} confirmed), avg score={avg_score:.2f}",
            }
        ]

    def _score_predictions(
        self, predictions: List[Prediction]
    ) -> tuple[float, List[Dict[str, Any]]]:
        breach_preds = [p for p in predictions if p.breach_predicted]
        if not breach_preds:
            return 0.0, []
        pts = min(10.0, len(breach_preds) * 4)
        return round(pts, 2), [
            {
                "component": "predicted_breach",
                "pts": round(pts, 2),
                "detail": f"{len(breach_preds)} breach(es) predicted",
            }
        ]

    def _score_hazard(
        self, pollutants: List[PollutantType]
    ) -> tuple[float, List[Dict[str, Any]]]:
        if not pollutants:
            return 0.0, []
        hazards = [_POLLUTANT_HAZARD.get(p.value, "LOW") for p in pollutants]
        max_weight = max(_HAZARD_WEIGHTS.get(h, 0.25) for h in hazards)
        pts = round(max_weight * 10, 2)
        worst = hazards[hazards.index(max(hazards, key=lambda h: _HAZARD_WEIGHTS.get(h, 0)))]
        return pts, [
            {
                "component": "hazard_class",
                "pts": pts,
                "detail": f"Highest hazard class = {worst}",
            }
        ]

    def _persistence_bonus(self, unit_id: str, current_score: float) -> float:
        """Bonus for sustained elevated scores (up to 15 pts)."""
        recent = self._recent_scores.get(unit_id, [])
        if len(recent) < 3:
            return 0.0
        # If last 3 scores were all elevated, add persistence bonus
        if all(s >= 41 for s in recent[-3:]) and current_score >= 41:
            sustained_rounds = sum(1 for s in recent if s >= 41)
            return min(15.0, sustained_rounds * 1.5)
        return 0.0

    def _update_persistence(self, unit_id: str, score: float) -> None:
        if unit_id not in self._recent_scores:
            self._recent_scores[unit_id] = []
        self._recent_scores[unit_id].append(score)
        self._recent_scores[unit_id] = self._recent_scores[unit_id][-20:]

    def _dominant_pollutant(
        self,
        breaches: List[ThresholdBreachEvent],
        anomalies: List[AnomalyEvent],
    ) -> Optional[PollutantType]:
        """Return the pollutant with the highest combined evidence."""
        from collections import Counter
        cnt: Counter = Counter()
        for b in breaches:
            cnt[b.pollutant] += 2   # breach is stronger evidence
        for a in anomalies:
            cnt[a.pollutant] += 1
        if not cnt:
            return None
        return cnt.most_common(1)[0][0]


# Module-level singleton
risk_engine = RiskEngine()
