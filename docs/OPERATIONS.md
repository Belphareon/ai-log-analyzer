# Provoz — AI Log Analyzer

Vše pro běžný provoz, manuální zásahy a diagnostiku. Systém běží **autonomně přes K8s CronJoby** — tato příručka je pro situace, kdy je třeba ručně zasáhnout.

---

## 1. CronJoby — přehled

| CronJob | Schedule | Co dělá | Typická doba |
|---------|----------|---------|--------------|
| `log-analyzer` | `*/15 * * * *` | Hlavní pipeline: ES fetch → detect peaks → alert → export | 1–5 min |
| `log-analyzer-backfill` | `0 9 * * *` | Denní backfill + Confluence publish | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP z peak_raw_data | 1–5 min |

### Závislosti

```
Init Job (jednorázově po instalaci)
  └─ backfill → plní peak_raw_data + peak_investigation
  └─ threshold calc → vypočítá P93/CAP z backfill dat

Poté autonomně:
  regular (*/15)       → fetch ES → detect → alert → plní peak_raw_data
  backfill (09:00)     → zpracuje předchozí den → publikuje Confluence
  thresholds (Ne 03:00) → přepočítá P93/CAP z posledních 4 týdnů
```

### Stav

```bash
kubectl get cronjobs -n ai-log-analyzer
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp | tail -10
kubectl logs job/<job-name> -n ai-log-analyzer
```

---

## 2. Manuální spuštění jobů

Když potřebujete spustit job mimo schedule:

```bash
# Regular phase
kubectl create job manual-regular --from=cronjob/log-analyzer -n ai-log-analyzer
kubectl logs -f job/manual-regular -n ai-log-analyzer

# Backfill
kubectl create job manual-backfill --from=cronjob/log-analyzer-backfill -n ai-log-analyzer
kubectl logs -f job/manual-backfill -n ai-log-analyzer

# Threshold přepočet
kubectl create job manual-thresholds --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/manual-thresholds -n ai-log-analyzer

# Úklid po manuálním jobu
kubectl delete job manual-regular manual-backfill manual-thresholds -n ai-log-analyzer --ignore-not-found
```

### Re-bootstrap (init job)

Pro přeplnění dat od nuly (změna namespace, nové prostředí):

```bash
kubectl delete job log-analyzer-init -n ai-log-analyzer --ignore-not-found
helm template <infra-apps-dir> | kubectl apply -f - -l job-type=init
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

---

## 3. Parametry — values.yaml

Všechny parametry jsou v `values.yaml` daného prostředí (v infra-apps repu).

### Alerting

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.MAX_PEAK_ALERTS_PER_WINDOW` | `3` | Max peaků v jednom digest emailu |
| `env.ALERT_DIGEST_ENABLED` | `true` | Digest místo individuálních emailů |
| `env.ALERT_COOLDOWN_MIN` | `45` | Min. interval mezi alerty pro stejný peak |
| `env.ALERT_HEARTBEAT_MIN` | `120` | Opakovat alert pro trvající peak |
| `env.ALERT_MIN_DELTA_PCT` | `30` | Min. % změna pro znovu-odeslání |
| `env.ALERT_CONTINUATION_LOOKBACK_MIN` | `60` | Lookback pro pokračující peak |

### Detekce

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.PERCENTILE_LEVEL` | `0.93` | Percentil pro P93 thresholds |
| `env.MIN_SAMPLES_FOR_THRESHOLD` | `10` | Min vzorků pro spolehlivý threshold |
| `env.DEFAULT_THRESHOLD` | `100` | Fallback pokud chybí P93/CAP data |

### Init job

| Parametr | Default | Popis |
|----------|---------|-------|
| `init.backfillDays` | `21` | Dní zpětně pro backfill |
| `init.backfillWorkers` | `4` | Paralelní workery |
| `init.thresholdWeeks` | `3` | Týdnů pro výpočet thresholdů |
| `init.activeDeadlineSeconds` | `14400` | Max doba běhu (4h) |

### Alerting profily

**Méně emailů:**
```yaml
env:
  ALERT_COOLDOWN_MIN: "90"
  ALERT_HEARTBEAT_MIN: "180"
  ALERT_MIN_DELTA_PCT: "50"
```

**Citlivější:**
```yaml
env:
  ALERT_COOLDOWN_MIN: "30"
  ALERT_HEARTBEAT_MIN: "60"
  ALERT_MIN_DELTA_PCT: "20"
```

### Změna parametrů

1. Upravit `values.yaml` v infra-apps repu
2. Commit + push + PR
3. ArgoCD sync — CronJoby se aktualizují
4. Nový parametr platí od příštího běhu (do 15 min)

---

## 4. Přidání nové aplikace / namespace

1. **Přidat do `.env`:**
   ```
   MONITORED_NAMESPACES=...,nova-app-01-app
   ```

2. **Nový Docker image** (obsahuje `config/namespaces.yaml`):
   ```bash
   ./install.sh --skip-db
   ```

3. **Naplnit data pro nový namespace:**
   ```bash
   kubectl delete job log-analyzer-init -n ai-log-analyzer --ignore-not-found
   helm template <infra-apps-dir> | kubectl apply -f - -l job-type=init
   kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
   ```

> Bez historických dat pro nový namespace použije detektor fallback `DEFAULT_THRESHOLD`.

---

## 5. Přepočet thresholdů

**Automatický:** CronJob každou neděli 03:00 UTC.

**Manuální:**
```bash
kubectl create job manual-thresholds --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/manual-thresholds -n ai-log-analyzer
kubectl delete job manual-thresholds -n ai-log-analyzer
```

---

## 6. Monitoring a diagnostika

### Failed joby

```bash
kubectl get jobs -n ai-log-analyzer --field-selector=status.successful=0
kubectl logs job/<failed-job> -n ai-log-analyzer
```

### Typické chyby

| Chyba | Příčina | Řešení |
|-------|---------|--------|
| `connection refused DB_HOST` | DB nedostupná z K8s | Ověřit DB_HOST, network policy |
| `ES connection timeout` | ES nedostupný | Ověřit ES_HOST, proxy |
| `401 Unauthorized (Confluence)` | Neplatný token | Obnovit credentials v CyberArk |
| `No thresholds found` | Prázdná DB | Spustit init job |
| `SMTP connection refused` | Mail server | Ověřit SMTP_HOST z K8s |

### DB diagnostika

```sql
SELECT MAX(created_at) FROM ailog_peak.peak_raw_data;
SELECT namespace, COUNT(*) FROM ailog_peak.peak_thresholds GROUP BY namespace;
SELECT COUNT(*) FROM ailog_peak.peak_investigation WHERE created_at > NOW() - INTERVAL '24 hours';
```

---

## 7. Lokální testování (development)

> Vyžaduje přímý síťový přístup k DB a ES.

```bash
cp .env.example .env
# Vyplnit credentials

python3 scripts/regular_phase.py --window 15 --dry-run
python3 scripts/backfill.py --days 1 --dry-run
python3 scripts/core/calculate_peak_thresholds.py --dry-run --verbose
python3 scripts/core/peak_detection.py --show-thresholds
```
