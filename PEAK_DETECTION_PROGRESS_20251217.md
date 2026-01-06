# Peak Detection Progress Report
**Date:** 2025-12-17  
**Phase:** 5A - Peak Detection Baseline Collection  
**Status:** ✅ COMPLETE - Data Ingested with Peak Detection Active

---

## Executive Summary

Successfully collected and ingested **16 days of baseline data** (2025-12-01 to 2025-12-16) with intelligent peak detection algorithm. Total **6,678 patterns** processed, **6,585 inserted** (98.6%), **93 peaks skipped** (1.4%). Final database contains **3,392 aggregated rows** with multi-day smoothing via Welford's algorithm.

---

## Data Collection Results

### Files Processed (9 total)
```
/tmp/peak_fixed_2025_12_01.txt       → 186 patterns
/tmp/peak_fixed_2025_12_02_03.txt    → 712 patterns
/tmp/peak_fixed_2025_12_04_05.txt    → 946 patterns
/tmp/peak_fixed_2025_12_06_07.txt    → 843 patterns
/tmp/peak_fixed_2025_12_08_09.txt    → 968 patterns
/tmp/peak_fixed_2025_12_10_11.txt    → 947 patterns
/tmp/peak_fixed_2025_12_12_13.txt    → 930 patterns
/tmp/peak_fixed_2025_12_14_15.txt    → 896 patterns
/tmp/peak_fixed_2025_12_16.txt       → 250 patterns
---------------------------------------------------
TOTAL:                                6,678 patterns
```

### Ingestion Statistics
- **Inserted:** 6,585 rows (98.6%)
- **Failed:** 0 rows (0%)
- **Skipped (peaks):** 93 rows (1.4%)
- **Final DB rows:** 3,392 (with multi-day aggregation)

---

## Peak Detection Analysis

### Algorithm Configuration (Current)
```python
THRESHOLD: 10× median of reference values
REFERENCES: 3 previous days, same time slot
FORMULA: if current > median(refs) * 10 → SKIP
```

### Detected Peaks by File

**2025-12-01:** 0 peaks (baseline day)

**2025-12-02_03:** 0 peaks

**2025-12-04_05:** 15 peaks
```
(3,22,3,pcb-dev-01-app): 46.0 (ratio: 11.5×)
(3,23,0,pcb-dev-01-app): 573.0 (ratio: 17.4×)
(3,23,1,pcb-dev-01-app): 532.0 (ratio: 66.5×)
(3,23,1,pcb-fat-01-app): 530.0 (ratio: 265.0×)
(3,23,1,pcb-uat-01-app): 529.0 (ratio: 132.2×)
(4,8,0,pcb-dev-01-app): 13154.0 (ratio: 398.6×) ⚠️
(4,8,1,pcb-dev-01-app): 40856.0 (ratio: 5107.0×) 🔴 EXTREME
(4,8,2,pcb-dev-01-app): 10226.0 (ratio: 538.2×) ⚠️
```

**2025-12-06_07:** 3 peaks

**2025-12-08_09:** 18 peaks
```
(0,15,2,pcb-dev-01-app): 8352.0 (ratio: 334.1×) ⚠️
(0,15,2,pcb-fat-01-app): 9835.0 (ratio: 427.6×) ⚠️
(0,15,2,pcb-sit-01-app): 7763.0 (ratio: 646.9×) ⚠️
(0,15,2,pcb-uat-01-app): 9593.0 (ratio: 799.4×) ⚠️
```

**2025-12-10_11:** 18 peaks
```
Multiple pca-dev-01-app peaks at 68 errors (ratio: 13.6×)
pcb-sit-01-app peaks 17:00-19:00 (ratios: 20-54×)
```

**2025-12-12_13:** 6 peaks
```
(6,0,1,pcb-sit-01-app): 9946.0 (ratio: 1989.2×) 🔴 EXTREME
(6,0,2,pcb-sit-01-app): 34276.0 (ratio: 3427.6×) 🔴 EXTREME
```

**2025-12-14_15:** 17 peaks
```
(0,15,2,*): Multiple namespaces 6K-10K errors (ratios: 150-858×) ⚠️
(6,1,0,pcb-sit-01-app): 10855.0 (ratio: 452.3×) ⚠️
```

**2025-12-16:** 4 peaks

---

## Peak Categories Analysis

### 🔴 Extreme Outliers (>1000× ratio) - 3 peaks
```
Thu 8:15 (4,8,1) pcb-dev-01-app: 40,856 errors (5107×)
Sat 0:15 (6,0,1) pcb-sit-01-app: 9,946 errors (1989×)
Sat 0:30 (6,0,2) pcb-sit-01-app: 34,276 errors (3428×)
```
**Action:** ✅ SKIP (clear anomalies)

### ⚠️ Severe Peaks (100-1000× ratio) - ~15 peaks
```
Thu 8:00-8:30 pcb-dev-01-app: 10K-13K errors (334-538×)
Mon 15:30 pcb-*: 6K-10K errors (150-858×)
Sat 1:00 pcb-sit-01-app: 10,855 errors (452×)
```
**Action:** ✅ SKIP (systematic anomalies, likely batch jobs)

### 🟡 Moderate Peaks (20-100× ratio) - ~30 peaks
```
Wed 23:00-23:15 pcb-*: 500-573 errors (66-265×)
Mon 7:00-12:00 pcb-*: 60-150 errors (20-73×)
```
**Action:** ⚠️ CURRENTLY SKIPPED - May want to ANALYZE instead

### 🟢 Low Peaks (10-20× ratio) - ~45 peaks
```
Thu 22:45 pcb-dev-01-app: 46 errors (11.5×)
Sat 4:00 pcb-fat/uat: 69-72 errors (12-17×)
pca-dev-01-app recurring: 68 errors (13.6×) - appears 8× times
```
**Action:** ⚠️ CURRENTLY SKIPPED - Should likely be KEPT (recurring patterns)

---

## Identified Issues & Recommendations

### Issue 1: Threshold Too Aggressive (10×)
**Problem:** Captures legitimate recurring patterns in 10-20× range  
**Evidence:** pca-dev-01-app shows 68 errors repeatedly (13.6×) - clearly systematic  
**User Suggestion:** Move threshold to **15-20×**  
**Recommendation:** **Use 20× threshold**

### Issue 2: No Ratio-Based Categorization
**Problem:** Binary decision (skip or keep) loses valuable data  
**Recommendation:** Implement multi-tier approach:
```python
if ratio > 100:
    action = "SKIP"
    log_to_anomaly_table(...)
elif ratio > 20:
    action = "SKIP"
    log_to_analysis_table(...)  # For investigation
elif ratio > 15:
    action = "KEEP"
    flag_for_review = True
else:
    action = "KEEP"
```

### Issue 3: Systematic Peaks Not Investigated
**Pattern:** Recurring peaks at specific times:
- **Thursday 8:00-8:30:** Massive spikes (40K errors)
- **Monday 15:30:** Multi-namespace spikes (6-10K errors)
- **Saturday 0:00-1:00:** pcb-sit-01-app spikes (10-34K errors)

**Hypothesis:** Batch jobs, deployments, or scheduled tasks  
**Action Required:** Correlate with:
1. CI/CD deployment logs
2. Scheduled job definitions
3. System maintenance windows

---

## Database State

### Connection Info
```
Host: P050TD01.DEV.KB.CZ:5432
Database: ailog_analyzer
Schema: ailog_peak
Table: peak_statistics
```

### Table Schema
```sql
CREATE TABLE ailog_peak.peak_statistics (
    day_of_week INT,           -- 0=Mon, 6=Sun
    hour_of_day INT,           -- 0-23
    quarter_hour INT,          -- 0-3 (0=:00, 1=:15, 2=:30, 3=:45)
    namespace VARCHAR(50),
    mean_errors NUMERIC(10,1),
    stddev_errors NUMERIC(10,1),
    samples_count INT,         -- Number of days aggregated
    last_updated TIMESTAMP,
    PRIMARY KEY (day_of_week, hour_of_day, quarter_hour, namespace)
);
```

### Current Stats
```
Total rows: 3,392
Namespaces: 10 (pcb-dev, pcb-fat, pcb-sit, pcb-uat, pcb-ch-*, pca-*)
Date range: 2025-12-01 to 2025-12-16 (16 days)
Aggregation: Multi-day smoothing via Welford's algorithm
stddev: >0 when samples_count ≥ 2
```

---

## Technical Implementation

### Algorithm: Welford's Online Variance
```python
# Multi-day aggregation formula
new_count = old_count + 1
delta = new_mean - old_mean
new_mean = old_mean + delta / new_count
new_M2 = old_M2 + delta * (new_mean - old_mean)
new_stddev = sqrt(new_M2 / new_count)
```

### Peak Detection Query
```sql
SELECT mean_errors FROM ailog_peak.peak_statistics
WHERE namespace = %s AND (
    (day_of_week = ((current_dow - 1 + 7) % 7) AND hour = %s AND quarter = %s) OR
    (day_of_week = ((current_dow - 2 + 7) % 7) AND hour = %s AND quarter = %s) OR
    (day_of_week = ((current_dow - 3 + 7) % 7) AND hour = %s AND quarter = %s)
)
ORDER BY mean_errors
```

### Timezone Fix Applied
**Problem:** ES data stored with -1 hour offset  
**Solution:** Parser applies `+1 hour` correction:
```python
hour = (hour + 1) % 24
if hour == 0:  # Rolled over to next day
    day_of_week = (day_of_week + 1) % 7
```

---

## Next Steps

### Priority 1: Adjust Threshold
- [ ] Change from **10×** to **20×** in `ingest_from_log.py` line ~128
- [ ] Delete DB data: `DELETE FROM ailog_peak.peak_statistics;`
- [ ] Re-run batch ingestion with new threshold
- [ ] Compare: Expected **~50 peaks skipped** instead of 93

### Priority 2: Implement Ratio Categories
- [ ] Create `peak_analysis` table for 20-100× peaks
- [ ] Create `peak_anomalies` table for >100× peaks
- [ ] Modify parser to insert into appropriate tables
- [ ] Keep main table for <20× data

### Priority 3: Investigate Systematic Peaks
- [ ] Query Jenkins/ArgoCD for deployments on:
  - Thursday 2025-12-05 08:00-08:30
  - Monday 2025-12-09 15:30
  - Saturday 2025-12-14 00:00-01:00
- [ ] Check scheduled jobs in AWX
- [ ] Correlate with namespace patterns

### Priority 4: Documentation
- [ ] Update `scripts/INDEX.md` with peak detection docs
- [ ] Add ratio threshold configuration to `.env`
- [ ] Document peak categories in `CONTEXT_RETRIEVAL_PROTOCOL.md`

---

## Files Modified

### `scripts/ingest_from_log.py`
**Changes:**
- Added `detect_and_skip_peaks()` function
- Integrated peak detection into main insertion loop
- Added ratio logging and statistics tracking
- Implemented value rounding to 1 decimal place

**Key Code:**
```python
is_peak, ref_median = detect_and_skip_peaks(cur, day_of_week, hour_of_day, quarter_hour, namespace, mean_val)
if is_peak:
    ratio = mean_val / ref_median if ref_median > 0 else float('inf')
    print(f"🚨 PEAK DETECTED ({day_of_week},{hour_of_day},{quarter_hour},{namespace}): {mean_val} (ref_median: {ref_median}, ratio: {ratio:.1f}x)")
    skipped_peaks += 1
    continue
```

### `scripts/collect_peak_detailed.py`
**Previous Changes (Completed):**
- Fixed timezone offset (win_start instead of win_end)
- Removed `[:5]` limit on pattern output
- Outputs ALL patterns to log file

---

## Command Reference

### Delete DB and Re-Ingest
```bash
export PGPASSWORD="..." 
psql -h P050TD01.DEV.KB.CZ -U ailog_user -d ailog_analyzer -c "DELETE FROM ailog_peak.peak_statistics;"

for file in /tmp/peak_fixed_2025_*.txt; do
    echo "📥 Ingesting $(basename $file)..."
    python scripts/ingest_from_log.py --input "$file"
done
```

### Query Peak Statistics
```sql
-- Total rows
SELECT COUNT(*) FROM ailog_peak.peak_statistics;

-- Rows per namespace
SELECT namespace, COUNT(*) FROM ailog_peak.peak_statistics GROUP BY namespace ORDER BY COUNT(*) DESC;

-- Top peaks by namespace
SELECT namespace, day_of_week, hour_of_day, quarter_hour, mean_errors, samples_count
FROM ailog_peak.peak_statistics
WHERE namespace = 'pcb-dev-01-app'
ORDER BY mean_errors DESC
LIMIT 20;

-- Multi-day aggregated rows
SELECT namespace, COUNT(*) FROM ailog_peak.peak_statistics WHERE samples_count > 1 GROUP BY namespace;
```

---

## Key Learnings

1. **Timezone Critical:** ES timestamps must be carefully handled - used parser-level correction (+1h offset)
2. **Peak Detection Valuable:** 93 anomalies detected (1.4% of data) that would distort analysis
3. **Threshold Tuning Needed:** 10× too aggressive - captures recurring patterns that should be preserved
4. **Systematic vs Random:** Many peaks are recurring (Thu 8am, Mon 3:30pm, Sat midnight) - likely batch jobs
5. **Multi-Tier Approach:** Binary skip/keep insufficient - need analysis categories (15-20×, 20-100×, >100×)

---

## Contact & Context

**Database:** P050TD01.DEV.KB.CZ:5432/ailog_analyzer  
**Elasticsearch:** elasticsearch-test.kb.cz:9500  
**Docker Image:** dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:v0.4.0-docker-verified  
**Git Branch:** main  
**Work Directory:** ~/git/sas/ai-log-analyzer  

**Next Session:** Adjust threshold to 20×, implement ratio categories, investigate systematic peaks

---
**End of Report**
