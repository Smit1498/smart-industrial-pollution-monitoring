"""
Ingestion pipeline.

Converts raw dicts from data sources → validated SensorReading objects,
then feeds them to the data-quality agent and persists them.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.models import DataSourceType, MediaType, PollutantType, SensorReading
from utils.helpers import get_logger, utcnow

logger = get_logger(__name__)

_MEDIA_MAP = {p.value: "AIR" for p in PollutantType if p.value in {
    "PM2.5", "PM10", "SO2", "NO2", "CO", "CO2", "VOC", "NH3", "H2S", "O3"
}}
_MEDIA_MAP.update({p.value: "WATER" for p in PollutantType if p.value in {
    "pH", "BOD", "COD", "TSS", "DO", "WaterTemp", "Conductivity", "Turbidity", "HeavyMetals"
}})


def coerce_reading(raw: Dict[str, Any]) -> Optional[SensorReading]:
    """
    Convert a raw dict (from any data source) to a SensorReading.
    Returns None if required fields are missing or malformed.
    """
    try:
        # Required fields
        sensor_id = str(raw["sensor_id"])
        unit_id = str(raw["industrial_unit_id"])
        zone = str(raw.get("zone", "Unknown"))
        pollutant_raw = str(raw["pollutant"])
        value_raw = raw["value"]
        unit = str(raw.get("unit", ""))
        source_type_raw = raw.get("source_type", DataSourceType.LIVE.value)
        source_id = str(raw.get("source_id", "unknown"))

        # Coerce pollutant
        try:
            pollutant = PollutantType(pollutant_raw)
        except ValueError:
            logger.debug("Unknown pollutant '%s' — skipping", pollutant_raw)
            return None

        # Coerce value
        value = float(value_raw)

        # Coerce timestamp
        ts_raw = raw.get("timestamp")
        if ts_raw is None:
            timestamp = utcnow()
        elif isinstance(ts_raw, datetime):
            timestamp = ts_raw
        else:
            timestamp = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            # Strip timezone for uniform naive-UTC storage
            if timestamp.tzinfo is not None:
                from datetime import timezone
                timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)

        # Coerce source type
        try:
            source_type = DataSourceType(source_type_raw)
        except ValueError:
            source_type = DataSourceType.LIVE

        # Determine media
        media_raw = raw.get("media", _MEDIA_MAP.get(pollutant.value, "AIR"))
        try:
            media = MediaType(media_raw)
        except ValueError:
            media = MediaType.AIR

        return SensorReading(
            id=uuid4(),
            sensor_id=sensor_id,
            industrial_unit_id=unit_id,
            zone=zone,
            pollutant=pollutant,
            media=media,
            value=value,
            unit=unit,
            timestamp=timestamp,
            source_type=source_type,
            source_id=source_id,
            raw_value=value,
            metadata=raw.get("metadata", {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("coerce_reading failed: %s | raw=%s", exc, raw)
        return None


def coerce_batch(raw_records: List[Dict[str, Any]]) -> List[SensorReading]:
    """Coerce a batch of raw dicts, silently dropping invalid ones."""
    readings = []
    for raw in raw_records:
        r = coerce_reading(raw)
        if r is not None:
            readings.append(r)
    return readings
