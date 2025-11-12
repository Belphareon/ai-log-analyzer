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

## 🚀 PHASE 2: AI Agent & Self-Learning (NEXT)

**Priorita:** Vysoká
**Cíl:** Produkční AI agent pro real-time analýzu

### 2.1 Database Layer
- [ ] PostgreSQL schema design
  - [ ] Tabulka: analysis_history
  - [ ] Tabulka: learned_patterns
  - [ ] Tabulka: user_feedback
  - [ ] Tabulka: known_issues
- [ ] SQLAlchemy models
- [ ] Alembic migrations
- [ ] Init script pro DB setup

### 2.2 LLM Integration
- [ ] Ollama client wrapper
- [ ] Prompt templates pro root cause analysis
- [ ] Mock LLM pro testing (bez Ollama dependency)
- [ ] LLM response parser
- [ ] Context builder (error + deployment info)

### 2.3 REST API (FastAPI)
- [ ] Endpoint: POST /analyze - analyze specific error
- [ ] Endpoint: GET /patterns - list learned patterns
- [ ] Endpoint: POST /feedback - submit feedback
- [ ] Endpoint: GET /trends - weekly trends
- [ ] Endpoint: GET /health - health check
- [ ] API authentication (token-based)
- [ ] OpenAPI documentation

### 2.4 Self-Learning Module
- [ ] Feedback collector
- [ ] Pattern accuracy tracker
- [ ] Auto-ignore logic (repeated false positives)
- [ ] Confidence scoring
- [ ] Pattern update mechanism

### 2.5 Integration Testing
- [ ] Mock ES data generator
- [ ] API integration tests
- [ ] LLM mock responses
- [ ] End-to-end test scenario

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

## 📅 Timeline (Estimate)

### Week 1-2: Database & Core API
- PostgreSQL schema
- Basic CRUD operations
- FastAPI endpoints skeleton

### Week 3-4: LLM Integration
- Ollama setup
- Root cause analysis
- Prompt engineering

### Week 5-6: Self-Learning
- Feedback loop
- Pattern improvement
- Testing & validation

### Week 7-8: Production Prep
- K8s deployment
- Monitoring
- Documentation

---

## 🎯 Immediate Next Steps

1. **Database Schema Design** (2-3 hodiny)
   - Navrhnout ER diagram
   - Vytvořit SQLAlchemy models
   - Připravit init migrations

2. **FastAPI Skeleton** (2 hodiny)
   - Basic app structure
   - Health endpoint
   - Mock analyze endpoint

3. **LLM Mock** (1 hodina)
   - Pro testing bez Ollama
   - Stub responses

4. **Integration Test** (2 hodiny)
   - End-to-end test
   - Verify flow works

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

