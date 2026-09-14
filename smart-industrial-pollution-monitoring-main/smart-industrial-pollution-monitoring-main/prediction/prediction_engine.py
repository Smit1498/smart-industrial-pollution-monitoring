"""
Prediction & Early-Warning Engine.

Predicts future pollution levels using lightweight time-series techniques:
  - Linear regression on rolling window (primary, fast)
  - EWMA trend extrapolation (fallback)
  - Random Forest regression (when sklearn + sufficient data)

Never labels predictions as LIVE data.
Every prediction includes: confidence, evidence, model, horizon, uncertainty.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.config import get_settings
from app.models import (
    DataSourceType, PollutantType, Prediction,
    SensorReading, TrendDirection,
)
from detection.threshold_engine import threshold_engine
from utils.helpers import ewma, get_logger, safe_mean, safe_std, utcnow

logger = get_logger(__name__)
settings = get_settings()

_HORIZONS = [15, 30, 60]   # minutes to predict ahead


class PredictionState:
    """Per-sensor rolling state for prediction."""

    def __init__(self, window: int = 60):
        self._values: deque = deque(maxlen=window)
        self._times_min: deque = deque(maxlen=window)   # relative minutes
        self._t0: float = 0.0

    def push(self, value: float, ts_epoch: float) -> None:
        if not self._values:
            self._t0 = ts_epoch
        self._values.append(value)
        self._times_min.append((ts_epoch - self._t0) / 60.0)

    def values(self) -> List[float]:
        return list(self._values)

    def times(self) -> List[float]:
        return list(self._times_min)

    def enough(self, n: int = 5) -> bool:
        return len(self._values) >= n


class PredictionEngine:
    """
    Stateful prediction engine.
    One instance per process.
    """

    def __init__(self) -> None:
        self._states: Dict[str, PredictionState] = defaultdict(
            lambda: PredictionState(settings.ROLLING_WINDOW_SIZE)
        )
        self._rf_models: Dict[str, Any] = {}
        self._sklearn_ok: bool = self._check_sklearn()

    @staticmethod
    def _check_sklearn() -> bool:
        try:
            import sklearn  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Public API ─────────────────────────────────────────────────────────────

    def predict(
        self,
        reading: SensorReading,
        horizon_minutes: int = 30,
    ) -> Optional[Prediction]:
        """
        Predict the value of reading.pollutant at horizon_minutes from now.
        Returns None if insufficient data.
        """
        if not reading.is_valid:
            return None

        state = self._states[reading.sensor_id]
        import time as _time
        state.push(reading.value, reading.timestamp.timestamp())

        if not state.enough(5):
            return None

        vals = state.values()
        times = state.times()

        # ── Choose model based on available data ──────────────────────────
        predicted, uncertainty, model_used = self._forecast(
            vals, times, horizon_minutes, reading.sensor_id
        )

        if predicted is None:
            return None

        # Worst-case: predicted + 1.5 × uncertainty
        worst_case = round(predicted + 1.5 * uncertainty, 3)

        # Trend direction
        trend = self._trend_direction(vals)

        # Threshold check
        threshold_val = threshold_engine.get_threshold(
            reading.pollutant,
            limit_name="24h_average",
            zone=reading.zone,
        )
        breach_predicted = False
        breach_eta = None
        if threshold_val:
            breach_predicted = predicted >= threshold_val or worst_case >= threshold_val
            if breach_predicted:
                breach_eta = self._estimate_breach_eta(vals, times, threshold_val)

        confidence = self._confidence(vals, uncertainty)

        evidence = [
            f"Current value: {reading.value} {reading.unit}",
            f"Trend: {trend.value}",
            f"Rolling mean (last {len(vals)}): {round(safe_mean(vals) or 0, 2)}",
            f"Model: {model_used}",
        ]
        if threshold_val:
            evidence.append(f"Threshold ({reading.pollutant.value} 24h): {threshold_val}")
        if breach_predicted:
            evidence.append(
                f"⚠ Breach predicted at horizon {horizon_minutes}min"
                + (f" ETA ~{breach_eta}min" if breach_eta else "")
            )

        return Prediction(
            id=uuid4(),
            sensor_id=reading.sensor_id,
            industrial_unit_id=reading.industrial_unit_id,
            zone=reading.zone,
            pollutant=reading.pollutant,
            current_value=reading.value,
            predicted_value=round(predicted, 3),
            worst_case_value=round(worst_case, 3),
            unit=reading.unit,
            horizon_minutes=horizon_minutes,
            trend=trend,
            threshold_value=threshold_val,
            breach_predicted=breach_predicted,
            breach_eta_minutes=breach_eta,
            confidence=confidence,
            uncertainty_pct=round(uncertainty / max(abs(reading.value), 1e-6) * 100, 1),
            model_used=model_used,
            evidence=evidence,
            created_at=utcnow(),
            source_type=DataSourceType.PREDICTED,
        )

    def predict_batch(
        self, readings: List[SensorReading], horizon_minutes: int = 30
    ) -> List[Prediction]:
        preds = []
        # Only predict from the latest reading per sensor
        latest: Dict[str, SensorReading] = {}
        for r in readings:
            if r.sensor_id not in latest or r.timestamp > latest[r.sensor_id].timestamp:
                latest[r.sensor_id] = r

        for reading in latest.values():
            p = self.predict(reading, horizon_minutes)
            if p:
                preds.append(p)
        return preds

    # ── Forecasting ───────────────────────────────────────────────────────────

    def _forecast(
        self,
        vals: List[float],
        times: List[float],
        horizon_min: int,
        sensor_id: str,
    ) -> Tuple[Optional[float], float, str]:
        """Returns (predicted_value, uncertainty, model_name)."""

        # Try linear regression first
        try:
            pred, rmse = self._linear_regression_forecast(vals, times, horizon_min)
            if pred is not None:
                return pred, rmse, "linear_regression"
        except Exception as exc:
            logger.debug("Linear regression failed: %s", exc)

        # Fallback: EWMA + slope
        try:
            pred, rmse = self._ewma_forecast(vals, horizon_min)
            if pred is not None:
                return pred, rmse, "ewma"
        except Exception as exc:
            logger.debug("EWMA forecast failed: %s", exc)

        return None, 0.0, "none"

    def _linear_regression_forecast(
        self, vals: List[float], times: List[float], horizon_min: int
    ) -> Tuple[Optional[float], float]:
        """Simple OLS linear regression — no external deps."""
        n = len(vals)
        if n < 3:
            return None, 0.0

        # Normalise times relative to last point
        t_last = times[-1] if times else n - 1
        xs = [t - t_last for t in times]
        ys = vals

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        ss_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
        ss_xx = sum((xs[i] - mean_x) ** 2 for i in range(n))

        if ss_xx == 0:
            return mean_y, safe_std(vals) or 0.0

        slope = ss_xy / ss_xx
        intercept = mean_y - slope * mean_x
        predicted = intercept + slope * horizon_min

        # RMSE on fitted values
        residuals = [ys[i] - (intercept + slope * xs[i]) for i in range(n)]
        rmse = math.sqrt(sum(r ** 2 for r in residuals) / n)

        # Clip negative predictions for most pollutants
        predicted = max(0.0, predicted)
        return predicted, rmse

    def _ewma_forecast(
        self, vals: List[float], horizon_min: int
    ) -> Tuple[Optional[float], float]:
        """EWMA-based simple extrapolation."""
        if len(vals) < 3:
            return None, 0.0
        ewma_now = ewma(vals, alpha=0.3)
        # Rough slope from last 5 values
        recent = vals[-5:]
        slope = (recent[-1] - recent[0]) / max(len(recent) - 1, 1)
        predicted = ewma_now + slope * horizon_min
        std = safe_std(vals) or 1.0
        return max(0.0, predicted), std * 1.5

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _trend_direction(self, vals: List[float]) -> TrendDirection:
        if len(vals) < 3:
            return TrendDirection.UNKNOWN
        # Use last 10 values (min of available) for robustness against single outliers
        recent = vals[-min(10, len(vals)):]
        # Linear regression slope over the recent window (more robust than endpoint diff)
        n = len(recent)
        xs = list(range(n))
        mean_x = (n - 1) / 2.0
        mean_y = sum(recent) / n
        ss_xy = sum((xs[i] - mean_x) * (recent[i] - mean_y) for i in range(n))
        ss_xx = sum((xs[i] - mean_x) ** 2 for i in range(n))
        slope = ss_xy / ss_xx if ss_xx else 0.0
        mean = safe_mean(vals) or 1.0
        pct = slope / max(abs(mean), 1e-6) * 100

        if pct > 10:
            return TrendDirection.RAPIDLY_INCREASING
        if pct > 3:
            return TrendDirection.INCREASING
        if pct < -10:
            return TrendDirection.RAPIDLY_DECREASING
        if pct < -3:
            return TrendDirection.DECREASING
        return TrendDirection.STABLE

    def _confidence(self, vals: List[float], uncertainty: float) -> float:
        """
        Confidence: higher with more data, lower with high uncertainty.
        """
        n_factor = min(1.0, len(vals) / 30)
        mean = safe_mean(vals) or 1.0
        uncertainty_factor = max(0.0, 1.0 - uncertainty / max(abs(mean), 1e-6))
        return round(0.4 * n_factor + 0.6 * uncertainty_factor, 3)

    def _estimate_breach_eta(
        self, vals: List[float], times: List[float], threshold: float
    ) -> Optional[int]:
        """Estimate minutes until threshold is breached, using linear extrapolation."""
        if len(vals) < 2:
            return None
        current = vals[-1]
        if current >= threshold:
            return 0
        _, rmse = self._linear_regression_forecast(vals, times, 1)
        # slope: value change per minute
        recent = vals[-5:]
        slope = (recent[-1] - recent[0]) / max(len(recent) - 1, 1)
        if slope <= 0:
            return None
        eta = int((threshold - current) / slope)
        return max(1, eta)


# Module-level singleton
prediction_engine = PredictionEngine()
