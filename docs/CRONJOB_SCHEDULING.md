# 🕐 AI Log Analyzer - K8s CronJob Scheduling
## Timing, Deployment Status, a Monitoring

---

## 📋 CURRENT DEPLOYMENT STATUS (Feb 10, 2026)

### ✅ Configured & Ready
- **Two CronJobs** deployed in K8s manifests
- **Docker image**: r4 (174 MB) pushed to dockerhub.kb.cz
- **Teams integration**: ENABLED (TEAMS_ENABLED=true)
- **Confluence integration**: Ready (page 1334314207)

### 🚀 Next: `kubectl apply -f k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/`

---

## 🕐 CURRENT SCHEDULE

### 1️⃣ **REGULAR PHASE** - Každých 15 minut
```yaml
# CronJob: log-analyzer
schedule: "*/15 * * * *"  # 24/7,每 15 分钟
command: python3 /app/scripts/regular_phase_v6.py
```

**Co dělá:**
- Zpracuje poslední 15 minut dat z Elasticsearch
- Detekuje spikes/bursts/cross-namespace issues
- Ukládá incidenty do PostgreSQL
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
command: python3 /app/scripts/backfill_v6.py --days 1 --output /app/scripts/reports
```

**Co dělá:**
- Zpracuje VČERAJŠÍ DEN (kompletní 24h data)
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
│ python3 regular_phase_v6.py     │
└────────┬────────────────────────┘
         │
         ├─→ Fetch last 15 min from ES
         ├─→ Pipeline: detect → classify → propagate
         ├─→ Save to PostgreSQL
         ├─→ Update registry
         └─→ IF critical → Teams alert

Daily at 09:00 UTC (Backfill Phase):
┌─────────────────────────────────┐
│ Backfill CronJob (0 9 * * *)    │
│ python3 backfill_v6.py          │
└────────┬────────────────────────┘
         │
         ├─→ Fetch YESTERDAY'S data from ES
         ├─→ Pipeline: detect → classify → propagate
         ├─→ Save to PostgreSQL
         ├─→ Aggregate problems
         ├─→ Generate reports
         │  ├─ problem_report_*.txt (human-readable)
         │  ├─ problem_report_*.json (machine-readable)
         │  └─ errors/peaks CSVs
         │
         ├─→ Publish to Confluence (API)
         └─→ Send Teams notification (webhook)
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

**Content:** PROBLEM_ANALYSIS_REPORT V6
```
═══════════════════════════════════════════
PROBLEM_ANALYSIS_REPORT V6
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
  image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r4
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
# .env nebo config/values.yaml
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_USER=ailog_analyzer_user_d1
DB_DDL_USER=ailog_analyzer_ddl_user_d1
DB_PASSWORD=...
DB_DDL_PASSWORD=...
DB_DDL_ROLE=role_ailog_analyzer_ddl

ES_HOST=elasticsearch.kb.cz
ES_PORT=9200

TEAMS_WEBHOOK_URL=https://outlook.webhook.office.com/webhookb2/...
TEAMS_ENABLED=true

CONFLUENCE_URL=https://confluence.kb.cz
CONFLUENCE_USERNAME=XX_AWX_CONFLUENCE
CONFLUENCE_PASSWORD=PP_@9532bb-xmHV26
CONFLUENCE_DAILY_REPORT_PAGE_ID=1334314207
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
            - cd /app && python3 scripts/backfill_v6.py --days 1 --output /app/scripts/reports
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
            - cd /app && python3 scripts/regular_phase_v6.py
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
python3 scripts/backfill_v6.py --days 1 --dry-run

# 2. Test regular phase
python3 scripts/regular_phase_v6.py --window 15 --dry-run

# 3. Test publishing
bash scripts/publish_daily_reports.sh --dry-run

# 4. Test Confluence connection
python3 scripts/confluence_publisher.py \
  --page-id 1334314201 \
  --csv-file ./scripts/exports/errors_table_latest.csv \
  --title "Test: Known Errors"

# 5. Test Teams notification
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
- [ ] Teams webhook ověřen (message přijat)
- [ ] Confluence credentials ověřeny (CSV uploadován)
- [ ] K8s manifesty vytvořeny
- [ ] Resource limits nastaveny
- [ ] Logs nakonfigurány
- [ ] Monitoring/Alerting setup
- [ ] Backup strategie (registry YAML)
- [ ] Runbook pro failure scenarios

---

**Více info:** [docs/PIPELINE_V4_ARCHITECTURE.md](./PIPELINE_V4_ARCHITECTURE.md)
