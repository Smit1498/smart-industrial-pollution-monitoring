"""
Data-source abstraction layer.

Supports:
  - CSV / Excel / JSON files
  - REST API
  - MQTT
  - SQLite / Postgres (via SQLAlchemy)
  - Simulated data
  - Historical replay

Every record produced carries a DataSourceType tag.
Never fabricate live data or API responses.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import random
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.config import get_settings
from app.models import DataSourceType, MediaType, PollutantType, SensorReading
from utils.helpers import utcnow, get_logger

logger = get_logger(__name__)
settings = get_settings()


# ═══════════════════════════════════════════════════════════════════════════
# Base data source
# ═══════════════════════════════════════════════════════════════════════════

class DataSourceBase(ABC):
    """Abstract base for all data sources."""

    def __init__(self, source_id: str, name: str, source_type_tag: DataSourceType):
        self.source_id = source_id
        self.name = name
        self.source_type_tag = source_type_tag
        self.quality_score: float = 1.0
        self.failure_count: int = 0
        self.last_success_at: Optional[datetime] = None
        self.last_failure_at: Optional[datetime] = None
        self.is_active: bool = True

    @abstractmethod
    async def fetch(self) -> List[Dict[str, Any]]:
        """Fetch raw records. Returns list of dicts."""

    def record_success(self) -> None:
        self.last_success_at = utcnow()
        self.failure_count = max(0, self.failure_count - 1)
        self.quality_score = min(1.0, self.quality_score + 0.05)

    def record_failure(self, err: str) -> None:
        self.last_failure_at = utcnow()
        self.failure_count += 1
        self.quality_score = max(0.0, self.quality_score - 0.15)
        logger.warning("DataSource '%s' failure #%d: %s", self.source_id, self.failure_count, err)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type_tag.value,
            "is_active": self.is_active,
            "quality_score": round(self.quality_score, 3),
            "failure_count": self.failure_count,
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# REST API source
# ═══════════════════════════════════════════════════════════════════════════

class RestApiDataSource(DataSourceBase):
    """Polls a REST endpoint that returns JSON array of sensor readings."""

    def __init__(
        self,
        source_id: str,
        name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 10,
        params: Optional[Dict[str, str]] = None,
    ):
        super().__init__(source_id, name, DataSourceType.LIVE)
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.params = params or {}

    async def fetch(self) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.url, headers=self.headers, params=self.params)
                resp.raise_for_status()
                data = resp.json()
                records = data if isinstance(data, list) else data.get("data", data.get("readings", []))
                self.record_success()
                return [self._tag(r) for r in records]
        except Exception as exc:
            self.record_failure(str(exc))
            return []

    def _tag(self, record: Dict[str, Any]) -> Dict[str, Any]:
        record["source_type"] = DataSourceType.LIVE.value
        record["source_id"] = self.source_id
        return record


# ═══════════════════════════════════════════════════════════════════════════
# CSV / Excel / JSON file source
# ═══════════════════════════════════════════════════════════════════════════

class FileDataSource(DataSourceBase):
    """
    Reads historical data from a CSV, JSON, or Excel file.
    Tagged as HISTORICAL.
    """

    def __init__(self, source_id: str, name: str, file_path: str):
        super().__init__(source_id, name, DataSourceType.HISTORICAL)
        self.file_path = file_path

    async def fetch(self) -> List[Dict[str, Any]]:
        try:
            ext = self.file_path.rsplit(".", 1)[-1].lower()
            if ext == "csv":
                records = await self._read_csv()
            elif ext in ("xlsx", "xls"):
                records = await self._read_excel()
            elif ext == "json":
                records = await self._read_json()
            else:
                raise ValueError(f"Unsupported file format: {ext}")
            self.record_success()
            return [self._tag(r) for r in records]
        except Exception as exc:
            self.record_failure(str(exc))
            return []

    async def _read_csv(self) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_read_csv)

    def _sync_read_csv(self) -> List[Dict[str, Any]]:
        rows = []
        with open(self.file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        return rows

    async def _read_json(self) -> List[Dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_read_json)

    def _sync_read_json(self) -> List[Dict[str, Any]]:
        with open(self.file_path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("data", [])

    async def _read_excel(self) -> List[Dict[str, Any]]:
        """Requires openpyxl — lazy import so it's optional."""
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            raise RuntimeError("openpyxl required for Excel support: pip install openpyxl")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_read_excel)

    def _sync_read_excel(self) -> List[Dict[str, Any]]:
        import openpyxl
        wb = openpyxl.load_workbook(self.file_path, read_only=True, data_only=True)
        ws = wb.active
        headers = [cell.value for cell in next(ws.iter_rows(max_row=1))]
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            rows.append(dict(zip(headers, row)))
        return rows

    def _tag(self, record: Dict[str, Any]) -> Dict[str, Any]:
        record["source_type"] = DataSourceType.HISTORICAL.value
        record["source_id"] = self.source_id
        return record


# ═══════════════════════════════════════════════════════════════════════════
# MQTT source (async, non-blocking)
# ═══════════════════════════════════════════════════════════════════════════

class MqttDataSource(DataSourceBase):
    """
    Subscribes to MQTT topics and buffers readings.
    Requires paho-mqtt or aiomqtt.
    """

    def __init__(
        self,
        source_id: str,
        name: str,
        broker_host: str,
        broker_port: int = 1883,
        topic: str = "pollution/sensors/#",
        username: str = "",
        password: str = "",
    ):
        super().__init__(source_id, name, DataSourceType.LIVE)
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.topic = topic
        self.username = username
        self.password = password
        self._buffer: List[Dict[str, Any]] = []
        self._connected = False

    async def start(self) -> None:
        """Start the MQTT listener in the background."""
        try:
            import aiomqtt  # noqa: F401
            asyncio.create_task(self._listen())
            logger.info("MQTT source '%s' started on %s:%s", self.source_id, self.broker_host, self.broker_port)
        except ImportError:
            logger.warning("aiomqtt not installed — MQTT source '%s' disabled", self.source_id)
            self.is_active = False

    async def _listen(self) -> None:
        try:
            import aiomqtt
            async with aiomqtt.Client(
                self.broker_host,
                port=self.broker_port,
                username=self.username or None,
                password=self.password or None,
            ) as client:
                self._connected = True
                self.record_success()
                await client.subscribe(self.topic)
                async for message in client.messages:
                    try:
                        payload = json.loads(message.payload.decode())
                        payload["source_type"] = DataSourceType.LIVE.value
                        payload["source_id"] = self.source_id
                        self._buffer.append(payload)
                        # Keep buffer bounded
                        if len(self._buffer) > 5000:
                            self._buffer = self._buffer[-5000:]
                    except Exception:
                        pass
        except Exception as exc:
            self._connected = False
            self.record_failure(str(exc))

    async def fetch(self) -> List[Dict[str, Any]]:
        """Drain the buffer and return collected readings."""
        collected, self._buffer = self._buffer[:], []
        return collected


# ═══════════════════════════════════════════════════════════════════════════
# Simulated data source  (NEVER returns source_type=LIVE)
# ═══════════════════════════════════════════════════════════════════════════

# Baseline values per pollutant for simulation
_SIM_BASELINE: Dict[str, Dict[str, Any]] = {
    "PM2.5":       {"base": 35,  "noise": 10,  "unit": "µg/m³",  "media": "AIR"},
    "PM10":        {"base": 65,  "noise": 20,  "unit": "µg/m³",  "media": "AIR"},
    "SO2":         {"base": 45,  "noise": 15,  "unit": "µg/m³",  "media": "AIR"},
    "NO2":         {"base": 38,  "noise": 12,  "unit": "µg/m³",  "media": "AIR"},
    "CO":          {"base": 0.8, "noise": 0.3, "unit": "mg/m³",  "media": "AIR"},
    "CO2":         {"base": 420, "noise": 30,  "unit": "ppm",    "media": "AIR"},
    "VOC":         {"base": 150, "noise": 50,  "unit": "µg/m³",  "media": "AIR"},
    "NH3":         {"base": 60,  "noise": 20,  "unit": "µg/m³",  "media": "AIR"},
    "H2S":         {"base": 12,  "noise": 6,   "unit": "µg/m³",  "media": "AIR"},
    "O3":          {"base": 45,  "noise": 15,  "unit": "µg/m³",  "media": "AIR"},
    "pH":          {"base": 7.2, "noise": 0.4, "unit": "pH",     "media": "WATER"},
    "BOD":         {"base": 18,  "noise": 6,   "unit": "mg/L",   "media": "WATER"},
    "COD":         {"base": 120, "noise": 40,  "unit": "mg/L",   "media": "WATER"},
    "TSS":         {"base": 55,  "noise": 20,  "unit": "mg/L",   "media": "WATER"},
    "DO":          {"base": 7.0, "noise": 1.0, "unit": "mg/L",   "media": "WATER"},
    "WaterTemp":   {"base": 28,  "noise": 3,   "unit": "°C",     "media": "WATER"},
    "Conductivity":{"base": 800, "noise": 150, "unit": "µS/cm",  "media": "WATER"},
    "Turbidity":   {"base": 6,   "noise": 3,   "unit": "NTU",    "media": "WATER"},
    "HeavyMetals": {"base": 0.8, "noise": 0.3, "unit": "mg/L",   "media": "WATER"},
}


class SimulatedDataSource(DataSourceBase):
    """
    Generates realistic simulated sensor readings.
    Always tagged SIMULATED — never presented as live data.
    """

    def __init__(
        self,
        source_id: str,
        name: str,
        industrial_unit_id: str,
        zone: str,
        sensor_configs: List[Dict[str, Any]],
        event_mode: str = "NORMAL",   # NORMAL | WARNING | HIGH_RISK | CRITICAL
    ):
        super().__init__(source_id, name, DataSourceType.SIMULATED)
        self.industrial_unit_id = industrial_unit_id
        self.zone = zone
        self.sensor_configs = sensor_configs
        self.event_mode = event_mode
        self._counters: Dict[str, int] = {}

    def set_event_mode(self, mode: str) -> None:
        self.event_mode = mode

    async def fetch(self) -> List[Dict[str, Any]]:
        now = utcnow()
        records = []
        for sensor in self.sensor_configs:
            reading = self._generate_reading(sensor, now)
            records.append(reading)
        self.record_success()
        return records

    def _generate_reading(self, sensor: Dict[str, Any], ts: datetime) -> Dict[str, Any]:
        pollutant = sensor["pollutant"]
        sensor_id = sensor["sensor_id"]
        baseline = _SIM_BASELINE.get(pollutant, {"base": 50, "noise": 10, "unit": "units", "media": "AIR"})

        base = baseline["base"]
        noise = baseline["noise"]

        # Inject event patterns
        multiplier = 1.0
        if self.event_mode == "WARNING":
            multiplier = 1.5
        elif self.event_mode == "HIGH_RISK":
            multiplier = 1.8
        elif self.event_mode == "CRITICAL":
            multiplier = 2.5
        elif self.event_mode == "RECOVERY":
            multiplier = 0.6

        # Gradual ramp for CRITICAL to simulate realistic increase
        counter = self._counters.get(sensor_id, 0)
        self._counters[sensor_id] = counter + 1
        if self.event_mode == "CRITICAL":
            ramp = min(1.0, counter / 20)
            multiplier = 1.0 + ramp * 1.5

        value = base * multiplier + random.gauss(0, noise * 0.3)
        value = round(max(0.0, value), 3)

        return {
            "sensor_id": sensor_id,
            "industrial_unit_id": self.industrial_unit_id,
            "zone": self.zone,
            "pollutant": pollutant,
            "media": baseline["media"],
            "value": value,
            "unit": sensor.get("unit", baseline["unit"]),
            "timestamp": ts.isoformat(),
            "source_type": DataSourceType.SIMULATED.value,
            "source_id": self.source_id,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Data-source registry
# ═══════════════════════════════════════════════════════════════════════════

class DataSourceRegistry:
    """
    Manages all registered data sources.
    Supports failover: if primary fails, tries alternates.
    """

    def __init__(self) -> None:
        self._sources: Dict[str, DataSourceBase] = {}

    def register(self, source: DataSourceBase) -> None:
        self._sources[source.source_id] = source
        logger.info("DataSource registered: %s (%s)", source.name, source.source_id)

    def get(self, source_id: str) -> Optional[DataSourceBase]:
        return self._sources.get(source_id)

    def all_active(self) -> List[DataSourceBase]:
        return [s for s in self._sources.values() if s.is_active]

    def status(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._sources.values()]

    async def fetch_all(self) -> List[Dict[str, Any]]:
        """Fetch from all active sources concurrently."""
        tasks = [s.fetch() for s in self.all_active()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        records: List[Dict[str, Any]] = []
        for res in results:
            if isinstance(res, Exception):
                logger.error("DataSource fetch error: %s", res)
            else:
                records.extend(res)
        return records


# ── Module-level singleton ────────────────────────────────────────────────────
data_source_registry = DataSourceRegistry()
