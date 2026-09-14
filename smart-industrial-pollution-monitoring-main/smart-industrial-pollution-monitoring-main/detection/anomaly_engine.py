"""
Anomaly Detection Engine.

Uses a layered approach — simplest reliable method first:

  Layer 1 (always active): Z-score on rolling window
  Layer 2 (always active): EWMA deviation
  Layer 3 (when sufficient data): Isolation Forest
  Layer 4 (when sufficient data): Change-point detection (CUSUM)

Results are combined; an anomaly is confirmed when ≥2 methods agree.
Sensor reliability weights the final anomaly score.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.config import get_settings
from app.models import AnomalyEvent, DataSourceType, PollutantType, SensorReading
from utils.helpers import ewma, get_logger, safe_mean, safe_std, zscore, utcnow

logger = get_logger(__name__)
settings = get_settings()

_MIN_POINTS_ISOLATION_FOREST = 30
_MIN_POINTS_CUSUM = 10


class SensorAnomalyState:
    """Per-sensor rolling state for anomaly detection."""

    def __init__(self, window: int = 60):
        self.window = window
        self._values: deque = deque(maxlen=window)
        # CUSUM state
        self._cusum_pos: float = 0.0
        self._cusum_neg: float = 0.0

    def push(self, value: float) -> None:
        self._values.append(value)

    def values(self) -> List[float]:
        return list(self._values)

    def enough_data(self, min_n: int = 5) -> bool:
        return len(self._values) >= min_n


class AnomalyDetectionEngine:
    """
    Stateful anomaly engine; one instance per process.
    """

    def __init__(self) -> None:
        self._states: Dict[str, SensorAnomalyState] = defaultdict(
            lambda: SensorAnomalyState(settings.ROLLING_WINDOW_SIZE)
        )
        self._isolation_models: Dict[str, Any] = {}  # lazy sklearn models
        self._sklearn_available: bool = self._check_sklearn()

    @staticmethod
    def _check_sklearn() -> bool:
        try:
            import sklearn  # noqa: F401
            return True
        except ImportError:
            logger.warning("scikit-learn not installed — Isolation Forest disabled")
            return False

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        reading: SensorReading,
        reliability: float = 1.0,
    ) -> Optional[AnomalyEvent]:
        """
        Analyze a single reading.
        Returns AnomalyEvent if anomalous, None otherwise.
        """
        if not reading.is_valid:
            return None

        state = self._states[reading.sensor_id]
        value = reading.value
        vals = state.values()

        detections: List[Tuple[str, float]] = []  # (method, score)

        # ── Layer 1: Z-score ──────────────────────────────────────────────
        if state.enough_data(min_n=5):
            mean = safe_mean(vals)
            std = safe_std(vals)
            if mean is not None and std is not None:
                z = zscore(value, mean, std)
                if z is not None and abs(z) >= settings.ANOMALY_ZSCORE_THRESHOLD:
                    score = min(1.0, abs(z) / (settings.ANOMALY_ZSCORE_THRESHOLD * 2))
                    detections.append(("zscore", score))
                    logger.debug(
                        "Z-score anomaly on %s: value=%.3f z=%.2f", reading.sensor_id, value, z
                    )

        # ── Layer 2: EWMA deviation ───────────────────────────────────────
        if state.enough_data(min_n=5):
            ewma_val = ewma(vals, alpha=0.3)
            if ewma_val is not None:
                std = safe_std(vals) or 1.0
                deviation = abs(value - ewma_val)
                threshold = settings.ANOMALY_ZSCORE_THRESHOLD * std
                if deviation > threshold:
                    score = min(1.0, deviation / (threshold * 2))
                    detections.append(("ewma", score))

        # ── Layer 3: Isolation Forest (lazy, retrain every 50 points) ─────
        if (
            self._sklearn_available
            and state.enough_data(min_n=_MIN_POINTS_ISOLATION_FOREST)
        ):
            iso_score = self._isolation_forest_score(reading.sensor_id, vals, value)
            if iso_score is not None and iso_score > 0.6:
                detections.append(("isolation_forest", iso_score))

        # ── Layer 4: CUSUM change-point ───────────────────────────────────
        if state.enough_data(min_n=_MIN_POINTS_CUSUM):
            cusum_score = self._cusum(reading.sensor_id, value, vals)
            if cusum_score is not None and cusum_score > 0.5:
                detections.append(("cusum", cusum_score))

        # Push value AFTER scoring so we detect fresh anomalies
        state.push(value)

        if not detections:
            return None

        # ── Combine scores ────────────────────────────────────────────────
        methods = [m for m, _ in detections]
        combined_score = sum(s for _, s in detections) / len(detections)

        # Weight by sensor reliability
        final_score = combined_score * reliability
        final_score = round(min(1.0, final_score), 4)

        # Confirm if ≥2 methods agree OR single strong signal
        is_confirmed = len(detections) >= 2 or combined_score >= 0.85

        z_val = None
        if state.enough_data(5):
            m, s = safe_mean(vals), safe_std(vals)
            if m is not None and s is not None:
                z_val = zscore(value, m, s)

        return AnomalyEvent(
            id=uuid4(),
            sensor_id=reading.sensor_id,
            industrial_unit_id=reading.industrial_unit_id,
            zone=reading.zone,
            pollutant=reading.pollutant,
            value=value,
            unit=reading.unit,
            anomaly_score=final_score,
            method="+".join(methods),
            zscore=round(z_val, 3) if z_val else None,
            ewma_deviation=None,
            is_confirmed=is_confirmed,
            source_type=reading.source_type,
            timestamp=utcnow(),
            details={
                "detections": [{"method": m, "score": s} for m, s in detections],
                "reliability_weight": reliability,
                "window_size": len(vals),
            },
        )

    def analyze_batch(
        self,
        readings: List[SensorReading],
        reliability_map: Optional[Dict[str, float]] = None,
    ) -> List[AnomalyEvent]:
        """Analyze a batch; cross-sensor confirmation applied at end."""
        reliability_map = reliability_map or {}
        events: List[AnomalyEvent] = []
        for r in readings:
            rel = reliability_map.get(r.sensor_id, 1.0)
            ev = self.analyze(r, rel)
            if ev:
                events.append(ev)

        # Cross-sensor: mark confirmed if same pollutant from multiple sensors
        self._cross_sensor_confirm(events)
        return events

    # ── Isolation Forest ──────────────────────────────────────────────────────

    def _isolation_forest_score(
        self, sensor_id: str, history: List[float], value: float
    ) -> Optional[float]:
        try:
            from sklearn.ensemble import IsolationForest
            import numpy as np

            key = f"{sensor_id}:{len(history)}"
            if key not in self._isolation_models or len(history) % 50 == 0:
                X = np.array(history).reshape(-1, 1)
                model = IsolationForest(
                    contamination=settings.ISOLATION_FOREST_CONTAMINATION,
                    random_state=42,
                    n_estimators=50,
                )
                model.fit(X)
                self._isolation_models[sensor_id] = model

            model = self._isolation_models.get(sensor_id)
            if model is None:
                return None

            import numpy as np
            score = model.decision_function([[value]])[0]
            # decision_function: negative = anomalous, 0 = boundary
            # Normalise to 0–1
            normalised = max(0.0, min(1.0, -score))
            return normalised
        except Exception as exc:
            logger.debug("Isolation Forest failed: %s", exc)
            return None

    # ── CUSUM ─────────────────────────────────────────────────────────────────

    def _cusum(
        self, sensor_id: str, value: float, history: List[float]
    ) -> Optional[float]:
        """
        Simplified CUSUM.  Returns a score in [0,1] indicating change-point.
        """
        try:
            if not history:
                return None
            mean = safe_mean(history) or 0.0
            std = safe_std(history) or 1.0
            slack = 0.5 * std

            state = self._states[sensor_id]
            state._cusum_pos = max(0, state._cusum_pos + (value - mean) - slack)
            state._cusum_neg = max(0, state._cusum_neg - (value - mean) - slack)

            threshold = 5 * std
            cusum_val = max(state._cusum_pos, state._cusum_neg)
            if cusum_val > threshold:
                score = min(1.0, cusum_val / (threshold * 2))
                return score
            return None
        except Exception as exc:
            logger.debug("CUSUM failed: %s", exc)
            return None

    # ── Cross-sensor confirmation ─────────────────────────────────────────────

    def _cross_sensor_confirm(self, events: List[AnomalyEvent]) -> None:
        """If the same pollutant is anomalous on ≥2 sensors, mark all confirmed."""
        by_pollutant: Dict[str, List[AnomalyEvent]] = defaultdict(list)
        for ev in events:
            by_pollutant[ev.pollutant.value].append(ev)

        for pollutant, evs in by_pollutant.items():
            unit_ids = {ev.industrial_unit_id for ev in evs}
            sensor_ids = {ev.sensor_id for ev in evs}
            if len(sensor_ids) >= 2 or len(unit_ids) >= 2:
                for ev in evs:
                    ev.is_confirmed = True
                    ev.details["cross_sensor_confirmed"] = True


# Module-level singleton
anomaly_engine = AnomalyDetectionEngine()
