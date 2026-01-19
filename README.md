# 🔍 AI Log Analyzer

**Intelligent automated analysis of Kubernetes error peaks with DYNAMIC detection thresholds**

Detekuje error spiky automaticky s dynamickými prahy, analyzuje root causes a generuje doporučení pro opravu.

---

## 📋 Table of Contents

- [Quick Start](#-quick-start)
- [Architecture](#-architecture)
- [Database Schema](#-database-schema)
- [Scripts Reference](#-scripts-reference)
- [Configuration](#-configuration)
- [Production Pipeline](#-production-pipeline)
- [Troubleshooting](#-troubleshooting)

---

## 🚀 Quick Start

### Prerequisites

```bash
# Python 3.8+
python3 --version

# Required packages
pip install psycopg2-binary python-dotenv pyyaml elasticsearch

# Environment file
cp .env.example .env
# Edit .env with your credentials
```

### 1. Setup Database (one-time)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Create schema and tables
python3 scripts/setup_peak_db_v2.py
python3 scripts/grant_permissions.py
```

### 2. INIT Phase (Load baseline data)

```bash
# Load December 2025 data (uses *_CONVERTED.txt files)
./scripts/batch_ingest.sh --init

# Fill missing windows with zeros
python3 scripts/fill_missing_windows_fast.py

# Calculate aggregation baseline
python3 scripts/calculate_aggregation_baseline.py

# Verify
python3 scripts/verify_peak_data.py
```

### 3. REGULAR Phase (Daily/15-min runs)

```bash
# Run complete pipeline
python3 scripts/run_pipeline.py

# Or with custom date range
python3 scripts/run_pipeline.py --from "2026-01-15T00:00:00Z" --to "2026-01-16T00:00:00Z"

# Or batch ingest from ES
./scripts/batch_ingest.sh --regular
```

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────┐
│           ELASTICSEARCH (all errors)            │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌──────────────────────────────────────────────────┐
│  collect_peak_detailed.py                        │
│  (aggregate by 15-min windows per namespace)     │
└────────────────────┬─────────────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │  ingest_from_log_v2.py │
         │  (INIT or REGULAR)     │
         └───────────────┬────────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
        ▼                ▼                ▼
   ┌─────────┐    ┌───────────┐    ┌─────────────┐
   │ IS PEAK │    │ NO PEAK   │    │ ALL ERRORS  │
   └────┬────┘    └─────┬─────┘    └──────┬──────┘
        │               │                 │
        ▼               ▼                 ▼
┌──────────────────────────────────────────────────┐
│              PostgreSQL Database                 │
│              (6 tables in ailog_peak)            │
├──────────────────────────────────────────────────┤
│ • peak_raw_data      (30 days retention)         │
│ • aggregation_data   (7-day rolling baseline)    │
│ • peak_investigation (peaks audit, FOREVER)      │
│ • known_issues       (active bugs database)      │
│ • known_peaks        (solved problems)           │
│ • error_patterns     (all errors tracking)       │
└──────────────────────────────────────────────────┘
```

### Peak Detection Logic

1. **Collect**: Fetch errors from ES, aggregate by 15-min windows
2. **Compare**: Check current value vs baseline (aggregation_data)
3. **Detect**: If `ratio >= threshold` AND `value >= minimum` → PEAK
4. **Log**: Record peak with full context to peak_investigation
5. **Replace**: Use baseline value instead of spike for aggregation
6. **Update**: Refresh aggregation_data with new rolling average

### Dynamic Thresholds (from values.yaml)

```
current_value = 5000 errors
baseline_mean = 100 errors

ratio = 5000 / 100 = 50
threshold = min_ratio_multiplier (e.g., 3.0)
minimum = 24h_avg × dynamic_min_multiplier

is_peak = (ratio >= 3.0) AND (value >= minimum)
```

---

## 💾 Database Schema

**Connection:** `P050TD01.DEV.KB.CZ:5432/ailog_analyzer`  
**Schema:** `ailog_peak`

### Tables Overview

| Table | Purpose | Retention |
|-------|---------|-----------|
| `peak_raw_data` | Raw 15-min window data | 30 days |
| `aggregation_data` | Baseline statistics per (day,hour,quarter,ns) | Rolling |
| `peak_investigation` | Full context for detected peaks | Forever |
| `known_issues` | Database of active known bugs | Forever |
| `known_peaks` | Solved problems with solutions | Forever |
| `error_patterns` | Tracking all error patterns | 90 days |

### Key Columns

**peak_raw_data:**
```sql
timestamp, day_of_week, hour_of_day, quarter_hour, namespace, 
mean_errors, stddev_errors, samples_count
```

**aggregation_data:**
```sql
day_of_week, hour_of_day, quarter_hour, namespace,
mean_errors, stddev_errors, samples_count, last_updated
```

**peak_investigation:**
```sql
timestamp, namespace, original_value, reference_value, ratio,
context_before, context_after, trace_id, app_name, error_type,
ai_analysis, resolution_status
```

---

## 📜 Scripts Reference

### Core Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `run_pipeline.py` | Complete orchestration | `python3 scripts/run_pipeline.py` |
| `batch_ingest.sh` | Batch INIT/REGULAR phases | `./scripts/batch_ingest.sh --init` |
| `ingest_from_log_v2.py` | Data ingestion with peak detection | `python3 scripts/ingest_from_log_v2.py --init FILE` |
| `collect_peak_detailed.py` | Fetch data from ES | `python3 scripts/collect_peak_detailed.py --from DATE --to DATE` |

### Setup Scripts

| Script | Purpose |
|--------|---------|
| `setup_peak_db_v2.py` | Create database tables |
| `grant_permissions.py` | Set DB permissions |
| `verify_peak_data.py` | Verify data integrity |

### Data Processing

| Script | Purpose |
|--------|---------|
| `fill_missing_windows_fast.py` | Fill gaps with zeros |
| `calculate_aggregation_baseline.py` | Compute baseline stats |
| `enrich_peaks.py` | Add trace_id to peaks from ES |

### Analysis

| Script | Purpose |
|--------|---------|
| `intelligent_analysis.py` | Trace-based root cause analysis |
| `export_peak_investigation.py` | Export peaks to CSV |

See [scripts/INDEX.md](scripts/INDEX.md) for complete reference.

---

## ⚙️ Configuration

### Environment Variables (.env)

```bash
# Database
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_analyzer_user_d1
DB_PASSWORD=your_password

# Elasticsearch
ES_HOST=your_es_host
ES_PORT=9200
ES_USER=your_user
ES_PASSWORD=your_password

# Optional
TEAMS_WEBHOOK_URL=https://...
```

### Dynamic Thresholds (values.yaml)

```yaml
peak_detection:
  # Ratio threshold: current_value / baseline >= this
  min_ratio_multiplier: 3.0
  
  # Minimum absolute value threshold
  dynamic_min_multiplier: 2.5
  
  # Reference windows for same-day comparison
  reference_windows: [-15, -30, -45]  # minutes
  
  # Data retention
  retention_days: 30
```

---

## 🔄 Production Pipeline

### Workflow Steps

```
1. COLLECT DATA (15min)      → collect_peak_detailed.py
2. INGEST + PEAK DETECT      → ingest_from_log_v2.py
3. INTELLIGENT ANALYSIS      → intelligent_analysis.py (TODO)
4. KNOWN ISSUES MATCHING     → (TODO)
5. PEAK INVESTIGATION LOG    → peak_investigation table
6. EVALUATION                → DB stats
7. AI ANALYSIS               → GitHub Copilot API (TODO)
8. NOTIFICATION              → Teams webhook (TODO)
9. MAINTENANCE               → auto-delete old data
```

### Cron Setup (K8s/Linux)

```bash
# Every 15 minutes
*/15 * * * * cd /home/jvsete/git/sas/ai-log-analyzer && python3 scripts/run_pipeline.py >> /var/log/ai-log-analyzer.log 2>&1
```

---

## 🔧 Troubleshooting

### Common Issues

**No data in peak_raw_data:**
```bash
# Check if files exist
ls -la /tmp/ai-log-data/peak_*.txt

# Check file format (should start with DATA|)
head -5 /tmp/ai-log-data/peak_fixed_2025_12_01_CONVERTED.txt
```

**Wrong timestamps:**
```bash
# Use CONVERTED files (have correct timestamps)
ls /tmp/ai-log-data/*_CONVERTED.txt
```

**Connection errors:**
```bash
# Verify .env
cat .env | grep DB_

# Test connection
python3 -c "
from dotenv import load_dotenv
import psycopg2, os
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
print('✅ Connected!')
conn.close()
"
```

### Useful Queries

```sql
-- Check data counts
SELECT 'peak_raw_data' as tbl, COUNT(*) FROM ailog_peak.peak_raw_data
UNION ALL
SELECT 'aggregation_data', COUNT(*) FROM ailog_peak.aggregation_data
UNION ALL
SELECT 'peak_investigation', COUNT(*) FROM ailog_peak.peak_investigation;

-- Check timestamp range
SELECT MIN(timestamp), MAX(timestamp) FROM ailog_peak.peak_raw_data;

-- Check namespaces
SELECT DISTINCT namespace FROM ailog_peak.peak_raw_data ORDER BY 1;
```

---

## 📁 Project Structure

```
ai-log-analyzer/
├── scripts/              # All Python/Bash scripts
│   ├── INDEX.md          # Scripts documentation
│   └── _archive_scripts/ # Deprecated scripts
├── values.yaml           # Configuration
├── .env                  # Credentials (not in git)
├── .env.example          # Template
├── README.md             # This file
├── ROADMAP.md            # What's TODO
├── CONTEXT.md            # Session context
└── _archive_md/          # Old documentation
```

---

## 📞 Contact

**Maintainer:** jvsete  
**Repository:** /home/jvsete/git/sas/ai-log-analyzer
