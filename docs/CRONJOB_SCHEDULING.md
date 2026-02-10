# 🕐 AI Log Analyzer - K8s CronJob Scheduling
## Timing, Fallback Strategie, a Orchestration

---

## 📋 OVERVIEW

Máme 3 hlavní cronjobs:
1. **Backfill** - 1x denně, procesuje včerajší data (historické)
2. **Regular Phase** - Každých 15 minut, zpracuje poslední 15 minut
3. **Publish Reports** - Po backfilu, publikuje do Teams + Confluence

---

## 🕐 DOPORUČENÝ SCHEDULE

### 1️⃣ **BACKFILL** - Jednou denně ráno
```yaml
# CronJob: ai-log-analyzer-backfill
schedule: "0 9 * * *"  # 09:00 UTC (11:00 CET) = dopoledne v Praze
# NEBO pokud chceš večer:
# schedule: "0 22 * * *"  # 22:00 UTC (00:00 CET) = polnoc v Praze
```

**Důvody pro 02:00 UTC (ráno):**
- ✅ Data z včerejšího dne jsou completní
- ✅ Nejedou přes noc (nižší load)
- ✅ Report je hotový na začátku pracovního dne
- ✅ Teams & Confluence updaty ráno

**Alternativa - 22:00 UTC (večer):**
- Report se publikuje večer/v noci
- Data jsou available hned (ne až další den)

---

### 2️⃣ **REGULAR PHASE** - Každých 15 minut
```yaml
# CronJob: ai-log-analyzer-regular
schedule: "*/15 * * * *"  # Každých 15 minut
# Běží 24/7 - sleduje real-time incidenty
```

**Co dělá:**
- Zpracuje poslední 15 minut dat
- Detekuje spikes/bursts
- POUZE pokud je critical issue → Teams alert
- Updatuje DB a registry

---

### 3️⃣ **PUBLISH REPORTS** - Automaticky po backfilu
```yaml
# Nespouští se samostatně!
# Volá se z run_backfill.sh na konci
# Pokud chceš samostatný cronjob:
schedule: "0 9 30 * * *"  # 09:30 UTC = 30 minut po backfilu
# (jakmile je backfil hotový)
```

---

## 📊 PUBLIKOVÁNÍ DO CONFLUENCE & TEAMS

### Backfill Flow:
```
Backfill (02:00)
    ↓
Generates reports (problem_report_*.json)
    ↓
Exports CSV (errors_table_latest.csv, peaks_table_latest.csv)
    ↓
publish_daily_reports.sh
    ├─ Daily Report → Teams (top 5 issues)
    ├─ Known Errors CSV → Confluence (page 1334314201)
    └─ Known Peaks CSV → Confluence (page 1334314203)
```

### Regular Phase Flow:
```
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
