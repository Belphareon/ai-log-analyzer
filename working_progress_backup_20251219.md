# 🔄 Working Progress - AI Log Analyzer

**Projekt:** AI Log Analyzer - Phase 5B (Production Readiness)  
**Poslední update:** 2025-12-19 15:15 UTC  
**Status:** ✅ Peak detection HOTOVO! | ✅ Data v DB | 🔄 Next: Verifikace + Deploy

---

## 📋 AKTUÁLNÍ STAV (2025-12-19)

### ✅ HOTOVO DNES

| Task | Status | Details |
|------|--------|---------|
| Peak Detection Implementace | ✅ | `detect_and_skip_peaks()` v ingest_from_log.py |
| Baseline Normalization | ✅ | reference < 5 → use 5 |
| Batch Ingest (9 files) | ✅ | 6,678 parsed → 6,599 inserted, 79 peaks skipped |
| DB Population | ✅ | 3,393 rows (po UPSERT deduplikaci) |
| Peak Verification | ✅ | Kritické peaks (2884-2899 v pcb-ch-sit) jsou skipnuty |

### 📊 RESULTS (2025-12-19 14:40 UTC)

```
Input:    6,678 parsed patterns
Skipped:  79 peaks (1.2% - správné anomálie)
Inserted: 6,599 rows
DB Final: 3,393 rows (UPSERT agregace)

Top Skipped Peaks:
- Thu 07:00 pcb-ch-sit: 2884.0 (46.5×) ✅
- Fri 07:00 pcb-ch-sit: 2899.0 (46.8×) ✅
- Mon 15:30 pcb-dev: ~150× ✅
- Sat 07:00 pcb-ch-sit: 2895.0 (46.7×) ✅
```

---

## 📋 TODO - Next Steps (Priority)

### 1️⃣ VERIFY DATA QUALITY
- [ ] Check max value v DB: `SELECT MAX(mean_errors) FROM peak_statistics;`
- [ ] Check distribution: `SELECT hour_of_day, COUNT(*) FROM peak_statistics GROUP BY hour_of_day;`
- [ ] Ověřit že MAX value < 1000 (peaks jsou skipnuty)

### 2️⃣ PREPARE FOR DEPLOYMENT
- [ ] Review Peak Detection CODE one more time
- [ ] Update README.md s Phase 5B results
- [ ] Commit: "Phase 5B: Peak detection + batch ingest complete"
- [ ] Tag: v0.4.1-peak-detection

### 3️⃣ PHASE 6: DEPLOYMENT TO K8S
- [ ] Build Docker image: `docker build -t ai-log-analyzer:v0.4.1 .`
- [ ] Push to Harbor: `docker push dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:v0.4.1`
- [ ] Deploy to nprod cluster: `kubectl apply -f k8s/`
- [ ] Verify pods running: `kubectl get pods -n ai-log-analyzer`

### 4️⃣ FINALIZATION
- [ ] Smoke tests v prod
- [ ] Monitor CPU/Memory
- [ ] Archive working_progress.md → SESSION_2025_12_19.md (v _archive_md/)

---

## 🔑 KEY INFO FOR NEXT SESSION

**Database:**
- Host: P050TD01.DEV.KB.CZ:5432
- Table: ailog_peak.peak_statistics
- Current rows: 3,393
- Peak detection: ✅ ACTIVE (threshold 15×, baseline normalization)

**Code:**
- Peak detection: `scripts/ingest_from_log.py` (lines 89-153)
- Baseline normalization: `reference = max(5, reference)`
- Threshold: 15× ratio → SKIP (with logging)

**Data Files:**
- 9× peak_fixed_*.txt files in /tmp/ (ready for re-ingest if needed)
- Peak logs: /tmp/peaks_skipped.log (contains all skipped peaks)

**Last Commit:**
- Need to commit: "Phase 5B: Peak detection + batch ingest - 6,599 rows inserted, 79 peaks skipped"

---

## 📝 SESSION NOTES (2025-12-19)

### Root Cause Found & Fixed
Problem: Peak detection hledala v DB, ale DB byla prázdná během prvního ingest
Solution: Změnit logiku na hledání v parsed data (dostupných ihned)

### Implementation Details
1. Created `detect_and_skip_peaks()` - kombinovaná logika:
   - 3 okna PŘED (same day: -15min, -30min, -45min)
   - 3 dny zpět (same time: day-1, day-2, day-3)
   - reference = (avg_windows + avg_days) / 2
   
2. Baseline normalization:
   - if reference < 5: reference = 5
   - Důvod: Malé baseline → přirozená variabilita, ne anomálie

3. Threshold aplikace:
   - ratio = current_value / reference
   - if ratio >= 15: SKIP (is_peak=True)
   - Log: timestamp, namespace, ratio, values

### Verification
✅ Peaks jsou správně skipnuty
✅ DB obsahuje normální hodnoty (bez anomálií)
✅ UPSERT deduplikace funguje (6,678 → 6,599 → 3,393 rows)

---

## ⚡ QUICK COMMANDS

```bash
# Check DB
psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer_user_d1 ailog_analyzer -c \
  "SELECT COUNT(*), MAX(mean_errors) FROM ailog_peak.peak_statistics;"

# Re-ingest if needed
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate
for f in /tmp/peak_fixed_*.txt; do python scripts/ingest_from_log.py --input "$f"; done

# Check logs
tail -f /tmp/peaks_skipped.log
tail -f /tmp/ingest.log
```

---

**📌 Last Updated:** 2025-12-19 15:15 UTC  
**📌 Next Session Focus:** Data verification + K8s deployment prep
