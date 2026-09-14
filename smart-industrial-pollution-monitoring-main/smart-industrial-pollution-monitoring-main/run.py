#!/usr/bin/env python3
"""
Entry point.
Usage:
  python run.py           # starts the API server (default port 8000)
  python run.py --port 8080
  python run.py --test    # run test scenarios and exit
  python run.py --demo    # inject a demo critical event then start server
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import os

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))


def start_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Start the FastAPI server via uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: pip install -r requirements.txt")
        sys.exit(1)

    from utils.helpers import configure_logging
    configure_logging()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║   Industrial Pollution Monitor — Gujarat Golden Corridor     ║
║   API  : http://{host}:{port}/docs                           ║
║   Dash : http://{host}:{port}/dashboard                     ║
╚══════════════════════════════════════════════════════════════╝
""")

    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


def run_tests():
    """Run scenario tests and print results."""
    print("Running scenario tests...\n")
    from simulator.scenarios import ScenarioRunner
    runner = ScenarioRunner()

    scenarios = [
        "normal", "warning", "high_risk", "critical",
        "sensor_failure", "missing_data", "recovery", "multi_pollutant",
    ]

    all_ok = True
    for sc in scenarios:
        result = runner.run_scenario(sc)
        status = "✓" if "error" not in result else "✗"
        if "error" in result:
            all_ok = False
        print(
            f"  {status} {sc:<20} | readings={result.get('valid_readings',0)}"
            f" | risk={result.get('risk_level','?'):<10}"
            f" | breaches={result.get('threshold_breaches',0)}"
            f" | anomalies={result.get('anomalies',0)}"
        )

    print(f"\n{'All scenarios passed ✓' if all_ok else 'Some scenarios failed ✗'}")
    return 0 if all_ok else 1


def inject_demo():
    """Inject a demo CRITICAL event into the simulated source, then start server."""
    import asyncio
    print("Injecting demo CRITICAL event for VAPI-001...\n")

    async def _inject():
        from api.bootstrap import bootstrap_system
        from database.db_models import init_db
        await init_db()
        await bootstrap_system()
        from data_sources.manager import data_source_registry, SimulatedDataSource
        source = data_source_registry.get("sim-VAPI-001")
        if isinstance(source, SimulatedDataSource):
            source.set_event_mode("CRITICAL")
            print("Demo: VAPI-001 set to CRITICAL mode — activates on first monitoring cycle.")
        else:
            print("Demo: Could not find sim-VAPI-001 source.")

    asyncio.run(_inject())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pollution Monitor AI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--test", action="store_true", help="Run scenario tests and exit")
    parser.add_argument("--demo", action="store_true", help="Inject demo event before starting")
    args = parser.parse_args()

    if args.test:
        sys.exit(run_tests())

    if args.demo:
        inject_demo()

    start_server(args.host, args.port, args.reload)
