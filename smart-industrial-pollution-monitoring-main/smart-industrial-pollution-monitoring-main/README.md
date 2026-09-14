# Industrial Pollution Monitoring AI — Gujarat Golden Corridor

**Agentic AI system for real-time industrial pollution monitoring covering Vapi, Ankleshwar, Vatva, and configurable industrial zones.**

---

## Architecture

```
OBSERVE → VALIDATE → ANALYZE → PREDICT → DECIDE → ACT → MONITOR → LEARN
```

### Component Map

| Layer | Component | Purpose |
|---|---|---|
| **Core** | `app/models.py` | Domain types, enums — every record tagged LIVE/HISTORICAL/SIMULATED/PREDICTED |
| **Config** | `app/config.py` | All settings from `.env`, no hard-coded secrets |
| **Data Sources** | `data_sources/manager.py` | REST, CSV, Excel, JSON, MQTT, Simulated — with failover |
| **Ingestion** | `data_sources/ingestion.py` | Raw dict → validated SensorReading |
| **Data Quality** | `agents/data_quality_agent.py` | Validates every reading; per-sensor reliability score |
| **Threshold** | `detection/threshold_engine.py` | Configurable regulatory limits, zone overrides |
| **Anomaly** | `detection/anomaly_engine.py` | Z-score + EWMA + Isolation Forest + CUSUM |
| **Prediction** | `prediction/prediction_engine.py` | Linear regression + EWMA trend, early warning |
| **Risk** | `risk/risk_engine.py` | Deterministic 0–100 risk score, 5-level classification |
| **Root Cause** | `agents/root_cause_agent.py` | Structured hypothesis generation |
| **Orchestrator** | `orchestration/orchestrator.py` | Central agent loop, bounded autonomy |
| **Granite** | `ai/granite_client.py` | IBM watsonx.ai — explanations only, never overrides safety |
| **Alerts** | `agents/alert_agent.py` | WebSocket + Email + Webhook, rate-limited |
| **API** | `api/` | FastAPI with all endpoints |
| **Dashboard** | `dashboard/index.html` | Real-time web UI |
| **Simulator** | `simulator/scenarios.py` | 8 test scenarios |
| **Tests** | `tests/test_pipeline.py` | Unit + integration + failure tests |

---

## Quick Start

### 1. Install dependencies

```bash
cd pollution-monitoring-ai
pip install -r requirements.txt
```

> **Note on environment**: The project requires pydantic ≥ 2.7, FastAPI ≥ 0.95, SQLAlchemy 2.x, and greenlet.
> On MSYS2/MinGW Python, install `greenlet` via MSYS2 pacman:
> ```
> pacman -S mingw-w64-ucrt-x86_64-python-greenlet
> ```
> Then add the system site-packages path to your venv:
> ```
> echo C:\msys64\ucrt64\lib\python3.12\site-packages >> <venv>\lib\python3.12\site-packages\msys2_greenlet.pth
> ```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — add IBM_CLOUD_API_KEY etc. for Granite AI
# System works fully without Granite; AI features degrade gracefully
```

### 3. Start the server

```bash
python run.py
# API:       http://localhost:8000/docs
# Dashboard: http://localhost:8000/dashboard
# Or with demo CRITICAL event pre-injected:
python run.py --demo
```

### 4. Run tests

```bash
python run.py --test      # scenario tests (8 scenarios, fast)
pytest tests/ -v          # full test suite (48 unit + integration + resilience tests)
python tests/test_pure_logic.py   # 68 pure-logic checks (no external deps)
```

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | System health + Granite status |
| GET | `/industries` | All industries with risk scores |
| GET | `/industries/{id}` | Detailed unit view |
| GET | `/sensors` | All sensors + reliability |
| GET | `/pollution/current` | Latest readings |
| GET | `/pollution/history` | Historical data |
| GET | `/incidents` | Active/historical incidents |
| GET | `/alerts` | Alerts + filter by severity/status |
| GET | `/risk/{unit_id}` | Risk score + contributing factors |
| GET | `/predictions/{unit_id}` | Predictions + early warnings |
| GET | `/data-sources` | Registered sources + quality |
| POST | `/sensor-data` | Submit live reading |
| POST | `/simulate-event` | Inject simulation mode |
| POST | `/analyze` | One-shot analysis |
| POST | `/monitor` | Trigger monitoring cycle |
| POST | `/alerts/test` | Test alert pipeline |
| POST | `/assistant/query` | Natural-language query (Granite) |
| WS | `/ws/alerts` | Real-time alert stream |

---

## Regulatory Thresholds

`data/regulatory_thresholds.json` — configurable, versioned, source-attributed.

> **Important**: These are reference thresholds only (CPCB/NAAQS India).
> Always verify with official gazette notifications.
> The system uses **"Potential Violation Detected"** — never auto-claims a confirmed legal violation.

Zone-specific overrides supported (Vapi, Ankleshwar, Vatva pre-configured).

---

## Granite Integration

Granite is called **only** for:
- ELEVATED / HIGH / CRITICAL risk events — asynchronously, after deterministic analysis
- Natural-language queries
- Incident explanations

**Critical alerts are NEVER delayed waiting for Granite.**
If Granite fails, deterministic monitoring continues uninterrupted.

```
Normal:     Python → Rules → ML
Suspicious: Python → ML → Risk → Granite (async)
Critical:   Deterministic Alert → Granite (async, non-blocking)
```

---

## Risk Score (0–100)

| Score | Level | Action |
|---|---|---|
| 0–20 | LOW | Monitor normally |
| 21–40 | MODERATE | Increased attention |
| 41–60 | ELEVATED | Alert generated, Granite explanation |
| 61–80 | HIGH | Escalation, root-cause analysis |
| 81–100 | CRITICAL | Immediate escalation, all channels |

---

## Data Source Types

Every record is tagged:

| Tag | Meaning |
|---|---|
| `LIVE` | Real sensor data from REST/MQTT |
| `HISTORICAL` | From CSV/Excel/DB |
| `SIMULATED` | Generated by simulator |
| `PREDICTED` | Forecast by ML model |

**Simulated data is NEVER presented as live. Predictions are NEVER presented as measurements.**

---

## Bounded Autonomy

The system **MAY**:
- Detect anomalies and generate alerts
- Increase monitoring frequency
- Generate predictions and recommendations
- Request additional data
- Escalate events

The system **MUST NOT**:
- Shut down factories
- Impose legal penalties
- Make irreversible decisions
- Fabricate regulatory findings
- Bypass authentication

---

## Resilience

| Failure | Response |
|---|---|
| API failure | Use alternate source → historical fallback |
| Granite failure | Continue deterministic monitoring |
| ML failure | Statistical fallback (Z-score + EWMA) |
| DB failure | Queue critical events |
| Sensor failure | Mark unreliable, use other evidence |

---

## Project Structure

```
pollution-monitoring-ai/
├── app/                    # config, models
├── agents/                 # data quality, root cause, alert agents
├── ai/                     # Granite client
├── orchestration/          # central agent loop
├── data_sources/           # multi-source ingestion
├── detection/              # threshold + anomaly engines
├── prediction/             # forecasting engine
├── risk/                   # risk scoring engine
├── database/               # ORM models + CRUD
├── api/                    # FastAPI + all routes
├── simulator/              # test scenarios
├── dashboard/              # web UI
├── utils/                  # helpers
├── tests/                  # test suite
├── data/                   # regulatory_thresholds.json
├── requirements.txt
├── .env.example
├── run.py
└── README.md
```

---

## Design Philosophy

> Build the **smallest system that provides the highest reliable intelligence per unit of compute**.
>
> **Reliability → Data Quality → Critical Event Recall → Prediction → Accuracy → Explainability → Latency**

- Python handles all math, validation, thresholds, statistics, risk
- ML handles anomaly detection and forecasting
- Granite handles reasoning, explanations, natural-language interaction only
- No complexity added for appearance
