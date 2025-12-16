# Scripts Index

**Last Updated:** 2025-12-16 11:00 UTC  
**Phase:** 5 - Peak Collection & Data Ingestion

---

## 🔷 CORE SCRIPTS (Active - Phase 5)

### 1. **collect_peak_detailed.py**
- **Purpose:** Main data collector for peak detection baseline
- **Input:** ES cluster, date range (--from/--to)
- **Output:** PostgreSQL table `peak_statistics`
- **Status:** ✅ Active, used daily
- **Last Run:** 2025-12-15 (163,847 errors) + 2025-12-01 (historical)
- **Usage:**
  ```bash
  python collect_peak_detailed.py --from 2025-12-15T00:00:00Z --to 2025-12-16T00:00:00Z
  ```

### 2. **fetch_unlimited.py**
- **Purpose:** Elasticsearch query utility with unlimited scrolling
- **Input:** ES query, scroll size
- **Output:** JSON documents
- **Status:** ✅ Utility/dependency for collectors
- **Used By:** collect_peak_detailed.py
- **Usage:** Internal library import

### 3. **analyze_period.py**
- **Purpose:** Orchestrator for full analysis pipeline
- **Input:** Time period configuration
- **Output:** Analysis reports + charts
- **Status:** ✅ Active, orchestrates other scripts
- **Last Run:** Phase 5 setup
- **Usage:**
  ```bash
  python analyze_period.py --period 2025-12-01_to_2025-12-16
  ```

---

## 🔷 DATABASE SETUP SCRIPTS (Setup Only - Phase 4 Complete)

### 4. **init_peak_statistics_db.py**
- **Purpose:** Initialize peak_statistics table (one-time)
- **Status:** ⚠️ Already executed (Phase 4)
- **Run:** ONLY on first setup
- **DB Target:** ailog_analyzer.peak_statistics

### 5. **setup_peak_db.py**
- **Purpose:** Full DB schema setup and initialization
- **Status:** ⚠️ Already executed (Phase 4)
- **Run:** ONLY on fresh DB

### 6. **grant_permissions.py**
- **Purpose:** PostgreSQL user permissions setup
- **Status:** ⚠️ Already executed (Phase 4)
- **Run:** ONLY after DB creation

---

## 🔷 DATA EXPORT & VALIDATION

### 7. **export_peak_statistics.py**
- **Purpose:** Export peak_statistics table to CSV
- **Input:** Date range (optional filter)
- **Output:** CSV file with timestamp
- **Status:** ✅ Active - used for data backup
- **Last Export:** 2025-12-16
- **Usage:**
  ```bash
  python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16
  ```

### 8. **verify_peak_data.py**
- **Purpose:** Verify data integrity in peak_statistics
- **Input:** DB connection
- **Output:** Validation report
- **Status:** ✅ Active - run after data load
- **Usage:**
  ```bash
  python verify_peak_data.py
  ```

---

## 🔷 UTILITY SCRIPTS

### 9. **create_known_issues_registry.py**
- **Purpose:** Build registry of known error patterns
- **Input:** Historical logs + patterns
- **Output:** PostgreSQL known_issues table
- **Status:** ✅ Active - maintains baseline
- **Usage:**
  ```bash
  python create_known_issues_registry.py
  ```

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

