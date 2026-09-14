"""
Standalone simulation runner.

Can be imported and called from tests or run directly:
  python -m simulator.scenarios

Generates sensor readings for various test scenarios and
injects them into the full pipeline without requiring a running server.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List
from uuid import uuid4

from app.models import DataSourceType, MediaType, PollutantType, SensorReading
from data_sources.ingestion import coerce_reading
from agents.data_quality_agent import data_quality_engine
from detection.threshold_engine import threshold_engine
from detection.anomaly_engine import anomaly_engine
from prediction.prediction_engine import prediction_engine
from risk.risk_engine import risk_engine
from utils.helpers import get_logger, utcnow

logger = get_logger(__name__)


# ── Scenario definitions ───────────────────────────────────────────────────────

def make_reading(
    sensor_id: str,
    unit_id: str,
    zone: str,
    pollutant: str,
    value: float,
    unit: str,
    media: str = "AIR",
    source_type: str = "SIMULATED",
    ts_offset_seconds: int = 0,
) -> Dict[str, Any]:
    ts = utcnow() - timedelta(seconds=ts_offset_seconds) if ts_offset_seconds else utcnow()
    return {
        "sensor_id": sensor_id,
        "industrial_unit_id": unit_id,
        "zone": zone,
        "pollutant": pollutant,
        "media": media,
        "value": value,
        "unit": unit,
        "timestamp": ts.isoformat(),
        "source_type": source_type,
        "source_id": "simulator",
    }


class ScenarioRunner:
    """
    Runs predefined scenarios through the full analysis pipeline.
    Returns structured results for testing and demos.
    """

    def run_scenario(self, scenario_name: str) -> Dict[str, Any]:
        """Synchronous wrapper — runs the async scenario in a new event loop."""
        return asyncio.run(self._run(scenario_name))

    async def _run(self, scenario_name: str) -> Dict[str, Any]:
        scenarios = {
            "normal":           self._scenario_normal,
            "warning":          self._scenario_warning,
            "high_risk":        self._scenario_high_risk,
            "critical":         self._scenario_critical,
            "sensor_failure":   self._scenario_sensor_failure,
            "missing_data":     self._scenario_missing_data,
            "recovery":         self._scenario_recovery,
            "multi_pollutant":  self._scenario_multi_pollutant,
        }
        fn = scenarios.get(scenario_name)
        if fn is None:
            return {"error": f"Unknown scenario: {scenario_name}"}
        raw_records = await fn()
        return self._analyze(raw_records, scenario_name)

    def _analyze(
        self, raw_records: List[Dict[str, Any]], scenario_name: str
    ) -> Dict[str, Any]:
        from data_sources.ingestion import coerce_batch
        readings = coerce_batch(raw_records)
        validated, reports = data_quality_engine.validate_batch(readings)
        valid = [r for r in validated if r.is_valid]

        all_breaches = []
        all_anomalies = []
        all_predictions = []
        reliability_map = {r.sensor_id: data_quality_engine.get_sensor_reliability(r.sensor_id) for r in valid}

        for r in valid:
            all_breaches.extend(threshold_engine.evaluate(r))

        all_anomalies = anomaly_engine.analyze_batch(valid, reliability_map)
        all_predictions = prediction_engine.predict_batch(valid, 30)

        avg_rel = sum(reliability_map.values()) / max(len(reliability_map), 1)
        unit_ids = list({r.industrial_unit_id for r in valid})
        risk = None
        if unit_ids:
            risk = risk_engine.assess(
                unit_id=unit_ids[0],
                zone=valid[0].zone if valid else "Unknown",
                threshold_breaches=all_breaches,
                anomaly_events=all_anomalies,
                predictions=all_predictions,
                sensor_reliability_avg=avg_rel,
                source_type=DataSourceType.SIMULATED,
            )

        return {
            "scenario": scenario_name,
            "source_type": "SIMULATED",
            "readings_coerced": len(readings),
            "valid_readings": len(valid),
            "invalid_readings": len(readings) - len(valid),
            "threshold_breaches": len(all_breaches),
            "anomalies": len(all_anomalies),
            "confirmed_anomalies": sum(1 for a in all_anomalies if a.is_confirmed),
            "predictions": len(all_predictions),
            "breach_predicted": sum(1 for p in all_predictions if p.breach_predicted),
            "risk_score": risk.risk_score if risk else 0.0,
            "risk_level": risk.risk_level.value if risk else "UNKNOWN",
            "dominant_pollutant": (
                risk.dominant_pollutant.value if risk and risk.dominant_pollutant else None
            ),
            "quality_reports": [r.model_dump() for r in reports],
            "breach_details": [
                {
                    "pollutant": b.pollutant.value,
                    "value": b.value,
                    "threshold": b.threshold_value,
                    "excess_pct": b.excess_pct,
                    "status": b.violation_status.value,
                }
                for b in all_breaches
            ],
        }

    # ── Scenarios ──────────────────────────────────────────────────────────────

    async def _scenario_normal(self) -> List[Dict[str, Any]]:
        """Baseline — all values well within limits."""
        return [
            make_reading("S001","VAPI-001","Vapi","SO2",30,"µg/m³"),
            make_reading("S002","VAPI-001","Vapi","NO2",25,"µg/m³"),
            make_reading("S003","VAPI-001","Vapi","PM2.5",20,"µg/m³"),
            make_reading("S004","VAPI-001","Vapi","H2S",5,"µg/m³"),
        ]

    async def _scenario_warning(self) -> List[Dict[str, Any]]:
        """Warning zone — approaching threshold (80% of limit)."""
        return [
            make_reading("S001","ANK-001","Ankleshwar","SO2",68,"µg/m³"),   # ~85% of 80
            make_reading("S002","ANK-001","Ankleshwar","NO2",66,"µg/m³"),   # ~82% of 80
            make_reading("S003","ANK-001","Ankleshwar","PM2.5",50,"µg/m³"), # ~83% of 60
        ]

    async def _scenario_high_risk(self) -> List[Dict[str, Any]]:
        """High-risk — multiple pollutants above threshold."""
        records = []
        for i in range(30):
            records.append(make_reading("S001","VAPI-001","Vapi","SO2",45+i*2,"µg/m³",ts_offset_seconds=30*(29-i)))
        records += [
            make_reading("S002","VAPI-001","Vapi","SO2",95,"µg/m³"),
            make_reading("S003","VAPI-001","Vapi","NO2",85,"µg/m³"),
            make_reading("S004","VAPI-001","Vapi","H2S",38,"µg/m³"),
        ]
        return records

    async def _scenario_critical(self) -> List[Dict[str, Any]]:
        """Critical — severe multi-pollutant breach."""
        records = []
        for i in range(30):
            records.append(make_reading("CRIT-S001","VAT-001","Vatva","SO2",40+i*3,"µg/m³",ts_offset_seconds=30*(29-i)))
        records += [
            make_reading("CRIT-S001","VAT-001","Vatva","SO2",130,"µg/m³"),
            make_reading("CRIT-S002","VAT-001","Vatva","H2S",55,"µg/m³"),
            make_reading("CRIT-S003","VAT-001","Vatva","NH3",250,"µg/m³"),
            make_reading("CRIT-S004","VAT-001","Vatva","VOC",600,"µg/m³"),
            make_reading("CRIT-S005","VAT-001","Vatva","COD",320,"mg/L","WATER"),
        ]
        return records

    async def _scenario_sensor_failure(self) -> List[Dict[str, Any]]:
        """Frozen sensor — repeated identical readings."""
        records = []
        for _ in range(15):
            records.append(make_reading("S_FROZEN","VAPI-002","Vapi","NO2",42.5,"µg/m³"))
        return records

    async def _scenario_missing_data(self) -> List[Dict[str, Any]]:
        """Missing values and impossible values — should be flagged invalid."""
        return [
            make_reading("S001","ANK-002","Ankleshwar","pH",15.0,"pH","WATER"),  # impossible
            make_reading("S002","ANK-002","Ankleshwar","BOD",20,"mg/L","WATER"),  # valid
            make_reading("S003","ANK-002","Ankleshwar","COD",-100,"mg/L","WATER"),  # negative — impossible
        ]

    async def _scenario_recovery(self) -> List[Dict[str, Any]]:
        """Recovery — values falling after a previous event.
        Starts elevated but ends well within limits; final risk should be MODERATE or lower.
        """
        records = []
        for i in range(20):
            # Falls from 85 → 25 over 20 readings; final value 25 is well below threshold
            so2 = max(25, 85 - i * 3)
            records.append(make_reading("REC-S001","REC-001","Vapi","SO2",so2,"µg/m³",ts_offset_seconds=60*(19-i)))
        return records

    async def _scenario_multi_pollutant(self) -> List[Dict[str, Any]]:
        """Multi-pollutant correlated event."""
        records = []
        for i in range(15):
            records.append(make_reading("S001","ANK-001","Ankleshwar","SO2",30+i*4,"µg/m³",ts_offset_seconds=60*(14-i)))
            records.append(make_reading("S002","ANK-001","Ankleshwar","NO2",25+i*3,"µg/m³",ts_offset_seconds=60*(14-i)))
        records += [
            make_reading("S001","ANK-001","Ankleshwar","SO2",92,"µg/m³"),
            make_reading("S002","ANK-001","Ankleshwar","NO2",84,"µg/m³"),
            make_reading("S003","ANK-001","Ankleshwar","H2S",36,"µg/m³"),
            make_reading("S004","ANK-001","Ankleshwar","VOC",480,"µg/m³"),
        ]
        return records


# Module-level singleton
scenario_runner = ScenarioRunner()
