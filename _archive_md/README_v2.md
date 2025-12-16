# AI Log Analyzer - v2.0 (Release)

**Automated intelligent error analysis pipeline for Kubernetes applications**

Production-ready orchestration tool that fetches, analyzes, and reports on application errors with detailed insights.

---

## 📊 Version: 2.0 - Release

**Status:** ✅ Production Ready  
**Date:** 2025-12-08  
**Phases Complete:** 1, 2, 3, 4, 5 (Orchestration with Intelligent Analysis)

---

## 🎯 What It Does

AI Log Analyzer provides an automated **end-to-end error analysis pipeline** that:

1. **STEP 1:** Fetches error logs from Elasticsearch (with unlimited pagination)
2. **STEP 2:** Extracts root causes using trace_id grouping
3. **STEP 3:** Generates detailed markdown reports
4. **STEP 4:** Consolidates results into comprehensive JSON
5. **STEP 5:** Runs intelligent analysis with trace patterns, timelines, API patterns, and cross-app correlation

**Output:** Single JSON file containing full analysis with statistics, root causes, markdown report, and intelligent insights.

---

## ⚡ Quick Start

### Basic Usage

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate

# Analyze errors from 11:00 to 12:00 UTC
python3 analyze_period.py \
  --from "2025-12-08T11:00:00Z" \
  --to "2025-12-08T12:00:00Z" \
  --output analysis_result.json

# Output: analysis_result.json (0.8MB+)
```

### Output Structure

```json
{
  "metadata": {
    "analysis_type": "Complete Trace-Based Root Cause Analysis",
    "period_start": "2025-12-08T11:00:00Z",
    "period_end": "2025-12-08T12:00:00Z",
    "generated_at": "2025-12-08T...",
    "version": "1.0"
  },
  "statistics": {
    "total_errors_fetched": 1518,
    "unique_traces": 281,
    "root_causes_identified": 68,
    "execution_time_seconds": 4,
    "app_distribution": { "bl-pcb-v1": 910, ... },
    "cluster_distribution": { "cluster-k8s_nprod_3100-in": 827, ... }
  },
  "batch_data": { ... },
  "root_causes_analysis": { ... },
  "markdown_report": "# Error Analysis Report\n...",
  "intelligent_analysis_output": "📊 Loading batches...\n🔍 TRACE-BASED...\n..."
}
```

---

## 📁 Project Structure

```
ai-log-analyzer/
├── analyze_period.py              # Main orchestration (STEP 1-5)
├── fetch_unlimited.py             # Elasticsearch fetcher (step 1)
├── trace_extractor.py             # Root cause extractor (step 2)
├── trace_report_detailed.py        # Report generator (step 3)
├── intelligent_analysis.py         # Intelligent analysis (step 5)
├── README.md                       # This file
├── HOW_TO_USE.md                   # Detailed usage guide
├── working_progress.md             # Session progress & fixes
├── requirements.txt                # Python dependencies
├── pyproject.toml                  # Project configuration
├── k8s/                            # Kubernetes manifests
└── docker/                         # Docker configuration
```

---

## 🔧 Core Components

### 1. `analyze_period.py` (Main Orchestrator)

**Purpose:** Runs complete analysis pipeline STEP 1-5 in one command

**Key Functions:**
- `analyze_period()` - Main orchestration function
- `run_cmd()` - Subprocess execution with progress bars
- Coordinates all steps with status logging

**Usage:**
```bash
python3 analyze_period.py \
  --from "2025-12-08T11:00:00Z" \
  --to "2025-12-08T12:00:00Z" \
  --output analysis.json \
  --batch-size 5000
```

**Parameters:**
- `--from` (required): Start datetime (ISO 8601 format: `2025-12-08T11:00:00Z`)
- `--to` (required): End datetime (ISO 8601 format)
- `--output` (required): Output JSON file path
- `--batch-size` (optional): Elasticsearch batch size, default 5000

### 2. `fetch_unlimited.py` (STEP 1)

**Purpose:** Fetches error logs from Elasticsearch using search_after pagination (unlimited, no 10K window limit)

**Key Feature:** Avoids ES 10K result window limit via search_after cursor pagination

**Usage:**
```bash
python3 fetch_unlimited.py \
  --from "2025-12-08T11:00:00Z" \
  --to "2025-12-08T12:00:00Z" \
  --batch-size 5000 \
  --output batch.json
```

### 3. `trace_extractor.py` (STEP 2)

**Purpose:** Extracts root causes from error batches using trace_id grouping

**Logic:** Groups errors by `trace_id`, finds first error in chain as root cause

**Output:** JSON with root_causes array and statistics

### 4. `trace_report_detailed.py` (STEP 3)

**Purpose:** Generates detailed markdown analysis report

**Output:** Markdown report with severity ratings (🔴 CRITICAL, 🟠 HIGH, 🟡 MEDIUM, 🟢 LOW)

### 5. `intelligent_analysis.py` (STEP 5)

**Purpose:** Detailed intelligent analysis with advanced insights

**Key Analyses:**
- 🔍 Trace-based root cause analysis (281 unique traces, 5.4 avg errors/trace)
- ⏰ Timeline analysis (5-minute buckets, peak detection)
- 🌐 API call pattern analysis (210 API-related errors)
- 🔗 Cross-app correlation & call chains
- 🎯 Executive summary with prioritized recommendations

**Input:** Batch directory with `batch_*.json` files (created by analyze_period.py STEP 4)

---

## 📊 Data Flow

```
Elasticsearch
    ↓ (STEP 1: fetch_unlimited.py)
batch.json (1,518 errors)
    ↓ (STEP 2: trace_extractor.py)
root_causes.json (68 root causes, 281 traces)
    ↓ (STEP 3: trace_report_detailed.py)
analysis_report.md (markdown report)
    ↓ (STEP 4: analyze_period.py - consolidate)
/tmp/batch_for_intelligent_analysis/ (batch_001.json)
    ↓ (STEP 5: intelligent_analysis.py)
intelligent_analysis_output (text analysis)
    ↓ (Final Output)
analysis_complete.json (8KB+ structured JSON)
```

---

## ✅ Verification

**Test Run Result (2025-12-08T11:00:00Z → 2025-12-08T12:00:00Z):**

```
✅ STEP 1: Fetched 1,518 ERROR logs
✅ STEP 2: Extracted 68 root causes from 281 unique traces
✅ STEP 3: Detailed report generated
✅ STEP 4: Comprehensive analysis saved: 0.8MB
✅ STEP 5: Intelligent analysis integrated (trace patterns, timelines, API analysis, cross-app correlation)

📊 Results:
- Total errors: 1,518
- Unique traces: 281
- Root causes: 68
- Execution time: 4 seconds
- Top app: bl-pcb-v1 (910 errors, 59.9%)
- Peak timeline: 12:50 CET (341 errors in 5 minutes)
- API failures: 210 (POST /api/v1/card/* → 404)
- Top recommendation: 🔴 HIGH - Fix event relay → bl-pcb-v1 communication (339 failures)
```

---

## 🔐 Configuration

### Environment Variables

```bash
# Elasticsearch
ES_HOST=elasticsearch-test.kb.cz
ES_PORT=9500

# Database (PostgreSQL)
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_USER=ailog_analyzer_user_d1
DB_PASS=<from-cyberark>
DB_NAME=ailog_analyzer

# Or set in .env file
```

### Requirements

```bash
pip install -r requirements.txt
```

**Key Dependencies:**
- Python 3.11+
- elasticsearch>=8.0
- psycopg2-binary (PostgreSQL)
- requests

---

## 📝 Important Notes

### Date Format

**CRITICAL:** All dates MUST be in ISO 8601 format with `Z` suffix for UTC:

✅ **Correct:**
- `2025-12-08T11:00:00Z`
- `2025-12-08T12:30:45Z`

❌ **Wrong:**
- `2025-12-08 11:00:00`
- `12/08/2025 11:00`
- `2025-12-08T11:00:00` (missing Z)

### Elasticsearch Connection

The orchestrator expects Elasticsearch to be accessible at the configured host/port. Error messages from ES will be captured and reported.

### Database

Database is optional for current analysis. Core features work with just Elasticsearch.

---

## 🐛 Known Issues & Fixes

### Issue: "Calling apps: unknown" in API Call Analysis

**Status:** ✅ FIXED (v2.0)

**Root Cause:** Elasticsearch data uses `application` field, not `app`

**Fix:** intelligent_analysis.py now uses fallback logic:
```python
def get_app(error):
    return error.get('application') or error.get('app') or 'unknown'
```

**Result:** API analysis now correctly shows calling application names (e.g., `bl-pcb-event-processor-relay-v1`)

---

## 📚 Documentation

- **[HOW_TO_USE.md](HOW_TO_USE.md)** - Detailed usage guide with examples
- **[working_progress.md](working_progress.md)** - Session progress, fixes, and detailed notes
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Kubernetes deployment guide
- **[HARBOR_DEPLOYMENT_GUIDE.md](HARBOR_DEPLOYMENT_GUIDE.md)** - Harbor registry setup

---

## 🚀 Next Steps

### Phase 5: Teams Webhook Integration
- Create Teams channel integration
- Send daily automated alerts
- Include summary + detailed insights

### Phase 6: Autonomous K8s Deployment
- Integrate into ArgoCD
- Scheduled daily analysis
- Automatic dashboard updates

---

## 📞 Support

For issues, see [working_progress.md](working_progress.md) for session logs and debugging notes.

---

**Last Updated:** 2025-12-08  
**Version:** 2.0 (Release)  
**Status:** ✅ Production Ready
