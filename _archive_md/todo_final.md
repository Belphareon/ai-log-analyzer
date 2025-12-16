1. 
a) projit soucasny system/postup od A-Z, vyzkouset, pak revize zbytecnych filu, ktere se nehodi odstranit
b) z toho pak udelat jednoduchou prirucku how to use.md kde bude v krocich popsano, jak se agent obsluhuje, jake scripty pouziva a jak an sebe navazuji

2. DETECTION & ML IMPROVEMENTS (PRIORITY)
a) overit detekci vsech problemu, ze se zadny dulezity nevynecha -> pridat indexy pca, pcb-ch
   - Review fetch_unlimited.py for hardcoded PCB indexes
   - Add support for PCA index (pca-*)
   - Add support for PCB-CH index (pcb-ch-*)
   - Test multi-index queries
   - Update analyze_period.py with new indexes
   
b) overit seznam vsech znamych/dlouhodobych erroru k likvidaci - jira ticket (vymyslet efektivni zpusob kde ukladat)
   - Export current 49 root causes from last run to known_issues_baseline.json
   - Design storage format (JSON + metadata):
     { issue_id, pattern, count, first_seen, last_updated, severity, affected_apps[], affected_namespaces[] }
   - Create known_issues.json file in data/ directory
   - Implement filtering in analyze_period.py to:
     1. Compare new issues against baseline
     2. Highlight ONLY new issues in reports
     3. Track baseline updates (when issue count increases significantly)
   - Setup for future Jira integration (reserve issue_id field)
   
c) potvrdit machine-learning (hlavne aby dokazal diky DB snadneji poznavat uz zname errory) a vyhodnoceni trvalo mensi cas
   - Verify pattern matching logic in intelligent_analysis.py works correctly
   - Check "new unique patterns" calculation (< 5 errors = new pattern?)
   - Optimize query time (currently 4s for 743 errors, acceptable)
   - Prepare for DB integration (Point 4c)

3.
a) vylepsit zpusob vyhodnoceni - zaklad mame, lepe vyzusit kombinaci - apps affected, peak detection/rate app,ns... 
 aby to bylo vic nez klasicky alerting (ktery je velmi uzitecny, nicmene nezachyti vse a nema intelginetnejsi reakci):
Alert 792 - Major
Resource:
prod@cluster-k8s_prod_0792-in@ITO-114@err
Description:
ITO-114#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#114#Problem occurred in case processing step. Processing of step SET_CARD_LIMITS of case 15229758 processing failed due to error Called service OnlineServicesSoap.CardUsageConfigurationMaintenanceRequest error occurred. 1 - Invalid Card Serno . Step will be retried at 2025-11-18T12:58:01.531798391+01:00[Europe/Prague]. ::: CDC prod alerts
Trace ID:
23441d643fdbf302c64f7adf610b5219
Vyskytl se propustny problem behem zpracovani karetniho pozadavku. Zpracovani pokracuje dalsim krokem: Problem occurred in case processing step. Processing of step SET_CARD_LIMITS of case 15229758 processing failed due to error Called service OnlineServicesSoap.CardUsageConfigurationMaintenanceRequest error occurred. 1 - Invalid Card Serno . Step will be retried at 2025-11-18T12:58:01.531798391+01:00[Europe/Prague]. --- traceId: 23441d643fdbf302c64f7adf610b5219 --- v case: 2025-11-18T12:57:01.542+01:00

b) pridat i dohledani ostatni severity logu pro komplexni detekci podle trace ID - tzn primarne fungovat jen pres errory, ale pokud je tam neco opakovaneho, tak podle traceID dohledat i ostatni logy nezavisle na severite pro big picture

c) co to chce dodelat - vyuzit affected apps, najit root cause, ktery tady v detailu je, ale ukazat pres co to jde
                      - podle peak detection vyhodnotit zavaznost (pokud je najednou nekolikrat vice erroru, neni to nahoda, musi se vedet proc)
                      - dat lepsi describtion nez zatim mame
                      - porovnavat s known issue pro rychlejsi vyhodnoceni
                      - navrh reseni problemu



4.
a) predelat agenta do automatickeho modu - aby fungoval autonomne v clusteru a hlasil vysledky sve prace
b) pravidelny evaluation dotazu, sledovat zlepsivani/ubytek dotazu na zaklade denni zpetne vazby, po tydnu zkusit 2-3x tydne
c) napojeni na novou DB s dual ucty:

PostgreSQL database ailog_analyzer was created on instance P050TD01.
Database accounts:
ailog_analyzer_ddl_user_d1/WWvkHhyjje8YSgvU
ailog_analyzer_ddl_user_d2/rO1c4d2ocn3bAHXe
ailog_analyzer_user_d1/y01d40Mmdys/lbDE
ailog_analyzer_user_d2/qE+2bfLaXc3FmoRL
JDBC connection string : jdbc:postgresql://P050TD01.DEV.KB.CZ:5432/ailog_analyzer


5.
napojeni na alertovaci Teams kanal, kam se pak bude propagovat info a nasledne predelat na produkci a testovat tam

6.
monitorovani celeho agenta a postupu uceni, navrhovani optimalizaci pro lepsi uceni, priprava how-to pro jine squady

---


## 📋 DETAILED SPECIFICATION: POINT 2a - PEAK DETECTION WITH DB STATISTICS

### Architecture: Single Peak Statistics Table

**NPROD Peak Statistics Table Structure:**
- **Total rows:** 7 days × 24 hours × 4 quarters × 4 namespaces = **2,688 rows**
- **Update frequency:** Every 15 minutes (one sample per window per week)
- **Retention:** Permanent (historical baseline)

**Table: peak_statistics**
```sql
CREATE TABLE peak_statistics (
  day_of_week INT,              -- 0-6 (Sun-Sat)
  hour_of_day INT,              -- 0-23
  quarter_hour INT,             -- 0-3 (00-15, 15-30, 30-45, 45-60 min)
  namespace VARCHAR(255),       -- pcb-dev-01-app, pca-sit-01-app, etc.
  
  mean_errors FLOAT,            -- Baseline average error count
  stddev_errors FLOAT,          -- Standard deviation
  samples_count INT,            -- How many weeks of data (0 if peak, 1+ if normal)
  last_updated TIMESTAMP,       -- When this constant was calculated
  
  UNIQUE(day_of_week, hour_of_day, quarter_hour, namespace)
);
```

### Process A: Continuous Data Collection (Every 15 minutes)
**Purpose:** Update one baseline constant per 15-min window when NO peak is occurring

**Execution:** Every 15 minutes (cron: `*/15 * * * *`)

**Input:** Elasticsearch - error count from last 15 minutes

**Processing:**
1. Query ES: COUNT errors WHERE @timestamp >= now-15min AND level=ERROR
2. Group by: each namespace separately
3. Calculate: error_count for 15-min window
4. Determine: day_of_week, hour_of_day, quarter_hour from current time
5. **Logic:**
   ```
   error_count = fetch_from_ES()
   stats = lookup_peak_statistics(day, hour, quarter, namespace)
   
   # Threshold: If error_count > mean + 1.5*mean → Potential PEAK
   if error_count > (stats.mean + stats.mean * 1.5):
       # PEAK DETECTED - do NOT update peak_statistics
       # Store in temporary peak_detection data
       detected_peak = True
   else:
       # Normal operation - UPDATE the baseline constant
       update_rolling_average(error_count, stats)
       # With 3-window smoothing (look at ±1 hour) to avoid extreme values
   ```

**Update Strategy (Rolling Average):**
- Current mean: 300 errors
- New sample: 310 errors  
- With 3-window smoothing (±1 hour context): prevents day-to-day noise
- New mean: weighted average that adapts to changing patterns
- samples_count incremented (tracks: how many weeks contributed to this constant)

**Output (Database):**
- UPDATE `peak_statistics` table (ONLY when NO peak detected):
  - mean_errors: rolling average (updated)
  - stddev_errors: updated standard deviation
  - samples_count: incremented
  - last_updated: current timestamp

**Script:** `collect_peak_data_continuous.py` (Run via cron or Kubernetes CronJob)

**Key Point:** We DON'T store raw 15-min data. We ONLY update the constant (mean, stddev) in peak_statistics.
During a peak, we SKIP the update to preserve the baseline.

---

### Process B: Threshold Tuning & Continuous Improvement
**Threshold Formula:** error_count > mean + 1.5*mean

**Example:** If mean=300, then threshold=450 (50% spike above baseline = peak detected)

**Tuning Based on Data:**
- Monitor false positives: peaks that aren't real problems
- If too many false positives: increase to mean + 2*mean
- If missing real peaks: decrease to mean + 1*mean
- Adjust continuously as production data arrives

---

### Process C: Orchestration with Peak Detection (Modified analyze_period.py)

**Normal Workflow (No Peak):**
1. Fetch errors from last 15 minutes (same as current)
2. Extract root causes (same as current)
3. Query `peak_statistics` for current window (day_of_week, hour, quarter_hour, namespace)
4. Calculate: is_this_a_peak = error_count > (mean + 2*stddev)?
5. IF NO PEAK → Generate normal report (skip all peak-related sections)

**Peak Detection Workflow (If Peak Detected):**
1. Same fetch, same root cause extraction
2. PEAK DETECTED (error_count > mean + 2*stddev)
3. Parse errors with 10-second granularity:
   - Divide 15-min window into 90 intervals (15 min / 10 sec = 90)
   - For each 10-second window, count errors
   - Find exact PEAK START TIME: first 10-sec window that exceeded threshold
4. Root Cause Chain Analysis:
   - Look at first errors in peak (closest to peak_start_time - 60 sec)
   - Trace error chain: what happened BEFORE peak?
   - Identify: which upstream service failed, which error pattern triggered cascade
5. Peak Impact Analysis:
   - Count errors per app/namespace during peak
   - Determine most affected component
   - Map propagation path: root service → affected services
6. Generate Peak Report Section:
   ```
   ### Peak N: [peak_start_time - peak_end_time] UTC (total_errors)

   **Root Cause (Why):**
   - [Specific error/service failure]
   - [When it occurred]
   - [Why cascade happened]

   **Affected Components:**
   - Apps: [list with error counts and percentages]
   - Namespaces: [list with error counts]
   - Clusters: [list]

   **Impact (What happened):**
   - [error_count] errors in [duration]
   - Error rate: [X errors/min] (normal baseline: [Y errors/min])
   - Top error message: "[actual error text]"
   - [N] apps affected downstream

   **Propagation Path:**
   - [upstream_service] (failed at HH:MM:SS)
   → [primary_app] (retry logic, then circuit breaker)
   → [downstream_apps] (cascade failure)
   ```
7. Store peak metadata in `active_peaks` (temporary, deleted after peak ends)
8. Check `peak_history`: is this a known/recurring peak?
   - If YES: note in report ("3rd occurrence this month")
   - If NO: add to `peak_history` with is_known=FALSE

---

### Database Tables

**Table 1: peak_statistics** (Permanent baseline)
- Size: 2,688 rows per NPROD (with 4 namespaces)
- Updated: Every 15 min when no peak (rolling average)
- Stores: day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count, last_updated

**Table 2: peak_history** (Long-term tracking)
- Stores: peak_id, root_cause_pattern, first_occurrence, last_occurrence, occurrence_count, is_known, resolution_note
- Updated: When peak is detected (if recurring)
- Purpose: Track recurring peaks and resolutions

**Table 3: active_peaks** (Temporary during peak)
- Stores: peak_id, start_time, end_time, namespace, error_count
- Deleted: After peak ends (cleanup after report generated)
- Purpose: Prevent duplicate reports, track ongoing peaks

---

### Implementation Phases

**Phase 1: Database Setup & Initial Data Collection**
1. Connect to PostgreSQL P050TD01 (jdbc:postgresql://P050TD01.DEV.KB.CZ:5432/ailog_analyzer)
2. Create `peak_statistics` table with proper indexes
3. Create `peak_history` and `active_peaks` tables
4. Collect 2 weeks of historical 15-min window data from ES
5. Calculate initial mean/stddev for each (day_of_week, hour, quarter, namespace) combination
   - Use 3-window smoothing (±1 hour) to smooth outliers
   - Initialize samples_count with number of weeks collected

**Phase 2: Continuous Data Collection**
1. Deploy `collect_peak_data_continuous.py` script
   - Runs every 15 minutes
   - Updates peak_statistics with rolling average (only when NO peak)
   - Skips update during peak to preserve baseline
2. Verify rolling average logic works correctly
3. Monitor baseline improvements over time

**Phase 3: Peak Detection in Orchestration**
1. Modify `analyze_period.py`:
   - Query peak_statistics for current window
   - Compare error_count vs threshold
   - IF peak detected: parse 10-second windows, find start time
   - Analyze root cause chain (what happened BEFORE peak)
2. Implement 10-second window parsing for precise peak detection
3. Implement root cause chain analysis
4. Generate peak report section with proper formatting

**Phase 4: Production Tuning**
1. Collect real data for 1-2 weeks
2. Tune threshold based on false positive/negative rates
3. Monitor peak_history for patterns
4. Adjust smoothing and threshold as needed

---

### Key Design Points

1. **Single constant per 15-min window:** peak_statistics stores only mean/stddev, not raw data
2. **Rolling average:** Updates continuously, adapts to changing patterns
3. **Peak preservation:** Skip updates during peak to keep baseline clean
4. **3-window smoothing:** Reduces impact of single anomalous days
5. **10-second precision:** Finds exact peak start time for root cause analysis
6. **Temporary active_peaks:** Prevents duplicate reports while peak is ongoing
7. **Peak history:** Tracks recurring patterns for faster diagnosis

---

### Monitoring & Maintenance

- Monitor: peak_statistics update frequency (should be continuous when no peak)
- Monitor: false positive rate (peak detections that aren't real)
- Adjust: Threshold formula if too many false positives
- Review: peak_history monthly for patterns
- Update: is_holiday flags for special events

