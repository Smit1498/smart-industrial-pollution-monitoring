"""
Bootstrap: seed the database with industrial units and
register simulated data sources so the system works out-of-the-box.
"""
from __future__ import annotations

from data_sources.manager import SimulatedDataSource, data_source_registry
from orchestration.orchestrator import orchestrator
from database.db_models import AsyncSessionLocal
from database.crud import upsert_industrial_unit, upsert_sensor_metadata
from utils.helpers import get_logger

logger = get_logger(__name__)

# ── Sample industrial units ────────────────────────────────────────────────────

_UNITS = [
    {"unit_id": "VAPI-001", "name": "Vapi Chemical Industries", "zone": "Vapi",
     "industry_type": "Chemical", "location_lat": 20.3724, "location_lon": 72.9065},
    {"unit_id": "VAPI-002", "name": "Vapi Pharma Cluster", "zone": "Vapi",
     "industry_type": "Pharma", "location_lat": 20.3690, "location_lon": 72.9100},
    {"unit_id": "ANK-001", "name": "Ankleshwar Petrochemical", "zone": "Ankleshwar",
     "industry_type": "Petrochemical", "location_lat": 21.6270, "location_lon": 73.0030},
    {"unit_id": "ANK-002", "name": "Ankleshwar Dye Works", "zone": "Ankleshwar",
     "industry_type": "Dye", "location_lat": 21.6310, "location_lon": 73.0080},
    {"unit_id": "VAT-001", "name": "Vatva Chemical Complex", "zone": "Vatva",
     "industry_type": "Chemical", "location_lat": 22.9730, "location_lon": 72.6530},
    {"unit_id": "VAT-002", "name": "Vatva Textile Processing", "zone": "Vatva",
     "industry_type": "Textile", "location_lat": 22.9750, "location_lon": 72.6560},
]

# ── Sensor configurations per unit ────────────────────────────────────────────

_AIR_SENSORS = [
    {"pollutant": "SO2",   "unit": "µg/m³"},
    {"pollutant": "NO2",   "unit": "µg/m³"},
    {"pollutant": "PM2.5", "unit": "µg/m³"},
    {"pollutant": "PM10",  "unit": "µg/m³"},
    {"pollutant": "H2S",   "unit": "µg/m³"},
    {"pollutant": "VOC",   "unit": "µg/m³"},
]

_WATER_SENSORS = [
    {"pollutant": "pH",    "unit": "pH"},
    {"pollutant": "COD",   "unit": "mg/L"},
    {"pollutant": "BOD",   "unit": "mg/L"},
    {"pollutant": "TSS",   "unit": "mg/L"},
]


async def bootstrap_system() -> None:
    """Seed DB and register simulated data sources."""
    async with AsyncSessionLocal() as db:
        for unit_data in _UNITS:
            unit_id = unit_data["unit_id"]
            zone = unit_data["zone"]
            sensor_configs = []

            # Build sensors
            for i, s in enumerate(_AIR_SENSORS):
                sid = f"{unit_id}-AIR-{i+1:02d}"
                sensor_configs.append({
                    "sensor_id": sid,
                    "pollutant": s["pollutant"],
                    "unit": s["unit"],
                })
                await upsert_sensor_metadata(db, {
                    "sensor_id": sid,
                    "industrial_unit_id": unit_id,
                    "zone": zone,
                    "pollutant": s["pollutant"],
                    "media": "AIR",
                    "unit": s["unit"],
                })

            for i, s in enumerate(_WATER_SENSORS):
                sid = f"{unit_id}-WAT-{i+1:02d}"
                sensor_configs.append({
                    "sensor_id": sid,
                    "pollutant": s["pollutant"],
                    "unit": s["unit"],
                })
                await upsert_sensor_metadata(db, {
                    "sensor_id": sid,
                    "industrial_unit_id": unit_id,
                    "zone": zone,
                    "pollutant": s["pollutant"],
                    "media": "WATER",
                    "unit": s["unit"],
                })

            # Upsert industrial unit with sensor IDs
            sensor_ids = [sc["sensor_id"] for sc in sensor_configs]
            await upsert_industrial_unit(db, {**unit_data, "sensors": sensor_ids})

            # Register simulated data source
            sim = SimulatedDataSource(
                source_id=f"sim-{unit_id}",
                name=f"Simulator — {unit_data['name']}",
                industrial_unit_id=unit_id,
                zone=zone,
                sensor_configs=sensor_configs,
                event_mode="NORMAL",
            )
            data_source_registry.register(sim)

            # Register unit with orchestrator
            orchestrator.register_unit({**unit_data, "sensors": sensor_ids})

    logger.info("Bootstrap complete: %d industrial units registered", len(_UNITS))
