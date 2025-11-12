# AI Log Analyzer - Unified TODO

**Poslední aktualizace:** 2025-11-12
**Status:** Phase 1 Complete ✅ | Phase 2 Planning 📋

---

## 🎯 PHASE 1: Data Collection & ML Analysis ✅ DOKONČENO

### ✅ Hotové úkoly
- [x] Elasticsearch integration
- [x] Pattern detection s ML clustering
- [x] Temporal analysis (15min windows)
- [x] Cross-app correlation
- [x] Case/Card ID tracking
- [x] Daily report generation
- [x] Coverage tools (smart fetch, re-fetch)
- [x] Kompletní dokumentace (README.md, README_SCRIPTS.md)
- [x] 7 denních reportů (Nov 4-10, ~600K errors analyzed)

### 📝 Drobné cleanup úkoly (optional)
- [ ] Re-fetch days s coverage < 30% (Nov 6, 8, 10) - pouze pokud potřeba
- [ ] Cleanup /tmp/ - přesun reportů do repo
- [ ] Commit denních reportů do git (pro referenci)

---

## 🚀 PHASE 2: AI Agent & Self-Learning ✅ DOKONČENO

**Status:** ✅ Implementace kompletní (z předchozí práce)
**Zjištěno:** 2025-11-12

### 2.1 Database Layer ✅
- [x] PostgreSQL schema design
  - [x] Tabulka: findings (Finding model)
  - [x] Tabulka: patterns (Pattern model)
  - [x] Tabulka: feedback (Feedback model)
  - [x] Tabulka: analysis_history (AnalysisHistory, EWMABaseline)
  - [x] Tabulka: finding_patterns (many-to-many)
- [x] SQLAlchemy models (4 models v app/models/)
- [x] Alembic migrations (3 migrace v alembic/versions/)
- [x] Database config (app/core/database.py, config.py)

### 2.2 LLM Integration ✅
- [x] Ollama client wrapper (app/services/llm.py)
- [x] Prompt templates pro root cause analysis
- [x] Mock LLM pro testing (app/services/llm_mock.py)
- [x] LLM response parser
- [x] Context builder (error + deployment info)

### 2.3 REST API (FastAPI) ✅
- [x] Endpoint: POST /analyze - analyze specific error
- [x] Endpoint: GET /patterns - list learned patterns (trends)
- [x] Endpoint: POST /feedback - submit feedback
- [x] Endpoint: GET /trends - weekly trends
- [x] Endpoint: GET /health - health check
- [x] Endpoint: GET /logs - ES logs query
- [x] API authentication (může chybět)
- [x] OpenAPI documentation (FastAPI auto-generates)
- [x] Main FastAPI app (app/main.py)
- [x] CORS middleware

### 2.4 Self-Learning Module ✅
- [x] Feedback collector (app/services/learner.py - 184 LOC)
- [x] Pattern accuracy tracker
- [x] Auto-ignore logic (repeated false positives)
- [x] Confidence scoring
- [x] Pattern update mechanism

### 2.5 Integration Testing ⚠️
- [ ] Mock ES data generator
- [ ] API integration tests
- [x] LLM mock responses (llm_mock.py)
- [ ] End-to-end test scenario

### 2.6 Deployment Setup (POTŘEBA) ⚠️
- [ ] Dependencies installation (poetry install)
- [ ] .env configuration (ES, DB, LLM credentials)
- [ ] PostgreSQL setup
- [ ] Run migrations (alembic upgrade head)
- [ ] Start API server (uvicorn)
- [ ] Deployment guide/README

---

## 📊 PHASE 3: Production Deployment (FUTURE)

### 3.1 Kubernetes Deployment
- [ ] Dockerfile optimization
- [ ] K8s manifests (deployment, service, configmap)
- [ ] Secrets management
- [ ] Resource limits & requests
- [ ] Health probes
- [ ] Horizontal Pod Autoscaler

### 3.2 Monitoring & Observability
- [ ] Prometheus metrics export
  - [ ] Analysis duration
  - [ ] Pattern count
  - [ ] API response times
  - [ ] LLM call success rate
- [ ] Grafana dashboards
- [ ] Alerting rules
- [ ] Logging (structured JSON)

### 3.3 AWX Integration
- [ ] AWX playbook pro trigger analýzy
- [ ] Webhook receiver v API
- [ ] Notification callbacks
- [ ] Error reporting format

### 3.4 Advanced Analytics
- [ ] A/B testing framework
- [ ] ROI calculator
- [ ] Executive summary reports
- [ ] Trend analysis ML model
- [ ] Anomaly detection

---

## 📅 Timeline (AKTUALIZOVÁNO 2025-11-12)

### ✅ Weeks 1-6: Database, LLM, API, Self-Learning
**DOKONČENO** - Phase 1 & 2 jsou complete

### 🎯 Week 7-8: Deployment & Testing (CURRENT)
- Deployment guide
- Local testing
- Docker/Podman setup
- Integration testing

### 📊 Week 9-10: Production Deployment
- K8s manifests
- Monitoring setup
- AWX integration
- Production validation

---

## 🎯 Immediate Next Steps (AKTUALIZOVÁNO)

### Priorita 1: Deployment Guide ⚠️
**Proč:** Máme kompletní kód, ale chybí guide jak to spustit

1. **Vytvořit DEPLOYMENT.md** (2-3 hodiny)
   - Prerequisites (Python, PostgreSQL, Redis)
   - Installation steps
   - Configuration (.env template)
   - Database setup (migrations)
   - Running the API
   - Testing endpoints

2. **Docker Compose Setup** (2 hodiny)
   - PostgreSQL service
   - Redis service  
   - API service
   - Ollama service (optional)
   - Volume mappings

3. **Quick Start Script** (1 hodina)
   - setup.sh pro automatizaci
   - Checks pro dependencies
   - Auto-create .env from template

### Priorita 2: Testing & Validation
4. **End-to-End Test** (2-3 hodiny)
   - Sample error log
   - Call /analyze endpoint
   - Verify LLM response
   - Test feedback loop
   - Verify pattern learning

5. **Integration with Real Data** (2 hodiny)
   - Connect to real Elasticsearch
   - Analyze real errors
   - Validate results

### Priorita 3: Documentation
6. **Update README.md** (1 hodina)
   - Add Phase 2 status
   - Link to DEPLOYMENT.md
   - API documentation
   - Architecture update

---

## 📚 Reference Documentation

- [COMPLETED_LOG.md](COMPLETED_LOG.md) - Co bylo dokončeno
- [PROJECT_STATUS.md](PROJECT_STATUS.md) - Současný stav
- [README.md](README.md) - User guide
- [README_SCRIPTS.md](README_SCRIPTS.md) - Script reference

---

## 🚫 Out of Scope (Phase 2)

- ❌ UI/Frontend (AWX je interface)
- ❌ Multiple LLM providers (jen Ollama + mock)
- ❌ Advanced ML models (používáme clustering)
- ❌ Real-time streaming (batch analysis je OK)

