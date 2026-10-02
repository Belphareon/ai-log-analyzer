# Provoz — AI Log Analyzer

Vše pro běžný provoz, manuální zásahy a diagnostiku. Systém běží **autonomně přes K8s CronJoby** — tato příručka je pro situace, kdy je třeba ručně zasáhnout.

---

## 1. CronJoby — přehled

| CronJob | Schedule | Co dělá | Typická doba |
|---------|----------|---------|--------------|
| `log-analyzer` | `*/15 * * * *` | Hlavní pipeline: ES fetch → detect peaks → alert → export | 1–5 min |
| `log-analyzer-backfill` | `0 9 * * *` | Denní backfill + Confluence publish | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet robustního Pxx/CAP z úplných fact rows | 1–5 min |
| `log-analyzer-maintenance` | `30 2 * * *` | Denní rollup + retention faktů | 1–30 min |

### Závislosti

```
Init Job (jednorázově po instalaci)
  └─ backfill → plní authoritative 15min facts + peak_investigation
  └─ threshold calc → vypočítá robustní Pxx/CAP z complete facts

Poté autonomně:
  regular (*/15)       → fetch ES → Pxx/CAP + family gate → alert → plní complete facts
  backfill (09:00)     → zpracuje předchozí den → publikuje Confluence
  thresholds (Ne 03:00) → přepočítá robustní Pxx/CAP z posledních 4 týdnů
  maintenance (02:30)  → denní rollupy → smaže fakta starší než retention limit
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
# Uprav init values nebo image v infra-apps a spusť Argo sync.
# Argo Job samo delete/create díky resource-level Force/Replace.
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

Argo Application používá běžný apply a `ApplyOutOfSyncOnly=true`; globální `Replace=true` je zakázaný kvůli immutable bound PVC. Init Job je jediný resource s `Force=true,Replace=true`. Ruční mazání Jobu před běžným syncem není potřeba.

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

### Workflow lifecycle diagnostics

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.LIFECYCLE_ANALYSIS_ENABLED` | `false` | Zapne INFO-level lifecycle probe a evidence fetch |
| `env.LIFECYCLE_ALERT_ENABLED` | `false` | Povolí alert až po complete persisted high-confidence runu |
| `env.LIFECYCLE_PROBE_MAX_HITS` | `200` | Cap discovery probe; cap znamená partial run |
| `env.LIFECYCLE_FETCH_BATCH_SIZE` | `1000` | PIT/search_after page size |
| `env.LIFECYCLE_MAX_RECORDS_PER_QUERY` | `50000` | Cap záznamů per root/predecessor query |
| `env.LIFECYCLE_MAX_PREDECESSOR_IDS` | `500` | Cap predecessor ID per scope |
| `env.LIFECYCLE_MIN_RETRIES` | `3` | Minimum retry/return cyklů pro kandidáta |

Zavádění: nejprve zapnout pouze `LIFECYCLE_ANALYSIS_ENABLED`, ověřit complete/partial runy a evidence v DB i logu regular CronJobu, a teprve poté povolit `LIFECYCLE_ALERT_ENABLED`. Partial nebo failed run je diagnostický stav, nikdy alert.

### Detekce

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.PERCENTILE_LEVEL` | `0.93` | Uživatelská citlivost namespace Pxx thresholdu |
| `env.MIN_SAMPLES_FOR_THRESHOLD` | `10` | Min vzorků pro spolehlivý threshold |
| `env.DEFAULT_THRESHOLD` | `100` | CAP pro namespace bez vlastního thresholdu v kompatibilním snapshotu |
| `env.FINGERPRINT_SPIKE_MIN_COUNT` | `20` | Absolutní minimum pro historickou cause family |
| `env.FINGERPRINT_SPIKE_MAD_MULTIPLIER` | `6` | MAD násobek pro namespace/fingerprint family gate |

Pokud nelze inicializovat `PeakDetector` z authoritative threshold snapshotu, regular phase a backfill skončí s chybou. Selhání načtení authoritative namespace/fingerprint baseline běh nezastaví, ale fail-closed potlačí přiřazení namespace peaku ke cause family. Pro spike rozhodování není EWMA fallback.

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
  # Po merge změny spusť Argo sync; Job se při změně manifestu znovu vytvoří.
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
| `401/403 (Confluence)` | Neplatný Bearer token nebo chybějící edit oprávnění | Ověřit token v `CONFLUENCE_PASSWORD`/`CONFLUENCE_TOKEN` a oprávnění cílové stránky |
| Daily Incident Analysis je prázdná | Chybné `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` nebo selhal publisher v `backfill.py` | Ověřit page ID v rendered backfill CronJobu a hledat `Recent Incidents` v logu posledního backfill jobu |
| Argo sync selže na immutable Job/PVC | Globální `Replace=true` v Application | Odstranit globální Replace; ponechat Force/Replace pouze na init Jobu a zapnout `ApplyOutOfSyncOnly=true` |
| `No thresholds found` | Prázdná DB | Spustit init job |
| `Pxx/CAP peak detector initialization failed` | DB snapshot nebo baseline není dostupný/kompatibilní | Ověřit DB přístup, complete facts a `PERCENTILE_LEVEL`; job nespustí legacy EWMA fallback |
| `SMTP connection refused` | Mail server | Ověřit SMTP_HOST z K8s |

### DB diagnostika

```sql
SELECT MAX(window_start) FROM ailog_peak.v_complete_namespace_error_counts;
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
