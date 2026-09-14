"""
Shared utilities: logging, time helpers, unit conversion, statistics.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional, Sequence

from app.config import get_settings

# ── Logging setup ────────────────────────────────────────────────────────────

def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(stream=sys.stdout, level=level, format=fmt, force=True)
    # Quieten noisy third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ── Time helpers ─────────────────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seconds_since(ts: datetime) -> float:
    """Return seconds elapsed since *ts* (naive UTC assumed)."""
    return (utcnow() - ts).total_seconds()


def is_future(ts: datetime) -> bool:
    return ts > utcnow()


# ── Statistics ───────────────────────────────────────────────────────────────

def safe_mean(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def safe_std(values: Sequence[float]) -> Optional[float]:
    mean = safe_mean(values)
    if mean is None or len(values) < 2:
        return None
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance ** 0.5


def zscore(value: float, mean: float, std: float) -> Optional[float]:
    if std == 0:
        return None
    return (value - mean) / std


def ewma(
    values: List[float],
    alpha: float = 0.3,
) -> Optional[float]:
    """Exponentially Weighted Moving Average of a series — returns last value."""
    if not values:
        return None
    result = values[0]
    for v in values[1:]:
        result = alpha * v + (1 - alpha) * result
    return result


def pct_change(old: float, new: float) -> Optional[float]:
    if old == 0:
        return None
    return ((new - old) / abs(old)) * 100.0


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# ── Unit helpers ─────────────────────────────────────────────────────────────

_AIR_CONVERSIONS: dict[str, dict[str, float]] = {
    # ppm → µg/m³ at 25°C, 1 atm
    "SO2":  {"ppm_to_ugm3": 2620.0},
    "NO2":  {"ppm_to_ugm3": 1880.0},
    "CO":   {"ppm_to_ugm3": 1145.0},
    "NH3":  {"ppm_to_ugm3": 696.0},
    "H2S":  {"ppm_to_ugm3": 1390.0},
    "O3":   {"ppm_to_ugm3": 1960.0},
}


def convert_ppm_to_ugm3(pollutant: str, ppm_value: float) -> Optional[float]:
    entry = _AIR_CONVERSIONS.get(pollutant)
    if entry is None:
        return None
    return ppm_value * entry["ppm_to_ugm3"]


# ── Formatting helpers ────────────────────────────────────────────────────────

def truncate_str(s: str, max_len: int = 500) -> str:
    return s if len(s) <= max_len else s[:max_len] + "…"


def safe_json(obj: Any) -> Any:
    """Make an object JSON-serialisable (best-effort)."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)
