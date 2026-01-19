# Scripts Index - Production Pipeline

**Architecture:** Dynamic Thresholds with Trace Analysis  
**DB Tables:** peak_raw_data, aggregation_data, peak_investigation, known_issues, known_peaks, error_patterns  
**Configuration:** values.yaml (dynamické parametry pro tuning)

---

## 🎯 Quick Start - Production

### Run Full Pipeline (single execution)
```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Regular run (last 15 minutes)
python3 scripts/run_pipeline.py

# Custom date range
python3 scripts/run_pipeline.py --from "2026-01-15T10:00:00Z" --to "2026-01-15T11:00:00Z"

# Skip intelligent analysis (faster)
python3 scripts/run_pipeline.py --skip-analysis

# Dry run (no DB writes)
python3 scripts/run_pipeline.py --dry-run
```

### Batch Ingestion (historical data)
```bash
# INIT phase: December 2025 from local files (baseline, no peak detection)
./scripts/batch_ingest.sh --init

# REGULAR phase: January 2026 from ES (with peak detection + analysis)
./scripts/batch_ingest.sh --regular

# Both phases
./scripts/batch_ingest.sh --all

# Dry run (see what would happen)
./scripts/batch_ingest.sh --all --dry-run
```

---

## 📂 Active Scripts (18 files)

| Script | Purpose | Usage |
|--------|---------|-------|
| **run_pipeline.py** ⭐ | Main 9-step orchestrator | `python3 run_pipeline.py` |
| **batch_ingest.sh** ⭐ | Batch ingestion for INIT/REGULAR | `./batch_ingest.sh --all` |
| **ingest_from_log_v2.py** | Ingestion + peak detection | `python3 ingest_from_log_v2.py --input file.txt` |
| **collect_peak_detailed.py** | Fetch errors from ES → windows | `python3 collect_peak_detailed.py --from --to` |
| **analyze_and_track.py** | Trace analysis + error tracking | `python3 analyze_and_track.py --from --to` |
| **enrich_peaks.py** | Add trace_id to detected peaks | `python3 enrich_peaks.py --all` |
| **validate_detection.py** | Validate peak detection accuracy | `python3 validate_detection.py` |
| **fetch_unlimited.py** | Raw ES fetcher (search_after) | Used by other scripts |
| **intelligent_analysis.py** | Legacy analysis (used by pipeline) | Internal |
| **fill_missing_windows_v3.py** | Fill missing grid combinations | `python3 fill_missing_windows_v3.py` |
| **fill_missing_windows_fast.py** | Fast version of above | `python3 fill_missing_windows_fast.py` |
| **calculate_aggregation_baseline.py** | Recalculate baseline from raw data | `python3 calculate_aggregation_baseline.py` |
| **create_investigation_tables.py** | Create DB schema | `python3 create_investigation_tables.py` |
| **create_known_issues_registry.py** | Create known_issues table | `python3 create_known_issues_registry.py` |
| **grant_permissions.py** | Grant DB permissions | `python3 grant_permissions.py` |
| **backup_db.py** | Export DB to CSV | `python3 backup_db.py` |
| **check_db_data.py** | Quick DB stats | `python3 check_db_data.py` |
| **show_data_for_date.py** | Show data for specific date | `python3 show_data_for_date.py 2026-01-15` |
| **analyze_period.py** | Analyze ES data for period | `python3 analyze_period.py --from --to` |
| **fix_timezone_in_txt.py** | Fix timezone in .txt files | `python3 fix_timezone_in_txt.py file.txt` |

---

## 🚀 Main Scripts Detail

### `run_pipeline.py` ⭐ MAIN ENTRY POINT
**Purpose:** Orchestrate complete 9-step pipeline

**Steps:**
1. **SBĚR DAT** - Fetch errors from ES (collect_peak_detailed.py)
2. **IDENTIFIKACE** - Classify errors (intelligent_analysis.py)
3. **ANALÝZA** - Trace-based root cause analysis
4. **INGESTION** - Insert to DB + peak detection (ingest_from_log_v2.py)
5. **KNOWN ISSUES** - Match against known patterns
6. **VYHODNOCENÍ** - Record stats
7. **AI ANALÝZA** - GitHub Copilot API (future)
8. **NOTIFIKACE** - Teams webhook
9. **MAINTENANCE** - Delete old data (>30 days)

---

### `batch_ingest.sh` ⭐ BATCH INGESTION
**Purpose:** Run INIT or REGULAR phase for multiple days

**Phases:**
- **INIT (December 2025):** Load from `/tmp/ai-log-data/` without peak detection
- **REGULAR (January 2026):** Fetch from ES with peak detection + intelligent analysis

**Options:**
```bash
--init          # Run INIT phase only
--regular       # Run REGULAR phase only
--all           # Run both phases
--from DATE     # Start REGULAR from specific date
--to DATE       # End at date (default: yesterday)
--dry-run       # Show what would be done
--force         # Don't skip existing days
```

---

### `ingest_from_log_v2.py` ⭐ INGESTION + PEAK DETECTION
**Purpose:** Load peak data into PostgreSQL with dynamic peak detection

**Modes:**
- `--init` - INIT mode: no peak detection, just load baseline
- (default) - REGULAR mode: WITH peak detection

**Features:**
- Dynamic thresholds from `values.yaml`
- ON CONFLICT for duplicate handling
- Auto-update `peak_investigation` with unique constraint
- Handles `inf` ratio (stores as 999.0)

---

### `analyze_and_track.py` ⭐ INTELLIGENT ANALYSIS
**Purpose:** Trace-based root cause analysis + error pattern tracking

**Classes:**
- `TraceAnalyzer` - Groups errors by trace_id, finds root causes
- `ErrorPatternTracker` - Creates hash-based patterns, tracks to DB
- `KnownIssuesMatcher` - Matches against known issues

**What it does:**
1. Fetches ALL errors from ES (via fetch_unlimited.py)
2. Groups by trace_id, finds first error = root cause
3. Creates pattern hash for each error type
4. Updates `error_patterns` table
5. Matches against `known_issues`

---

### `enrich_peaks.py` 🆕 PEAK ENRICHMENT
**Purpose:** Add trace_id and analysis details to detected peaks

**What it does:**
1. Finds peaks in `peak_investigation` with missing trace_id
2. Fetches errors from ES for that time window + namespace
3. Identifies most representative trace_id
4. Classifies error type (timeout, connection, database, etc.)
5. Updates peak with trace_id, app_name, error_type, affected_services

**Usage:**
```bash
# Enrich all peaks without trace_id
python3 enrich_peaks.py --all

# Enrich specific peak
python3 enrich_peaks.py --peak-id 5
```

---

## 🗄️ Database Tables

| Table | Purpose | Retention |
|-------|---------|-----------|
| `peak_raw_data` | Raw error counts per 15-min window | 30 days |
| `aggregation_data` | Rolling baseline (mean, stddev, samples) | Permanent |
| `peak_investigation` | Detected peaks with full context | Forever |
| `known_issues` | Active bugs with patterns | Until resolved |
| `known_peaks` | Resolved issues with solutions | Forever |
| `error_patterns` | Every error pattern for AI analysis | 90 days |

**Constraints:**
- `peak_investigation`: UNIQUE on (timestamp, namespace)
- `peak_raw_data`: UNIQUE on (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)

---

## 📋 Typical Workflows

### Fresh Start (New Installation)
```bash
# 1. Create DB schema
python3 create_investigation_tables.py
python3 grant_permissions.py

# 2. Run INIT phase (December 2025 baseline)
./batch_ingest.sh --init

# 3. Fill missing grid combinations
python3 fill_missing_windows_fast.py

# 4. Run REGULAR phase (January 2026)
./batch_ingest.sh --regular

# 5. Enrich peaks with trace analysis
python3 enrich_peaks.py --all
```

### Daily Cron Job
```bash
# Every 15 minutes
python3 run_pipeline.py

# Every hour - enrich new peaks
python3 enrich_peaks.py --all
```

### Validate Detection
```bash
python3 validate_detection.py
```

---

## 📁 Archived Scripts

Old/deprecated scripts moved to `_archive_scripts/`:
- `ingest_from_log.py` (replaced by v2)
- `setup_peak_db.py` (replaced by create_investigation_tables.py)
- `test_*.py` (test scripts)
- `verify_*.py` (old verification)
- `check_*.py` (old checks, replaced by validate_detection.py)
- Various old batch scripts

---

## 🔧 Configuration

### values.yaml
```yaml
peak_detection:
  min_ratio_multiplier: 3.0      # Ratio threshold for peak
  max_ratio_multiplier: 5.0      # Upper bound
  dynamic_min_multiplier: 2.5    # 24h average multiplier
  min_absolute_value: 100        # Minimum error count
  same_day_window_count: 3       # Reference windows (-15, -30, -45 min)
```

### .env
```bash
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_analyzer_user_d1
DB_PASSWORD=xxx

ES_HOST=https://elasticsearch-test.kb.cz:9500
ES_USER=XX_PCBS_ES_READ
ES_PASSWORD=xxx
```

---

**Version:** 4.0 | **Updated:** 2026-01-16 | **Phase:** REGULAR (January 2026)
