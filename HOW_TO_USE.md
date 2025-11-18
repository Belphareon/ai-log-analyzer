# AI Log Analyzer - Operational Manual

**Pro operátory a DevOps týmy**

---

## 📋 Quick Navigation

- **[Installation & Setup](#installation--setup)** - První spuštění
- **[Running the Pipeline](#running-the-pipeline)** - Jak spustit analýzu
- **[Understanding Output](#understanding-output)** - Čtení reportů
- **[Common Tasks](#common-tasks)** - Typické úkoly
- **[Troubleshooting](#troubleshooting)** - Řešení problémů
- **[Production Deployment](#production-deployment)** - Nasazení v K8s

---

## Installation & Setup

### Prerequisites

```bash
# Python 3.11+
python3 --version

# Dependencies
pip install -r requirements.txt

# Or with Poetry (recommended for development)
poetry install
```

### Configuration

```bash
# Copy template
cp .env.example .env

# Edit for your environment
nano .env
```

**Key variables:**
- `ES_HOST` - Elasticsearch host (default: localhost:9200)
- `ES_INDEX_PATTERN` - Log index pattern (e.g., cluster-app_pcb-*, cluster-app_pca-*)
- `POSTGRES_URL` - Database connection
- `OLLAMA_URL` - LLM service (optional)

---

## Running the Pipeline

### Step 1: Fetch Errors from Elasticsearch

#### Simple Fetch (for quick testing)

```bash
python3 simple_fetch.py \
  --from "2025-11-18T08:00:00" \
  --to "2025-11-18T12:00:00" \
  --max-sample 50000 \
  --output data/sample_errors.json
```

**Output:** `data/sample_errors.json` - JSON with error entries

**What it does:**
- Connects to Elasticsearch
- Fetches ERROR level logs in time range
- Samples up to `--max-sample` errors
- Includes: timestamp, app, namespace, message, trace_id

#### Smart Fetch (production)

```bash
python3 fetch_errors_smart.py \
  --from "2025-11-18T08:00:00" \
  --to "2025-11-18T12:00:00" \
  --target-coverage 35 \
  --output data/batch_errors.json
```

**Smart features:**
- Auto-calculates sampling based on error volume
- Target coverage % (default: 35% = 210K errors from 600K)
- Timezone-aware (converts local → UTC)
- Metadata: error stats, sampling ratio

### Step 2: Extract Trace-Based Root Causes

```bash
python3 trace_extractor.py \
  --input data/sample_errors.json \
  --output data/root_causes.json
```

**Input:** `data/sample_errors.json`
**Output:** `data/root_causes.json` - JSON with grouped traces & root causes

**What it extracts:**
- Groups errors by trace_id
- Finds root cause (first error in chain)
- Classifies by severity
- Identifies affected apps & namespaces

**Example output structure:**
```json
{
  "stats": {
    "total_errors": 3500,
    "unique_traces": 917,
    "root_causes": 126
  },
  "root_causes": [
    {
      "trace_id": "abc123...",
      "message": "Card 12345 not found",
      "app": "bl-pcb-v1",
      "error_count": 42,
      "first_seen": "2025-11-18T08:32:45",
      "last_seen": "2025-11-18T11:22:10"
    }
  ]
}
```

### Step 3: Generate Detailed Report

```bash
python3 trace_report_detailed.py \
  --input data/root_causes.json \
  --output data/analysis_report.md
```

**Input:** `data/root_causes.json`
**Output:** `data/analysis_report.md` - Markdown report

**Report includes:**
- 📊 Overview (error count, traces, root causes)
- 🏢 App Impact Distribution (which apps affected, roles)
- 🔴 Concrete Root Causes (top issues with specificity)
- ⚠️ Semi-Specific Issues (needs investigation)
- ❓ Generic Issues (insufficient info)
- 📋 Executive Summary (primary issue + action items)

---

## Understanding Output

### Report Structure

#### 🔴 CRITICAL Issues (Red)
- Top priority problems
- Affecting multiple apps
- Immediate action needed

**Example:**
```
🔴 CRITICAL (11.2%, 393 errors): bl-pcb-v1 Service Error
Context: External service call failed during card processing
Apps affected: bl-pcb-v1 (primary), bl-pcb-v1-processing (secondary)
```

#### 🟠 HIGH Issues (Orange)
- Significant impact
- Specific error type
- Should investigate

#### 🟡 MEDIUM Issues (Yellow)
- Moderate impact
- May be temporary
- Monitor trends

#### 🟢 LOW Issues (Green)
- Low frequency
- Known issues
- Can schedule fix

### Key Metrics

**Specificity Rates:**
- 🎯 **Concrete (57%)**: Actionable causes - HTTP status, service name, ID
- ⚠️ **Semi-Specific (30%)**: Exception type with context
- ❓ **Generic (13%)**: General error - needs investigation

---

## Common Tasks

### Task 1: Daily Analysis

```bash
# Run analysis for last 24 hours
python3 simple_fetch.py \
  --from "$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')" \
  --to "$(date -u '+%Y-%m-%dT%H:%M:%S')" \
  --output data/daily_errors.json

python3 trace_extractor.py \
  --input data/daily_errors.json \
  --output data/daily_causes.json

python3 trace_report_detailed.py \
  --input data/daily_causes.json \
  --output data/daily_report_$(date +%Y-%m-%d).md
```

**Output:** `data/daily_report_2025-11-18.md`

### Task 2: Real-time Monitoring

```bash
# Fetch last 30 minutes
python3 simple_fetch.py \
  --from "$(date -u -d '30 minutes ago' '+%Y-%m-%dT%H:%M:%S')" \
  --to "$(date -u '+%Y-%m-%dT%H:%M:%S')" \
  --output data/realtime_errors.json --max-sample 10000

# Quick analysis
python3 trace_extractor.py \
  --input data/realtime_errors.json \
  --output data/realtime_causes.json

python3 trace_report_detailed.py \
  --input data/realtime_causes.json \
  --output data/realtime_report.md
```

### Task 3: Investigate Specific App

```bash
# Fetch errors for specific app
python3 simple_fetch.py \
  --from "2025-11-18T08:00:00" \
  --to "2025-11-18T12:00:00" \
  --output data/sample.json

# Then examine
grep -i "bl-pcb-v1" data/sample.json | wc -l  # Count errors

# Extract causes for that batch
python3 trace_extractor.py \
  --input data/sample.json \
  --output data/causes.json

# View report
python3 trace_report_detailed.py \
  --input data/causes.json \
  --output data/report.md

cat data/report.md
```

---

## Troubleshooting

### Problem: "Connection refused" to Elasticsearch

**Solution:**
1. Check ES is running: `curl -u user:pass https://elasticsearch-test.kb.cz:9500`
2. Verify `ES_HOST` in `.env`
3. Check network connectivity: `ping elasticsearch-test.kb.cz`

### Problem: No errors found

**Possible causes:**
- Time range is incorrect (check timezone)
- Index pattern doesn't match (check `ES_INDEX_PATTERN`)
- No errors in that time period (check ES directly)

**Debug:**
```bash
# Check available indices
curl -s https://elasticsearch-test.kb.cz:9500/_cat/indices | grep cluster

# Check error count in time range
# (use Kibana or curator tool)
```

### Problem: Report is empty or generic

**Causes:**
- Error messages lack context
- Not enough data (< 100 errors)
- All errors are generic ("Error handler threw exception")

**Solution:**
- Ensure messages include IDs (card, case, service name)
- Collect more data (wider time range)
- Check with dev team on message format

### Problem: "Out of memory" or slow processing

**For large datasets:**
```bash
# Use smart fetch with lower coverage
python3 fetch_errors_smart.py \
  --from "..." \
  --to "..." \
  --target-coverage 10  # 10% = faster
  --output data/sample.json

# Then process as usual
```

**Monitor:**
```bash
top -p $(pgrep -f python3)  # Check memory usage
```

---

## Testing

### Run Test Suite

```bash
# All tests
python3 test_integration_pipeline.py

# Individual tests
python3 test_pattern_detection.py
python3 test_temporal_clustering.py
python3 test_cross_app.py
```

**Expected output:**
```
✅ Integration Test Passed
   - 3,500 errors loaded
   - 917 traces extracted
   - 126 root causes found
   - Report generated
```

---

## Production Deployment

### Docker Compose (Local)

```bash
docker-compose up -d
```

Services:
- PostgreSQL: localhost:5432
- Redis: localhost:6379
- FastAPI: localhost:8000
- Ollama: localhost:11434

### Kubernetes (ArgoCD)

```bash
# Configuration stored in k8s/
# Auto-deployed via ArgoCD

# Check status
kubectl get pods -n ai-log-analyzer

# View logs
kubectl logs -n ai-log-analyzer deployment/ai-log-analyzer -f
```

---

## Support & Escalation

### Common Escalation Paths

| Issue | Owner | Action |
|-------|-------|--------|
| ES connectivity | DevOps | Check ES cluster, network |
| Memory spike | DevOps | Tune container limits, reduce data range |
| Generic errors in report | Dev Team | Improve error message format |
| Business rule changes | Product | Update analyzer configuration |

### Contact

- **DevOps:** `devops-team@kb.cz`
- **Logs:** `/var/log/ai-log-analyzer/app.log` (K8s: `kubectl logs`)
- **Issues:** Jira project `AILOG`

