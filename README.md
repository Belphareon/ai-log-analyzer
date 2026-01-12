# AI Log Analyzer

**Intelligent automated analysis of Kubernetes application errors with AI recommendations**

AI Log Analyzer detekuje error patterns, analyzuje root causes a generuje AI doporučení pro opravu. Nahrazuje manuální hodinový debugging automatickou analýzou v minutách.

---

## 🚀 Current Phase: Phase 5B (INIT Baseline Collection)

**Version:** 0.6.0  
**Last Update:** 2026-01-12  
**Status:** 🔄 INIT Phase 3 Weeks in progress

### ✅ Completed Phases
- ✅ Phase 1-4: Docker, K8s, schema, deployments
- ✅ Data collection from Elasticsearch
- ✅ Workspace reorganization

### 🔄 Current Work (Phase 5B)
- 🔄 INIT Phase: Load 3 weeks baseline (1-21.12.2025)
- [ ] REGULAR Phase: Daily ingestion with peak detection
- [ ] Phase 6: Peak analysis + AI insights  
- [ ] Phase 7: Autonomous PR generation with GitHub Copilot

### 📋 Quick Links
- **Start Here:** [GETTING_STARTED.md](GETTING_STARTED.md) - Complete setup & execution
- **Today's Tasks:** [working_progress.md](working_progress.md) - Session log + checklist  
- **Quick Ref:** [CONTEXT_RETRIEVAL_PROTOCOL.md](CONTEXT_RETRIEVAL_PROTOCOL.md) - DB, scripts, quick commands
- **Scripts:** [scripts/INDEX.md](scripts/INDEX.md) - All script documentation

---

## 🎯 Vision: AI-Driven Incident Response

### Current Workflow (Manual)
```
Error spike detected
    ↓
Hours of log analysis
    ↓
Root cause guessed
    ↓
Manual PR creation
    ↓
Code review cycle
    ↓
TOTAL: 3-5 hours per incident
```

### AI Log Analyzer Workflow (Automated)
```
Error spike detected (via peak detection)
    ↓
Automatic AI analysis (5 min)
    ↓
Root cause identified + recommendations
    ↓
GitHub Copilot generates PR automatically
    ↓
Code review + merge
    ↓
TOTAL: 30 min per incident (90% faster!)
```

**Key Components:**
1. **Peak Detection** - Identifies anomalies automatically
2. **Pattern Analysis** - Groups similar errors
3. **AI Analysis** - Uses Ollama for intelligent insights
4. **GitHub Copilot** - Generates PRs based on recommendations

---

## 🤖 AI Analysis (with Ollama)
  - Tracks errors across microservices
  - Same namespace/environment correlation
  - Case/Card ID chain tracking
  
- 📊 **Smart Sampling & Extrapolation**
  - Representative sampling from large datasets
  - Statistical extrapolation for total counts
  - Coverage tracking (target: 35%+)
  
- 💡 **Automated Daily Reports** - Markdown reports with:
  - Top 20 error patterns with estimated totals
  - Temporal clusters (error bursts)
  - Cross-app error propagation chains
  - Affected applications & namespaces
  - Actionable recommendations

### Phase 2: AI Agent & Self-Learning (✅ Code Complete)

- 🤖 **LLM Integration** - AI-powered root cause analysis
  - Ollama support for local LLM
  - Mock LLM for testing
  - Context-aware analysis
  
- 🗄️ **PostgreSQL Database** - Pattern storage & history
  - Finding, Pattern, Feedback models
  - Analysis history tracking
  - EWMA baselines for anomaly detection
  
- 🌐 **REST API** - FastAPI endpoints
  - `/analyze` - Analyze error logs
  - `/feedback` - Submit feedback for learning
  - `/patterns` - Query known patterns
  - `/history` - Analysis history
  - `/health` - Health check
  
- 🧠 **Self-Learning** - Continuous improvement
  - Feedback processing from operators
  - Pattern confidence adjustment
  - Learning from historical data

### Phase 3: Production Deployment (📋 Planned)

- ☸️ Kubernetes deployment with Helm
- 📊 Grafana dashboards & metrics
- 🔔 Automated alerting & notifications
- ⚡ Real-time analysis (15-min intervals)
- 🧪 A/B testing framework

---

## 📊 Real-World Results

**Production Data (Nov 4-10, 2025):**

| Metric | Value |
|--------|-------|
| **Total Errors Analyzed** | ~600,000 |
| **Sample Size** | ~210,000 (35% coverage) |
| **Daily Reports Generated** | 7 reports |
| **Unique Patterns Detected** | 65+ patterns |
| **Top Pattern** | "Card {ID} not found" (~12K occurrences) |
| **Temporal Clusters Found** | 15+ error bursts |
| **Processing Time** | ~30 seconds per 30K errors |

**Key Insights:**
- ✅ Reduced manual log analysis from **hours to minutes**
- ✅ Identified **cascading failures** across 3-4 microservices
- ✅ Detected **error bursts** correlating with deployments
- ✅ Tracked **Case/Card IDs** through entire error chains
- ✅ **35% sample coverage** sufficient for major pattern detection

**Example Pattern Detection:**
```
Original errors (different):
  - "Card 12345 not found, card states will not be updated"
  - "Card 67890 not found, card states will not be updated"  
  - "Card abc-def not found, card states will not be updated"

Normalized pattern (same):
  - "Card {ID} not found, card states will not be updated"
  
Result: Clustered ~12,000 similar errors into 1 pattern
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Elasticsearch                           │
│           (Kubernetes logs - ERROR level)                   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ fetch_errors.py / fetch_errors_smart.py
                     ▼
         ┌─────────────────────────┐
         │   Daily Error Sample    │
         │   (JSON with metadata)  │
         └───────────┬─────────────┘
                     │
                     │ analyze_daily.py
                     ▼
         ┌─────────────────────────┐
         │  Pattern Detector       │
         │  - ML Clustering        │
         │  - Temporal Analysis    │
         │  - Cross-App Correlation│
         └───────────┬─────────────┘
                     │
                     ▼
         ┌─────────────────────────┐
         │  Markdown Report        │
         │  - Top Patterns         │
         │  - Error Bursts         │
         │  - Related Errors       │
         └─────────────────────────┘
```

**Data Flow:**
1. **Fetch** - Stáhnutí error samplu z Elasticsearch za období (den/hodina)
2. **Cluster** - ML pattern detection seskupí podobné errory
3. **Analyze** - Temporal clustering, cross-app correlation, case tracking
4. **Report** - Generování markdown reportu s insights
5. **Learn** (future) - Feedback loop pro zlepšování detekce

## Quick Start

### Prerequisites

- Python 3.11+
- Access to Elasticsearch (logs)
- ~500MB RAM for pattern analysis

**For full setup including Phase 2 (API & Database), see [DEPLOYMENT.md](DEPLOYMENT.md)**

### Installation - Phase 1 Only (Standalone Scripts)

```bash
# Clone repository
cd ~/git/sas/ai-log-analyzer

# Install minimal dependencies for Phase 1
pip3 install --user elasticsearch httpx

# Verify scripts
ls -l *.py
```

**Note:** Phase 1 scripts (`fetch_errors.py`, `analyze_daily.py`) work standalone without database or API setup!

### Fetch Errors from Elasticsearch

```bash
# Fetch errors for specific day
python3 fetch_errors.py \
  --from "2025-11-10T00:00:00" \
  --to "2025-11-10T23:59:59" \
  --max-sample 50000 \
  --output /tmp/daily_2025-11-10.json

# Output: JSON with errors, total count, coverage %
```

### Analyze and Generate Report

```bash
# Analyze daily errors
python3 analyze_daily.py \
  --input /tmp/daily_2025-11-10.json \
  --output /tmp/report_2025-11-10.md

# View report
less /tmp/report_2025-11-10.md
```

### Example Report Output

```markdown
# Daily Error Report

**Period:** 2025-11-10 00:00:00 → 2025-11-10 23:59:59
**Total Errors:** 98,661
**Sample Size:** 30,000 (30.4% coverage)
**Unique Patterns Found:** 65

---

## Top 20 Error Patterns

### 1. Card {ID} not found, card states will not be updated

**Estimated Total:** ~12,450 occurrences
**Sample Count:** 3,782
**Error Code:** `404`
**Affected Apps:** bl-pcb-v1-processing
**Namespaces:**
- `pcb-uat-01-app`: ~8,234
- `pcb-sit-01-app`: ~4,216

---

## ⏰ Temporal Clusters - Error Bursts

### Cluster 1: 2025-11-10T05:00:01

**Burst Size:** ~45,123 errors (sample: 13,700)
**Affected Apps (3):** bl-pcb-v1-processing, bl-pcb-batch-processor-v1, bl-pcb-billing-v1
**Namespaces:**
- `pcb-uat-01-app`: ~31,250
- `pcb-sit-01-app`: ~13,873

---

## 🔄 Cross-App Error Propagation

### Case 12345 @ `pcb-uat-01-app`

**Total Errors:** ~234
**Affected Apps (4):** bl-pcb-v1, bl-pcb-billing-v1, bl-pcb-notification-v1, ...

**Error Chain:**
1. `10:23:45` [bl-pcb-v1] `Case 12345 validation failed...`
2. `10:23:46` [bl-pcb-billing-v1] `Billing error for case 12345...`
3. `10:23:47` [bl-pcb-notification-v1] `Failed to send notification...`
```

## Components

### Phase 1: Data Collection & Analysis (✅ Production Ready)

- **fetch_errors.py** - Fetch errors from Elasticsearch with sampling
- **fetch_errors_smart.py** - Smart fetch with auto-calculated sample for target coverage
- **analyze_daily.py** - ML pattern detection and report generation
- **refetch_low_coverage.py** - Re-fetch days with insufficient coverage
- **app/services/pattern_detector.py** - Core ML clustering engine

### Phase 2: AI Agent & Self-Learning (✅ Code Complete)

- **app/api/** - FastAPI REST endpoints
  - `analyze.py` - Analysis endpoint
  - `feedback.py` - Feedback submission
  - `patterns.py` - Pattern queries
  - `health.py` - Health checks
- **app/models/** - SQLAlchemy database models
  - `finding.py`, `pattern.py`, `feedback.py`, `analysis_history.py`
- **app/services/analyzer.py** - LLM-based root cause analysis
- **app/services/learner.py** - Self-learning from feedback
- **app/services/ollama_service.py** - Ollama LLM integration
- **app/services/llm_mock.py** - Mock LLM for testing

### Phase 3: Production Deployment (📋 Planned)

- **k8s/** - Kubernetes manifests
- **Grafana dashboards** - Metrics & visualization
- **Prometheus metrics** - Monitoring
- **CI/CD pipelines** - Automated deployment

## Tech Stack

**Core:**
- Python 3.11+ (3.12 compatible)
- FastAPI 0.121+ (async REST API)
- SQLAlchemy 2.0+ (async ORM)
- PostgreSQL 14+ (data persistence)
- Alembic 1.12+ (database migrations)

**ML & Analysis:**
- Custom pattern detection (similarity-based clustering)
- Ollama (local LLM for root cause analysis)
- EWMA (Exponentially Weighted Moving Average for baselines)

**Infrastructure:**
- Elasticsearch 8.x (log source)
- Docker/Podman (containerization)
- Kubernetes (orchestration)
- Redis 7+ (caching - future)

## Project Structure

```
ai-log-analyzer/
├── app/
│   ├── api/              # ✅ FastAPI endpoints
│   │   ├── analyze.py
│   │   ├── feedback.py
│   │   ├── patterns.py
│   │   └── health.py
│   ├── core/             # ✅ Core configuration
│   │   ├── config.py
│   │   ├── database.py
│   │   └── logging.py
│   ├── models/           # ✅ SQLAlchemy models
│   │   ├── finding.py
│   │   ├── pattern.py
│   │   ├── feedback.py
│   │   └── analysis_history.py
│   ├── services/         # ✅ Business logic
│   │   ├── pattern_detector.py   # ML clustering engine
│   │   ├── analyzer.py           # LLM analysis
│   │   ├── learner.py            # Self-learning
│   │   ├── ollama_service.py     # Ollama integration
│   │   ├── llm_mock.py           # Mock LLM
│   │   └── elasticsearch.py      # ES client
│   ├── schemas/          # ✅ Pydantic schemas
│   └── utils/            # Helpers
├── alembic/              # ✅ Database migrations
├── tests/                # Unit tests
├── k8s/                  # Kubernetes manifests
├── analyze_daily.py      # ✅ Daily analysis script
├── fetch_errors.py       # ✅ ES error fetcher
├── fetch_errors_smart.py # ✅ Smart fetch with coverage
├── refetch_low_coverage.py # ✅ Re-fetch helper
├── DEPLOYMENT.md         # ✅ Deployment guide
├── README_SCRIPTS.md     # ✅ Script documentation
├── PROJECT_STATUS.md     # ✅ Current status
├── TODO_UNIFIED.md       # Development roadmap
├── docker-compose.yml    # ✅ Local dev environment
├── Dockerfile            # Container image
├── pyproject.toml        # ✅ Dependencies
└── requirements.txt      # ✅ Pip dependencies
```

## Documentation

- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete deployment guide (installation, setup, testing)
- **[README_SCRIPTS.md](README_SCRIPTS.md)** - Detailed script usage and examples
- **[PROJECT_STATUS.md](PROJECT_STATUS.md)** - Current development status
- **[TODO_UNIFIED.md](TODO_UNIFIED.md)** - Development roadmap
- **[COMPLETED_LOG.md](COMPLETED_LOG.md)** - Completed tasks log

## Development Status

**Phase 1: Data Collection & ML Training** ✅ **COMPLETE** (Weeks 1-6)
- ✅ Elasticsearch integration
- ✅ Pattern detection with ML clustering  
- ✅ Temporal analysis (15-min windows)
- ✅ Cross-app correlation
- ✅ Daily report generation
- ✅ Coverage tracking and re-fetch tools
- ✅ ~600K errors analyzed (Nov 4-10, 2025)

**Phase 2: AI Agent & Self-Learning** ✅ **CODE COMPLETE** (Week 7)
- ✅ LLM integration (Ollama + Mock)
- ✅ Root cause analysis service
- ✅ PostgreSQL schema & models (4 models, 3 migrations)
- ✅ Feedback loop for learning
- ✅ REST API (5 endpoints: analyze, feedback, patterns, history, health)

**Phase 3: Orchestration & Automation** ✅ **COMPLETE** (Week 8)
- ✅ Workspace reorganization (5 script folders: core/, fetch/, test/, setup/, analysis/)
- ✅ Orchestration tool (`analyze_period.py` - combines all steps)
- ✅ Database integration (Baseline statistics calculated)
- ✅ EWMA anomaly detection (Configured with 2.0σ threshold)
- ✅ Baseline data: 2,608 records (14-day history, 15-min windows)
- ✅ Script consolidation (removed duplicates, organized by function)

**Phase 4: Kubernetes Deployment Preparation** ✅ **COMPLETE** (Week 9)
- ✅ K8s manifests v2.0 (6 YAML files: namespace, configmap, secret, service, deployment, ingress)
- ✅ Removed Ollama deployment (optional for Phase 4, heavy resource requirement)
- ✅ DEPLOYMENT.md - Comprehensive guide (430+ lines)
- ✅ HARBOR_DEPLOYMENT_GUIDE.md - Step-by-step K8s deployment (450+ lines)
- ✅ k8s-manifests-v2/README.md - Manifest documentation
- ✅ Database schema ready (ailog_peak.peak_statistics)
- ✅ Baseline data loaded (2608 records for anomaly detection)
- ⏳ Docker image build (Docker Hub rate limit: waiting for reset or token auth)
- ⏳ Harbor push (after image build)
- ⏳ ArgoCD deployment (after git commit)

**Phase 5: Teams Integration & Autonomous Alerting** �� **IN PROGRESS**
- [ ] Teams webhook configuration
- [ ] Alert message formatting
- [ ] Integration in analyze_period.py
- [ ] Autonomous peak detection alerts
- [ ] Feedback from Teams to database

**Phase 6: Autonomous K8s Deployment & Monitoring** 🔄 **PLANNED**
- [ ] CronJob for 15-min baseline updates
- [ ] Prometheus metrics export
- [ ] Grafana dashboards
- [ ] Alerting rules (Kubernetes events)
- [ ] Auto-scaling based on load

**Timeline:**
- Phase 4 Docker build: ~20-30 min (after rate limit reset)
- Phase 4 Deployment: ~5-10 min (via ArgoCD)
- Phase 5 Teams: 2-3 days
- Phase 6 Monitoring: 3-5 days

**Status Tracking:** See [working_progress.md](working_progress.md) for daily session logs

## Getting Started

**For Quick Analysis (Phase 1):**
```bash
# 5-minute setup - no database needed
python3 fetch_errors.py --from "2025-11-12T00:00:00" --to "2025-11-12T23:59:59" --output /tmp/errors.json
python3 analyze_daily.py --input /tmp/errors.json --output /tmp/report.md
```

**For Full Setup (Phase 2):**
See [DEPLOYMENT.md](DEPLOYMENT.md) for complete installation guide.

---

## Contributing

Internal KB project. For questions contact:
- Jiri Vsetecka <jiri_vsetecka@kb.cz>

## License

Internal KB use only

## Advanced Usage

### Batch Analysis for Multiple Days

```bash
# Analyze week of data
for day in {04..10}; do
  python3 analyze_daily.py \
    --input /tmp/daily_2025-11-${day}.json \
    --output /tmp/report_2025-11-${day}.md
done
```

### Re-fetch Low Coverage Days

```bash
# Check coverage and re-fetch if needed
python3 refetch_low_coverage.py --target-coverage 75

# Auto re-fetch all days below 75%
python3 refetch_low_coverage.py --target-coverage 75 --auto
```

### Custom Analysis

```python
from app.services.pattern_detector import pattern_detector

# Load your errors
errors = [...]  # List of error dicts

# Cluster by pattern
clusters = pattern_detector.cluster_errors(errors)

# Analyze specific cluster
for fingerprint, error_list in clusters.items():
    print(f"Pattern: {fingerprint}")
    print(f"Count: {len(error_list)}")
```

## Understanding the Output

### Pattern Detection

Patterns jsou normalizované verze error zpráv:
- `Card 12345 not found` → `Card {ID} not found`
- `Timeout after 30000ms` → `Timeout after {N}ms`

Clustering seskupí podobné errory do patterns pomocí:
- Token similarity (upravené Levenshtein distance)
- Numeric/ID placeholder detection
- Error code extraction

### Temporal Clusters

Temporal clustering detekuje "error bursts":
- Errors v 15-minutovém okně
- Minimum 5 errorů pro cluster
- Ukazuje cascading failures nebo deployment issues

### Cross-App Correlation

Sleduje jak se error šíří mezi aplikacemi:
- Stejné Case ID v různých apps
- Stejný namespace (environment)
- Časová posloupnost (error chain)

## Troubleshooting

### "No module named 'elasticsearch'"

```bash
pip3 install --user elasticsearch httpx
```

### Elasticsearch connection failed

Zkontroluj credentials a přístup:
```bash
curl -u "$ES_USER:$ES_PASS" "$ES_HOST/_cat/indices"
```

### Low coverage (<30%)

Zvyš sample size:
```bash
python3 fetch_errors.py --max-sample 100000 ...
```

### Pattern detector too slow

Sniž sample size nebo zvyš similarity threshold:
```python
# In pattern_detector.py
SIMILARITY_THRESHOLD = 0.90  # Stricter matching = fewer patterns
```

## Configuration

### Elasticsearch Connection

Set environment variables or configure in scripts:

```bash
export ES_HOST="https://logs.domena.cz"
export ES_USER="elasticsearch_user"
export ES_PASS="elasticsearch_password"
```

### Coverage Settings

```bash
# Fetch with target coverage
python3 fetch_errors_smart.py \
  --from "2025-11-10T00:00:00" \
  --to "2025-11-10T23:59:59" \
  --coverage 75 \
  --max-sample 100000 \
  --output /tmp/daily.json
```

**Coverage explained:**
- `coverage = (sample_size / total_errors) * 100`
- Higher coverage = more representative sample
- 35% coverage sufficient for major patterns
- 75% coverage recommended for comprehensive analysis

### Pattern Detection Parameters

In `app/services/pattern_detector.py`:

```python
# Similarity threshold for clustering (0.0 - 1.0)
SIMILARITY_THRESHOLD = 0.85

# Minimum occurrences to include pattern in report
MIN_PATTERN_COUNT = 3  # daily
MIN_PATTERN_COUNT = 10  # weekly

# Temporal clustering window
TEMPORAL_WINDOW_MINUTES = 15
```

## Development Roadmap

- [x] Project setup
- [ ] Core analyzer with Ollama
- [ ] PostgreSQL schema and models
- [ ] REST API endpoints
- [ ] Self-learning module
- [ ] Elasticsearch integration
- [ ] Kubernetes deployment
- [ ] AWX integration

## License

Internal KB use only
