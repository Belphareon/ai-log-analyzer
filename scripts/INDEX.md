# Scripts Index - Phase 5B (INIT Phase 3 Weeks)

**Data Flow:** `Elasticsearch → collect_peak_detailed.py → /tmp/*.txt → ingest_from_log_v2.py → PostgreSQL`  
**DB Table:** `ailog_peak.peak_statistics` | **Unique Key:** `(day_of_week, hour_of_day, quarter_hour, namespace)`  
**Phase:** Phase 5B - INIT Phase 3 Weeks (21 days baseline, no peak detection)

---

## 🎯 Quick Start

**INIT Phase (3 Weeks - NO peak detection):**
```bash
cd /home/jvsete/git/sas/ai-log-analyzer/scripts

# Setup DB (one-time)
python3 setup_peak_db.py
python3 grant_permissions.py

# Ingest all 14 files (1-21.12)
for file in /tmp/peak_fixed_2025_12_*.txt; do
  python3 ingest_from_log_v2.py --init "$file"
done

# Complete the grid
python3 fill_missing_windows.py

# Verify (should be 24,192 rows)
python3 verify_peak_data.py
```

---

## 📊 Core Pipeline Scripts

### `collect_peak_detailed.py` - Data Collection from Elasticsearch
**Purpose:** Fetch errors from ES → group into 15-min windows → calculate statistics

- **Input:** `--from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z"` (Z suffix required!)
- **Output:** Text to stdout → redirect to `/tmp/peak_fixed_YYYY_MM_DD.txt`
- **What it does:**
  - Queries Elasticsearch for errors in time range
  - Groups by (day_of_week, hour, quarter_hour, namespace)
  - Applies 3-window smoothing to normalize spikes
  - Calculates mean_errors, stddev_errors, samples_count

**Example:**
```bash
python3 collect_peak_detailed.py --from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z" > /tmp/peak_fixed_2025_12_01.txt
```

---

### `ingest_from_log_v2.py` ⭐ MAIN SCRIPT - Two-Phase Ingestion
**Purpose:** Load peak data from .txt file into PostgreSQL (INIT or REGULAR mode)

**Input:** `--input /tmp/peak_fixed_YYYY_MM_DD.txt` + `--init` flag for INIT phase

#### INIT Mode (--init flag)
- No peak detection
- Just aggregate and store baseline data
- Used for loading 3 weeks (21 days)

```bash
python3 ingest_from_log_v2.py --init /tmp/peak_fixed_2025_12_01.txt
```

**What it does:**
1. Reads file (1,918 patterns: 96 windows × 12 namespaces)
2. Aggregates duplicates using weighted average
3. Inserts to peak_statistics WITHOUT peak detection
4. Result: Clean baseline data

#### REGULAR Mode (default, no flag)
- With peak detection enabled
- Compares against 3 previous 15-min windows (same day)
- If ratio >= 15× AND value >= 100 → PEAK!
- Replaces peak with reference value

```bash
python3 ingest_from_log_v2.py /tmp/peak_fixed_2025_12_22.txt
```

**What it does:**
1. Reads file
2. For each window:
   - Find 3 previous 15-min windows on SAME day (-15, -30, -45 min)
   - Calculate ratio = value / average(references)
   - If ratio >= 15× AND value >= 100 → replace with reference
3. Inserts (replaced or original) to DB

**Key Features:**
- In-memory aggregation for duplicate keys
- ON CONFLICT UPDATE with weighted average
- Peak detection uses same-day only references
- Handles missing windows gracefully

---

### `fill_missing_windows.py` - Complete the Grid
**Purpose:** Fill missing (day, hour, quarter, namespace) combinations with mean=0

- **When to use:** AFTER INIT phase (before REGULAR phase)
- **Why:** Ensures all 24,192 combinations exist (21 days × 96 windows × 12 namespaces)

```bash
python3 fill_missing_windows.py
```

**Expected result:** 24,192 total rows (all combinations present)

---

## 🗄️ Database Management Scripts

### Setup Scripts (Run Once)

#### `setup_peak_db.py`
- Creates schema: `ailog_peak`
- Creates table: `peak_statistics` with proper columns

```bash
python3 setup_peak_db.py
```

#### `grant_permissions.py`
- Grants SELECT, INSERT, UPDATE, DELETE to data user
- Runs ONCE after schema creation

```bash
python3 grant_permissions.py
```

### Data Management

#### `clear_peak_db.py`
- DELETE all rows from peak_statistics (for fresh re-ingestion)
- Safe: Uses regular user (no DDL issues)
- Interactive: Asks for confirmation

```bash
python3 clear_peak_db.py
```

#### `backup_db.py`
- Exports all peak_statistics to CSV file
- Output: `/tmp/backup_peak_statistics_YYYYMMDD_HHMMSS.csv`
- Use BEFORE major operations

```bash
python3 backup_db.py
```

---

## ✅ Validation & Verification Scripts

### `verify_peak_data.py`
- Checks total row count
- Verifies day_of_week values (0-6)
- Counts distinct namespaces (should be 12)
- Finds NULL values
- Shows value ranges

```bash
python3 verify_peak_data.py
```

**Expected output for INIT Phase complete:**
```
✅ Total rows: 24,192
✅ Days: 7 (0-6)
✅ Namespaces: 12
✅ NULL values: 0
✅ Value range: 0.0 - 9,965.3
```

### `export_peak_statistics.py`
- Export specific date range to CSV
- Columns: day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count

```bash
python3 export_peak_statistics.py --from 2025-12-01 --to 2025-12-21 --output baseline.csv
```

---

## 🔧 Utility Scripts

### `check_db_data.py`
- Shows row count
- Shows distinct days and namespaces
- Shows value ranges
- Shows zero rows (OK status)

```bash
python3 check_db_data.py
```

---

## 📁 Script Status

| Script | Purpose | Phase | Status |
|--------|---------|-------|--------|
| `collect_peak_detailed.py` | ES data collection | Both | ✅ Active |
| `ingest_from_log_v2.py` | Load to DB (INIT + REGULAR) | Both | ✅ Active |
| `fill_missing_windows.py` | Complete grid | INIT | ✅ Active |
| `setup_peak_db.py` | Create schema | Setup | ✅ Setup |
| `grant_permissions.py` | Grant DB perms | Setup | ✅ Setup |
| `clear_peak_db.py` | Delete all data | Both | ✅ Active |
| `backup_db.py` | Backup to CSV | Both | ✅ Active |
| `verify_peak_data.py` | Data validation | Both | ✅ Active |
| `export_peak_statistics.py` | Export to CSV | Both | ✅ Active |
| `check_db_data.py` | Quick check | Both | ✅ Active |

---

## 🗄️ Database Connection & Configuration

### Connection Info
```
Host: P050TD01.DEV.KB.CZ
Port: 5432
Database: ailog_analyzer
Schema: ailog_peak

USERS:
- ailog_analyzer_user_d1     → Data operations (SELECT, INSERT, UPDATE, DELETE)
- ailog_analyzer_ddl_user_d1 → DDL operations (CREATE, ALTER, DROP, GRANT)

ROLE:
- role_ailog_analyzer_ddl    → DDL role (required before DDL operations)
```

### Environment Variables (.env)
```
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_analyzer_user_d1
DB_PASSWORD=<your_ldap_password>
DB_DDL_USER=ailog_analyzer_ddl_user_d1
DB_DDL_PASSWORD=<your_ldap_password>
```

### How to Connect - Data Operations

**Python:**
```python
from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()  # ⚠️ REQUIRED! Loads .env file

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cursor = conn.cursor()

# Normal data operations
cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics;")
count = cursor.fetchone()[0]
print(f"Total rows: {count}")
```

### How to Connect - DDL Operations (Setup Only)

**Python:**
```python
from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()

# Use DDL user
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_DDL_USER'),
    password=os.getenv('DB_DDL_PASSWORD')
)
cursor = conn.cursor()

# ⚠️ REQUIRED: Set DDL role before DDL operations
cursor.execute("SET ROLE role_ailog_analyzer_ddl;")

# Now safe to do DDL
cursor.execute("CREATE TABLE IF NOT EXISTS ailog_peak.peak_statistics (...);")
conn.commit()
```

### Critical Rules
1. ✅ Always `load_dotenv()` BEFORE connecting
2. ✅ For DDL: Use DB_DDL_USER + `SET ROLE role_ailog_analyzer_ddl`
3. ✅ For data: Use DB_USER (regular user)
4. ✅ Never commit `.env` to git

---

## 🎯 Database Schema

```sql
CREATE TABLE ailog_peak.peak_statistics (
    day_of_week INT,           -- 0-6 (Mon-Sun, repeats weekly)
    hour_of_day INT,           -- 0-23
    quarter_hour INT,          -- 0-3 (:00, :15, :30, :45)
    namespace VARCHAR,         -- e.g., pcb-dev-01-app
    mean_errors FLOAT,         -- Average errors in this window
    stddev_errors FLOAT,       -- Standard deviation
    samples_count INT,         -- How many times aggregated
    
    PRIMARY KEY (day_of_week, hour_of_day, quarter_hour, namespace)
);
```

---

## 🔑 Key Concepts

### Two-Phase Architecture

**INIT Phase (3 Weeks):**
- Collect 1-21.12 (21 days)
- NO peak detection
- Just baseline aggregation
- Result: 24,192 rows
- Purpose: Create reference baseline

**REGULAR Phase (Daily):**
- Start day 22 (22.12+)
- WITH peak detection (ratio >= 15×)
- Compare against 3 previous 15-min windows (same day)
- Replace peaks with reference value

### Peak Detection Algorithm
```
For each (day, hour, quarter, namespace):
  1. Get 3 previous 15-min windows on SAME day: -15, -30, -45 min
  2. Calculate reference = average(3 windows)
  3. Calculate ratio = current_value / reference
  4. IF ratio >= 15.0 AND current_value >= 100:
       - Replace with reference value
       - Log to peak_investigation table
  5. INSERT (replaced or original) to peak_statistics
```

### Why Same-Day Only?
- Monday traffic differs from Friday traffic
- Same-day windows provide reliable baseline

### Why 3 Weeks?
- Each day-of-week needs 3 reference points
- With 3 weeks: 3 data points for each day-of-week/time

---

## 🚀 Common Workflows

### INIT Phase 3 Weeks
```bash
cd /home/jvsete/git/sas/ai-log-analyzer/scripts

# Setup (once)
python3 setup_peak_db.py
python3 grant_permissions.py

# Ingest all 14 files
for file in /tmp/peak_fixed_2025_12_*.txt; do
  python3 ingest_from_log_v2.py --init "$file"
done

# Complete the grid
python3 fill_missing_windows.py

# Verify
python3 verify_peak_data.py
```

### REGULAR Phase Daily
```bash
# Every day, ingest yesterday's data
python3 ingest_from_log_v2.py /tmp/peak_fixed_2025_12_22.txt
python3 ingest_from_log_v2.py /tmp/peak_fixed_2025_12_23.txt
# ... continue daily
```

### Re-Ingestion (Fresh Start)
```bash
# Backup first
python3 backup_db.py

# Clear all data
python3 clear_peak_db.py

# Ingest files again
for file in /tmp/peak_fixed_*.txt; do
  python3 ingest_from_log_v2.py --init "$file"
done

# Verify
python3 verify_peak_data.py
```

---

## 📋 Troubleshooting

### "ModuleNotFoundError: No module named 'dotenv'"
```bash
pip install python-dotenv
```

### "psycopg2.OperationalError: could not connect"
- Check VPN is connected
- Verify DB_HOST = P050TD01.DEV.KB.CZ
- Check port 5432 is accessible

### "peak_statistics table does not exist"
```bash
python3 setup_peak_db.py
python3 grant_permissions.py
```

### "Rows < expected after ingest"
- Check script output for errors
- Run one file at a time to isolate issues
- Verify input file format

### "Peak detection not triggering"
- Ensure REGULAR phase (no --init flag)
- Check reference data exists (need 3 previous windows)
- Day 1 of dataset has NO references (peaks won't detect)

---

## �� Related Documentation

- **[GETTING_STARTED.md](../GETTING_STARTED.md)** - Complete 6-step setup guide
- **[CONTEXT_RETRIEVAL_PROTOCOL.md](../CONTEXT_RETRIEVAL_PROTOCOL.md)** - Quick reference
- **[working_progress.md](../working_progress.md)** - Session log & progress

---

**Version:** 3.0 | **Updated:** 2026-01-12 | **Phase:** 5B (INIT Phase 3 Weeks)
