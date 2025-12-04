# 🎯 MASTER - AI Log Analyzer Project Guide

**Poslední aktualizace:** 2025-12-02 UTC
**Typ:** Project Orientation Guide

---

## ⚡ QUICK START - Project Overview

### 📌 What is This Project?

**AI Log Analyzer** = Automated root cause analysis for application errors
- **Input:** Application error logs from Elasticsearch
- **Processing:** ML-based pattern detection + trace analysis
- **Output:** Actionable root causes with recommendations
- **Architecture:** Python backend + PostgreSQL DB + FastAPI REST API

### 🚀 ORCHESTRATION TOOL (NEW - USE THIS)

**PRIMARY WAY TO RUN ANALYSIS:** Use `analyze_period.py` - Complete A-Z pipeline in one command!

```bash
python3 analyze_period.py --from "2025-12-02T07:30:00Z" --to "2025-12-02T10:30:00Z" --output result.json
```

→ See `HOW_TO_USE.md` for complete examples and usage patterns.

---

### 🎯 Key Goals

1. **Automated Error Analysis** - Detect root causes without manual intervention
2. **Known Issues Database** - Track recurring problems and solutions
3. **Intelligent Alerting** - Move beyond threshold-based alerts
4. **Continuous Learning** - Improve pattern recognition over time

---

## 📚 Documentation Map

### Start Here
- **ORCHESTRATION_PROGRESS.md** - Main project which conains orchestration above whole project, needs improvement
- **README.md** - Comprehensive project documentation, architecture, features
- **HOW_TO_USE.md** - Practical quick-start guide, common commands, examples

### For Implementation
- **README_SCRIPTS.md** - Detailed reference for all Python scripts
- **DEPLOYMENT.md** - Installation, configuration, K8s deployment
- **KNOWN_ISSUES_DESIGN.md** - Database schema and known issues registry

### For Development
- **working_progress.md** - Current session tracking and ongoing work
- **COMPLETED_LOG.md** - Historical record of completed tasks and milestones
- **todo_final.md** - Master TODO list for remaining work

---

## 🏗️ Project Structure

### Core Scripts (Production)
- **fetch_*.py** - Data collection from Elasticsearch
- **trace_extractor.py** - Extract traces and correlate errors
- **intelligent_analysis.py** - ML-based pattern recognition
- **analyze_daily.py** - Daily analysis pipeline orchestrator
- **trace_report_detailed.py** - Generate markdown reports

### Test Scripts (Validation)
- **test_*.py** - Integration and unit tests for validation

### Data (Working Directory)
- **data/batches/** - Raw error log batches from Elasticsearch
- **data/known_issues_sample.json** - Sample known issues registry
- **reports/** - Generated analysis reports

### Configuration
- **.env** - Elasticsearch and database credentials
- **requirements.txt** - Python dependencies
- **docker-compose.yml** - Local development environment
- **Dockerfile** - Application container

### FastAPI Backend (Phase 2)
- **app/api/** - REST endpoints
- **app/models/** - SQLAlchemy database models
- **app/services/** - Business logic services
- **app/core/** - Configuration and middleware

---

## 🔄 Data Pipeline

```
Raw Logs (Elasticsearch)
    ↓
Fetch & Clean (fetch_*.py)
    ↓
Extract Patterns (trace_extractor.py)
    ↓
ML Analysis (intelligent_analysis.py)
    ↓
Generate Reports (trace_report_detailed.py)
    ↓
Store Findings (PostgreSQL / JSON)
    ↓
Actionable Insights
```

---

## 📊 Project Phases

### Phase 1: Foundation ✅ COMPLETE
- Error collection infrastructure
- ML pattern detection
- Report generation

### Phase 2: API & Database ✅ COMPLETE
- FastAPI REST endpoints
- PostgreSQL integration
- Feedback loop system

### Phase 3: Testing & Documentation ✅ COMPLETE (98%)
- End-to-end test suite
- Comprehensive documentation
- Production readiness review

### Phase 4: Autonomous Mode 📅 IN PROGRESS
  - ✅ Orchestration tool complete (analyze_period.py)
  - Known issues database integration (next)
  - Teams/Slack alerts (next)
- Autonomous analysis execution
- Known issues database integration
- Teams/Slack alerts
- Continuous learning improvements

---

## 🛠️ Technology Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12+ |
| Data Source | Elasticsearch 8.x |
| Database | PostgreSQL 12+ |
| API Framework | FastAPI |
| ORM | SQLAlchemy 2.0 |
| ML/Analytics | Pattern matching, clustering |
| Async | httpx, asyncpg |
| Deployment | Docker + Kubernetes |

---

## 📋 Common Tasks

### Run Daily Analysis
See: `HOW_TO_USE.md` - Daily Analysis section

### Fetch Error Data
See: `README_SCRIPTS.md` - Fetching section

### Deploy to Kubernetes
See: `DEPLOYMENT.md` - K8s Deployment section

### Understand System Design
See: `README.md` - Architecture & Design section

### Check Progress
See: `working_progress.md` - Current session status

---

## 🚀 Quick Navigation

**First Time Here?**
1. Read `README.md` (5 min)
2. Check `HOW_TO_USE.md` (5 min)
3. Review `working_progress.md` (current status)

**Need to Deploy?**
→ `DEPLOYMENT.md`

**Need to Run Analysis?**
→ `HOW_TO_USE.md`

**Need to Understand a Script?**
→ `README_SCRIPTS.md`

**Need to Know What's Planned?**
→ `todo_final.md`

---

## 📁 File Reference

| File | Purpose | Audience |
|------|---------|----------|
| README.md | Complete documentation | Everyone |
| HOW_TO_USE.md | Quick-start guide | Users/Operators |
| README_SCRIPTS.md | Script reference | Developers |
| DEPLOYMENT.md | Setup & deployment | DevOps/Admins |
| KNOWN_ISSUES_DESIGN.md | DB schema & design | Developers |
| working_progress.md | Current work | Team |
| COMPLETED_LOG.md | History | Project tracking |
| todo_final.md | Remaining work | Project leads |
| MASTER.md | This file | Navigation |

---
---

## 📁 DIRECTORY STRUCTURE

```
ai-log-analyzer/
├── 📋 MASTER.md                    ← YOU ARE HERE (orientation guide)
├── 📋 README.md                    (main documentation)
├── 📋 HOW_TO_USE.md                (operational manual)
├── 📋 working_progress.md          (today's session)
├── 📋 COMPLETED_LOG.md             (task history)
├── 📋 todo_final.md                (TODO items for Phase 4)
├── 📋 KNOWN_ISSUES_DESIGN.md       (registry design)
├── 📋 DEPLOYMENT.md                (K8s deployment)
├── 📋 README_SCRIPTS.md            (script reference)
│
├── .archive/                       (old documentation)
│   ├── SESSION_PROGRESS.md
│   ├── PROJECT_STATUS.md
│   ├── PHASE_3_SUMMARY.md
│   ├── REAL_DATA_TEST_PLAN.md
│   └── E2E_TEST_RESULTS.md
│
├── 🐍 Core Scripts:
│   ├── fetch_errors_smart.py       (smart ES fetch with sampling)
│   ├── simple_fetch.py             (basic ES fetch)
│   ├── fetch_today_batches.py      (daily batch collector)
│   ├── fetch_all_errors_paginated.py (paginated fetch - FIXED TODAY)
│   ├── trace_extractor.py          (extract traces + root causes)
│   ├── intelligent_analysis.py     (ML pattern recognition)
│   ├── analyze_daily.py            (daily pipeline orchestrator)
│   └── trace_report_detailed.py    (markdown report generation)
│
├── 🧪  Test Scripts:
│   ├── test_integration_pipeline.py
│   ├── test_pattern_detection.py
│   ├── test_temporal_clustering.py
│   └── test_cross_app.py
│
├── 📊 Data:
│   ├── data/batches/               (batch error data)
│   ├── data/known_issues_sample.json
│   ├── data_archive/               (historical backup)
│   └── reports/                    (generated reports)
│
├── 🔧 App (Phase 2 - FastAPI):
│   ├── app/api/                    (REST endpoints)
│   ├── app/models/                 (database models)
│   ├── app/services/               (business logic)
│   └── app/core/                   (config, middleware)
│
└── 📚 Configuration:
    ├── .env.example
    ├── requirements.txt
    ├── docker-compose.yml
    ├── Dockerfile
    └── alembic/                    (DB migrations)
```

---
###  Cluster Configuration by field "topic"

```
3100 Cluster:      "cluster-k8s_nprod_3100-in"
3095 Cluster:      "cluster-k8s_nprod_3095-in"

3100 conatins namespaces dev/fat: *dev-01-app, *fat-01-app
3100 conatins namespaces sit/uat: *sit-01-app, *uat-01-app

both clusters conains all applications with different namespace/env
```

## 🔗 External References

**Elasticsearch:** https://elasticsearch-test.kb.cz:9500
**Database:** P050TD01 (PostgreSQL)
**Deployment:** ArgoCD + K8s (nprod)

---

**Need Help?** Check the appropriate `.md` file above based on your task.

