# AI Log Analyzer - Operational Manual

**Pro operátory a DevOps týmy**
**Poslední aktualizace:** 2025-12-03 | **Priorita:** Orchestrační nástroj `analyze_period.py`

---

## 📋 Quick Navigation

- **[⭐ ORCHESTRATION - Recommended](#orchestration---recommended-priority)** - PRIMARY approach
- **[Installation & Setup](#installation--setup)** - První spuštění
- **[Running the Pipeline](#running-the-pipeline)** - Jak spustit analýzu
- **[Understanding Output](#understanding-output)** - Čtení reportů
- **[Common Tasks](#common-tasks)** - Typické úkoly
- **[Troubleshooting](#troubleshooting)** - Řešení problémů
- **[Production Deployment](#production-deployment)** - Nasazení v K8s

---

## ⭐ ORCHESTRATION - Recommended (PRIORITY)

### 🎯 One Command = Complete Analysis A-Z

The **`analyze_period.py`** orchestration tool runs the entire pipeline in a single command:

```bash
python3 analyze_period.py \
  --from "2025-12-02T07:30:00Z" \
  --to "2025-12-02T10:30:00Z" \
  --output analysis_result.json
```

**What it does (automatically):**
1. ✅ Fetches ALL errors from Elasticsearch (search_after pagination - no limits)
2. ✅ Extracts root causes and identifies patterns
3. ✅ Generates detailed markdown report
4. ✅ Creates comprehensive JSON output with statistics
5. ✅ Shows progress bars for each step
6. ✅ Provides executive summary with findings

**Output:** Single JSON file with:
- Complete error dataset
- Root cause analysis
- Markdown report (embedded)
- Comprehensive statistics
- App/cluster distribution
- Performance metrics

### 📊 Example Usage

**Daily Analysis:**
```bash
python3 analyze_period.py \
  --from "2025-12-03T00:00:00Z" \
  --to "2025-12-03T23:59:59Z" \
  --output daily_analysis_2025-12-03.json
```

**Specific Time Window:**
```bash
python3 analyze_period.py \
  --from "2025-12-02T08:00:00Z" \
  --to "2025-12-02T12:00:00Z" \
  --output morning_spike_analysis.json
```

**Custom Batch Size (larger for speed):**
```bash
python3 analyze_period.py \
  --from "2025-12-02T00:00:00Z" \
  --to "2025-12-02T23:59:59Z" \
  --output full_day_analysis.json \
  --batch-size 10000
```

**Real-time (Last hour):**
```bash
python3 analyze_period.py \
  --from "$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')" \
  --to "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --output recent_errors.json
```

### 📈 Sample Output

```json
{
  "metadata": {
    "analysis_type": "Complete Trace-Based Root Cause Analysis",
    "period_start": "2025-12-02T07:30:00Z",
    "period_end": "2025-12-02T10:30:00Z",
    "version": "1.0"
  },
  "statistics": {
    "total_errors_fetched": 65901,
    "errors_with_trace_id": 49900,
    "trace_id_coverage_percent": 75.7,
    "unique_traces": 429,
    "root_causes_identified": 68,
    "app_distribution": { ... },
    "cluster_distribution": { ... }
  },
  "batch_data": { ... },
  "root_causes_analysis": { ... },
  "markdown_report": "# Analysis Report\n..."
}
```

---

## ⚡ QUICK REFERENCE - Common Operations

### View Results from analyze_period.py

```bash
# Pretty-print the JSON (with Python)
python3 -m json.tool analysis_result.json | less

# Extract just the markdown report
python3 << 'PYEOF'
import json
with open('analysis_result.json') as f:
    data = json.load(f)
print(data['markdown_report'])
PYEOF

# View statistics
python3 << 'PYEOF'
import json
with open('analysis_result.json') as f:
    stats = json.load(f)['statistics']
for key, val in stats.items():
    print(f"{key}: {val}")
PYEOF
```

### Compare Multiple Analysis Results

```bash
# Run analysis for different periods
python3 analyze_period.py --from "2025-12-02T00:00:00Z" --to "2025-12-02T12:00:00Z" --output morning.json
python3 analyze_period.py --from "2025-12-02T12:00:00Z" --to "2025-12-02T23:59:59Z" --output evening.json

# Compare statistics
python3 << 'PYEOF'
import json
for fname in ['morning.json', 'evening.json']:
    with open(fname) as f:
        stats = json.load(f)['statistics']
    print(f"\n{fname}:")
    print(f"  Errors: {stats['total_errors_fetched']}")
    print(f"  Root Causes: {stats['root_causes_identified']}")
PYEOF
```

---

## 📥 Advanced: Individual Pipeline Steps (If Needed)

If you need more control or want to run steps separately:

### Step 1: Fetch Errors from Elasticsearch

#### ⭐ RECOMMENDED: Fetch Unlimited (search_after)

For **unlimited data fetching** without ES window limits:

```bash
python3 fetch_unlimited.py \
  --from "2025-12-02T07:30:00Z" \
  --to "2025-12-02T10:30:00Z" \
  --batch-size 5000 \
  --output data/errors_unlimited.json
```

**Features:**
- ✅ Uses search_after cursor pagination (NO 10K window limit)
- ✅ HTTPBasicAuth for reliable authentication
- ✅ Unlimited data fetching - fetch millions of records
- ✅ Retry logic for transient errors

### Step 2: Extract Root Causes

```bash
python3 trace_extractor.py \
  --input data/errors_unlimited.json \
  --output data/root_causes.json
```

### Step 3: Generate Report

```bash
python3 trace_report_detailed.py \
  --input data/root_causes.json \
  --output reports/analysis_report.md
```

### View the Report

```bash
cat reports/analysis_report.md
# Or with pager
less reports/analysis_report.md
```

---

## Installation & Setup

### Prerequisites

```bash
# Python 3.11+
python3 --version

# Dependencies
pip install -r requirements.txt
```

### Configuration

```bash
# Copy template
cp .env.example .env

# Edit for your environment
nano .env
```

**Key variables:**
- `ES_HOST` - Elasticsearch host
- `ES_USER` - Username (for BasicAuth)
- `ES_PASSWORD` - Password (for BasicAuth)
- `ES_INDEX_PATTERN` - Log index pattern
- `POSTGRES_URL` - Database connection (optional)
- `OLLAMA_URL` - LLM service (optional)

---

## Understanding Output

### Markdown Report Sections

1. **Executive Summary** - Top findings and recommended actions
2. **Overview Statistics** - Total errors, traces, root causes
3. **App Impact Distribution** - Which apps affected (PRIMARY/SECONDARY)
4. **Namespace Distribution** - Errors across environments
5. **Root Cause Analysis**
   - **Concrete Issues** - Actionable, specific problems
   - **Semi-Specific Issues** - Need manual investigation
6. **Severity Indicators** - 🔴🟠🟡🟢 color coding

### Severity Scale

| Level | Indicator | Meaning |
|-------|-----------|---------|
| **Critical** | 🔴 | Many errors, immediate action needed |
| **High** | 🟠 | Multiple apps affected, important |
| **Medium** | 🟡 | Specific to one area |
| **Low** | 🟢 | Isolated incidents |

---

## Common Tasks

### Task: Analyze Last 24 Hours

```bash
python3 analyze_period.py \
  --from "$(date -u -d '1 day ago' '+%Y-%m-%dT%H:%M:%SZ')" \
  --to "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --output daily_report.json
```

### Task: Find Root Cause of Production Issue

```bash
# Use known time window from incident report
python3 analyze_period.py \
  --from "2025-12-02T09:10:00Z" \
  --to "2025-12-02T09:30:00Z" \
  --output incident_analysis.json

# Check the markdown report within JSON
python3 -c "import json; print(json.load(open('incident_analysis.json'))['markdown_report'])"
```

### Task: Compare Error Rate Trends

```bash
# Morning
python3 analyze_period.py --from "2025-12-03T06:00:00Z" --to "2025-12-03T12:00:00Z" --output morning.json

# Afternoon
python3 analyze_period.py --from "2025-12-03T12:00:00Z" --to "2025-12-03T18:00:00Z" --output afternoon.json

# Evening
python3 analyze_period.py --from "2025-12-03T18:00:00Z" --to "2025-12-03T23:59:59Z" --output evening.json
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "ES Connection refused" | Check ES_HOST in .env, verify network connectivity |
| "401 Unauthorized" | Verify ES_USER and ES_PASSWORD in .env, test with curl first |
| "No root causes found" | Check if errors have trace_id field (should be ~75%+) |
| "Memory error" | Reduce time range, analyze shorter periods |
| "Execution timeout" | Increase batch size, reduce time range |
| "analyze_period.py not found" | Verify you're in correct directory: `/home/jvsete/git/sas/ai-log-analyzer` |

### Test Your Setup

```bash
# Test ES connection
python3 << 'PYEOF'
import os, requests
from requests.auth import HTTPBasicAuth
url = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
auth = HTTPBasicAuth(os.getenv('ES_USER'), os.getenv('ES_PASSWORD'))
resp = requests.get(f"{url}/_cluster/health", auth=auth, verify=False)
print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    print("✅ ES connection OK")
    print(resp.json())
else:
    print("❌ ES connection failed")
PYEOF

# Test a small fetch
python3 analyze_period.py \
  --from "2025-12-03T09:00:00Z" \
  --to "2025-12-03T09:30:00Z" \
  --output test_result.json
```

---

## Production Deployment

### K8s Cronjob (Scheduled Daily Analysis)

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-log-analyzer-daily
spec:
  schedule: "0 0 * * *"  # Midnight UTC daily
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: analyzer
            image: ai-log-analyzer:latest
            command:
            - python3
            - analyze_period.py
            - --from
            - "$(date -u -d '1 day ago' '+%Y-%m-%dT%H:%M:%SZ')"
            - --to
            - "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
            - --output
            - /results/daily_$(date +%Y-%m-%d).json
            envFrom:
            - configMapRef:
                name: ai-log-analyzer-config
            volumeMounts:
            - name: results
              mountPath: /results
          volumes:
          - name: results
            persistentVolumeClaim:
              claimName: analyzer-results-pvc
          restartPolicy: OnFailure
```

---

## Resources

- **Main Documentation:** `README.md`
- **Project Guide:** `MASTER.md`
- **Script Reference:** `README_SCRIPTS.md`
- **Deployment Details:** `DEPLOYMENT.md`
- **Session Progress:** `working_progress.md`

---

**Last Updated:** 2025-12-03
**Version:** 2.0 (Orchestration-focused)
