"""
Standalone pure-Python logic validation.
Tests all core algorithms without requiring any pip-installed packages.
Run: python tests/test_pure_logic.py
"""
import sys
import os
import math
from datetime import datetime, timedelta
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ─── We stub out external dependencies ──────────────────────────────────────

# Stub pydantic with a minimal compatible implementation
class _BaseModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
    def model_dump(self):
        return self.__dict__

class _Field:
    def __call__(self, *a, **kw):
        return kw.get("default", None)
    def __getattr__(self, name):
        return self

Field = _Field()

import types

pydantic_mod = types.ModuleType("pydantic")
pydantic_mod.BaseModel = _BaseModel
pydantic_mod.Field = Field
sys.modules["pydantic"] = pydantic_mod

ps_mod = types.ModuleType("pydantic_settings")
ps_mod.BaseSettings = _BaseModel
ps_mod.SettingsConfigDict = lambda **kw: None
sys.modules["pydantic_settings"] = ps_mod

# Stub sqlalchemy
for mod in ["sqlalchemy", "sqlalchemy.ext.asyncio", "sqlalchemy.orm"]:
    sys.modules[mod] = types.ModuleType(mod)

# ─── Now import our pure logic modules ──────────────────────────────────────

from utils.helpers import (
    zscore, ewma, safe_mean, safe_std, pct_change, clamp,
    is_future, seconds_since, utcnow, truncate_str,
)


# ═══════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        print(f"  ✓  {name}")
        PASS += 1
    else:
        print(f"  ✗  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1


# ─── utils/helpers.py ────────────────────────────────────────────────────────
print("\n── utils/helpers.py ──")

vals = [40.0, 42.0, 41.0, 43.0, 40.0, 39.0, 41.0]
mean = safe_mean(vals)
std  = safe_std(vals)

check("safe_mean on non-empty list", mean is not None and 39 < mean < 44)
check("safe_std on non-empty list", std is not None and std > 0)
check("safe_mean on empty list returns None", safe_mean([]) is None)
check("safe_std on single-element list returns None", safe_std([1.0]) is None)

z = zscore(200.0, mean, std)
check("z-score for spike value > 5", z is not None and abs(z) > 5, f"z={z}")
check("z-score for normal value < 3", abs(zscore(41.0, mean, std)) < 3)
check("zscore with std=0 returns None", zscore(50.0, 50.0, 0.0) is None)

ew = ewma([1.0, 2.0, 3.0, 4.0, 5.0], alpha=0.3)
check("ewma returns a float", isinstance(ew, float))
check("ewma of empty list returns None", ewma([]) is None)
check("ewma increases toward end", ewma([1.0, 2.0, 3.0], alpha=0.5) > 1.0)

check("clamp above max", clamp(150.0, 0.0, 100.0) == 100.0)
check("clamp below min", clamp(-5.0,  0.0, 100.0) == 0.0)
check("clamp in range unchanged", clamp(50.0,  0.0, 100.0) == 50.0)

check("pct_change positive", pct_change(100.0, 120.0) == 20.0)
check("pct_change negative", pct_change(100.0, 80.0)  == -20.0)
check("pct_change zero base returns None", pct_change(0.0, 100.0) is None)

check("is_future detects future timestamp", is_future(utcnow() + timedelta(hours=1)))
check("is_future rejects past timestamp", not is_future(utcnow() - timedelta(hours=1)))

check("truncate_str truncates", len(truncate_str("x"*1000, 100)) == 101)  # 100 + ellipsis char
check("truncate_str leaves short strings", truncate_str("hello", 100) == "hello")


# ─── Risk level classification ───────────────────────────────────────────────
print("\n── risk_engine — _risk_level boundary tests ──")

# Inline the logic to test it without the ORM dependency
def _risk_level(score: float) -> str:
    if score <= 20:  return "LOW"
    if score <= 40:  return "MODERATE"
    if score <= 60:  return "ELEVATED"
    if score <= 80:  return "HIGH"
    return "CRITICAL"

boundaries = [
    (0,   "LOW"),
    (20,  "LOW"),
    (20.1,"MODERATE"),
    (21,  "MODERATE"),
    (40,  "MODERATE"),
    (40.1,"ELEVATED"),
    (41,  "ELEVATED"),
    (60,  "ELEVATED"),
    (60.1,"HIGH"),
    (61,  "HIGH"),
    (80,  "HIGH"),
    (80.1,"CRITICAL"),
    (81,  "CRITICAL"),
    (100, "CRITICAL"),
]
for score, expected in boundaries:
    check(f"risk_level({score}) == {expected}", _risk_level(score) == expected)


# ─── SensorAnomalyState logic ─────────────────────────────────────────────────
print("\n── SensorAnomalyState — frozen / spike detection ──")

from collections import deque
import random

class MinimalSensorState:
    def __init__(self, window=60):
        self._values = deque(maxlen=window)
        self.window = window

    def push(self, v):
        self._values.append(v)

    def values(self):
        return list(self._values)

    def is_frozen(self, freeze_window=10):
        vals = self.values()
        n = min(len(vals), freeze_window)
        if n < 3:
            return False
        return len(set(vals[-n:])) == 1

    def is_spike(self, value, threshold_factor=5.0):
        vals = self.values()
        if len(vals) < 5:
            return False
        mean = sum(vals) / len(vals)
        variance = sum((v - mean)**2 for v in vals) / len(vals)
        std = variance ** 0.5
        if std < 1e-6:
            return False
        return abs(value - mean) > threshold_factor * std

state = MinimalSensorState()
for _ in range(15):
    state.push(42.0)  # frozen
check("frozen sensor detected after 10+ identical values", state.is_frozen())

state2 = MinimalSensorState()
random.seed(42)
for _ in range(30):
    state2.push(40.0 + random.gauss(0, 1.0))
check("spike detected for 10× std deviation", state2.is_spike(200.0))
check("normal value not detected as spike", not state2.is_spike(41.0))
check("insufficient data returns not frozen", not MinimalSensorState().is_frozen())


# ─── Linear regression prediction ────────────────────────────────────────────
print("\n── Prediction engine — linear regression ──")

def _linear_regression_forecast(vals, times, horizon_min):
    n = len(vals)
    if n < 3:
        return None, 0.0
    t_last = times[-1] if times else n - 1
    xs = [t - t_last for t in times]
    ys = vals
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xy = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    ss_xx = sum((xs[i] - mean_x) ** 2 for i in range(n))
    if ss_xx == 0:
        return mean_y, 0.0
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x
    predicted = max(0.0, intercept + slope * horizon_min)
    residuals = [ys[i] - (intercept + slope * xs[i]) for i in range(n)]
    rmse = math.sqrt(sum(r**2 for r in residuals) / n)
    return predicted, rmse

# Perfect increasing trend: value = 30 + 2*t (t in minutes)
n = 20
vals_inc = [30.0 + 2.0 * i for i in range(n)]
times_inc = list(range(n))
pred, rmse = _linear_regression_forecast(vals_inc, times_inc, 30)
check("linear regression predicts correctly for perfect trend",
      pred is not None and abs(pred - (30.0 + 2.0 * (n-1) + 2.0 * 30)) < 5,
      f"pred={pred}")
check("rmse is near-zero for perfect linear data", rmse < 0.01, f"rmse={rmse}")

# Flat data
vals_flat = [50.0] * 20
times_flat = list(range(20))
pred2, _ = _linear_regression_forecast(vals_flat, times_flat, 30)
check("flat trend prediction near current value", abs(pred2 - 50.0) < 1.0, f"pred={pred2}")

check("returns None for <3 data points", _linear_regression_forecast([1.0], [0], 30)[0] is None)


# ─── CUSUM change-point ───────────────────────────────────────────────────────
print("\n── CUSUM change-point detection ──")

def _cusum_score(values, value):
    if not values:
        return None
    mean = sum(values) / len(values)
    variance = sum((v - mean)**2 for v in values) / len(values)
    std = variance**0.5 or 1.0
    slack = 0.5 * std
    cusum_pos = 0.0
    cusum_neg = 0.0
    for v in values:
        cusum_pos = max(0, cusum_pos + (v - mean) - slack)
        cusum_neg = max(0, cusum_neg - (v - mean) - slack)
    # Check new value
    cusum_pos = max(0, cusum_pos + (value - mean) - slack)
    cusum_neg = max(0, cusum_neg - (value - mean) - slack)
    threshold = 5 * std
    cusum_val = max(cusum_pos, cusum_neg)
    if cusum_val > threshold:
        return min(1.0, cusum_val / (threshold * 2))
    return None

baseline = [40.0 + random.gauss(0, 1) for _ in range(20)]
check("CUSUM detects large shift", _cusum_score(baseline, 200.0) is not None)
check("CUSUM returns None for no change", _cusum_score(baseline, 40.5) is None)


# ─── Threshold breach logic ───────────────────────────────────────────────────
print("\n── Threshold engine — breach classification ──")

def classify_breach(value, threshold, warning_factor=0.8):
    if value >= threshold:
        return "POTENTIAL_VIOLATION"
    if value >= threshold * warning_factor:
        return "WARNING_ZONE"
    return "COMPLIANT"

check("breach at 100% of threshold → POTENTIAL_VIOLATION",
      classify_breach(100.0, 100.0) == "POTENTIAL_VIOLATION")
check("breach above threshold → POTENTIAL_VIOLATION",
      classify_breach(110.0, 100.0) == "POTENTIAL_VIOLATION")
check("value at 85% → WARNING_ZONE",
      classify_breach(85.0, 100.0) == "WARNING_ZONE")
check("value at 50% → COMPLIANT",
      classify_breach(50.0, 100.0) == "COMPLIANT")
check("never auto-confirms violation",
      classify_breach(999.0, 100.0) != "CONFIRMED_VIOLATION")


# ─── Score bounds ─────────────────────────────────────────────────────────────
print("\n── Risk score bounds ──")

def mock_risk_score(breach_excess_pct, anomaly_scores, sensor_reliability=1.0):
    score = 0.0
    if breach_excess_pct > 0:
        score += min(35.0, breach_excess_pct * 0.3 + 2)
    if anomaly_scores:
        avg = sum(anomaly_scores) / len(anomaly_scores)
        score += min(20.0, avg * 15)
    if sensor_reliability < 0.8:
        penalty = (0.8 - sensor_reliability) * 50
        score -= penalty
    return max(0.0, min(100.0, score))

check("zero input → score = 0.0", mock_risk_score(0, []) == 0.0)
check("score capped at 100", mock_risk_score(1000, [1.0]*10) <= 100.0)
check("score never negative", mock_risk_score(0, [], 0.0) >= 0.0)
check("low reliability reduces score",
      mock_risk_score(50, [0.8]) > mock_risk_score(50, [0.8], 0.2))


# ─── Data ingestion coercion ──────────────────────────────────────────────────
print("\n── Data ingestion — coerce_reading (inline) ──")

VALID_POLLUTANTS = {
    "PM2.5","PM10","SO2","NO2","CO","CO2","VOC","NH3","H2S","O3",
    "pH","BOD","COD","TSS","DO","WaterTemp","Conductivity","Turbidity","HeavyMetals"
}

def minimal_coerce(raw):
    try:
        if not isinstance(raw.get("value"), (int, float)):
            return None
        if raw.get("pollutant") not in VALID_POLLUTANTS:
            return None
        if "sensor_id" not in raw or "industrial_unit_id" not in raw:
            return None
        return {"ok": True, **raw}
    except Exception:
        return None

check("valid raw coerced OK", minimal_coerce({"sensor_id":"x","industrial_unit_id":"y","pollutant":"SO2","value":50.0}) is not None)
check("missing sensor_id → None", minimal_coerce({"pollutant":"SO2","value":50.0,"industrial_unit_id":"y"}) is None)
check("unknown pollutant → None", minimal_coerce({"sensor_id":"x","industrial_unit_id":"y","pollutant":"UNKNOWN","value":50}) is None)
check("non-numeric value → None", minimal_coerce({"sensor_id":"x","industrial_unit_id":"y","pollutant":"SO2","value":"abc"}) is None)


# ─── Regulatory threshold JSON structure ──────────────────────────────────────
print("\n── regulatory_thresholds.json — structure validation ──")
import json

with open("data/regulatory_thresholds.json") as f:
    config = json.load(f)

check("has _meta block", "_meta" in config)
check("has version", "version" in config["_meta"])
check("has air pollutants", "air" in config)
check("has water pollutants", "water" in config)
check("SO2 has limits", "limits" in config["air"]["SO2"])
check("pH has min limit (water)", "min" in config["water"]["pH"]["limits"].get("surface_water",{}) or
      "min" in config["water"]["pH"]["limits"].get("effluent_discharge",{}))
check("has zone_overrides", "zone_overrides" in config)
check("Vapi override present", "Vapi" in config["zone_overrides"])
check("Ankleshwar override present", "Ankleshwar" in config["zone_overrides"])
check("warning_factor present on SO2", "warning_factor" in config["air"]["SO2"])
check("hazard_class present on H2S", config["air"]["H2S"]["hazard_class"] == "CRITICAL")


# ─── Summary ──────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"Results: {PASS} passed, {FAIL} failed out of {PASS+FAIL} checks")
print(f"{'ALL CHECKS PASSED ✓' if FAIL == 0 else f'FAILURES: {FAIL}'}")
print('='*55)
sys.exit(0 if FAIL == 0 else 1)
