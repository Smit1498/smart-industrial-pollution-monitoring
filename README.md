# smart-industrial-pollution-monitoring
AI-powered smart industrial pollution monitoring system for Gujarat Golden Corridor using Python, FastAPI and IBM Granite integration.
# 🌍 Industrial Pollution Monitoring AI

### Agentic AI for Real-Time Industrial Pollution Intelligence

#### Gujarat Golden Corridor: Vapi • Ankleshwar • Vatva

<p align="center">

**Observe pollution. Detect anomalies. Predict risk. Explain incidents. Trigger timely action.**

</p>

---

## 🚨 Problem Statement

The industrial belt of Gujarat, including **Vapi, Ankleshwar, and Vatva**, contains several chemical, pharmaceutical, manufacturing, and processing industries.

These industrial zones can generate:

* Air pollution
* Water pollution
* Chemical emissions
* Abnormal industrial discharge
* Hazardous environmental events
* Sudden pollution spikes

Traditional monitoring systems may struggle with:

* Delayed detection
* Limited real-time visibility
* Poor data quality
* Lack of predictive intelligence
* Slow incident analysis
* Difficult coordination between monitoring systems

## 💡 Our Solution

**Industrial Pollution Monitoring AI** is an intelligent monitoring platform designed to detect, analyze, predict, and explain industrial pollution events.

The system combines:

* Real-time sensor data
* Historical environmental data
* Simulated pollution scenarios
* Statistical analysis
* Machine learning
* Risk scoring
* Agentic workflows
* IBM Granite-powered explanations
* Real-time alerts
* Interactive monitoring dashboard

The goal is to help environmental teams identify potential pollution incidents earlier and make better-informed decisions.

---

## 🧠 Agentic AI Workflow

```text
OBSERVE
   ↓
VALIDATE
   ↓
ANALYZE
   ↓
DETECT ANOMALY
   ↓
PREDICT
   ↓
ASSESS RISK
   ↓
EXPLAIN WITH GRANITE
   ↓
ALERT
   ↓
MONITOR
   ↓
LEARN
```

### How It Works

1. **Observe**
   Collect readings from sensors, APIs, CSV files, Excel files, MQTT sources, or simulation.

2. **Validate**
   Check data quality, missing values, invalid readings, and sensor reliability.

3. **Analyze**
   Compare readings with configured environmental thresholds.

4. **Detect Anomaly**
   Identify unusual pollution behavior using statistical and machine learning techniques.

5. **Predict**
   Estimate future pollution trends and possible early warnings.

6. **Assess Risk**
   Generate a deterministic risk score between 0 and 100.

7. **Explain**
   Use IBM Granite to generate human-readable explanations and recommendations.

8. **Alert**
   Send alerts through supported channels such as WebSocket, email, or webhook.

9. **Monitor**
   Continue monitoring the affected industrial unit and update its risk status.

---

## ✨ Key Features

### 📡 Multi-Source Data Ingestion

Supports pollution data from:

* REST APIs
* CSV files
* Excel files
* JSON files
* MQTT sources
* Simulated sensor data
* Historical datasets

### 🧪 Data Quality Monitoring

* Reading validation
* Sensor reliability scoring
* Missing data detection
* Invalid data detection
* Fallback handling
* Source quality tracking

### 📊 Pollution Detection

* Configurable pollution thresholds
* Zone-specific threshold overrides
* Z-score anomaly detection
* EWMA trend analysis
* CUSUM detection
* Isolation Forest support
* Sudden pollution spike detection

### 🔮 Pollution Prediction

* Linear regression
* EWMA-based trend prediction
* Early warning generation
* Future pollution trend estimation
* Prediction confidence handling

### ⚠️ Risk Assessment

Every industrial unit receives a risk score from **0 to 100**.

| Risk Score | Risk Level  | Recommended Action                        |
| ---------: | ----------- | ----------------------------------------- |
|       0–20 | 🟢 LOW      | Normal monitoring                         |
|      21–40 | 🟡 MODERATE | Increased attention                       |
|      41–60 | 🟠 ELEVATED | Generate alert and explanation            |
|      61–80 | 🔴 HIGH     | Escalation and root-cause analysis        |
|     81–100 | 🚨 CRITICAL | Immediate escalation through all channels |

### 🤖 IBM Granite Integration

IBM Granite is used for:

* Pollution incident explanations
* Natural-language questions
* Risk summaries
* Root-cause hypotheses
* Environmental recommendations
* Incident report generation

Granite is used as an **explanation and reasoning layer**.

Safety-critical monitoring decisions continue through deterministic rules and monitoring logic even if Granite is unavailable.

### 🔔 Alert System

Supported alert mechanisms include:

* WebSocket alerts
* Email alerts
* Webhook notifications
* Severity-based filtering
* Rate-limited alerts
* Critical event escalation

### 🖥️ Interactive Dashboard

The dashboard provides:

* Industrial unit overview
* Sensor readings
* Pollution status
* Risk levels
* Active incidents
* Historical trends
* Prediction information
* Alert monitoring
* Data-source status

---

## 🏗️ System Architecture

```text
                    ┌─────────────────────────┐
                    │   Sensors / APIs / CSV   │
                    │   Excel / MQTT / Demo    │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Data Source Manager   │
                    │  Ingestion + Validation  │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Data Quality Agent    │
                    │ Sensor Reliability Score │
                    └────────────┬────────────┘
                                 │
                ┌────────────────┼────────────────┐
                ▼                ▼                ▼
      ┌────────────────┐ ┌───────────────┐ ┌───────────────┐
      │ Threshold      │ │ Anomaly       │ │ Prediction    │
      │ Engine         │ │ Detection     │ │ Engine        │
      └────────┬───────┘ └───────┬───────┘ └───────┬───────┘
               │                 │                 │
               └─────────────────┼─────────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │      Risk Engine        │
                    │   Deterministic Score   │
                    └────────────┬────────────┘
                                 │
                  ┌──────────────┴──────────────┐
                  ▼                             ▼
       ┌────────────────────┐        ┌────────────────────┐
       │ Alert Agent        │        │ IBM Granite        │
       │ WebSocket / Email  │        │ Explanation Layer  │
       │ Webhook            │        │ Natural Language   │
       └──────────┬─────────┘        └──────────┬─────────┘
                  │                             │
                  └──────────────┬──────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │   FastAPI Backend       │
                    │   REST API + WebSocket  │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   Monitoring Dashboard  │
                    └─────────────────────────┘
```

---

## 🛠️ Technology Stack

### Backend

* Python
* FastAPI
* Uvicorn
* Pydantic
* SQLAlchemy

### Artificial Intelligence

* IBM Granite
* IBM watsonx.ai
* Machine learning models
* Statistical anomaly detection
* Risk analysis

### Machine Learning and Analytics

* Linear Regression
* EWMA
* Z-score analysis
* CUSUM
* Isolation Forest

### Frontend

* HTML
* CSS
* JavaScript
* Interactive dashboard
* WebSocket-based updates

### Data and Storage

* JSON
* CSV
* Excel
* Database integration
* Historical and simulated data

---

## 📂 Project Structure

```text
smart-industrial-pollution-monitoring/
│
├── agents/
│   ├── data_quality_agent.py
│   ├── root_cause_agent.py
│   └── alert_agent.py
│
├── ai/
│   └── granite_client.py
│
├── api/
│   └── API routes and endpoints
│
├── app/
│   ├── config.py
│   └── models.py
│
├── dashboard/
│   └── index.html
│
├── data/
│   └── regulatory_thresholds.json
│
├── database/
│   └── Database models and operations
│
├── detection/
│   ├── threshold_engine.py
│   └── anomaly_engine.py
│
├── orchestration/
│   └── orchestrator.py
│
├── prediction/
│   └── prediction_engine.py
│
├── risk/
│   └── risk_engine.py
│
├── simulator/
│   └── scenarios.py
│
├── tests/
│   ├── test_pipeline.py
│   └── test_pure_logic.py
│
├── utils/
│   └── Utility modules
│
├── .env.example
├── requirements.txt
├── run.py
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/KrishTandel16/smart-industrial-pollution-monitoring.git
```

```bash
cd smart-industrial-pollution-monitoring
```

### 2. Create a Virtual Environment

#### Windows

```powershell
python -m venv .venv
```

```powershell
.venv\Scripts\Activate.ps1
```

#### Linux/macOS

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file from `.env.example`.

#### Windows

```powershell
copy .env.example .env
```

#### Linux/macOS

```bash
cp .env.example .env
```

Add IBM watsonx.ai credentials if IBM Granite features are required.

> The monitoring system can continue working without Granite. AI explanations may be unavailable, but deterministic monitoring and risk analysis can continue.

---

## ▶️ Run the Application

Start the server:

```bash
python run.py
```

### Dashboard

```text
http://localhost:8000/dashboard
```

### API Documentation

```text
http://localhost:8000/docs
```

### Health Check

```text
http://localhost:8000/health
```

---

## 🧪 Run Demo Mode

Run the project with a pre-injected critical pollution event:

```bash
python run.py --demo
```

Demo mode helps demonstrate:

* Pollution spikes
* Anomaly detection
* Risk classification
* Alert generation
* Incident analysis
* Dashboard updates

---

## ✅ Run Tests

Run scenario tests:

```bash
python run.py --test
```

Run the complete test suite:

```bash
pytest tests/ -v
```

Run pure-logic tests:

```bash
python tests/test_pure_logic.py
```

---

## 🔌 API Endpoints

| Method | Endpoint                 | Description                          |
| ------ | ------------------------ | ------------------------------------ |
| GET    | `/health`                | System health and Granite status     |
| GET    | `/industries`            | List all industrial units            |
| GET    | `/industries/{id}`       | Detailed industrial unit information |
| GET    | `/sensors`               | Sensor readings and reliability      |
| GET    | `/pollution/current`     | Latest pollution readings            |
| GET    | `/pollution/history`     | Historical pollution data            |
| GET    | `/incidents`             | Active and historical incidents      |
| GET    | `/alerts`                | Alerts with filtering                |
| GET    | `/risk/{unit_id}`        | Risk score and contributing factors  |
| GET    | `/predictions/{unit_id}` | Pollution predictions                |
| GET    | `/data-sources`          | Registered data sources              |
| POST   | `/sensor-data`           | Submit sensor readings               |
| POST   | `/simulate-event`        | Inject a simulated pollution event   |
| POST   | `/analyze`               | Run one-shot pollution analysis      |
| POST   | `/monitor`               | Trigger a monitoring cycle           |
| POST   | `/alerts/test`           | Test alert pipeline                  |
| POST   | `/assistant/query`       | Ask a natural-language AI question   |
| WS     | `/ws/alerts`             | Real-time alert stream               |

---

## 🧭 Supported Industrial Zones

The project is designed for configurable industrial zones, including:

* Vapi
* Ankleshwar
* Vatva
* Other industrial areas through configuration

---

## 🧾 Data Classification

Every pollution record is classified using a source tag.

| Tag          | Meaning                   |
| ------------ | ------------------------- |
| `LIVE`       | Real sensor data          |
| `HISTORICAL` | Historical dataset        |
| `SIMULATED`  | Generated demo data       |
| `PREDICTED`  | Machine learning forecast |

The system follows two important principles:

* Simulated data is never presented as live data.
* Predictions are never presented as actual measurements.

---

## 🛡️ Safety and Responsible AI

This system is designed as a decision-support and monitoring platform.

The system may:

* Detect abnormal pollution behavior
* Generate alerts
* Increase monitoring frequency
* Generate predictions
* Recommend investigation
* Escalate incidents
* Generate explanations

The system must not:

* Shut down factories automatically
* Impose legal penalties
* Make irreversible decisions
* Fabricate regulatory findings
* Bypass authentication
* Claim a confirmed legal violation without official verification

### Regulatory Disclaimer

Regulatory thresholds are reference values only.

The system reports:

> **Potential Violation Detected**

It does not automatically claim:

> **Confirmed Legal Violation**

Official regulatory notifications and authorized inspections must be used for legal confirmation.

---

## 🧠 Why IBM Granite?

IBM Granite adds a natural-language intelligence layer to the monitoring system.

It can help environmental teams understand:

* Why a pollution event may have occurred
* Which factors contributed to the risk score
* What the monitoring system detected
* What action should be considered
* How to summarize an incident
* How to ask questions using natural language

### Example Questions

```text
Why is Industrial Unit 12 marked as high risk?
```

```text
Explain the pollution spike detected in Ankleshwar.
```

```text
What are the main contributing factors to this incident?
```

```text
Generate a short environmental incident report.
```

---

## 📈 Example Monitoring Scenario

```text
Sensor detects sudden increase in PM2.5
              ↓
Data quality agent validates the reading
              ↓
Threshold engine checks regulatory limits
              ↓
Anomaly engine detects unusual behavior
              ↓
Prediction engine estimates future trend
              ↓
Risk engine calculates score: 86/100
              ↓
System classifies event as CRITICAL
              ↓
Alert agent sends notification
              ↓
IBM Granite generates incident explanation
              ↓
Dashboard displays incident and recommended action
```

---

## 🎯 Use Cases

* Industrial pollution monitoring
* Environmental sustainability
* Smart city monitoring
* Industrial safety
* Pollution early warning
* Regulatory inspection support
* Environmental risk analysis
* Pollution trend forecasting
* Chemical industry monitoring
* AI-powered incident reporting

---

## 🔮 Future Enhancements

* Real IoT sensor integration
* Live air-quality APIs
* Water-quality sensor integration
* Satellite pollution data
* GIS-based pollution heatmaps
* SMS notifications
* WhatsApp alerts
* Mobile application
* Advanced deep learning models
* Multi-language AI assistant
* Government dashboard integration
* Automated PDF incident reports
* Explainable AI visualizations
* Digital twin for industrial zones

---

## 🏆 Project Highlights

* Agentic monitoring workflow
* Real-time pollution dashboard
* Configurable industrial zones
* Multi-source data ingestion
* Data quality and sensor reliability
* Statistical and ML anomaly detection
* Predictive pollution analysis
* Deterministic risk scoring
* IBM Granite explanations
* Real-time alert pipeline
* Simulation mode for demonstrations
* Safety-aware AI design
* API documentation with FastAPI
* Testable modular architecture

---

## 👥 Target Users

* Environmental monitoring teams
* Industrial safety officers
* Pollution control authorities
* Factory management
* Smart city teams
* Researchers
* Environmental consultants
* Government inspection teams

---



## 🌱 Project Vision

Our vision is to build a reliable, explainable, and scalable environmental intelligence platform that helps industrial regions detect pollution risks earlier.

By combining monitoring systems, machine learning, and IBM Granite, this project aims to support:

* Faster environmental awareness
* Better incident investigation
* Predictive pollution monitoring
* Transparent AI explanations
* Responsible industrial operations
* Sustainable industrial development

---

## 📜 License

This project is developed for educational, research, hackathon, and demonstration purposes.

---

## ⭐ Support the Project

If you find this project useful:

* Star the repository
* Report issues
* Suggest improvements
* Contribute new detection models
* Add new data sources
* Improve the dashboard
* Help build smarter environmental monitoring systems

---

<p align="center">

### Built for a cleaner, safer, and smarter industrial future 🌍

</p>
