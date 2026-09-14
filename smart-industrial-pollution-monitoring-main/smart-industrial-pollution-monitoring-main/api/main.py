"""
FastAPI application — main entry point.

Mounts all routers, initialises the database, starts the orchestrator,
and wires up the WebSocket / startup / shutdown lifecycle.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from database.db_models import init_db
from utils.helpers import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ─────────────────────────────────────────────────────────────
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # 1. Init DB
    await init_db()
    logger.info("Database initialised")

    # 2. Bootstrap sample industrial units + simulated data sources
    from api.bootstrap import bootstrap_system
    await bootstrap_system()

    # 3. Start orchestrator
    from orchestration.orchestrator import orchestrator
    from agents.alert_agent import alert_agent

    # Wire alert callbacks
    orchestrator.register_alert_callback(alert_agent.dispatch)

    await orchestrator.start()
    logger.info("Monitoring orchestrator started")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    await orchestrator.stop()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Agentic AI system for industrial pollution monitoring — Gujarat Golden Corridor",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount routers ──────────────────────────────────────────────────────────────
from api.routes import (
    health, industries, sensors, pollution,
    incidents, alerts, risk, predictions, data_sources,
    monitor, assistant, simulate,
)

app.include_router(health.router,        prefix="",           tags=["Health"])
app.include_router(industries.router,    prefix="/industries", tags=["Industries"])
app.include_router(sensors.router,       prefix="/sensors",    tags=["Sensors"])
app.include_router(pollution.router,     prefix="/pollution",  tags=["Pollution"])
app.include_router(incidents.router,     prefix="/incidents",  tags=["Incidents"])
app.include_router(alerts.router,        prefix="/alerts",     tags=["Alerts"])
app.include_router(risk.router,          prefix="/risk",       tags=["Risk"])
app.include_router(predictions.router,   prefix="/predictions",tags=["Predictions"])
app.include_router(data_sources.router,  prefix="/data-sources",tags=["Data Sources"])
app.include_router(monitor.router,       prefix="",            tags=["Monitor"])
app.include_router(assistant.router,     prefix="/assistant",  tags=["AI Assistant"])
app.include_router(simulate.router,      prefix="/simulate",   tags=["Simulator"])

# ── Root redirect → dashboard ─────────────────────────────────────────────────
from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard")

# ── Static files (dashboard) ──────────────────────────────────────────────────
import os
_dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard")
if not os.path.isdir(_dashboard_dir):
    _dashboard_dir = "dashboard"
if os.path.isdir(_dashboard_dir):
    app.mount("/dashboard", StaticFiles(directory=_dashboard_dir, html=True), name="dashboard")
