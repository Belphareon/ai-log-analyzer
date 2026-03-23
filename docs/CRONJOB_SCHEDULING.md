# 🕐 AI Log Analyzer - K8s CronJob Scheduling
## Timing, Deployment Status, a Monitoring

## Important Deployment Note

- Local `k8s/` in this repository is only a sample/reference structure.
- Real manifests used for deployment to a cluster are typically maintained in a separate infrastructure repository.
- That location is not official or fixed here and can differ by user, team, or environment.
- Example of one local setup: `~/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer`

---

## 📋 CURRENT DEPLOYMENT STATUS (Mar 23, 2026)

### ✅ Configured & Ready
- **Two CronJobs** deployed in K8s manifests
- **Latest locally built image**: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r55`
- **Current deployed image in external infra repo example**: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r47`
- **Teams integration**: ENABLED (TEAMS_ENABLED=true)
- **Confluence integration**: Ready (page 1334314207)

### 🚀 Example deploy source: `~/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer`

---

## 🕐 CURRENT SCHEDULE

### 1️⃣ **REGULAR PHASE** - Každých 15 minut
```yaml
# CronJob: log-analyzer
schedule: "*/15 * * * *"  # 24/7,每 15 分钟
command: python3 /app/scripts/regular_phase.py
```

**Co dělá:**
- Zpracuje poslední 15 minut dat z Elasticsearch
- Používá PeakDetector (P93/CAP) pro spike detekci na úrovni namespace
- Detekuje spikes/bursts/cross-namespace issues
- Ukládá incidenty do PostgreSQL
- Ukládá namespace totaly do `peak_raw_data` (pro budoucí P93 přepočet)
- Updatuje registry (problémy + peaks)
- POUZE na kritické problémy → Teams alert

**Expected output:**
```
✅ Fetched X incidents from ES
✅ Saved Y incidents to PostgreSQL
Registry updated: P problems, K peaks
[No Teams message unless critical]
```

---

### 2️⃣ **BACKFILL PHASE** - Jednou denně ráno
```yaml
# CronJob: log-analyzer-backfill
schedule: "0 9 * * *"  # 09:00 UTC (11:00 CET Praha)
command: python3 /app/scripts/backfill.py --days 1 --output /app/scripts/reports
```

**Co dělá:**
- Zpracuje VČERAJŠÍ DEN (kompletní 24h data)
- Používá PeakDetector (P93/CAP) pro spike detekci na úrovni namespace
- Generuje podrobný problem report (JSON, TXT, CSV)
- Publikuje do Confluence (page 1334314207)
- Odesílá Teams notifikaci s EXECUTIVE SUMMARY
- Updatuje registry s novými problémy/peaks

**Expected output:**
```
✅ Backfill processing started for N days
✅ Total incidents fetched: X
✅ Saved to PostgreSQL: Y
✅ Problem reports generated:
   - problem_report_TIMESTAMP.txt
   - problem_report_TIMESTAMP.json
   - problem_report_TIMESTAMP.csv
✅ Published to Confluence
✅ Teams notification sent
```

---

### 3️⃣ **THRESHOLD RECALCULATION** - Týdně (doporučeno)
```bash
# Ruční nebo CronJob (doporučeno neděle v noci)
# schedule: "0 3 * * 0"  # 03:00 UTC neděle
python3 /app/scripts/core/calculate_peak_thresholds.py --weeks 4 --verbose
```

**Co dělá:**
- Čte `peak_raw_data` za posledních N týdnů (default: 4)
- Počítá P93 percentil per (namespace, day_of_week)
- Počítá CAP = (median_P93 + avg_P93) / 2 per namespace
- Ukládá do `peak_thresholds` + `peak_threshold_caps`
- PeakDetector automaticky načte nové thresholds (5-min cache)

**Konfigurace (env vars z values.yaml):**
- `PERCENTILE_LEVEL` - percentil (default: 0.93 = P93)
- `MIN_SAMPLES_FOR_THRESHOLD` - min vzorků pro spolehlivý threshold (default: 10)
- `DEFAULT_THRESHOLD` - fallback pokud chybí data (default: 100)

**Expected output:**
```
✅ Loaded X raw data points from peak_raw_data
✅ Calculated P93 thresholds for Y namespaces
✅ Calculated CAP values for Y namespaces
✅ Saved to peak_thresholds: Z rows
✅ Saved to peak_threshold_caps: Y rows
```

**Teams message format:**
```
Log Analyzer run at 2026-02-10 09:15:32 UTC

Run Summary:
[TOP 3-5 Problems from EXECUTIVE SUMMARY]
- Problem 1: X occurrences
- Problem 2: Y severity
- ...
```

---

## 📊 FLOW DIAGRAM

```
Every 15 min (Regular Phase):
┌─────────────────────────────────┐
│ Regular Phase CronJob (*/15)    │
│ python3 regular_phase.py     │
└────────┬────────────────────────┘
         │
         ├─→ Fetch last 15 min from ES
         ├─→ Create PeakDetector (P93/CAP z DB)
         ├─→ Pipeline: detect (P93/CAP) → classify → propagate
         ├─→ Save to PostgreSQL
         ├─→ Save namespace totals to peak_raw_data ←── vstup pro P93 přepočet
         ├─→ Update registry
         └─→ IF critical → Teams alert

Daily at 09:00 UTC (Backfill Phase):
┌─────────────────────────────────┐
│ Backfill CronJob (0 9 * * *)    │
│ python3 backfill.py          │
└────────┬────────────────────────┘
         │
         ├─→ Fetch YESTERDAY'S data from ES
         ├─→ Create PeakDetector (P93/CAP z DB)
         ├─→ Pipeline: detect (P93/CAP) → classify → propagate
         ├─→ Save to PostgreSQL
         ├─→ Aggregate problems
         ├─→ Generate reports
         │  ├─ problem_report_*.txt (human-readable)
         │  ├─ problem_report_*.json (machine-readable)
         │  └─ errors/peaks CSVs
         │
         ├─→ Publish to Confluence (API)
         └─→ Send Teams notification (webhook)

Weekly (Threshold Recalculation - doporučeno neděle):
┌──────────────────────────────────────────────┐
│ calculate_peak_thresholds.py --weeks 4       │
└────────┬─────────────────────────────────────┘
         │
         ├─→ Read peak_raw_data (posledních N týdnů)
         ├─→ Calculate P93 per (namespace, day_of_week)
         ├─→ Calculate CAP per namespace
         └─→ Save to peak_thresholds + peak_threshold_caps
                  ↓
         PeakDetector automaticky načte (5-min cache)
```

**Samozdokonalovací smyčka:**
```
Regular Phase → peak_raw_data roste → calculate_peak_thresholds → přesnější P93/CAP
     ↑                                                                    ↓
     └──────────── PeakDetector načte nové thresholds ←───────────────────┘
```

---

## 📊 PUBLIKOVÁNÍ DO CONFLUENCE & TEAMS

### Backfill Output Files
```
/app/scripts/reports/
├── problem_report_2026-02-10T091532.txt     ← Human-readable summary
├── problem_report_2026-02-10T091532.json    ← Structured data
├── problem_report_2026-02-10T091532.csv     ← Table format
├── errors_table_latest.csv                  ← All errors
└── peaks_table_latest.csv                   ← All peaks
```

### Confluence Updates
**Page:** 1334314207 (Recent Incidents - Problem Analysis)

**Content:** PROBLEM_ANALYSIS_REPORT
```
═══════════════════════════════════════════
PROBLEM_ANALYSIS_REPORT
Backfill Analysis: 2026-02-09

EXECUTIVE SUMMARY
─────────────────
[Top 3-5 problems with occurrence count]

PROBLEM DETAILS (Top 20)
───────────────────────
For each problem:
  - ID: CATEGORY:flow:error_class
  - Count: X occurrences
  - First: timestamp
  - Last: timestamp
  - Services: [service1, service2, ...]
  - Sample: [sample error message]
═══════════════════════════════════════════
```

### Teams Integration
**Webhook:** `TEAMS_WEBHOOK_URL` from values.yaml
**Trigger:** At end of backfill (around 09:15 UTC)
**Message Format:**
```
Log Analyzer run at 2026-02-10 09:15:32 UTC

Run Summary:
BUSINESS:card_servicing:validation_error (245 occurrences)
DATABASE:batch_processing:connection_pool (128 occurrences)
AUTH:card_opening:access_denied (89 occurrences)
```

---

## ⚙️ CONFIGURATION (K8s values.yaml)

```yaml
# Image
app:
  image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r47
  imagePullPolicy: IfNotPresent

# Schedules are hardcoded in templates/cronjob.yaml
# Do NOT use {{ .Values.schedule }} - each job has own schedule

# Environment
env:
  DB_HOST: P050TD01.DEV.KB.CZ
  DB_NAME: ailog_analyzer
  ES_HOST: https://elasticsearch-test.kb.cz:9500
  REGISTRY_DIR: /data/registry
  EXPORT_DIR: /data/exports

  # Peak Detection Algorithm (P93 OR CAP)
  PERCENTILE_LEVEL: "0.93"             # Percentil pro peak thresholds (P93 = 0.93)
  MIN_SAMPLES_FOR_THRESHOLD: "10"      # Min počet vzorků pro spolehlivý threshold
  DEFAULT_THRESHOLD: "100"             # Fallback threshold pokud chybí data v DB

  # Informativní metriky (EWMA/MAD - NE pro spike detekci)
  EWMA_ALPHA: "0.3"                    # EWMA smoothing faktor pro trend metriky
  WINDOW_MINUTES: "15"                 # Časové okno pro analýzu

# Teams & Confluence
teams:
  webhook_url: "https://sgcz.webhook.office.com/webhookb2/..."

# (TEAMS_ENABLED=true is set in cronjob.yaml)
# (CONFLUENCE_URL/PAGE_ID only used by backfill)
```

---

## 🔍 MONITORING

### Check CronJob Status
```bash
kubectl get cronjobs -n ai-log-analyzer
kubectl get cronjob log-analyzer-backfill -n ai-log-analyzer -o wide
```

### Check Next Scheduled Run
```bash
kubectl get cronjob log-analyzer-backfill -n ai-log-analyzer \
  -o jsonpath='{.status.lastSuccessfulTime}'
```

### Monitor Logs
```bash
# Regular phase (last 15 min)
kubectl logs -n ai-log-analyzer -l job-type=regular --tail=50 -f

# Backfill (today's run)
kubectl logs -n ai-log-analyzer -l job-type=backfill --tail=200
```

### Verify Output
```bash
# Check if problem reports generated
kubectl exec -it POD_NAME -n ai-log-analyzer -- \
  ls -lah /app/scripts/reports/

# Check Confluence updated
curl -s https://confluence.kb.cz/pages/api/page/1334314207 \
  | grep -o "problem_report"

# Check Teams integration
# (Look at Teams channel for notifications)
```

---

## ⚠️ TROUBLESHOOTING

### Backfill Not Running
```bash
# Check CronJob exists
kubectl describe cronjob log-analyzer-backfill -n ai-log-analyzer

# Check if pod created
kubectl get pods -n ai-log-analyzer --sort-by=.status.startTime

# Check pod logs
kubectl logs POD_NAME -n ai-log-analyzer
```

### Teams Notification Not Received
1. Verify webhook URL in values.yaml
2. Verify `TEAMS_ENABLED=true` in pod env:
   ```bash
   kubectl exec POD_NAME -n ai-log-analyzer -- \
     env | grep TEAMS
   ```
3. Check backfill logs for "Teams notification sent"

### Problem Reports Not Generated
1. Check `/app/scripts/reports/` directory exists
2. Verify output directory has write permissions
3. Check backfill logs for report generation step
4. Verify `--output /app/scripts/reports` argument in backfill command

### Confluence Not Updated
1. Verify page ID = 1334314207
2. Check Confluence credentials in pod
3. Verify `CONFLUENCE_URL=https://confluence.kb.cz`
4. Check logs for "Published to Confluence" message

---

## 📋 MANUAL TESTING
Regular Phase (každých 15 minut)
    ↓
Detects critical issues?
    ├─ YES: Teams Alert (spike/burst/critical)
    └─ NO: Silent (no alert)
    ↓
Exports CSV (updated)
    ↓
(Optional) Auto-publish to Confluence
```

---

## ⚠️ FALLBACK STRATEGIE

Pokud se něco nezdaří:

### **Backfill Failed**
```
❌ DB write error / Elasticsearch error
├─ Skript NEPROKRAŠÍ (exit code ≠ 0)
├─ K8s zaznamenádal failure (CronJob status: Failed)
├─ Alert: "⚠️ Backfill failed on DATE"
└─ Recovery: Manual re-run `run_backfill.sh --days 1`
```

### **Teams Notification Failed**
```
⚠️ Webhook is down / Network error
├─ NEPROKRÁŠUJE backfil (non-blocking)
├─ Log: "⚠️ Teams notification failed: [error]"
├─ Data jsou uložena v DB (je OK)
└─ Recovery: Automatically sent next run (retry)
```

### **Confluence Upload Failed**
```
⚠️ API error / Invalid credentials
├─ NEPROKRÁŠUJE script (non-blocking)
├─ Log: "⚠️ Failed to publish to Confluence: [error]"
├─ CSV generován lokálně (je OK)
└─ Recovery: Manual `python confluence_publisher.py ...`
```

### **Regular Phase Failed**
```
❌ Fetch error / Pipeline error
├─ Skript ends with error (exit code ≠ 0)
├─ Next run za 15 minut (retry)
├─ Alert: "⚠️ Regular phase failed"
└─ Recovery: Automatic next run
```

---

## 🔧 STRATEGIE PRO DLOUHODOBOU STABILITU

### 1. **Retry Logic**
```python
# V confluence_publisher.py a teams_notifier.py
for attempt in range(3):
    try:
        send_notification()
        break
    except Exception:
        if attempt < 2:
            time.sleep(5 * (attempt + 1))  # Exponential backoff
            continue
        raise
```

### 2. **Logging**
```bash
# Všechny cronjobdy logují do:
# /var/log/ai-log-analyzer/backfill.log
# /var/log/ai-log-analyzer/regular.log
# /var/log/ai-log-analyzer/publish.log

# Můžeš vidět:
kubectl logs -n ai-log-analyzer job/ai-log-analyzer-backfill-<ID>
```

### 3. **Monitoring**
```yaml
# Doporučujeme Prometheus/Grafana metrics:
# - Backfill success/failure rate
# - Regular phase duration
# - Confluence publish status
# - DB write latency
```

### 4. **Alerting**
```yaml
# Teams Webhook Alert Conditions:
# - Backfill failed (3x fail in a row)
# - Regular phase stopped (no run for 30 min)
# - Confluence API unreachable
# - DB connection lost
```

---

## 📐 ENVIRONMENT VARIABLES (v K8s)

```yaml
# Nastaveno v k8s/values.yaml -> injektováno jako env vars přes cronjob.yaml

# === Database ===
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_USER=ailog_analyzer_user_d1
DB_DDL_USER=ailog_analyzer_ddl_user_d1
DB_PASSWORD=...  # z Conjur/CyberArk
DB_DDL_PASSWORD=...  # z Conjur/CyberArk
DB_DDL_ROLE=role_ailog_analyzer_ddl

# === Elasticsearch ===
ES_HOST=https://elasticsearch-test.kb.cz:9500
ES_INDEX=cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*

# === Peak Detection (P93/CAP) ===
PERCENTILE_LEVEL=0.93              # Percentil pro peak thresholds
MIN_SAMPLES_FOR_THRESHOLD=10       # Min vzorků pro spolehlivý P93
DEFAULT_THRESHOLD=100              # Fallback pokud chybí data v DB

# === Informativní metriky ===
EWMA_ALPHA=0.3                     # EWMA smoothing (jen trend metriky, NE spike detekce)
WINDOW_MINUTES=15                  # Časové okno pro analýzu

# === Teams & Confluence ===
TEAMS_WEBHOOK_URL=https://sgcz.webhook.office.com/webhookb2/...
TEAMS_ENABLED=true

CONFLUENCE_URL=https://wiki.kb.cz
CONFLUENCE_PROXY=http://cntlm.speed-default:3128
CONFLUENCE_KNOWN_ERRORS_PAGE_ID=1334314201
CONFLUENCE_KNOWN_PEAKS_PAGE_ID=1334314203
```

---

## 🚀 PŘÍKLAD K8S CRONJOB MANIFESTY

### Backfill CronJob:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-log-analyzer-backfill
  namespace: ai-log-analyzer
spec:
  schedule: "0 9 * * *"  # 09:00 UTC
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backfill
            image: ai-log-analyzer:latest
            command:
            - /bin/sh
            - -c
            - cd /app && python3 scripts/backfill.py --days 1 --output /app/scripts/reports
            env:
            - name: DB_HOST
              valueFrom:
                configMapKeyRef:
                  name: ai-log-analyzer-config
                  key: db-host
            # ... ostatní env vars
            resources:
              requests:
                memory: "2Gi"
                cpu: "1000m"
              limits:
                memory: "4Gi"
                cpu: "2000m"
          restartPolicy: OnFailure
          backoffLimit: 3
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 5
```

### Regular Phase CronJob:
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ai-log-analyzer-regular
  namespace: ai-log-analyzer
spec:
  schedule: "*/15 * * * *"  # Každých 15 minut
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: regular
            image: ai-log-analyzer:latest
            command:
            - /bin/sh
            - -c
            - cd /app && python3 scripts/regular_phase.py
            env:
            # ... env vars
            resources:
              requests:
                memory: "1Gi"
                cpu: "500m"
              limits:
                memory: "2Gi"
                cpu: "1000m"
          restartPolicy: OnFailure
          backoffLimit: 2
  successfulJobsHistoryLimit: 5
  failedJobsHistoryLimit: 3
```

---

## 🧪 TESTING SCHEDULE

Než to deployneš do produkce:

```bash
# 1. Test backfill v suchém režimu
python3 scripts/backfill.py --days 1 --dry-run

# 2. Test regular phase
python3 scripts/regular_phase.py --window 15 --dry-run

# 3. Test P93/CAP thresholds
python3 scripts/core/calculate_peak_thresholds.py --dry-run --verbose

# 4. Zobrazit aktuální thresholds
python3 scripts/core/peak_detection.py --show-thresholds

# 5. Test publishing
bash scripts/publish_daily_reports.sh --dry-run

# 6. Test Confluence connection
python3 scripts/confluence_publisher.py \
  --page-id 1334314201 \
  --csv-file ./scripts/exports/errors_table_latest.csv \
  --title "Test: Known Errors"

# 7. Test Teams notification
python3 -c "
from core.teams_notifier import TeamsNotifier
notifier = TeamsNotifier()
notifier.send_backfill_completed(
    days_processed=1,
    successful_days=1,
    failed_days=0,
    total_incidents=100,
    saved_count=100,
    registry_updates={'problems': 5, 'peaks': 1},
    duration_minutes=5.5
)
"
```

---

## ✅ CHECKLIST PRO DEPLOYMENT

- [ ] Backfill testován lokalně (1 den)
- [ ] Regular phase testován (15 min okno)
- [ ] P93/CAP thresholds naplněny (`init_phase.py --days 21` + `calculate_peak_thresholds.py`)
- [ ] PeakDetector ověřen (`--show-thresholds` ukazuje data pro všechny namespace)
- [ ] Teams webhook ověřen (message přijat)
- [ ] Confluence credentials ověřeny (CSV uploadován)
- [ ] K8s manifesty vytvořeny
- [ ] Resource limits nastaveny
- [ ] Logs nakonfigurány
- [ ] Monitoring/Alerting setup
- [ ] Backup strategie (registry YAML)
- [ ] Runbook pro failure scenarios

---

**Více info:** [docs/PIPELINE_ARCHITECTURE.md](./PIPELINE_ARCHITECTURE.md)
