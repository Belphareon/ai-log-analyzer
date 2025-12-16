# 🔄 Working Progress - AI Log Analyzer (AKTUÁLNÍ)

**Projekt:** AI Log Analyzer - Phase 5A (Data Ingestion)  
**Poslední update:** 2025-12-16 13:10 UTC  
**Status:** 🐛 TIMEZONE BUG FOUND & FIXED - Re-collecting with correction

---

## 📊 CURRENT STATUS

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

### 🐛 BUG DETAILS

**Problem Found:**
```
- Data in DB were shifted -1 hour relative to reality
- Example: Real peak at 14:40 UTC stored as 13:40 (hour=13, quarter=3)
- Root cause: Using win_end (end of 15-min window) instead of win_start
- Window 14:30-14:45 end at 14:45, but data from 14:30-14:45 should use START
```

**Solution Applied:**
```python
# BEFORE (WRONG):
day_of_week = win_end.weekday()
hour_of_day = win_end.hour
quarter_hour = (win_end.minute // 15) % 4

# AFTER (CORRECT):
day_of_week = win_start.weekday()
hour_of_day = win_start.hour  
quarter_hour = (win_start.minute // 15) % 4
```

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

### 📋 TODO NEXT (PRIORITY ORDER)

```
PHASE 1 (IMMEDIATE):
  [ ] 1. Počkat na PID 30444 aby skončil (2-3 min)
  [ ] 2. Zkontrolovat: ls -lh /tmp/peak_fixed_2025_12_01.txt
  [ ] 3. Spustit ingest: python ingest_from_log.py --input /tmp/peak_fixed_2025_12_01.txt
  [ ] 4. OVĚŘIT V DB: Zkontrolovat že hour_of_day je teď SPRÁVNĚ (bez -1h)
  [ ] 5. Commitnout timezone fix: git add & git commit

PHASE 2 (SMOOTHING FIX):
  [ ] 6. Vyřešit smoothing: stddev_errors musí být > 0 (teď je vždy 0)
  [ ] 7. Bude potřeba opravit UPSERT logiku pro agregaci více dní

PHASE 3 (CONTINUE INGESTION):
  [ ] 8. Sbírání 2025-12-02 & 2025-12-03
  [ ] 9. Sbírání zbylých 12 dní (6 batchů po 2 dnech)
  [ ] 10. FINAL: Ověřit všech ~2,976 rows (384 × 16 dní / 2?)
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
