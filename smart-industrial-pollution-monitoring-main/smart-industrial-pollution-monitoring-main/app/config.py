"""
Central configuration — all settings loaded from environment / .env.
Never hard-code secrets.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # pydantic v2 style
except ImportError:
    from pydantic import BaseSettings  # pydantic v1 built-in


class Settings(BaseSettings):
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    # ── IBM / watsonx ───────────────────────────────────────────────────────
    IBM_CLOUD_API_KEY: str = ""
    IBM_WATSONX_URL: str = "https://us-south.ml.cloud.ibm.com"
    IBM_GRANITE_MODEL: str = "ibm/granite-13b-instruct-v2"
    IBM_PROJECT_ID: str = ""

    # ── App ─────────────────────────────────────────────────────────────────
    APP_NAME: str = "Industrial Pollution Monitor — Gujarat Golden Corridor"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── Database ────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./pollution_monitor.db"

    # ── Resource mode ───────────────────────────────────────────────────────
    # NORMAL | LOW_RESOURCE | EMERGENCY
    RESOURCE_MODE: str = "NORMAL"

    # ── Monitoring ──────────────────────────────────────────────────────────
    POLL_INTERVAL_SECONDS: int = 30
    STALE_DATA_THRESHOLD_SECONDS: int = 300   # 5 min → sensor considered stale
    SENSOR_FREEZE_WINDOW: int = 10             # identical readings → frozen

    # ── ML ──────────────────────────────────────────────────────────────────
    ANOMALY_ZSCORE_THRESHOLD: float = 3.0
    ISOLATION_FOREST_CONTAMINATION: float = 0.05
    ROLLING_WINDOW_SIZE: int = 60             # data-points for rolling stats

    # ── Risk ────────────────────────────────────────────────────────────────
    RISK_LOW_MAX: int = 20
    RISK_MODERATE_MAX: int = 40
    RISK_ELEVATED_MAX: int = 60
    RISK_HIGH_MAX: int = 80

    # ── Alert ───────────────────────────────────────────────────────────────
    ALERT_EMAIL_ENABLED: bool = False
    ALERT_SMTP_HOST: str = ""
    ALERT_SMTP_PORT: int = 587
    ALERT_SMTP_USER: str = ""
    ALERT_SMTP_PASSWORD: str = ""
    ALERT_RECIPIENTS: str = ""           # comma-separated e-mail list

    ALERT_WEBHOOK_URL: str = ""          # optional Slack/Teams/custom webhook

    # ── MQTT ────────────────────────────────────────────────────────────────
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_TOPIC_PREFIX: str = "pollution/sensors"
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""

    # ── Regulatory config file ──────────────────────────────────────────────
    REGULATORY_CONFIG_PATH: str = "data/regulatory_thresholds.json"

    # ── Industrial zones ────────────────────────────────────────────────────
    INDUSTRIAL_ZONES: List[str] = ["Vapi", "Ankleshwar", "Vatva", "Naroda", "Odhav"]

    # ── Granite usage ───────────────────────────────────────────────────────
    # Risk score threshold above which we call Granite
    GRANITE_TRIGGER_RISK_SCORE: int = 41   # ELEVATED and above
    GRANITE_MAX_CONTEXT_TOKENS: int = 2000
    GRANITE_TIMEOUT_SECONDS: int = 30

    @property
    def alert_recipient_list(self) -> List[str]:
        return [r.strip() for r in self.ALERT_RECIPIENTS.split(",") if r.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
