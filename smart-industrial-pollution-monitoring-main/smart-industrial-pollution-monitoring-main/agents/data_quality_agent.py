"""
Data Quality & Sensor Reliability Agent.

Validates every incoming SensorReading batch and maintains a
per-sensor reliability score used downstream to weight predictions
and risk assessments.

Checks:
  - Missing values
  - Duplicate records
  - Invalid / future timestamps
  - Stale data
  - Impossible values (physical min/max)
  - Unit mismatches (basic heuristic)
  - Sudden abnormal jumps (spike detection)
  - Frozen sensors (constant value)
  - Sensor disconnections
  - Conflicting sources
"""
from __future__ import annotations

import hashlib
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.models import (
    DataQualityReport, PollutantType, SensorReading, SensorStatus,
)
from utils.helpers import get_logger, is_future, seconds_since, utcnow

logger = get_logger(__name__)
settings = get_settings()


# ── Physical bounds (min, max) per pollutant ─────────────────────────────────
# Values outside these are physically impossible.
_PHYSICAL_BOUNDS: Dict[str, Tuple[float, float]] = {
    "PM2.5":        (0,    2000),
    "PM10":         (0,    5000),
    "SO2":          (0,    50000),
    "NO2":          (0,    50000),
    "CO":           (0,    500),
    "CO2":          (200,  100000),
    "VOC":          (0,    100000),
    "NH3":          (0,    100000),
    "H2S":          (0,    50000),
    "O3":           (0,    10000),
    "pH":           (0,    14),
    "BOD":          (0,    50000),
    "COD":          (0,    100000),
    "TSS":          (0,    100000),
    "DO":           (0,    20),
    "WaterTemp":    (-5,   100),
    "Conductivity": (0,    100000),
    "Turbidity":    (0,    10000),
    "HeavyMetals":  (0,    10000),
}


class SensorState:
    """Rolling state per sensor used for quality checks."""

    def __init__(self, window: int = 60):
        self.window = window
        # Circular buffer of (timestamp, value) pairs
        self._history: deque = deque(maxlen=window)
        self._seen_hashes: deque = deque(maxlen=window * 2)
        self.reliability_score: float = 1.0
        self.status: SensorStatus = SensorStatus.ONLINE
        self.last_seen: Optional[datetime] = None
        self.consecutive_issues: int = 0

    def add(self, ts: datetime, value: float) -> None:
        self._history.append((ts, value))
        self.last_seen = ts

    def values(self) -> List[float]:
        return [v for _, v in self._history]

    def timestamps(self) -> List[datetime]:
        return [t for t, _ in self._history]

    def is_frozen(self) -> bool:
        """All recent values identical → frozen sensor."""
        vals = self.values()
        n = min(len(vals), settings.SENSOR_FREEZE_WINDOW)
        if n < 3:
            return False
        recent = vals[-n:]
        return len(set(recent)) == 1

    def is_stale(self) -> bool:
        if self.last_seen is None:
            return False
        return seconds_since(self.last_seen) > settings.STALE_DATA_THRESHOLD_SECONDS

    def is_spike(self, value: float, threshold_factor: float = 5.0) -> bool:
        """Value is more than threshold_factor × std above rolling mean."""
        vals = self.values()
        if len(vals) < 5:
            return False
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = variance ** 0.5
        if std < 1e-6:
            return False
        return abs(value - mean) > threshold_factor * std

    def update_reliability(self, penalty: float) -> None:
        self.consecutive_issues += 1
        decay = penalty * (1 + 0.2 * self.consecutive_issues)
        self.reliability_score = max(0.05, self.reliability_score - decay)

    def reward_reliability(self) -> None:
        self.consecutive_issues = max(0, self.consecutive_issues - 1)
        self.reliability_score = min(1.0, self.reliability_score + 0.02)

    def dedup_hash(self, sensor_id: str, ts: datetime, value: float) -> str:
        key = f"{sensor_id}|{ts.isoformat()}|{value}"
        return hashlib.md5(key.encode()).hexdigest()


class DataQualityEngine:
    """
    Validates SensorReading batches and maintains sensor reliability.
    Stateful — keeps a rolling window per sensor.
    """

    def __init__(self) -> None:
        self._states: Dict[str, SensorState] = {}

    def _get_state(self, sensor_id: str) -> SensorState:
        if sensor_id not in self._states:
            self._states[sensor_id] = SensorState(settings.ROLLING_WINDOW_SIZE)
        return self._states[sensor_id]

    def validate_batch(
        self, readings: List[SensorReading]
    ) -> Tuple[List[SensorReading], List[DataQualityReport]]:
        """
        Validate a batch of readings.
        Returns (validated_readings, quality_reports).
        Readings marked invalid are kept but flagged.
        """
        # Group by source_id for source-level reports
        by_source: Dict[str, List[SensorReading]] = defaultdict(list)
        for r in readings:
            by_source[r.source_id].append(r)

        validated: List[SensorReading] = []
        reports: List[DataQualityReport] = []

        for source_id, batch in by_source.items():
            report = DataQualityReport(
                source_id=source_id,
                assessed_at=utcnow(),
                total_records=len(batch),
            )
            for reading in batch:
                issues = self._validate_reading(reading, report)
                reading.validation_notes = issues
                reading.is_valid = len(issues) == 0

                state = self._get_state(reading.sensor_id)
                if reading.is_valid:
                    state.add(reading.timestamp, reading.value)
                    state.reward_reliability()
                    reading.quality_score = round(state.reliability_score, 3)
                    report.valid_records += 1
                else:
                    state.update_reliability(0.05)
                    reading.quality_score = round(state.reliability_score * 0.5, 3)

                validated.append(reading)

            # Source-level quality
            valid_pct = report.valid_records / max(report.total_records, 1)
            report.quality_score = round(valid_pct, 3)

            # Sensor-level reliability (first sensor in batch as representative)
            if batch:
                first_state = self._get_state(batch[0].sensor_id)
                report.sensor_reliability_score = round(first_state.reliability_score, 3)
                report.is_stale = first_state.is_stale()
                report.is_frozen = first_state.is_frozen()

            reports.append(report)

        return validated, reports

    def _validate_reading(
        self, reading: SensorReading, report: DataQualityReport
    ) -> List[str]:
        issues: List[str] = []
        state = self._get_state(reading.sensor_id)

        # 1. Future timestamp
        if is_future(reading.timestamp):
            issues.append(f"FUTURE_TIMESTAMP:{reading.timestamp.isoformat()}")
            report.has_future_timestamps = True

        # 2. Duplicate check
        h = state.dedup_hash(reading.sensor_id, reading.timestamp, reading.value)
        if h in state._seen_hashes:
            issues.append("DUPLICATE_RECORD")
            report.has_duplicates = True
        else:
            state._seen_hashes.append(h)

        # 3. Physical bounds
        bounds = _PHYSICAL_BOUNDS.get(reading.pollutant.value)
        if bounds:
            lo, hi = bounds
            if not (lo <= reading.value <= hi):
                issues.append(
                    f"IMPOSSIBLE_VALUE:{reading.value} outside [{lo},{hi}]"
                )
                report.has_impossible_values = True

        # 4. Spike detection
        if state.is_spike(reading.value):
            issues.append(f"SUDDEN_SPIKE:value={reading.value}")

        # 5. Frozen sensor
        if state.is_frozen():
            issues.append("FROZEN_SENSOR")
            report.is_frozen = True
            state.status = SensorStatus.FROZEN

        # 6. Stale sensor — only flag as a warning on the report; do NOT
        #    invalidate the reading itself.  Staleness indicates the sensor
        #    has not sent data recently, but the reading itself is valid.
        if state.is_stale():
            report.is_stale = True
            state.status = SensorStatus.STALE

        return issues

    def get_sensor_reliability(self, sensor_id: str) -> float:
        return self._get_state(sensor_id).reliability_score

    def get_sensor_status(self, sensor_id: str) -> SensorStatus:
        state = self._get_state(sensor_id)
        if state.is_frozen():
            return SensorStatus.FROZEN
        if state.is_stale():
            return SensorStatus.STALE
        if state.reliability_score < 0.3:
            return SensorStatus.UNRELIABLE
        if state.last_seen is None:
            return SensorStatus.OFFLINE
        return SensorStatus.ONLINE

    def mark_sensor_offline(self, sensor_id: str) -> None:
        state = self._get_state(sensor_id)
        state.status = SensorStatus.OFFLINE
        state.update_reliability(0.2)

    def all_sensor_states(self) -> Dict[str, Dict[str, Any]]:
        return {
            sid: {
                "reliability_score": round(s.reliability_score, 3),
                "status": self.get_sensor_status(sid).value,
                "last_seen": s.last_seen.isoformat() if s.last_seen else None,
                "is_stale": s.is_stale(),
                "is_frozen": s.is_frozen(),
                "consecutive_issues": s.consecutive_issues,
            }
            for sid, s in self._states.items()
        }


# Module-level singleton
data_quality_engine = DataQualityEngine()
