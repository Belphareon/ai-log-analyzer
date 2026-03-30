# Provoz — AI Log Analyzer

Vše co SRE/ops potřebuje pro běžný provoz přes Kubernetes.

> **Konvence:** Veškeré operace se provádějí **přes K8s joby** (CronJob / manuální Job). Lokální spouštění je pouze pro vývoj/debugging.

---

## Obsah

1. [CronJob přehled](#1-cronjob-přehled)
2. [Parametry jobů (values.yaml)](#2-parametry-jobů-valuesyaml)
3. [Manuální spuštění jobů](#3-manuální-spuštění-jobů)
4. [Alerting tuning](#4-alerting-tuning)
5. [Přidání nové aplikace / namespace](#5-přidání-nové-aplikace--namespace)
6. [Přepočet thresholdů](#6-přepočet-thresholdů)
7. [Monitoring a diagnostika](#7-monitoring-a-diagnostika)
8. [Lokální testování (development)](#8-lokální-testování-development)

---

## 1. CronJob přehled

Po úspěšné instalaci systém běží autonomně přes 3 CronJoby:

| CronJob | Schedule | Co dělá | Typická doba |
|---------|----------|---------|--------------|
| `log-analyzer` | `*/15 * * * *` | Hlavní pipeline: ES fetch → detect peaks → email alert → export | 1–5 min |
| `log-analyzer-backfill` | `0 9 * * *` | Denní backfill + Confluence publish (Known Errors, Known Peaks, Recent Incidents) | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP thresholdů z peak_raw_data | 1–5 min |

### Pořadí závislostí

```
Init Job (jednorázově)
  └─ backfill 21 dní → plní peak_raw_data + peak_investigation
  └─ threshold calc → vypočítá P93/CAP z backfill dat

Poté běží autonomně:
  regular (*/15)    → fetch ES → detect → alert → plní peak_raw_data
  backfill (09:00)  → zpracuje předchozí den → publikuje Confluence
  thresholds (Ne 03:00) → přepočítá P93/CAP z posledních 4 týdnů
```

### Stav CronJobů

```bash
# Přehled CronJobů
kubectl get cronjobs -n ai-log-analyzer

# Posledních 5 jobů
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp | tail -5

# Logy konkrétního jobu
kubectl logs job/<job-name> -n ai-log-analyzer
```

---

## 2. Parametry jobů (values.yaml)

Všechny parametry jsou v `values.yaml` daného prostředí — v repozitáři `k8s-infra-apps-<env>/infra-apps/ai-log-analyzer/values.yaml`.

### Regular Phase — parametry alertingu

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.WINDOW_MINUTES` | `15` | Časové okno pro analýzu |
| `env.MAX_PEAK_ALERTS_PER_WINDOW` | `3` | Max peaků v jednom digest emailu |
| `env.ALERT_DIGEST_ENABLED` | `true` | Digest místo individuálních emailů |
| `env.ALERT_COOLDOWN_MIN` | `45` | Min. interval mezi alerty pro stejný peak |
| `env.ALERT_HEARTBEAT_MIN` | `120` | Opakovat alert pro trvající peak |
| `env.ALERT_MIN_DELTA_PCT` | `30` | Min. změna error_count pro znovu-odeslání |
| `env.ALERT_CONTINUATION_LOOKBACK_MIN` | `60` | Lookback pro pokračující peak |

### Regular Phase — parametry detekce

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.PERCENTILE_LEVEL` | `0.93` | Percentil pro peak thresholds (P93) |
| `env.MIN_SAMPLES_FOR_THRESHOLD` | `10` | Min počet vzorků pro spolehlivý threshold |
| `env.DEFAULT_THRESHOLD` | `100` | Fallback threshold pokud není data v DB |
| `env.SPIKE_THRESHOLD` | `3.0` | EWMA spike ratio (sekundární metrika) |
| `env.EWMA_ALPHA` | `0.3` | EWMA smoothing faktor |

### Init Job — parametry bootstrapu

| Parametr | Default | Popis |
|----------|---------|-------|
| `init.backfillDays` | `21` | Počet dní zpětně pro backfill |
| `init.backfillWorkers` | `4` | Paralelní workery |
| `init.thresholdWeeks` | `3` | Týdnů pro výpočet thresholdů |
| `init.activeDeadlineSeconds` | `14400` | Max doba běhu init jobu (4h) |

### Resources

| Job | CPU request | Memory request | CPU limit | Memory limit |
|-----|-------------|----------------|-----------|--------------|
| Regular | 500m | 1Gi | 2 | 4Gi |
| Backfill | 500m | 1Gi | 2 | 4Gi |
| Thresholds | 250m | 512Mi | 1 | 2Gi |
| Init | 250m | 512Mi | 1 | 2Gi |

---

## 3. Manuální spuštění jobů

Když potřebujete spustit job mimo schedule (ad-hoc backfill, přepočet thresholdů, test):

### 3.1 Manuální trigger CronJobu

```bash
# Spustit regular phase ručně
kubectl create job log-analyzer-manual --from=cronjob/log-analyzer -n ai-log-analyzer

# Spustit backfill ručně
kubectl create job backfill-manual --from=cronjob/log-analyzer-backfill -n ai-log-analyzer

# Spustit threshold recalc ručně
kubectl create job thresholds-manual --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer

# Sledovat logy
kubectl logs -f job/<job-name> -n ai-log-analyzer

# Po dokončení uklidit
kubectl delete job <job-name> -n ai-log-analyzer
```

### 3.2 Init Job (re-bootstrap)

Pro přeplnění dat od nuly (např. po změně namespace):

```bash
# Smazat starý init job (pokud existuje)
kubectl delete job log-analyzer-init -n ai-log-analyzer --ignore-not-found

# Spustit nový init
helm template k8s/ | kubectl apply -f - -l job-type=init

# Sledovat
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

---

## 4. Alerting tuning

### Doporučené profily

**Standardní (SIT/UAT):**

```yaml
env:
  MAX_PEAK_ALERTS_PER_WINDOW: "3"
  ALERT_DIGEST_ENABLED: "true"
  ALERT_COOLDOWN_MIN: "45"
  ALERT_HEARTBEAT_MIN: "120"
  ALERT_MIN_DELTA_PCT: "30"
```

**Méně emailů** (vyšší thresholdy):

```yaml
env:
  ALERT_COOLDOWN_MIN: "90"
  ALERT_HEARTBEAT_MIN: "180"
  ALERT_MIN_DELTA_PCT: "50"
```

**Více citlivé:**

```yaml
env:
  ALERT_COOLDOWN_MIN: "30"
  ALERT_HEARTBEAT_MIN: "60"
  ALERT_MIN_DELTA_PCT: "20"
```

### Chování

- Jeden digest email za 15min okno (pokud jsou alerty k odeslání)
- Pokračující peak bez materiální změny se potlačí
- Znovu se posílá při: změně trendu, změně error_count ≥ `ALERT_MIN_DELTA_PCT`, nové aplikaci/namespace, heartbeat intervalu
- Fallback na per-peak emaily: `ALERT_DIGEST_ENABLED=false`

### Změna parametrů

1. Upravit `values.yaml` v příslušném infra-apps repozitáři
2. Commitnout a pushnout
3. Aplikovat: `helm template k8s/ | kubectl apply -f -`
4. Nový parametr se projeví při příštím běhu CronJobu (do 15 min)

---

## 5. Přidání nové aplikace / namespace

### Krok 1: config/namespaces.yaml

Přidat namespace do monitoringu:

```yaml
namespaces:
  - <existing-ns>
  - nova-app-01-app    # ← přidat
```

### Krok 2: Nový Docker image

```bash
docker build -t dockerhub.kb.cz/<squad>/ai-log-analyzer:<new_tag> .
docker push dockerhub.kb.cz/<squad>/ai-log-analyzer:<new_tag>
```

### Krok 3: Aktualizovat values.yaml

```yaml
app:
  image: dockerhub.kb.cz/<squad>/ai-log-analyzer:<new_tag>
```

### Krok 4: Naplnit historická data

Spustit init job (nebo ad-hoc backfill):

```bash
# Smazat starý init job
kubectl delete job log-analyzer-init -n ai-log-analyzer --ignore-not-found

# Spustit nový init (backfill + threshold calc)
helm template k8s/ | kubectl apply -f - -l job-type=init
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

### Krok 5: Ověřit

```bash
# Ověřit thresholdy pro nový namespace
kubectl create job verify-thresholds --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/verify-thresholds -n ai-log-analyzer
# Výstup musí obsahovat thresholdy pro nový namespace
```

> **Poznámka:** Bez P93/CAP dat pro nový namespace použije detektor fallback `DEFAULT_THRESHOLD` (100).

---

## 6. Přepočet thresholdů

### Automatický (CronJob)

Běží každou neděli 03:00 UTC — žádná akce potřeba.

### Manuální

```bash
kubectl create job thresholds-manual --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/thresholds-manual -n ai-log-analyzer
```

### Po manuálním backfillu

Vždy přepočítat po backfillu:

```bash
# 1. Backfill
kubectl create job backfill-manual --from=cronjob/log-analyzer-backfill -n ai-log-analyzer
kubectl logs -f job/backfill-manual -n ai-log-analyzer

# 2. Přepočet thresholdů
kubectl create job thresholds-manual --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/thresholds-manual -n ai-log-analyzer

# 3. Úklid
kubectl delete job backfill-manual thresholds-manual -n ai-log-analyzer
```

---

## 7. Monitoring a diagnostika

### Kontrola stavu

```bash
# CronJoby a jejich poslední spuštění
kubectl get cronjobs -n ai-log-analyzer

# Posledních 10 jobů
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp | tail -10

# Failed joby
kubectl get jobs -n ai-log-analyzer --field-selector=status.successful=0

# Logy posledního failed jobu
kubectl logs job/<failed-job> -n ai-log-analyzer
```

### Typické chyby

| Chyba v logu | Příčina | Řešení |
|--------------|---------|--------|
| `connection refused DB_HOST` | DB není dostupná z klusteru | Ověřit DB_HOST v values.yaml, network policy |
| `ES connection timeout` | ES není dostupný | Ověřit ES_HOST, proxy konfigurace |
| `401 Unauthorized (Confluence)` | Neplatný Confluence token | Obnovit credentials v CyberArk |
| `No thresholds found` | Prázdná DB (po fresh install) | Spustit init job |
| `SMTP connection refused` | Mail server nedostupný | Ověřit SMTP_HOST:SMTP_PORT z K8s |

### DB diagnostika

```sql
-- Poslední data v peak_raw_data
SELECT MAX(created_at) FROM ailog_peak.peak_raw_data;

-- Počet thresholdů per namespace
SELECT namespace, COUNT(*) FROM ailog_peak.peak_thresholds GROUP BY namespace;

-- Počet investigation záznamů za posledních 24h
SELECT COUNT(*) FROM ailog_peak.peak_investigation
WHERE created_at > NOW() - INTERVAL '24 hours';
```

---

## 8. Lokální testování (development)

> **Pozor:** Lokální testy vyžadují přímý přístup k DB a ES. V produkčním prostředí je to obvykle dostupné pouze z K8s clusteru.

### Příprava

```bash
cp .env.example .env
# Vyplnit credentials
```

### Testy

```bash
# Dry-run regular phase (bez alertů)
python3 scripts/regular_phase.py --window 15 --dry-run

# Dry-run backfill (1 den, bez zápisu)
python3 scripts/backfill.py --days 1 --dry-run

# Dry-run thresholdů
python3 scripts/core/calculate_peak_thresholds.py --dry-run --verbose

# Zobrazit aktuální thresholdy z DB
python3 scripts/core/peak_detection.py --show-thresholds
```
