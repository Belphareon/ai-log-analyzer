# Scripts Index - AI Assistant Reference

**Data Flow:** `Elasticsearch → collect_peak_detailed.py → /tmp/*.txt → ingest_from_log.py → PostgreSQL`  
**DB Table:** `ailog_peak.peak_statistics` | **Unique Key:** `(day_of_week, hour_of_day, quarter_hour, namespace)`

---

## Core Pipeline

### `collect_peak_detailed.py`
- **Fetch errors from ES → group into 15-min windows → apply 3-window smoothing → output stats**
- **Input:** `--from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z"` (Z suffix required!)
- **Output:** Text to stdout → redirect to `/tmp/peak_fixed_YYYY_MM_DD.txt`
- **Groups:** (day_of_week 0-6, hour 0-23, quarter 0-3, namespace)
- **Calculates:** mean_errors, stddev_errors, samples_count
- **Example:** `python collect_peak_detailed.py --from "..." --to "..." > /tmp/peak_fixed_2025_12_01.txt`

### `ingest_init_inplace.py` ⭐ UPDATED 2026-01-08
- **Initialize DB with IN-PLACE peak replacement (not skip)**
- **Special INIT MODE:** Uses 5 previous 15-min windows (same day only)
- **Input:** `--input /tmp/peak_fixed_YYYY_MM_DD.txt`
- **NEW FIX (2026-01-08):**
  - ✅ `create_missing_patterns()`: Fills ALL missing namespace×time combinations with mean=0
  - ✅ Peak detection: value > 300 → treat as peak
  - ✅ Replacement: peak → reference value (NOT skip!)
  - ✅ In-place update: replaced value becomes reference for next window
  - ✅ Baseline normalization: value ≤ 0 → normalize to 1
- **Output:**
  - Normal values → INSERT to DB
  - Peaks → REPLACE with reference → INSERT to DB
  - Log replacements to `/tmp/peaks_replaced.log`
- **Result:** No gaps in DB, continuous reference chain
- **Example:** `python ingest_init_inplace.py --input /tmp/peak_fixed_2025_12_01.txt`

### `ingest_from_log.py` ⭐ UPDATED 2026-01-08
- **REGULAR phase: Parse & load with peak replacement (not skip)**
- **Input:** `--input /tmp/peak_fixed_YYYY_MM_DD.txt`
- **NEW FIX (2026-01-08):**
  - ✅ Renamed: `insert_statistics_to_db()` → `insert_statistics_to_db_with_peak_replacement()`
  - ✅ `create_missing_patterns()`: Fills ALL missing namespace×time combinations with mean=0
  - ✅ Peak detection: Uses historical data (3 days back + 3 windows before)
  - ✅ Replacement: peak → reference value (NOT skip!)
  - ✅ In-place update: replaced value becomes reference for next iteration
  - ✅ Baseline normalization: value ≤ 0 → normalize to 1
- **Output:**
  - Normal values → INSERT to DB
  - Peaks → REPLACE with reference → INSERT to DB
  - Log replacements to `/tmp/peaks_replaced.log`
- **Result:** No gaps, proper reference chain across days
- **Example:** `python ingest_from_log.py --input /tmp/peak_fixed_2025_12_08_09.txt`
- **When to use:** AFTER INIT phase complete (DB has history for references)

### `fetch_unlimited.py`
- **ES query with search_after scrolling (internal library only)**
- Imported by collect_peak_detailed.py - don't call directly

---

## Database Management

### `clear_peak_db.py`
- **DELETE all rows from peak_statistics (for re-ingestion)**
- **Example:** `python clear_peak_db.py`

### `truncate_peak_db.py`
- **TRUNCATE peak_statistics table - fresh start before re-ingestion**
- **Interactive:** Asks for confirmation before deleting all rows
- **Use when:** DB has corrupted/aggregated data from UPSERT conflicts
- **Example:** `python truncate_peak_db.py` → answer `yes` to confirm
- **Next:** After TRUNCATE, re-ingest all data files

### `init_peak_statistics_db.py`, `setup_peak_db.py`, `grant_permissions.py`
- **First-time DB setup only** (schema, tables, permissions) - run once

### `backup_db.py` ⭐ NEW 2026-01-08
- **Backup peak_statistics table to CSV**
- **Output:** `/tmp/backup_peak_statistics_YYYYMMDD_HHMMSS.csv`
- **Use when:** Before major operations (cleaning, re-ingestion)
- **Example:** `python backup_db.py`

### `fill_missing_windows.py` ⭐ NEW 2026-01-08
- **Fill missing 15-min windows for complete namespace × time grid**
- **Problem solved:** Some NS have no errors in certain periods (quiet systems)
- **Solution:** 
  - Identifies all unique (day, hour, quarter) combinations
  - Identifies all 12 namespaces (including those with no data)
  - Inserts mean=0 for ALL missing combinations
- **Output:** Adds missing windows to DB with mean_errors=0, stddev_errors=0, samples_count=1
- **Use when:** AFTER INIT phase 1 (to prepare for REGULAR phase with full reference data)
- **Example:** `python fill_missing_windows.py`
- **Result:** Complete grid - all NS have all time windows (some may be 0=no errors)

---

## Validation & Export

### `verify_peak_data.py`
- **Check data integrity** (gaps, anomalies, counts)
- **Example:** `python verify_peak_data.py`

### `query_top_values.py`
- **Quick query: Show top 20 highest values in DB**
- Displays statistics (total rows, max, avg)
- **Example:** `python query_top_values.py`

### `check_peak_detection.py`
- **Verify peak detection effectiveness**
- Shows top 30 values in DB and checks if critical peaks (>500) are correctly skipped
- **Output:**
  - ✅ Top 30 highest values (should be < 500 if peak detection works)
  - ✅ Count of values > 500 (should be 0)
  - Total rows count
- **Usage:** `python check_peak_detection.py`
- **When to use:** After ingest to verify peaks were properly skipped
- **Success criteria:** No values > 500 in output = peak detection working! ✅

### `verify_after_fix.py`
- **POST-FIX VERIFICATION: Check if all 9 user-reported peaks are correctly skipped**
- **Compares:** Expected values vs DB actual values after fix
- **Tests:** 6 extreme peaks (should be ~10-50 in DB) + 3 normal traffic windows
- **Example:** `python verify_after_fix.py` (run AFTER truncate + re-ingest)
- **Exit code:** 0 if all pass, 1 if any fail

### `export_peak_statistics.py`
- **Export to CSV:** `--from YYYY-MM-DD --to YYYY-MM-DD --output file.csv`
- **Example:** `python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16 --output backup.csv`

### `verify_distribution.py` ⭐ NEW 2026-01-08
- **Verify data distribution in DB**
- **Checks:**
  - Total unique time windows (expected: 7 days × 96 windows = 672)
  - Total unique namespaces (expected: 12)
  - Expected total: unique_times × unique_ns
  - Breakdown by namespace (each should have same count)
- **Output:** Shows which NS are complete (✅) vs incomplete (⚠️)
- **Use after:** INIT phase to verify grid completeness
- **Example:** `python verify_distribution.py`

---

## Analysis & Debugging

### `analyze_peaks.py`
- **Analyze detected peaks from logs**
- Extracts peak patterns and generates analysis reports
- **Example:** `python analyze_peaks.py`

### `analyze_problem_peaks.py`
- **Deep analysis of problematic peaks**
- Identifies systematic patterns and recurring anomalies
- **Example:** `python analyze_problem_peaks.py`

### `peaks_timeline.py`
- **Generate timeline view of peaks**
- Creates chronological view of all detected peaks for pattern analysis
- **Example:** `python peaks_timeline.py`

### `show_data_for_date.py`
- **Display DB data for specific date**
- Quick query tool for examining data on a particular day
- **Input:** Date parameter
- **Example:** `python show_data_for_date.py --date 2025-12-04`

---

## Utilities

### `create_known_issues_registry.py`
- Maintains known error patterns baseline

### `analyze_period.py`
- Full analysis orchestrator (future)

### `workflow_manager.sh`
- Batch operations wrapper

### `clear_peak_statistics.py`
- **Alternative clear script** (deprecated - use clear_peak_db.py instead)

### `ingest_peak_statistics.py`
- **Legacy ingest script** (deprecated - use ingest_from_log.py instead)

---

## Common Workflows

**Daily collection:**
```bash
python collect_peak_detailed.py --from "2025-12-16T00:00:00Z" --to "2025-12-17T00:00:00Z" > /tmp/peak_fixed_2025_12_16.txt
python ingest_from_log.py --input /tmp/peak_fixed_2025_12_16.txt
python verify_peak_data.py
```

**Re-ingestion (all files):**
```bash
python clear_peak_db.py
for file in /tmp/peak_fixed_*.txt; do python ingest_from_log.py --input "$file"; done
python verify_peak_data.py
```

**Backup:**
```bash
python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16 --output backup.csv
```

---

---

## � Script Files Summary

**ACTIVE SCRIPTS (používají se):**
- ✅ `collect_peak_detailed.py` - Core data collector
- ✅ `ingest_from_log.py` - Load to DB with peak detection
- ✅ `fetch_unlimited.py` - ES library (internal)
- ✅ `clear_peak_db.py` - Delete all DB data
- ✅ `verify_peak_data.py` - Data validation
- ✅ `verify_after_fix.py` - Post-fix verification
- ✅ `export_peak_statistics.py` - Export to CSV
- ✅ `analyze_peaks.py` - Peak analysis
- ✅ `analyze_problem_peaks.py` - Problem peak analysis
- ✅ `peaks_timeline.py` - Timeline view
- ✅ `show_data_for_date.py` - Date-specific query

**SETUP SCRIPTS (1× only):**
- 🔧 `init_peak_statistics_db.py` - Initial DB setup
- 🔧 `setup_peak_db.py` - Schema setup
- 🔧 `grant_permissions.py` - Permissions setup

**DEPRECATED (nepoužívat):**
- ❌ `truncate_peak_db.py` - Vyžaduje DDL user s LDAP issue
- ❌ `clear_peak_statistics.py` - Starý clear script
- ❌ `ingest_peak_statistics.py` - Starý ingest script

**UTILITIES:**
- 📋 `analyze_period.py` - Full pipeline (future)
- 📋 `workflow_manager.sh` - Batch wrapper
- 📋 `create_known_issues_registry.py` - Known issues

**BACKUPS:**
- 💾 `ingest_from_log.py.backup_20251218_1505` - Safety backup
- 💾 `peak_statistics_backup_20251216_105945.csv` - DB backup

**Total:** 24 files (11 active, 3 setup, 3 deprecated, 3 utilities, 2 backups, 1 INDEX, 1 pycache)

---

## �🗄️ Database Connection & Access

### Environment Variables (.env file)
```
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_analyzer_user_d1           # Normal user (SELECT, INSERT, UPDATE)
DB_PASSWORD=<LDAP password>              # Required for LDAP auth
DB_DDL_USER=ailog_analyzer_ddl_user_d1   # DDL user (CREATE, ALTER, DROP) - setup only
DB_DDL_PASSWORD=<LDAP password>          # Required for DDL operations
```

### How to Access DB Directly

**From Python Script:**
```python
from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()  # ⚠️ REQUIRED - load .env file
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
```

⚠️ **IMPORTANT:** Always call `load_dotenv()` before connecting - it loads credentials from `.env` file

**From Command Line (with venv):**
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate
python scripts/verify_peak_data.py
```

**Note:** Direct `psql` command-line access doesn't work due to LDAP authentication. Must use Python scripts.

### Table Schema

```sql
CREATE TABLE ailog_peak.peak_statistics (
    id SERIAL PRIMARY KEY,
    day_of_week INT (0-6: Mon-Sun),
    hour_of_day INT (0-23),
    quarter_hour INT (0-3: 0=:00, 1=:15, 2=:30, 3=:45),
    namespace VARCHAR,
    mean_errors FLOAT (average errors in 15-min window),
    stddev_errors FLOAT (standard deviation),
    samples_count INT (how many days aggregated),
    updated_at TIMESTAMP,
    
    UNIQUE KEY: (day_of_week, hour_of_day, quarter_hour, namespace)
);
```

### Key Data Points

- **Total rows:** Currently ~3,400
- **Time range:** 2025-12-01 to 2025-12-16 (16 days)
- **Namespaces:** 10 (pca-*, pcb-*, pcb-ch-*)
- **Aggregation:** Welford's algorithm (multi-day UPSERT)

### Common Queries

**Check specific time (e.g., Fri 7:00 for pcb-ch-sit):**
```sql
SELECT mean_errors, samples_count
FROM ailog_peak.peak_statistics
WHERE day_of_week = 4 AND hour_of_day = 7 AND namespace = 'pcb-ch-sit-01-app';
```

**Find peaks (high errors):**
```sql
SELECT * FROM ailog_peak.peak_statistics
WHERE mean_errors > 1000
ORDER BY mean_errors DESC
LIMIT 20;
```

**Count by namespace:**
```sql
SELECT namespace, COUNT(*) as count
FROM ailog_peak.peak_statistics
GROUP BY namespace
ORDER BY count DESC;
```

---

## ⚠️ KNOWN ISSUES & DEBUGGING

### UPSERT Aggregation Problem
When re-ingesting data, ON CONFLICT clause causes aggregation with old values. This can make peaks appear lower than actual. 

**Solution:** Always run `clear_peak_db.py` before batch re-ingestion to start fresh.

### HOW TO PROPERLY DELETE ALL DB DATA

**CRITICAL: TRUNCATE vs DELETE**
```bash
# ❌ WRONG: truncate_peak_db.py - Requires DDL user (DDL LDAP password issue)
echo "yes" | python scripts/truncate_peak_db.py
# ERROR: LDAP authentication failed for user "ailog_analyzer_ddl_user_d1"

# ✅ CORRECT: clear_peak_db.py - Uses regular user (DELETE permission)
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate
python scripts/clear_peak_db.py
# Output: 📊 Rows deleted: 3399, Rows remaining: 0
```

**Why?**
- `TRUNCATE` requires DDL permissions (ailog_analyzer_ddl_user_d1)
- DDL user má LDAP authentication issues v .env
- `DELETE` funguje s běžným userem (ailog_analyzer_user_d1) ✅
- Pro mazání dat VŽDY použij `clear_peak_db.py`

**Verification:**
```bash
python scripts/verify_peak_data.py | head -5
# Expected: 📊 Total rows: 0
```

### Peak Detection Not Triggering
If peaks aren't being skipped:
1. Check if reference data exists from previous 3 days
2. Day #1 of a new dataset has NO references (peaks won't be detected)
3. Verify ratio calculation: `current_mean / reference_median >= 15.0`

### Missing Credentials
Error: `fe_sendauth: no password supplied`
- Ensure `.env` file exists and has `DB_PASSWORD=<password>`
- Call `load_dotenv()` in Python scripts before connecting
- LDAP requires the password to be set

---

## Key Info for AI

- **Date format:** Always use `Z` suffix (e.g., `2025-12-01T00:00:00Z`)
- **File naming:** `/tmp/peak_fixed_YYYY_MM_DD.txt` (consistent)
- **Peak threshold:** 15× (3 previous days reference)
- **DB aggregation:** Multi-day UPSERT with Welford's algorithm
- **Setup scripts:** Run once only
- **DB access:** Always use Python + `load_dotenv()` - no direct psql
- **Test first:** Always test with 1 file before batch re-ingestion

