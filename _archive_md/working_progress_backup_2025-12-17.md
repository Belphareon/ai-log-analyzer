# 🔄 Working Progress - AI Log Analyzer (AKTUÁLNÍ)

**Projekt:** AI Log Analyzer - Phase 5B (Peak Detection Optimization)  
**Poslední update:** 2025-12-17 09:00 UTC  
**Status:** 🎯 Optimizing peak detection threshold and implementing ratio categories

---

## 📊 CURRENT SESSION - 2025-12-17

### ✅ CONTEXT RETRIEVED
- Phase 5A COMPLETE: 16 days baseline data ingested (2025-12-01 to 2025-12-16)
- Total: 6,678 patterns → 6,585 inserted (98.6%), 93 peaks skipped (1.4%)
- Final DB: 3,392 aggregated rows
- Current threshold: 10× (too aggressive - captures recurring patterns)

### 🎯 TODAY'S GOALS (Phase 5B Optimization)
1. **Change threshold:** 10× → 15× (user preference over 20×)
2. **Implement ratio categories:**
   - Skip >100× (extreme anomalies)
   - Analyze 15-50× (moderate peaks for investigation)
   - Keep <15× (normal patterns)
3. **Re-run batch ingestion** with new logic
4. **Investigate systematic peaks:**
   - Thursday 8am (40K errors)
   - Monday 3:30pm (6-10K errors)
   - Saturday midnight (10-34K errors)

---

## 📊 PREVIOUS STATUS (Phase 5A - COMPLETED)

### ✅ COMPLETED TODAY

| Task | Status | Details |
|------|--------|---------|
| Smazat testovací data z DB | ✅ | 186 rows deleted |
| Vytvořit `ingest_from_log.py` | ✅ | Script created & tested |
| Aktualizovat `scripts/INDEX.md` | ✅ | Full workflow documented |
| Spustit sbírání 2025-12-01 (v1) | ✅ | Jen 5 patterns - BUG FOUND |
| **BUG: Sbírání jen 5 patterns** | 🐛 FOUND | `print_detailed_report()` limited output |
| **FIX: Oprava collect_peak_detailed.py** | ✅ | Removed `[:5]` limit - ALL patterns |
| **Ingest 2025-12-01 (v1)** | ✅ | 186 rows loaded BUT timezone offset -1h! |
| **TIMEZONE BUG FOUND** | 🐛 FOUND | Data in DB shifted -1 hour vs reality |
| **ROOT CAUSE:** | 🔍 | Using `win_end.hour` instead of `win_start.hour` |
| **FIX: Timezone correction** | ✅ | Changed to `win_start.weekday()`, `win_start.hour` |
| **Re-collecting 2025-12-01** | ✅ | PID 30444 - RUNNING with fix |

## 🔧 SMOOTHING ALGORITHM (TO IMPLEMENT)

**Goal:** Detect real peaks by smoothing outliers using 3-window + cross-day aggregation

**Algorithm:**
```
For each time bucket (day_of_week, hour, quarter, namespace):

1. HORIZONTAL SMOOTHING (same day):
   - Take current + adjacent time windows (±2 = 5 windows total)
   - Calculate average: smooth_h = mean(win[i-2:i+3])
   
2. VERTICAL SMOOTHING (same time, different days):
   - For SAME time bucket from 3+ previous days
   - Calculate average: smooth_v = mean(day1, day2, day3)
   
3. COMBINE:
   - final_mean = (smooth_h + smooth_v) / 2
   - If only 1 day available: use only smooth_h
   - If no adjacent windows: use smooth_h with available neighbors
```

**Example (as user specified):**
```
Day 1 (2025-12-01):
  13:30 = 25, 13:45 = 4, 14:00 = 51, 14:15 = 9, 14:30 = 13433, 14:45 = 41303
  After smoothing:
    14:30 = (25+4+51+9+13433)/5=2704 (horizontal) 
           + later cross-day data (vertical)

Day 2-3: Will add vertical smoothing when available
```

**Current Status:** Pending - need 3+ days of data first

**Problem:**
- ES shows peak at **14:00:00 UTC (81,171 errors)** for pcb-dev-01-app on 2025-12-01
- DB stores same peak as **hour=13 (41,303 mean_errors)**
- **ALL data stored with -1 hour offset**

**Root Cause Investigation:**
1. Changed `collect_peak_detailed.py` from `win_end` to `win_start` for hour calculation
2. **BUT:** Data collected after change show SAME offset (-1 hour)
3. **CONCLUSION:** Either:
   - Python cache still running old code, OR
   - Bug is in `group_into_windows()` or timestamp parsing from ES

**Workaround Solution (IMMEDIATE):**
- FIX: Add +1 hour offset in `ingest_from_log.py` when parsing
- This corrects all data being inserted to DB
- Will apply to parser: `hour_of_day = (hour_of_day + 1) % 24`

**Root Cause Fix (LATER):**
- Debug `collect_peak_detailed.py` with print statements
- Verify windows are generated correctly
- Check ES timestamp parsing
- May need to re-run collection AFTER confirming fix works

### 🔄 CURRENTLY RUNNING

```
Terminal (Background):
  PID:     30444 (was 30443)
  Command: collect_peak_detailed.py --from "2025-12-01T00:00:00Z" --to "2025-12-02T00:00:00Z"
  Output:  /tmp/peak_fixed_2025_12_01.txt (BUILDING)
  Status:  ⏳ COLLECTING (WITH TIMEZONE FIX)
  
NEXT STEPS:
  1. ✅ Check if PID still running: ps aux | grep 30444
  2. ✅ When done: grep -c "^   Pattern " /tmp/peak_fixed_2025_12_01.txt
  3. ✅ Ingest: python ingest_from_log.py --input /tmp/peak_fixed_2025_12_01.txt
  4. ✅ Verify: SELECT * FROM peak_statistics WHERE hour_of_day IN (14,15) LIMIT 5
```

### 📋 TODO NEXT - 2025-12-17 (PRIORITY ORDER)

```
PHASE 5B-1 (PEAK DETECTION OPTIMIZATION - IN PROGRESS):
  [✅] 1. Review ingest_from_log.py peak detection logic
  [✅] 2. Change threshold: 10× → 15×
  [✅] 3. Implement ratio categories:
          - Skip >100× → 🔴 EXTREME PEAK (logged)
          - Skip 50-100× → 🟠 SEVERE PEAK (logged)
          - Skip 15-50× → 🟡 MODERATE PEAK (logged)
          - Keep <15× → ✅ NORMAL (insert to DB)
  [✅] 4. Create clear_peak_db.py utility script
  [✅] 5. Refactor scripts/INDEX.md → clean AI reference (removed statuses, dates)
  [ ] 6. Clear DB: DELETE FROM peak_statistics
  [ ] 7. Test with 2025-12-01 data (small batch)
  [ ] 8. Verify category logic works correctly
  [ ] 9. Re-run full batch ingestion (all 9 files)
  [ ] 10. Compare results: old (93 skipped) vs new

CHANGES MADE (2025-12-17 09:15-09:35 UTC):
  ✅ detect_and_skip_peaks(): Changed from boolean to ratio return
  ✅ Threshold: 10× → 15× 
  ✅ Ratio categories implemented:
     - ratio > 100: 🔴 EXTREME PEAK SKIPPED
     - ratio 50-100: 🟠 SEVERE PEAK SKIPPED  
     - ratio 15-50: 🟡 MODERATE PEAK FOR ANALYSIS
     - ratio < 15: ✅ INSERT NORMALLY
  ✅ Created clear_peak_db.py utility
  ✅ Updated scripts/INDEX.md with:
     - Phase 5B status
     - ingest_from_log.py peak detection details
     - clear_peak_db.py documentation
     - Re-ingestion workflow

PHASE 5B-2 (SYSTEMATIC PEAKS INVESTIGATION):
  [ ] 9. Extract all peaks >100× from logs
  [ ] 10. Analyze Thursday 8:00-8:30 pattern (pcb-dev-01-app)
  [ ] 11. Analyze Monday 15:30 pattern (multi-namespace)
  [ ] 12. Analyze Saturday 0:00-1:00 pattern (pcb-sit-01-app)
  [ ] 13. Correlate with CI/CD deployment logs
  [ ] 14. Document findings in PEAK_DETECTION_PROGRESS

PHASE 5B-3 (FINALIZATION):
  [ ] 15. Update CONTEXT_RETRIEVAL_PROTOCOL.md
  [ ] 16. Commit changes with detailed message
  [ ] 17. Prepare for Phase 6 (K8s deployment)
```

---

## 💾 DATA FILES

| File | Status | Notes |
|------|--------|-------|
| `/tmp/peak_full_2025_12_01.txt` | ❌ DELETED | v1 - had 186 patterns BUT with -1h offset |
| `/tmp/peak_fixed_2025_12_01.txt` | ⏳ COLLECTING | v2 - WITH TIMEZONE FIX (PID 30444) |
| `/tmp/peak_full_2025_12_02_03.txt` | 📋 TODO | |

---

## 🔧 COMMITS

```
Current Branch: main
Recent commits:
  - (pending) Timezone fix: Use win_start instead of win_end
  - e9b0280    Phase 5: Session complete - 2025-12-01 data loaded (186 patterns)
  - 0e83956    Status update
  - 5996374    Phase 5: Fix collect_peak_detailed.py to output ALL patterns
```

## 🚨 PRAVIDLA

⚠️ **NE RUŠIT BĚŽÍCÍ PROCES** - Sbírání trvá 2-3 minuty!  
⚠️ **PRACUJ V JINÉM TERMINÁLU** - Nech PID 30070 být!  
⚠️ **VŽDYCKY EXPLICIT DATES** - `--from "2025-12-XXT00:00:00Z" --to "2025-12-YYT00:00:00Z"`  
⚠️ **Z SUFFIX** - Elasticsearch potřebuje Z, ne +00:00  

---

## 🔑 KEY INFO

**DB:**
- Host: P050TD01.DEV.KB.CZ:5432
- DB: ailog_analyzer
- Table: ailog_peak.peak_statistics
- Current rows: 5 (stará data - bude se přepsat)
- Expected after 2025-12-01 load: 384 rows

**Scripts Updated:**
- `collect_peak_detailed.py` - ✅ FIXED (output ALL patterns)
- `ingest_from_log.py` - ✅ WORKS
- `scripts/INDEX.md` - ✅ UPDATED

**Git Commit:**
- SHA: 5996374
- Msg: "Phase 5: Fix collect_peak_detailed.py to output ALL patterns"

**Archiv starších logů:** `_archive_md/COMPLETED_LOG_2025_12_16.md`
