# Scripts Index - Phase 5 Peak Detection Baseline

**Last Updated:** 2025-12-16 12:00 UTC  
**Phase:** 5A - Data Ingestion & Baseline Collection  
**DB Status:** ✅ Peak statistics started (5 rows from 2025-12-01)

---

## 📊 WORKFLOW OVERVIEW

```
Step 1: COLLECT data from Elasticsearch
   └─> collect_peak_detailed.py (PRINTS statistics to text log)
        └─> fetch_unlimited.py (pulls all errors)
        └─> Outputs: statistics with mean/stddev

Step 2: EXTRACT statistics from log file
   └─> ingest_from_log.py (NEW!)
        └─> Parses text output
        └─> Loads into DB peak_statistics table

Step 3: VERIFY data integrity
   └─> verify_peak_data.py
        └─> Checks for gaps/anomalies
        └─> Reports by namespace
```

---

## 🔷 CORE WORKFLOW SCRIPTS (Active - Phase 5A)

### 1. **collect_peak_detailed.py** ⭐ MAIN DATA COLLECTOR
**What it does:** Collects error counts from Elasticsearch in 15-minute windows, groups by (day_of_week, hour, quarter, namespace), applies 3-window smoothing, calculates mean/stddev

**Input:** 
- Date range: `--from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z"`
- Alternative: `--days N` (last N days - not recommended for production)

**Output:** 
- **Text log to stdout** (displays statistics)
- **File:** `/tmp/peak_data_YYYY_MM_DD.txt` (captured when redirected)

**Usage:**
```bash
# Collect 24h data (CORRECT WAY - explicit dates!)
python collect_peak_detailed.py \
  --from "2025-12-01T00:00:00Z" \
  --to "2025-12-02T00:00:00Z" \
  > /tmp/peak_data_2025_12_01.txt

# Or relative (for testing only):
python collect_peak_detailed.py --days 1
```

**Example Output:**
```
🚀 Peak Data Collection - Detailed Analysis
📊 Generated 96 15-minute windows

✅ Total errors fetched: 230,146
   Namespaces: ['pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-sit-01-app', 'pcb-uat-01-app']

🔬 Smoothing Effectiveness (sample patterns):
   Pattern 1: Mon 10:30 - pcb-sit-01-app
      Mean: 12.00, StdDev: 0.00, Samples: 1
   ...
✅ Analysis complete!
```

**Status:** ✅ Active & Working
**Last Run:** 2025-12-16 (2025-12-01 data, 230K errors)

---

### 2. **ingest_from_log.py** ⭐ NEW - DATA LOADER
**What it does:** Parses statistics from `collect_peak_detailed.py` text output and loads into PostgreSQL `peak_statistics` table using UPSERT

**Input:** 
- Log file from collect_peak_detailed.py
- Format: `/tmp/peak_data_YYYY_MM_DD.txt`

**Output:** 
- PostgreSQL table: `ailog_peak.peak_statistics`
- Upserts data (updates if exists, inserts if new)

**Usage:**
```bash
# Parse log file and load to DB
python ingest_from_log.py --input /tmp/peak_data_2025_12_01.txt

# Output:
# ✅ Parsed 848 patterns from log
# ✅ Inserted: 848, Failed: 0
# ✅ Total rows in peak_statistics: 848
#    Breakdown by namespace:
#    - pcb-dev-01-app: 96 patterns
#    - pcb-fat-01-app: 96 patterns
#    - pcb-sit-01-app: 336 patterns
#    - pcb-uat-01-app: 320 patterns
```

**Status:** ✅ New (2025-12-16 12:00)
**Last Run:** 2025-12-01 data (5 sample patterns tested)

---

### 3. **fetch_unlimited.py**
**What it does:** Elasticsearch query utility with unlimited scroll via search_after (proven working)

**Input:** 
- Date range (ISO format with Z suffix)
- Batch size (default 5000)

**Output:** 
- List of error documents with timestamp + namespace

**Usage:** Internal library (imported by collect_peak_detailed.py)

**Example Direct Usage:**
```python
from fetch_unlimited import fetch_unlimited
errors = fetch_unlimited("2025-12-01T00:00:00Z", "2025-12-01T01:00:00Z", batch_size=5000)
```

**Status:** ✅ Core utility, working
**Tested:** All ES indices (pcb-*, pca-*, pcb-ch-*)

---

### 4. **analyze_period.py**
**What it does:** Orchestrator for full analysis pipeline (future use)

**Status:** ⏳ TODO - Phase 5B

---

## 🔷 DATABASE SETUP SCRIPTS (Setup Only - Phase 4 Complete)

### 5. **init_peak_statistics_db.py**
- **Status:** ⚠️ Already executed (Phase 4 - 2025-12-12)
- **Run:** ONLY on first DB setup

### 6. **setup_peak_db.py**
- **Status:** ⚠️ Already executed (Phase 4)
- **Run:** ONLY on fresh DB

### 7. **grant_permissions.py**
- **Status:** ⚠️ Already executed (Phase 4)
- **Run:** ONLY after DB creation

---

## 🔷 DATA EXPORT & VALIDATION

### 8. **export_peak_statistics.py**
**What it does:** Export peak_statistics table to CSV for backup/analysis

**Usage:**
```bash
python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16 --output backup.csv
```

**Status:** ✅ Active

### 9. **verify_peak_data.py**
**What it does:** Verify data integrity in peak_statistics (check for gaps, anomalies, etc.)

**Usage:**
```bash
python verify_peak_data.py
```

**Status:** ✅ Active

---

## 🔷 UTILITY SCRIPTS

### 10. **create_known_issues_registry.py**
**Status:** ✅ Active - maintains baseline of known error patterns

---

## 📋 DAILY WORKFLOW - How to Use

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate

# Step 1: Collect data for today
python scripts/collect_peak_detailed.py \
  --from "2025-12-16T00:00:00Z" \
  --to "2025-12-17T00:00:00Z" \
  > /tmp/peak_data_2025_12_16.txt

# Step 2: Load into database
python scripts/ingest_from_log.py --input /tmp/peak_data_2025_12_16.txt

# Step 3: Verify
python scripts/verify_peak_data.py

# Step 4: (Optional) Backup
python scripts/export_peak_statistics.py --from 2025-12-16 --to 2025-12-16
```

---

## 🚨 IMPORTANT NOTES

⚠️ **Always use EXPLICIT dates with Z suffix:**
```
CORRECT:   --from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z"
WRONG:     --days 1
WRONG:     datetime.now() + timedelta(...)
```

⚠️ **Data flow:**
```
Elasticsearch → collect_peak_detailed.py → /tmp/peak_data_*.txt
                                            ↓
                          ingest_from_log.py → PostgreSQL peak_statistics
```

⚠️ **DB Schema (peak_statistics):**
```
Columns: day_of_week (0-6), hour_of_day (0-23), quarter_hour (0,15,30,45),
         namespace, mean_errors, stddev_errors, samples_count, last_updated

Unique Key: (day_of_week, hour_of_day, quarter_hour, namespace)
```

---

## 📊 CURRENT STATUS (2025-12-16 12:00)

**Database content:**
- Total rows: 5 (sample from 2025-12-01)
- Namespaces: 4 (pcb-dev, pcb-fat, pcb-sit, pcb-uat)
- Date range in DB: 2025-12-01 only

**Next steps:**
1. Collect days 2025-12-02 to 2025-12-16 (15 days)
2. Load each day using ingest_from_log.py
3. Verify complete range in DB

---

## 📋 EXECUTION CHECKLIST (Daily Run)

```bash
# 1. Collect latest data
python collect_peak_detailed.py --from 2025-12-15T00:00:00Z --to 2025-12-16T00:00:00Z

# 2. Verify data quality
python verify_peak_data.py

# 3. Export backup (optional)
python export_peak_statistics.py

# 4. Full analysis (optional)
python analyze_period.py
```

---

## 🔧 ENVIRONMENT SETUP

All scripts require:
- PostgreSQL connection (see `.env`)
- Elasticsearch access
- Python 3.12+ with requirements.txt installed

```bash
source venv/bin/activate
pip install -r requirements.txt
```

---

## 📝 NOTES FOR NEXT SESSION

- **Never delete** `collect_peak_detailed.py` - this is the core
- **Setup scripts** (init_*, setup_*, grant_*) only run once
- **Always export backup** before major DB operations
- **Verify data** after every load with `verify_peak_data.py`

