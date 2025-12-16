# AI Log Analyzer - Phase 4+ Implementation Plan (REVISED 2025-12-04)

## 1. SYSTEM REVIEW & DOCUMENTATION ✅ COMPLETE
a) ✅ Test complete system A-Z - orchestration tool working
b) ✅ Create HOW_TO_USE.md documentation
c) ✅ Verify detection of all issues - PCA, PCB-CH indexes working

---

## 2. PEAK DETECTION & ADVANCED ANALYSIS (IN PROGRESS)

### 2a) PEAK DETECTION & ROOT CAUSE ANALYSIS - REFINED APPROACH

**Core Requirements:**

**1. Time Windows: 10 seconds (maximum precision)**
- Detect peak start exactly to identify where to search for root cause
- Peak can be short or long - size doesn't matter, precision does
- Smaller windows = better root cause detection accuracy

**2. Database Statistics - CRITICAL** 🔴
Must maintain **10,080 statistics records per week:**
- 4 windows per 15 minutes × 96 windows per 24h × 7 days = 10,080 total
- Granularity: 10-second windows mapped to 15-minute blocks
- Records: {cluster, app, namespace, time_of_day, day_of_week, mean, stddev, min, max}
- Continuously improve from each run (rolling window approach)
- Handle special cases later (holidays, Black Friday, etc.)

**3. Peak Persistence** 💾
- `active_peaks` table tracks ongoing peaks (prevent duplicate reports)
- **Report peak START immediately** when detected
- Generate **FINAL report once** when peak ends
- Store: peak_id, start_time, end_time, status, root_causes

**4. Root Cause Detection - FIND THE SOURCE** 🎯
Not "what happened" but "WHY it happened"
- Analyze: What errors occurred BEFORE peak start?
- Trace chain: Find first error that cascaded
- Example:
  * 13:07:45 - upstream_service timeout (ROOT CAUSE)
  * 13:08:00 - bl-pcb-v1 starts failing (PROPAGATION)
  * 13:08-13:10 - cascade to billing, event processor (IMPACT)

**5. Peak Impact Analysis** ��
- What was the BIGGEST problem during peak?
- Include error message details (not just generic type)
- Show which apps/namespaces affected
- Propagation chain: root → primary → secondary failures

**6. Report Timing** 📡
**ALERT on peak detection (immediate):**
```
🚨 Peak detected at 2025-12-03T13:08:00 UTC
  - 10s window: 45 errors (3x baseline 15/min)
  - Root cause identified: upstream_service timeout
  - Monitoring for progression...
```

**FINAL REPORT when peak ends:**
```
## Peak Summary: 2025-12-03T13:08-13:10 UTC (2 min)
- Total errors: 156 (baseline: ~40 during 2min window)
- Root cause: upstream_service unavailable (timeout at 13:07:45)
- Biggest problem: Card lookup failures (101 errors)
- Affected apps: bl-pcb-v1 (120), bl-pcb-billing-v1 (36)
- Affected namespaces: pcb-dev-01-app, pcb-fat-01-app, pcb-uat-01-app
- Propagation: timeout → bl-pcb-v1 circuit breaker → cascade downstream
- Error examples: "Resource not found. Card ID 121218", "HTTP 503 Service Unavailable"
```

---

### Implementation Phases:

**PHASE 1: Database Setup (PRIORITY - BLOCKS EVERYTHING)**
- [ ] Connect to PostgreSQL (P050TD01) with dual accounts
- [ ] Create `peak_statistics` table:
  - cluster, app, namespace, hour_of_day, day_of_week, mean, stddev, min, max
  - 10,080 records per week (rolling window)
- [ ] Create `active_peaks` table:
  - peak_id, cluster, start_time, end_time, status (in_progress/ended)
- [ ] Create `peak_errors` table:
  - peak_id, error_id, timestamp, app, message, is_root_cause

**PHASE 2: Peak Detection (depends on PHASE 1)**
- [ ] Implement 10-second windowing in data collection
- [ ] Load baseline statistics from DB
- [ ] Compare: current_window_count vs (baseline_mean + 2*baseline_stddev)
- [ ] Flag as peak if threshold exceeded
- [ ] Store in active_peaks table (for persistence)

**PHASE 3: Root Cause Analysis (depends on PHASE 2)**
- [ ] When peak detected, analyze 5-10 minutes before
- [ ] Find first error that differs from baseline (anomaly)
- [ ] Extract full error chain (trace_id based)
- [ ] Identify "patient zero" (first error in cascade)
- [ ] Determine root cause category (timeout, unavailable, permission, etc.)

**PHASE 4: Impact Analysis (depends on PHASE 2)**
- [ ] Analyze all errors during peak period
- [ ] Find most common error type (biggest problem)
- [ ] Calculate app/namespace distribution during peak
- [ ] Compare with normal baseline distribution
- [ ] Extract error message examples

**PHASE 5: Reporting (depends on PHASE 3 & 4)**
- [ ] Alert immediately on peak detection
- [ ] Final report on peak completion
- [ ] Include: root_cause, impact, propagation chain
- [ ] Add error message examples
- [ ] Show comparison with baseline

**PHASE 6: Statistics Learning (continuous)**
- [ ] After each run, update peak_statistics table
- [ ] Use exponential moving average (EMA) for smoothing
- [ ] Store raw data (rolling window, keep 2-4 weeks)
- [ ] Recalculate mean/stddev daily for accuracy

---

### 2b) Known Issues Storage (REFINED - AFTER 2a)
To be finalized after peak detection is working.
Current thinking:
- Create `known_issues` table in same DB
- Format: {issue_id, pattern_hash, first_occurrence, last_seen, occurrence_count, severity}
- Use pattern_hash to deduplicate across runs
- Track escalation (count increases = flag for investigation)

### 2c) ML Pattern Recognition Verification
- Verify intelligent_analysis.py correctly identifies patterns
- "New patterns" = errors with count < 5
- Optimize for DB integration (Point 4c)

---

## 3. ENHANCED ASSESSMENT & REPORTING (LATER - DEPENDS ON 2a)
a) Advanced evaluation using peak detection + apps + namespaces
b) Trace-based log search for all severity levels (not just ERROR)
c) Enhanced reporting with recommendations and confidence scoring

---

## 4. AUTONOMOUS MODE & DATABASE (PRIORITY PARALLEL WITH 2a)
a) Database connection (P050TD01) - PRIORITY
b) Deploy agent to cluster for autonomous execution
c) Setup regular evaluation and feedback loop (daily → 2-3x/week)

**Database Credentials:**
- ailog_analyzer_ddl_user_d1/WWvkHhyjje8YSgvU
- ailog_analyzer_ddl_user_d2/rO1c4d2ocn3bAHXe
- ailog_analyzer_user_d1/y01d40Mmdys/lbDE
- ailog_analyzer_user_d2/qE+2bfLaXc3FmoRL
- JDBC: jdbc:postgresql://P050TD01.DEV.KB.CZ:5432/ailog_analyzer

---

## 5. TEAMS ALERTING INTEGRATION (LATER)
- Connect to Teams channel for alert propagation
- Integrate peak alerts and final reports
- Test in production environment

---

## 6. MONITORING & DOCUMENTATION (LATER)
- Setup agent monitoring and learning progress tracking
- Create how-to guide for other squads
- Monitor statistics quality and peak detection accuracy

