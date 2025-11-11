# AI Log Analyzer

**Intelligent log analysis with self-learning AI for Kubernetes applications**

AI Log Analyzer automaticky detekuje error patterns, analyzuje jejich souvislosti a učí se z historických dat. Nahrazuje manuální procházení logů inteligentní analýzou založenou na ML pattern detection.

## Proč AI Log Analyzer?

**Problém:**
- 600K+ errorů týdně v Kubernetes clusteru
- Manuální analýza trvá hodiny
- Opakující se patterns nejsou automaticky detekovány
- Chybějící souvislosti mezi errory napříč aplikacemi

**Řešení:**
- ✅ Automatická detekce error patterns pomocí ML
- ✅ Temporal clustering - detekce error burstů v časových oknech
- ✅ Cross-app correlation - sledování chyb napříč aplikacemi
- ✅ Self-learning - zlepšování detekce na základě feedback
- ✅ Denní reporty s top issues a doporučeními

## Features

- 🤖 **Pattern Detection** - ML-based clustering podobných errorů
- ⏰ **Temporal Analysis** - Detekce error burstů v 15min oknech
- 🔄 **Cross-App Correlation** - Propojení errorů mezi aplikacemi na stejném env
- 📊 **Case/Card ID Tracking** - Sledování error chains pro konkrétní případy
- 🎯 **Smart Extrapolation** - Odhad celkového výskytu z reprezentativního vzorku
- 💡 **Daily Reports** - Markdown reporty s insights a trendy

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

### Installation

```bash
# Clone repository
cd ~/git/sas/ai-log-analyzer

# Install dependencies (optional - scripts work standalone)
pip3 install --user elasticsearch httpx

# Verify scripts
ls -l *.py
```

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

### Current (Data Collection & Analysis)

- **fetch_errors.py** - Fetch errors from Elasticsearch
- **fetch_errors_smart.py** - Smart fetch with auto-calculated sample for target coverage
- **analyze_daily.py** - ML pattern detection and report generation
- **refetch_low_coverage.py** - Re-fetch days with insufficient coverage
- **app/services/pattern_detector.py** - Core ML clustering engine

### Future (Production AI Agent)

- **API Server** (FastAPI) - REST endpoints for AWX integration
- **Analyzer** - LLM-based root cause analysis
- **Learner** - Self-learning from feedback
- **Context Provider** - Deployment correlation (ArgoCD)

## Tech Stack

- Python 3.11+
- FastAPI (async API)
- Ollama (local LLM)
- PostgreSQL (data persistence)
- SQLAlchemy (ORM)
- Kubernetes (deployment)

## Project Structure

```
ai-log-analyzer/
├── app/
│   ├── api/              # FastAPI endpoints (future)
│   ├── core/             # Core configuration
│   ├── models/           # SQLAlchemy models (future)
│   ├── services/
│   │   ├── pattern_detector.py   # ML clustering engine
│   │   ├── elasticsearch.py      # ES client
│   │   └── trend_analyzer.py     # Trend analysis
│   ├── schemas/          # Pydantic schemas
│   └── utils/            # Helpers
├── analyze_daily.py      # Daily error analysis script
├── fetch_errors.py       # ES error fetcher
├── fetch_errors_smart.py # Smart fetch with coverage
├── refetch_low_coverage.py # Re-fetch helper
├── README_SCRIPTS.md     # Detailed script documentation
├── k8s/                  # Kubernetes manifests (future)
├── tests/                # Unit tests
└── pyproject.toml        # Dependencies
```

## See Also

- **[README_SCRIPTS.md](README_SCRIPTS.md)** - Detailed script usage and examples
- **[TODO.md](TODO.md)** - Current development tasks
- **[TODO_FINAL.md](TODO_FINAL.md)** - Production roadmap

## Development Status

**Phase 1: Data Collection & ML Training** ✅ (Current)
- ✅ Elasticsearch integration
- ✅ Pattern detection with ML clustering
- ✅ Temporal analysis
- ✅ Cross-app correlation
- ✅ Daily report generation
- ✅ Coverage tracking and re-fetch tools

**Phase 2: AI Agent & Self-Learning** 🚧 (Next)
- [ ] LLM integration (Ollama)
- [ ] Root cause analysis
- [ ] PostgreSQL for pattern storage
- [ ] Feedback loop for learning
- [ ] REST API for AWX integration

**Phase 3: Production Deployment** 📋 (Future)
- [ ] Kubernetes deployment
- [ ] Real-time analysis (15-min intervals)
- [ ] Automated alerting
- [ ] Grafana dashboards
- [ ] A/B testing framework

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
