# 🗺️ AI Log Analyzer - Project Roadmap

**Last Updated:** 2026-01-19

---

## 📊 Project Phases

### ✅ Phase 1: INIT (Complete - 2026-01-19)

**Objective:** Load historical December 2025 baseline data into database

**Tasks:**
- ✅ Extract all individual day files from batch sources
- ✅ Convert to DATA|TIMESTAMP|... format for all 31 days
- ✅ Extract day 15 from batch file `peak_fixed_2025_12_14_15.txt`
- ✅ Ingest 13,482 original data rows
- ✅ Fill missing windows with zeros → 36,447 rows
- ✅ Calculate aggregation baseline → 8,064 rows
- ✅ Backup to `_backups/ailog_peak_*_20260119_092834.sql`

**Output:**
```
peak_raw_data:      36,447 rows (complete grid: 31 days × 12 namespaces × ~96 windows)
aggregation_data:    8,064 rows (7-day pattern × 12 namespaces × 96 windows)
```

**Key Data Points:**
- December 1-31, 2025: All 31 individual day files converted
- Timestamps: Corrected to proper dates (not all 2026-01-16)
- Batch files: Properly handled 3-day format with timezone fixes
- Duplicates: 735 extra rows (acceptable, from duplicate patterns)

---

### 🔄 Phase 2: REGULAR (Next - Ready to Start)

**Objective:** Process January 2026 data with real-time peak detection

**Tasks:**
- ⏳ Prepare January 2026 source data files
- ⏳ Ingest daily data from January onwards
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
./scripts/batch_ingest.sh --regular
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
| **Database Setup** | ✅ Complete | v1.0 | 2026-01-19 |
| **INIT Phase** | ✅ Complete | v1.0 | 2026-01-19 |
| **Data Ingestion** | ✅ Complete | v2.0 | 2026-01-19 |
| **Peak Detection** | 🔄 Ready | v1.0 | 2026-01-19 |
| **Baseline Calc** | ✅ Complete | v1.0 | 2026-01-19 |
| **Threshold Logic** | ✅ Complete | v3.0 | 2025-12-28 |
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
- ⏳ January 2026: Pending (0/31 days)

**Database Health:**
- ✅ peak_raw_data: 36,447 rows (36,447 = 100% of expected grid + duplicates)
- ✅ aggregation_data: 8,064 rows (8,064 = 100% of 7-day pattern)
- ✅ peak_investigation: 0 rows (ready for REGULAR phase)

**Performance Targets:**
- Daily ingestion: < 5 minutes per day
- Fill missing windows: < 30 seconds
- Baseline calculation: < 1 minute
- Peak detection: < 10 minutes per 1000 events

---

## 🚀 Next Immediate Steps

1. **Prepare January 2026 data**: Source files in `/tmp/ai-log-data/peak_2026_01_*_TS.txt`
2. **Start REGULAR phase**: `./scripts/batch_ingest.sh --regular`
3. **Monitor peak_investigation**: Check for detected anomalies
4. **Review thresholds**: Adjust values in `values.yaml` if needed
5. **Plan Phase 3**: Analysis and dashboard components

---

## 💾 Backup & Recovery

**Current Backup:** `_backups/ailog_peak_*_20260119_092834.sql`
- 6 files: one per table
- peak_raw_data: 8.0M
- aggregation_data: 1.8M
- Total: 9.7M

**Restore Command:**
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
# Restore individual tables
psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer -d ailog_analyzer < _backups/ailog_peak_peak_raw_data_20260119_092834.sql
psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer -d ailog_analyzer < _backups/ailog_peak_aggregation_data_20260119_092834.sql
```

---

## 📞 Contact & Resources

- **Project Location**: `/home/jvsete/git/sas/ai-log-analyzer`
- **Data Location**: `/tmp/ai-log-data/`
- **Database**: `P050TD01.DEV.KB.CZ:5432/ailog_analyzer` (schema: `ailog_peak`)
- **Documentation**: See [README.md](README.md) and [scripts/INDEX.md](scripts/INDEX.md)
