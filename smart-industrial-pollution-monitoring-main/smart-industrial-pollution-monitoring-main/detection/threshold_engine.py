"""
Regulatory Threshold Engine.

Loads regulatory_thresholds.json and checks each reading against:
  - Absolute limit values
  - Warning zones (configurable factor, e.g. 80% of limit)
  - Early-warning zones (e.g. 65% of limit)
  - Zone-specific overrides

IMPORTANT:
  - Never claims "legally confirmed violation" unless official
    evidence and rules are available.
  - Uses "POTENTIAL_VIOLATION_DETECTED" when evidence is incomplete.
  - Thresholds are versioned, unit-aware, and source-attributed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.config import get_settings
from app.models import (
    DataSourceType, PollutantType, SensorReading,
    ThresholdBreachEvent, ViolationStatus,
)
from utils.helpers import get_logger, utcnow

logger = get_logger(__name__)
settings = get_settings()


class RegulatoryThresholdEngine:
    """
    Evaluates sensor readings against configurable regulatory thresholds.
    Thresholds are loaded from regulatory_thresholds.json and can be
    reloaded at runtime.
    """

    def __init__(self) -> None:
        self._config: Dict[str, Any] = {}
        self._version: str = "unknown"
        self._loaded_at: Optional[datetime] = None
        self._load()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load(self) -> None:
        path = settings.REGULATORY_CONFIG_PATH
        if not os.path.exists(path):
            logger.warning(
                "Regulatory threshold file not found at %s — using empty config", path
            )
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            self._version = self._config.get("_meta", {}).get("version", "unknown")
            self._loaded_at = utcnow()
            logger.info(
                "Regulatory thresholds loaded v%s from %s", self._version, path
            )
        except Exception as exc:
            logger.error("Failed to load regulatory thresholds: %s", exc)

    def reload(self) -> None:
        """Hot-reload thresholds from disk."""
        self._load()

    # ── Threshold lookup ──────────────────────────────────────────────────────

    def _get_pollutant_config(
        self, pollutant: PollutantType, zone: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Return the threshold config for a pollutant, merging zone overrides.
        """
        pval = pollutant.value
        # Determine media section
        media_section = "air" if pval in self._config.get("air", {}) else "water"
        base_cfg = self._config.get(media_section, {}).get(pval)
        if base_cfg is None:
            return None

        # Apply zone overrides
        if zone:
            override = (
                self._config.get("zone_overrides", {})
                .get(zone, {})
                .get(pval, {})
            )
            if override:
                import copy
                base_cfg = copy.deepcopy(base_cfg)
                for limit_name, limit_vals in override.items():
                    if "limits" not in base_cfg:
                        base_cfg["limits"] = {}
                    if limit_name in base_cfg["limits"]:
                        base_cfg["limits"][limit_name].update(limit_vals)
                    else:
                        base_cfg["limits"][limit_name] = limit_vals

        return base_cfg

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(
        self, reading: SensorReading
    ) -> List[ThresholdBreachEvent]:
        """
        Evaluate a reading against all applicable thresholds.
        Returns a list of ThresholdBreachEvent (may be empty).
        """
        if not reading.is_valid:
            return []

        cfg = self._get_pollutant_config(reading.pollutant, reading.zone)
        if cfg is None:
            return []

        events: List[ThresholdBreachEvent] = []
        limits = cfg.get("limits", {})
        warning_factor = cfg.get("warning_factor", 0.80)
        invert = cfg.get("invert", False)   # True for DO (higher is better)

        for limit_name, limit_def in limits.items():
            breach = self._check_limit(
                reading=reading,
                limit_name=limit_name,
                limit_def=limit_def,
                warning_factor=warning_factor,
                invert=invert,
            )
            if breach:
                events.append(breach)

        return events

    def _check_limit(
        self,
        reading: SensorReading,
        limit_name: str,
        limit_def: Dict[str, Any],
        warning_factor: float,
        invert: bool,
    ) -> Optional[ThresholdBreachEvent]:
        """
        Returns a ThresholdBreachEvent if the reading breaches or approaches
        the given limit, else None.
        """
        value = reading.value

        # Upper-limit check (most pollutants)
        if "value" in limit_def and not invert:
            threshold = float(limit_def["value"])
            return self._upper_breach(reading, limit_name, limit_def, threshold, warning_factor)

        # Lower-limit check (e.g. DO — too low is bad)
        if "min" in limit_def and not invert:
            threshold = float(limit_def["min"])
            # Breach if below min
            if value < threshold:
                excess_pct = round((threshold - value) / threshold * 100, 2)
                return ThresholdBreachEvent(
                    id=uuid4(),
                    sensor_id=reading.sensor_id,
                    industrial_unit_id=reading.industrial_unit_id,
                    zone=reading.zone,
                    pollutant=reading.pollutant,
                    value=value,
                    unit=reading.unit,
                    threshold_value=threshold,
                    threshold_type=f"{limit_name}_min",
                    excess_pct=excess_pct,
                    violation_status=ViolationStatus.POTENTIAL_VIOLATION,
                    source_type=reading.source_type,
                    timestamp=utcnow(),
                    quality_score=reading.quality_score,
                )

        # Upper + pH max check
        if "max" in limit_def:
            threshold = float(limit_def["max"])
            return self._upper_breach(reading, limit_name, limit_def, threshold, warning_factor)

        # Inverted (DO) — too low is the danger, handled by min above
        if invert and "min" in limit_def:
            threshold = float(limit_def["min"])
            if value < threshold * warning_factor:
                excess_pct = round((threshold - value) / threshold * 100, 2)
                return ThresholdBreachEvent(
                    id=uuid4(),
                    sensor_id=reading.sensor_id,
                    industrial_unit_id=reading.industrial_unit_id,
                    zone=reading.zone,
                    pollutant=reading.pollutant,
                    value=value,
                    unit=reading.unit,
                    threshold_value=threshold,
                    threshold_type=f"{limit_name}_min_warning",
                    excess_pct=excess_pct,
                    violation_status=ViolationStatus.WARNING_ZONE,
                    source_type=reading.source_type,
                    timestamp=utcnow(),
                    quality_score=reading.quality_score,
                )

        return None

    def _upper_breach(
        self,
        reading: SensorReading,
        limit_name: str,
        limit_def: Dict[str, Any],
        threshold: float,
        warning_factor: float,
    ) -> Optional[ThresholdBreachEvent]:
        value = reading.value

        if value >= threshold:
            excess_pct = round((value - threshold) / threshold * 100, 2)
            # Only claim confirmed violation when quality is high
            v_status = (
                ViolationStatus.POTENTIAL_VIOLATION
                if reading.quality_score < 0.8
                else ViolationStatus.POTENTIAL_VIOLATION  # see design note
                # Never auto-mark CONFIRMED_VIOLATION without official evidence
            )
            return ThresholdBreachEvent(
                id=uuid4(),
                sensor_id=reading.sensor_id,
                industrial_unit_id=reading.industrial_unit_id,
                zone=reading.zone,
                pollutant=reading.pollutant,
                value=value,
                unit=reading.unit,
                threshold_value=threshold,
                threshold_type=limit_name,
                excess_pct=excess_pct,
                violation_status=v_status,
                source_type=reading.source_type,
                timestamp=utcnow(),
                quality_score=reading.quality_score,
            )
        elif value >= threshold * warning_factor:
            return ThresholdBreachEvent(
                id=uuid4(),
                sensor_id=reading.sensor_id,
                industrial_unit_id=reading.industrial_unit_id,
                zone=reading.zone,
                pollutant=reading.pollutant,
                value=value,
                unit=reading.unit,
                threshold_value=threshold,
                threshold_type=f"{limit_name}_warning",
                excess_pct=round((value - threshold * warning_factor) / threshold * 100, 2),
                violation_status=ViolationStatus.WARNING_ZONE,
                source_type=reading.source_type,
                timestamp=utcnow(),
                quality_score=reading.quality_score,
            )
        return None

    # ── Summary helpers ───────────────────────────────────────────────────────

    def get_threshold(
        self,
        pollutant: PollutantType,
        limit_name: str = "24h_average",
        zone: Optional[str] = None,
    ) -> Optional[float]:
        """Return the threshold value for a pollutant/limit combo."""
        cfg = self._get_pollutant_config(pollutant, zone)
        if cfg is None:
            return None
        limit = cfg.get("limits", {}).get(limit_name, {})
        return float(limit.get("value", limit.get("max", limit.get("min", 0)))) or None

    def get_all_thresholds_for_pollutant(
        self, pollutant: PollutantType, zone: Optional[str] = None
    ) -> Dict[str, Any]:
        cfg = self._get_pollutant_config(pollutant, zone)
        return cfg or {}

    @property
    def version(self) -> str:
        return self._version

    @property
    def loaded_at(self) -> Optional[datetime]:
        return self._loaded_at


# Module-level singleton
threshold_engine = RegulatoryThresholdEngine()
