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

**Reference:** See `working_progress.md` for complete implementation phases

### Overview
Peak detection requires TWO INDEPENDENT PROCESSES plus ONE MODIFIED ORCHESTRATION:

### Process A: Data Collection (Continuous Background Task)
**Purpose:** Sbírání počtu errorů v 15-minutových intervalech

**Execution:** Every 15 minutes (cron: `*/15 * * * *`)

**Input:** Elasticsearch - errors from last 15 minutes

**Processing:**
1. Query ES: COUNT errors WHERE @timestamp >= now-15min AND level=ERROR
2. Group by: environment, namespace, cluster (separate queries)
3. Calculate: error_count for 15-min window
4. Current time window: start_time = floor(now to 15-min), end_time = start + 15min

**Output (Database):**
- Insert into `peak_raw_data` table:
  - collection_timestamp: when data was collected (now)
  - window_start: 15-min window start (e.g., 2025-12-04 13:00:00)
  - window_end: 15-min window end (e.g., 2025-12-04 13:15:00)
  - error_count: number of errors in that window
  - day_of_week: 0-6 (Sunday-Saturday)
  - hour_of_day: 0-23
  - environment: 'nprod' or 'prod'
  - namespace: 'pcb-dev-01-app', 'pca-sit-01-app', etc.
  - cluster: 'cluster-k8s_nprod_3100-in', etc.

**Data Retention:** Keep 30-90 days (rolling window)

**Script:** `collect_peak_data_continuous.py` (Run via cron or Kubernetes CronJob)

---

### Process B: Weekly Statistics Aggregation
**Purpose:** Transform raw 15-min data into statistical baseline for anomaly detection

**Execution:** Once per week (Sunday 2:00 AM)

**Input:** All raw data from `peak_raw_data` from the PAST WEEK

**Processing:**
1. Group raw data by: (day_of_week, hour_of_day, quarter_hour, environment, namespace, cluster)
   - quarter_hour: 0-3 representing 00-15, 15-30, 30-45, 45-60 minutes
2. For each group, calculate:
   - mean_errors: average error count across all entries
   - stddev_errors: standard deviation
   - min_errors, max_errors: min and max values
   - samples_count: how many data points were aggregated
3. Apply 3-window smoothing to reduce outliers:
   - For each window, consider ±1 hour (3 windows total)
   - Recalculate mean/stddev across smoothed data
   - This prevents anomalous days from skewing the baseline

**Output (Database):**
- UPSERT into `peak_statistics` table (10,080 entries per environment)
  - For nprod with 4 namespaces: 4 × 10,080 = 40,320 rows
  - For prod with 1 namespace: 1 × 10,080 = 10,080 rows

**Special Cases:**
- is_holiday: Mark days with special events (Christmas, New Year, Black Friday, etc.)
  - These should have separate statistics or be marked for manual review
  - Use: `is_holiday = TRUE` to indicate anomalous traffic patterns

**Script:** `aggregate_peak_statistics_weekly.py`

---

### Process C: Orchestration with Peak Detection (Modified analyze_period.py)

**Normal Workflow (No Peak):**
1. Fetch errors from last 15 minutes (same as current)
2. Extract root causes (same as current)
3. Query `peak_statistics` for current time window (day_of_week, hour, quarter_hour, environment, namespace, cluster)
4. Calculate: is_this_a_peak = error_count > (mean + 2*stddev)?
5. IF NO PEAK → Generate normal report (skip all peak-related sections)
6. Generate output JSON and markdown report

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
9. Generate complete output JSON with peak data

---

### Database Schema (3 Tables)

**Table 1: peak_raw_data**
- Storage: 15-min error counts
- Retention: 30-90 days (rolling window)
- Updated: Every 15 minutes by Process A
- Size: ~6 entries per 15 min × 4 env × 8 namespaces = ~1900 entries per hour

**Table 2: peak_statistics**
- Storage: Aggregated baseline (mean, stddev per time slot)
- Retention: Permanent (updated weekly)
- Size: 10,080 entries per environment (~40K for nprod with 4 namespaces)
- Updated: Once per week by Process B
- Used: For anomaly detection during orchestration

**Table 3: peak_history**
- Storage: Long-term peak tracking
- Retention: Permanent
- Fields: peak_id, root_cause_pattern, affected_namespaces, is_known, resolution_note
- Updated: Every time peak is detected
- Used: For recurrence detection and pattern matching

**Table 4: active_peaks** (Temporary, not permanently stored)
- Storage: In-progress peaks during detection phase
- Retention: Until peak ends, then deleted
- Fields: peak_id, start_time, end_time, status
- Purpose: Prevent duplicate peak reports for same peak

---

### Implementation Timeline

**Phase 1: Database Setup (Day 1-2)**
- Connect to PostgreSQL P050TD01
- Create 3 tables (peak_raw_data, peak_statistics, peak_history)
- Create indexes on frequently-queried columns

**Phase 2: Baseline Collection (Day 2-4)**
- Collect 2 weeks of historical data from ES
- Insert into peak_raw_data
- Calculate initial statistics (with 3-window smoothing)
- Insert into peak_statistics

**Phase 3: Enable Continuous Collection (Day 4)**
- Deploy `collect_peak_data_continuous.py` as CronJob/scheduled task
- Verify it runs every 15 minutes
- Monitor raw_data table growth

**Phase 4: Enable Weekly Aggregation (Day 11)**
- Deploy `aggregate_peak_statistics_weekly.py` as weekly task
- Verify statistics are updated
- Compare with initial baseline

**Phase 5: Implement Peak Detection in Orchestration (Day 4-5)**
- Modify `analyze_period.py` to query peak_statistics
- Implement 10-second window parsing for peak start detection
- Implement root cause chain analysis
- Implement peak report generation
- Test with historical data

**Phase 6: Production Deployment (Day 5+)**
- Deploy modified orchestration
- Enable peak detection and reporting
- Monitor for false positives
- Fine-tune threshold (currently: mean + 2*stddev, adjustable)

---

### Key Design Decisions

1. **Two independent processes:** Decouples data collection from analysis/reporting
2. **15-minute granularity for statistics:** Matches typical business metrics and orchestration runs
3. **10-second granularity for peak detection:** Finds exact peak start time for root cause analysis
4. **3-window smoothing:** Reduces impact of anomalous single days on baseline
5. **Weekly aggregation:** Automatically adapts to changing traffic patterns
6. **Peak history tracking:** Enables recurrence detection and pattern matching
7. **Temporary peak storage:** Prevents duplicate reports while peak is ongoing

---

### Monitoring & Maintenance

- Monitor: peak_raw_data table size (should grow steadily)
- Monitor: peak_statistics update frequency (should be weekly)
- Monitor: false positive rate (peak detections that aren't real)
- Adjust: Threshold formula if too many false positives (try mean + 1.5*stddev or mean + 2.5*stddev)
- Review: peak_history monthly for patterns
- Update: is_holiday flags for special events/dates

```
