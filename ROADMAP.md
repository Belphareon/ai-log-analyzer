# 🗺️ AI Log Analyzer - Project Roadmap

**Last Updated:** 2026-01-19

---

## 📊 Project Phases

### ✅ Phase 1: EXTENDED INIT (Complete - 2026-01-19)

**Objective:** Load historical baseline data + early January data into database

**Tasks:**
- ✅ Extract all 31 days of December 2025
- ✅ Ingest 13,482 December data rows
- ✅ Ingest January 1-2 from batch files (945 rows)
- ✅ **EXTENDED**: Ingest January 3-6 12:00 from batch files (1,627 rows)
- ✅ Fill missing windows with zeros → 42,790 rows total
- ✅ Backup peak_raw_data: 9.9 MB
- ✅ Backup aggregation_data: 1.8 MB

**Output:**
```
peak_raw_data:      42,790 rows (complete grid: 37 days × 12 namespaces × 96 windows)
aggregation_data:    8,064 rows (baseline pattern for reference)
```

**Key Data Points:**
- December 1-31, 2025: All 31 individual day files
- January 1-2, 2026: From batch files
- January 3-6 (until 12:00), 2026: From batch files (all 12 namespaces now complete)
- Reason for extension: ES data only complete from Jan 6 12:00 onwards

---

### 🔄 Phase 2: REGULAR (Next - Ready to Start)

**Objective:** Process January 7+ 2026 data with real-time peak detection

**Tasks:**
- ⏳ Prepare January 7-31 2026 source data from Elasticsearch
- ⏳ Ingest daily data from January 7 onwards
- ⏳ Compare against aggregation baseline
- ⏳ Detect and categorize peaks in `peak_investigation`
- ⏳ Apply dynamic thresholds from `values.yaml`
- ⏳ Track known patterns and error distribution

**Expected Output:**
```
peak_raw_data:       Growing (30-day rolling retention)
aggregation_data:    Updated daily (rolling 7-day pattern)
peak_investigation:  Grows with detected anomalies
error_patterns:      Learned patterns from deviations
```

**Command:**
```bash
python3 scripts/run_pipeline.py --from "2026-01-07T00:00:00Z" --to "2026-01-31T23:59:59Z"
```

---

### 🚀 Phase 3: Analysis & Optimization (Pending)

**Objective:** Deep analysis of detected peaks and pattern learning

**Tasks:**
- ⏳ Analyze peak frequency per namespace
- ⏳ Identify repeating patterns
- ⏳ Auto-adjust thresholds based on learning
- ⏳ Generate summary reports
- ⏳ Create dashboards (if UI component added)

---

## 🎯 Current Status Matrix

| Component | Status | Version | Last Updated |
|-----------|--------|---------|--------------|
| **INIT Phase - December** | ✅ Complete | v1.0 | 2026-01-19 |
| **INIT Phase - January 1-6** | ✅ Complete | v1.0 | 2026-01-19 |
| **Data Ingestion** | ✅ Complete | v2.0 | 2026-01-19 |
| **Fill Missing Windows** | ✅ Complete | v2.0 | 2026-01-19 |
| **Database Backup** | ✅ Complete | v1.0 | 2026-01-19 |
| **Peak Detection** | ✅ Ready | v1.0 | 2025-12-28 |
| **Baseline Recalc** | ⏳ Pending | v1.0 | - |
| **REGULAR Phase** | ⏳ Ready | v1.0 | 2026-01-19 |
| **LLM Integration** | ⏳ Pending | v0.0 | - |
| **UI/Dashboard** | ⏳ Pending | v0.0 | - |

---

## 📁 File Structure

```
ai-log-analyzer/
├── scripts/
│   ├── batch_ingest.sh                    # INIT/REGULAR orchestrator ✅
│   ├── ingest_from_log_v2.py             # Data ingestion engine ✅
│   ├── fill_missing_windows_fast.py      # Grid completion ✅
│   ├── calculate_aggregation_baseline.py # Baseline computation ✅
│   ├── run_pipeline.py                    # Full pipeline runner
│   └── INDEX.md                           # Scripts documentation
├── values.yaml                             # Dynamic threshold config ✅
├── .env                                    # Database credentials ✅
├── _backups/                               # Database backups ✅
│   └── ailog_peak_*_20260119_092834.sql  # INIT backup
├── ROADMAP.md                              # This file
├── README.md                               # Project overview
├── CONTEXT.md                              # Session context ✅
└── STATUS.md                               # Detailed status
```

---

## 🔧 Key Technical Decisions

1. **Database Schema**: PostgreSQL with `ailog_peak` schema containing 6 tables
2. **Data Format**: Pipe-delimited with specific field ordering
3. **Baseline Approach**: Aggregation per day-of-week (7-day pattern)
4. **Peak Detection**: Ratio-based (threshold multipliers in values.yaml)
5. **Retention Policy**: 30-day rolling window for raw data

---

## ⚠️ Known Issues & Workarounds

| Issue | Status | Notes |
|-------|--------|-------|
| Batch files contain 3 days due to timezone fixes | ✅ Resolved | Pattern extraction implemented |
| Day 15 missing from initial conversion | ✅ Resolved | Manually extracted from batch file |
| 735 duplicate rows in final dataset | ⚠️ Acceptable | Identified as non-critical duplicates |
| LDAP authentication with psql | ⚠️ Workaround | Using Python psycopg2 instead |

---

## 📈 Metrics & Goals

**Data Coverage:**
- ✅ December 2025: 100% (31/31 days)
- ✅ January 1-6 (12:00) 2026: 100% (3.5/3.5 days)
- ⏳ January 7-31 2026: 0/25 days (REGULAR phase)

**Database Health:**
- ✅ peak_raw_data: 42,790 rows (100% coverage for Dec + Jan 1-6)
- ✅ aggregation_data: 8,064 rows (baseline ready)
- ✅ peak_investigation: 0 rows (ready for REGULAR phase)

**Performance Targets:**
- Daily ingestion: < 5 minutes per day
- Fill missing windows: < 30 seconds
- Baseline calculation: < 1 minute
- Peak detection: < 10 minutes per 1000 events
- Backup creation: < 2 minutes

---

## 🚀 Next Immediate Steps

1. **Recalculate baseline** (if needed): `python3 scripts/calculate_aggregation_baseline.py`
2. **Start REGULAR phase**: `python3 scripts/run_pipeline.py --from "2026-01-07T00:00:00Z"`
3. **Monitor peaks**: Check `peak_investigation` table for anomalies
4. **Review thresholds**: Adjust `values.yaml` based on early results
5. **Plan Phase 3**: Analysis and dashboard components

---

## 💾 Backup & Recovery

**Current Backup:** `_backups/ailog_peak_*_20260119_1303*.sql`
- peak_raw_data: 9.9M (42,790 rows)
- aggregation_data: 1.8M (8,064 rows)
- Total: 11.7M

**Restore Command (using Python script):**
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
# Restore individual tables by replaying INSERT statements from backup files
python3 << 'PYEOF'
import psycopg2
# Read and execute INSERT statements from backup files
PYEOF
```

---

## 📞 Contact & Resources

- **Project Location**: `/home/jvsete/git/sas/ai-log-analyzer`
- **Data Location**: `/tmp/ai-log-data/` (batch files: peak_2026_01_*_TS.txt)
- **Database**: `P050TD01.DEV.KB.CZ:5432/ailog_analyzer` (schema: `ailog_peak`)
- **Documentation**: See [README.md](README.md) and [scripts/INDEX.md](scripts/INDEX.md)
