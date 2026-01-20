# 📋 SESSION CONTEXT - AI Log Analyzer

**For next coding session - Quick reference**

---

## 🎯 Current State (2026-01-19 15:00 UTC)

### ⚠️ BUG FOUND & FIXED - INIT Phase Peak Detection!
**Problem:** INIT phase vkládal surová data bez detekce peaků
- Vysoké hodnoty (30k+) se vkládaly jak byly
- Baseline se počítala z **kontaminovaných** dat (s outliers)
- REGULAR fáze měla špatné reference

**Solution:** 
- ✅ INIT phase **NYNÍ detekuje peaky:** `value > 300 OR ratio >= 20×` (intra-day)
- ✅ Detekované peaky se **nahrazují** průměrem z 5 předchozích oken
- ✅ **Vkládá NAHRAZENÉ hodnoty** do `peak_raw_data`
- ✅ Loguje detekci jen do souboru (ne do DB - bez ES metadat)
- ✅ Baseline se počítá z **čistých** dat

### ✅ EXTENDED INIT Phase - Ready for Redo
- **December 1-31, 2025**: Ready to re-ingest WITH peak detection
- **January 1-2, 2026**: Ready to re-ingest WITH peak detection  
- **January 3-6 (12:00), 2026**: Ready to re-ingest WITH peak detection
- **Database Status**: Need to TRUNCATE and start fresh
- **Backup**: Old backups in `_backups/` (11.7M total)

---

## 🔧 Key Files

| File | Purpose |
|------|---------|
| `scripts/batch_ingest.sh` | Orchestrates INIT/REGULAR phases |
| `scripts/ingest_from_log_v2.py` | Main ingestion with peak detection |
| `scripts/fill_missing_windows_fast.py` | Fill gaps with zeros (EXTENDED) |
| `scripts/calculate_aggregation_baseline.py` | Compute baseline |
| `scripts/backup_peak_tables.py` | Database backup (NEW) |
| `values.yaml` | Dynamic threshold configuration |
| `.env` | Database credentials |

---

## 💾 Database Status

**Current Data:**
```
peak_raw_data: 42,790 rows (Dec 1-31 + Jan 1-6 to 12:00)
aggregation_data: 8,064 rows (baseline pattern)
peak_investigation: 0 rows (ready for REGULAR phase)
```

**Backup Location:**
```
_backups/ailog_peak_peak_raw_data_20260119_130329.sql (9.9M, 42,790 rows)
_backups/ailog_peak_aggregation_data_20260119_130338.sql (1.8M, 8,064 rows)
```

---

## 📁 Data Files

**December 2025 (INIT - Complete):**
```
/tmp/ai-log-data/peak_fixed_2025_12_01.txt to peak_fixed_2025_12_31.txt
Total: 13,482 DATA rows (all 31 days converted and validated)
```

**January 1-6 (INIT - Complete):**
```
/tmp/ai-log-data/peak_2026_01_01_TS.txt (445 rows)
/tmp/ai-log-data/peak_2026_01_02_TS.txt (472 rows)
/tmp/ai-log-data/peak_2026_01_03_TS.txt (465 rows)
/tmp/ai-log-data/peak_2026_01_04_TS.txt (474 rows)
/tmp/ai-log-data/peak_2026_01_05_TS.txt (476 rows)
/tmp/ai-log-data/peak_2026_01_06_HALF.txt (212 rows - until 12:00)
Total ingested: 3,144 rows + filled to complete grid = 42,790 total
```

**January 7+ (REGULAR - From ES):**
```
Elasticsearch data collection via run_pipeline.py
Starting from 2026-01-07T00:00:00Z onwards
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

## 🚀 Quick Commands (Next Steps - REDO INIT Phase)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# 0. BACKUP current data (if needed)
python3 scripts/backup_peak_tables.py

# 1. CLEAR old data
python3 -c "
import os, psycopg2
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')), database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
cur.execute('DELETE FROM ailog_peak.peak_raw_data;')
cur.execute('DELETE FROM ailog_peak.aggregation_data;')
cur.execute('DELETE FROM ailog_peak.peak_investigation;')
conn.commit()
print('✅ Tables cleared')
"

# 2. INGEST December 1-31 WITH PEAK DETECTION (INIT phase)
for day in {01..31}; do
  python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_fixed_2025_12_${day}.txt
done

# 3. INGEST January 1-2
python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_2026_01_01_TS.txt
python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_2026_01_02_TS.txt

# 4. INGEST January 3-6 (half)
python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_2026_01_03_TS.txt
python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_2026_01_04_TS.txt
python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_2026_01_05_TS.txt
python3 scripts/ingest_from_log_v2.py --init --input /tmp/ai-log-data/peak_2026_01_06_HALF.txt

# 5. Fill missing windows
python3 scripts/fill_missing_windows_fast.py --start 2025-12-01 --end 2026-01-06 --end-hour 12

# 6. Recalculate baseline from CLEANED data
python3 scripts/calculate_aggregation_baseline.py

# 7. Check results
python3 -c "
import os
os.chdir('/home/jvsete/git/sas/ai-log-analyzer')
from dotenv import load_dotenv
load_dotenv()
import psycopg2
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')), database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
for t in ['peak_raw_data', 'aggregation_data', 'peak_investigation']:
    cur.execute(f'SELECT COUNT(*) FROM ailog_peak.{t}')
    print(f'{t}: {cur.fetchone()[0]:,} rows')
conn.close()
"
```

---

## ⚠️ Important Notes

1. **EXTENDED INIT**: Added Jan 1-6 12:00 to INIT phase (ES data only complete from this point)
2. **Fill missing windows**: Updated script to handle arbitrary date ranges
3. **Database backup**: New Python-based backup script (avoids LDAP issues)
4. **All namespaces complete**: From Jan 6 12:00 onwards, all 12 namespaces have data

---

## 📊 Completion Status

| Phase | Status | Date | Notes |
|-------|--------|------|-------|
| INIT - Ingest Dec | ✅ Done | 2026-01-19 | All 31 December days |
| INIT - Ingest Jan 1-6 | ✅ Done | 2026-01-19 | From batch files, until 12:00 |
| INIT - Fill Missing | ✅ Done | 2026-01-19 | 42,790 total rows |
| INIT - Baseline | ⏳ Next | - | Recalculate for extended data |
| INIT - Backup | ✅ Done | 2026-01-19 | `_backups/ailog_peak_*_20260119_1303*.sql` |
| REGULAR - Pending | ⏳ Next | - | Ready when Jan 7+ data arrives |
