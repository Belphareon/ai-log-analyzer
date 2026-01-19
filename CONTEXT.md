# 📋 SESSION CONTEXT - AI Log Analyzer

**For next coding session - Quick reference**

---

## 🎯 Current State (2026-01-19)

### ✅ INIT Phase Complete!
- **INIT Phase**: ✅ DONE - ingested all 31 days of December 2025
- **fill_missing_windows**: ✅ DONE - 36,447 rows in peak_raw_data
- **calculate_baseline**: ✅ DONE - 8,064 rows in aggregation_data
- **Database Backup**: ✅ DONE - backed up to `_backups/` folder

### What's Next
1. Start **REGULAR Phase**: `./scripts/batch_ingest.sh --regular` for January 2026
2. Monitor peak_investigation table for detected peaks
3. Review peak patterns and thresholds

---

## 🔧 Key Files

| File | Purpose |
|------|---------|
| `scripts/batch_ingest.sh` | Orchestrates INIT/REGULAR phases |
| `scripts/ingest_from_log_v2.py` | Main ingestion with peak detection |
| `scripts/fill_missing_windows_fast.py` | Fill gaps with zeros |
| `scripts/calculate_aggregation_baseline.py` | Compute baseline |
| `values.yaml` | Dynamic threshold configuration |
| `.env` | Database credentials |

---

## 💾 Database Status

**Current Data:**
```
peak_raw_data: 36,447 rows (31 days × 12 namespaces × ~96 windows/day + duplicates)
aggregation_data: 8,064 rows (7 days × 12 namespaces per week pattern)
peak_investigation: 0 rows (ready for REGULAR phase)
```

**Backup Location:**
```
/home/jvsete/git/sas/ai-log-analyzer/_backups/ailog_peak_*_20260119_092834.sql
  - ailog_peak_peak_raw_data_20260119_092834.sql (8.0M)
  - ailog_peak_aggregation_data_20260119_092834.sql (1.8M)
```

---

## 📁 Data Files

**December 2025 (INIT - Complete):**
```
/tmp/ai-log-data/final/peak_fixed_2025_12_01.txt to peak_fixed_2025_12_31.txt
Total: 13,482 DATA rows (all 31 days converted and validated)
```

**January 2026 (REGULAR - Pending):**
```
/tmp/ai-log-data/peak_2026_01_*_TS.txt (needs to be prepared)
```

**Data Format:**
```
DATA|2025-12-01T11:15:00|0|11|1|pcb-dev-01-app|10.00|0.00|1
     │                   │ │  │ │              │     │    └─ samples
     │                   │ │  │ │              │     └────── stddev
     │                   │ │  │ │              └──────────── mean_errors
     │                   │ │  │ └─────────────────────────── namespace
     │                   │ │  └────────────────────────────── quarter (0-3)
     │                   │ └───────────────────────────────── hour (0-23)
     │                   └─────────────────────────────────── day_of_week (0=Sun)
     └─────────────────────────────────────────────────────── timestamp
```

---

## 🔗 Important Links

- **DB:** P050TD01.DEV.KB.CZ:5432/ailog_analyzer
- **Schema:** ailog_peak
- **Backups:** [_backups/](file:_backups/)
- **Scripts Index:** [scripts/INDEX.md](scripts/INDEX.md)
- **Roadmap:** [ROADMAP.md](ROADMAP.md)

---

## 🚀 Quick Commands (Next Steps)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Start REGULAR phase (processes January 2026 data with peak detection)
./scripts/batch_ingest.sh --regular

# Check current DB state
python3 << 'PYEOF'
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
for t in ['peak_raw_data', 'aggregation_data', 'peak_investigation']:
    cur.execute(f'SELECT COUNT(*) FROM ailog_peak.{t}')
    print(f'{t}: {cur.fetchone()[0]} rows')
conn.close()
PYEOF

# Restore from backup if needed
# psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer -d ailog_analyzer -f _backups/ailog_peak_peak_raw_data_20260119_092834.sql
```

---

## ⚠️ Important Notes

1. **INIT completion**: Ran ingest for all 31 individual day files from `/tmp/ai-log-data/final/`
2. **Day 15 extraction**: Successfully extracted from batch file `peak_fixed_2025_12_14_15.txt` (patterns 456-878, Sun)
3. **Data validation**: 735 extra rows from duplicates (36,447 vs expected 35,712) - acceptable
4. **Baseline ready**: aggregation_data has complete 7-day pattern (8,064 rows = 7 day_of_week × 12 namespaces × 96 windows)

---

## 📊 Completion Status

| Phase | Status | Date | Notes |
|-------|--------|------|-------|
| INIT - Ingest | ✅ Done | 2026-01-19 | All 31 December days |
| INIT - Fill Missing | ✅ Done | 2026-01-19 | 36,447 total rows |
| INIT - Baseline | ✅ Done | 2026-01-19 | 8,064 aggregation rows |
| INIT - Backup | ✅ Done | 2026-01-19 | `_backups/ailog_peak_*_20260119_092834.sql` |
| REGULAR - Pending | ⏳ Next | - | Ready when Jan data arrives |
