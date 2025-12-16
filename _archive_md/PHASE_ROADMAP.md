# 🗺️ Phase Roadmap - AI Log Analyzer

**Vytvořeno:** 2025-12-16  
**Zdroj:** Archivované todo_final*.md (Phase 4+ planning)  
**Status:** Phase 4 COMPLETE | Phase 5-6 IN PLANNING

---

## 📋 Overview

Projekt prochází fázemi development. Aktuální stav:

- ✅ **Phase 1-4:** COMPLETE (Orchestration, Docker, K8s)
- 🔄 **Phase 5:** IN PROGRESS (Peak Detection Baseline Collection)
- 📋 **Phase 6+:** PLANNED

---

## 🎯 Phase 5: Peak Detection Baseline Collection (CURRENT)

**Cíl:** Sbírání baseline peak detection dat pro anomaly detection

**Tasks:**
1. [ ] Sbírat error counts z ES v 15-minutových oknech (collect_peak_detailed.py) ✅
2. [ ] Exportovat data do CSV tabulky ✅
3. [ ] Vyčistit DB (DELETE staré záznamy)
4. [ ] Nahrát data do `peak_statistics` tabulky
5. [ ] Verifikovat integritu dat

**Timeline:** 2025-12-16 - 2025-12-18

---

## 📊 Phase 6+: Peak Detection & Advanced Analysis (PLANNED)

### Phase 6a: Database Setup (PRIORITY - Blocks Everything)
- [ ] Ověřit PostgreSQL connectivity (P050TD01)
- [ ] Vytvořit `peak_statistics` tabulka:
  - Struktura: day_of_week, hour_of_day, quarter_hour, namespace
  - Statistiky: mean, stddev, min, max per time pattern per namespace
  - Kapacita: 10,080 records per week (7 days × 24h × 4 quarters × ~15 namespaces)

- [ ] Vytvořit `active_peaks` tabulka:
  - Sledování in-progress peaks
  - Struktura: peak_id, cluster, start_time, end_time, status

- [ ] Vytvořit `peak_errors` tabulka:
  - Linkování errors k peaks
  - Root cause tracking

### Phase 6b: Peak Detection Implementation
- [ ] Implementovat 10-15 second windowing
- [ ] Load baseline statistics z DB
- [ ] Srovnání: current_window vs (baseline_mean + 2*stddev)
- [ ] Algoritmus: Flag peak pokud exceeds threshold
- [ ] Persistence: Store v `active_peaks` table

### Phase 6c: Root Cause Analysis
- [ ] Analyzovat 5-10 minut PŘED peak start
- [ ] Najít první anomalní error (differs from baseline)
- [ ] Extract error chain pomocí trace_id
- [ ] Identify "patient zero" (first error v cascade)
- [ ] Determine root cause category (timeout, unavailable, permission, etc.)

### Phase 6d: Impact Analysis
- [ ] Analyzovat všechny errors během peak
- [ ] Determine BIGGEST PROBLEM během peak
- [ ] Show app/namespace distribution
- [ ] Propagation chain: root → primary → secondary failures

### Phase 6e: Reporting & Alerting
- [ ] ALERT on peak detection (immediate):
  ```
  🚨 Peak detected at 2025-12-03T13:08:00 UTC
    - 10s window: 45 errors (3x baseline 15/min)
    - Root cause identified: upstream_service timeout
    - Monitoring for progression...
  ```

- [ ] FINAL REPORT when peak ends:
  ```
  ## Peak Summary: 2025-12-03T13:08-13:10 UTC (2 min)
  - Total errors: 156 (baseline: ~40 during 2min window)
  - Root cause: upstream_service unavailable
  - Biggest problem: Card lookup failures (101 errors)
  - Affected apps: bl-pcb-v1 (120), bl-pcb-billing-v1 (36)
  ```

### Phase 6f: Statistics Learning (Continuous)
- [ ] Continuous improvement z každého run
- [ ] Rolling window approach
- [ ] Handle special cases later (holidays, Black Friday, etc.)

---

## 🔄 Phase 7: Automation & Deployment

- [ ] Deploy agent do K8s clusteru (autonomous)
- [ ] Regular evaluation loop (weekly)
- [ ] Teams channel integration (alerting)
- [ ] Monitoring & optimization

---

## 📝 Database Schema (Phase 6a)

### peak_statistics
```sql
CREATE TABLE peak_statistics (
  id SERIAL PRIMARY KEY,
  day_of_week INT,          -- 0-6 (Mon-Sun)
  hour_of_day INT,          -- 0-23
  quarter_hour INT,         -- 0-3 (00, 15, 30, 45 min)
  namespace VARCHAR(255),   -- pcb-sit-01-app, pca-dev-01-app, etc.
  
  mean_errors FLOAT,        -- Baseline average
  stddev_errors FLOAT,      -- Standard deviation
  min_errors INT,           -- Minimum observed
  max_errors INT,           -- Maximum observed
  samples_count INT,        -- How many samples
  
  last_updated TIMESTAMP,
  UNIQUE(day_of_week, hour_of_day, quarter_hour, namespace)
);
```

### active_peaks
```sql
CREATE TABLE active_peaks (
  peak_id SERIAL PRIMARY KEY,
  cluster VARCHAR(100),
  start_time TIMESTAMP,
  end_time TIMESTAMP,
  status VARCHAR(20),       -- in_progress / ended
  detected_at TIMESTAMP,
  root_cause VARCHAR(500)
);
```

### peak_errors
```sql
CREATE TABLE peak_errors (
  id SERIAL PRIMARY KEY,
  peak_id INT REFERENCES active_peaks(peak_id),
  error_id BIGINT,
  timestamp TIMESTAMP,
  app VARCHAR(100),
  namespace VARCHAR(100),
  message TEXT,
  is_root_cause BOOLEAN,
  severity INT
);
```

---

## 🎯 Key Design Points

1. **Time Windows:** 10-15 seconds maximum precision
   - Detects peak start exactly
   - Better root cause identification

2. **Database Statistics:** 10,080 records per week
   - 4 windows per 15 min × 96 windows per 24h × 7 days
   - Granularity: 10s windows mapped to 15-min blocks
   - Continuous improvement from each run

3. **Peak Persistence:**
   - `active_peaks` tracks ongoing peaks
   - **Report peak START immediately**
   - Generate **FINAL REPORT once** when peak ends

4. **Root Cause Detection:**
   - "WHY it happened" not "WHAT happened"
   - Analyze BEFORE peak start
   - Find first error that cascaded
   - Example: upstream_service timeout → bl-pcb-v1 failures → cascade

5. **Peak Impact Analysis:**
   - What was BIGGEST PROBLEM during peak?
   - Include error message details
   - Show apps/namespaces affected
   - Propagation chain

---

## 📌 Current Focus (2025-12-16)

**Immediately:**
1. Complete Phase 5 data collection ✅
2. Export to CSV ✅
3. Clean DB & load data
4. Verify data integrity

**Next week:**
1. Start Phase 6a (DB setup)
2. Implement Phase 6b (peak detection)
3. Test on historical data

**By end of month:**
1. Integrate root cause analysis
2. Deploy to K8s
3. Test with real data

---

## 🔗 Related Files

- **working_progress.md** - Daily session log
- **CONTEXT_RETRIEVAL_PROTOCOL.md** - Quick reference
- **README_SCRIPTS.md** - 8 core scripts documentation
- **_archive_md/todo_final.md** - Detailed specification (reference)
- **_archive_md/todo_final_REVISED.md** - Phase breakdown (reference)

