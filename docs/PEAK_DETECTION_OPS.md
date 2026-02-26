# P93/CAP Peak Detection - Provozni prirucka

## Jak to funguje

Spike detekce pouziva **percentilovy system** misto EWMA:

```
is_peak = (namespace_total > P93_per_DOW) OR (namespace_total > CAP)
```

| Pojem | Vyznam |
|-------|--------|
| **P93** | 93. percentil error countu pro (namespace, den_tydne) |
| **CAP** | `(median_P93 + avg_P93) / 2` per namespace (fallback) |
| **DOW** | Day of week — thresholdy se lisi po dnech (Po vs So) |

### Datovy tok

```
Regular phase (15 min)
  └─ uklada namespace totals → peak_raw_data

Backfill (historicka data)
  └─ uklada 15-min namespace totals → peak_raw_data

calculate_peak_thresholds.py (tydenne)
  └─ cte peak_raw_data
  └─ pocita P93 per (namespace, DOW)
  └─ pocita CAP per namespace
  └─ uklada → peak_thresholds + peak_threshold_caps

Pipeline (Phase C)
  └─ PeakDetector cte thresholdy z DB
  └─ porovnava aktualni namespace total vs P93/CAP
```

### DB tabulky

| Tabulka | Ucel | Kdo plni |
|---------|------|----------|
| `peak_raw_data` | 15-min error counts per namespace | regular_phase, backfill |
| `peak_thresholds` | P93 per (namespace, DOW) | calculate_peak_thresholds.py |
| `peak_threshold_caps` | CAP per namespace | calculate_peak_thresholds.py |
| `peak_investigation` | Detekovane incidenty | regular_phase, backfill |

---

## Prvni nasazeni (bootstrap)

### Varianta A: K8s Init Job (doporuceno)

Automaticky provede backfill + vypocet thresholdu + verifikaci:

```bash
# 1. Renderovat a spustit init job
helm template k8s/ | kubectl apply -f - -l job-type=init

# 2. Sledovat prubeh
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer

# 3. Po uspesnem dokonceni smazat job
kubectl delete job log-analyzer-init -n ai-log-analyzer
```

Konfigurace v `k8s/values.yaml`:

```yaml
init:
  backfillDays: 21        # kolik dni zpetne
  backfillWorkers: 4      # paralelni workery
  thresholdWeeks: 3       # z kolika tydnu pocitat P93/CAP
  activeDeadlineSeconds: 14400  # max 4 hodiny
```

### Varianta B: Manualne (lokalne / ad-hoc)

#### 1. Naplnit historicka data (14-21 dni)

```bash
# Backfill 21 dni — plni peak_investigation + peak_raw_data
python3 scripts/backfill.py --days 21 --workers 4
```

Backfill automaticky uklada 15-min namespace totals do `peak_raw_data`.

#### 2. Vypocitat thresholdy

```bash
# Vypocitat P93/CAP z nasbiranych dat (posledni 3 tydny)
python3 scripts/core/calculate_peak_thresholds.py --weeks 3

# Dry-run (jen zobrazi, neulozi)
python3 scripts/core/calculate_peak_thresholds.py --weeks 3 --dry-run
```

#### 3. Overit thresholdy

```bash
# Zobrazit aktualni thresholdy z DB
python3 scripts/core/peak_detection.py --show-thresholds

# Otestovat konkretni hodnotu
python3 scripts/core/peak_detection.py --check 500 pcb-sit-01-app 0
#                                             ^value ^namespace    ^DOW(0=Po)
```

#### 4. Spustit regular phase

```bash
python3 scripts/regular_phase.py
```

Regular phase automaticky:
- Pouziva P93/CAP pro spike detekci
- Uklada namespace totals do `peak_raw_data` (self-improving)

---

## Bezny provoz

### Regular phase (kazdych 15 min, K8s CronJob)

```bash
python3 scripts/regular_phase.py --window 15
```

- Automaticky plni `peak_raw_data`
- Pouziva P93/CAP thresholdy z DB
- Pokud thresholdy nejsou v DB, fallback na EWMA

### Prepocet thresholdu (tydenne, K8s CronJob `log-analyzer-thresholds`)

```bash
# Automaticky: CronJob bezi kazdy nedele 03:00 UTC
# Manualne spusteni:
python3 scripts/core/calculate_peak_thresholds.py --weeks 4
```

K8s CronJob `log-analyzer-thresholds` bezi automaticky kazdy nedele 03:00 UTC.

### Backfill (ad-hoc, po vykonu dat)

```bash
# Doplnit konkretni obdobi
python3 scripts/backfill.py --from "2026-02-01" --to "2026-02-14" --workers 4

# Po backfillu prepocitat thresholdy
python3 scripts/core/calculate_peak_thresholds.py --weeks 4
```

---

## Edge cases

### Novy namespace (zatim nema thresholdy)

PeakDetector pouzije **CAP** (pokud existuje pro jiny DOW) nebo **default_threshold** (100).
Po nasbrani dostatku dat (min 10 samplu per DOW) se P93 zacne pouzivat automaticky.

### Prazdna peak_raw_data (prvni spusteni)

```bash
# 1. Spustit backfill
python3 scripts/backfill.py --days 21 --workers 4

# 2. Vypocitat thresholdy
python3 scripts/core/calculate_peak_thresholds.py --weeks 3
```

Bez dat v `peak_raw_data` PeakDetector pouziva default threshold (100) nebo EWMA fallback.

### Doplneni dat z existujiciho peak_investigation (SQL)

Pokud backfill uz probehl bez plneni `peak_raw_data` (starsi verze kodu):

```sql
INSERT INTO ailog_peak.peak_raw_data
  (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count, original_value)
SELECT
  date_trunc('hour', pi.timestamp) + (pi.quarter_hour * 15) * interval '1 minute',
  pi.day_of_week, pi.hour_of_day, pi.quarter_hour, pi.namespace,
  SUM(pi.original_value), SUM(pi.original_value)
FROM ailog_peak.peak_investigation pi
WHERE pi.timestamp >= NOW() - interval '21 days'
GROUP BY 1, 2, 3, 4, 5
ON CONFLICT (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
DO UPDATE SET error_count = EXCLUDED.error_count, original_value = EXCLUDED.original_value;
```

Pak: `python3 scripts/core/calculate_peak_thresholds.py --weeks 3`

### Smazani a prepocet thresholdu

`calculate_peak_thresholds.py` pred insertem automaticky maze stare thresholdy
(`DELETE FROM peak_thresholds` + `DELETE FROM peak_threshold_caps`).
Staci spustit znovu.

### Zmena percentilu (napr. P95 misto P93)

```bash
# Jednorazove
python3 scripts/core/calculate_peak_thresholds.py --percentile 0.95

# Trvale: nastavit env PERCENTILE_LEVEL=0.95 v k8s/values.yaml
```

---

## Konfigurace (env vars)

| Promenna | Default | Popis |
|----------|---------|-------|
| `PERCENTILE_LEVEL` | `0.93` | Pouzity percentil (0.93 = P93) |
| `DEFAULT_THRESHOLD` | `100` | Fallback kdyz neni P93 ani CAP |
| `MIN_SAMPLES_FOR_THRESHOLD` | `10` | Min pocet vzorku pro spolehlivy P93 |
| `EWMA_ALPHA` | `0.3` | Alpha pro EWMA (jen informacni metriky) |

---

## Diagnostika

### Kolik dat je v peak_raw_data?

```sql
SELECT
  MIN(timestamp) as od,
  MAX(timestamp) as do,
  COUNT(*) as radku,
  COUNT(DISTINCT namespace) as namespacu,
  COUNT(DISTINCT day_of_week) as dnu
FROM ailog_peak.peak_raw_data;
```

### Aktualni thresholdy

```sql
SELECT namespace, day_of_week, percentile_value, sample_count
FROM ailog_peak.peak_thresholds
ORDER BY namespace, day_of_week;
```

### CAP hodnoty

```sql
SELECT namespace, cap_value, total_samples
FROM ailog_peak.peak_threshold_caps
ORDER BY namespace;
```

### Posledni spiky

```sql
SELECT timestamp, namespace, original_value, score, severity, detection_method
FROM ailog_peak.peak_investigation
WHERE is_spike = true
ORDER BY timestamp DESC
LIMIT 20;
```

---

## K8s Jobs prehled

| Job | Typ | Schedule | Ucel |
|-----|-----|----------|------|
| `log-analyzer` | CronJob | `*/15 * * * *` | Regular phase (15-min detekce) |
| `log-analyzer-backfill` | CronJob | `0 9 * * *` | Denni backfill + Confluence publish |
| `log-analyzer-thresholds` | CronJob | `0 3 * * 0` | Tydenny prepocet P93/CAP |
| `log-analyzer-init` | Job | one-shot | Bootstrap: backfill + thresholds + verify |

```bash
# Sledovani jobu
kubectl get jobs -n ai-log-analyzer -l app=log-analyzer
kubectl get cronjobs -n ai-log-analyzer

# Logy posledniho runu
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
kubectl logs -f $(kubectl get pods -n ai-log-analyzer -l job-type=thresholds --sort-by=.metadata.creationTimestamp -o name | tail -1) -n ai-log-analyzer
```

---

## Migrace z EWMA

1. **Zadne DB schema zmeny** — tabulky `peak_thresholds`, `peak_threshold_caps`, `peak_raw_data` uz existuji (migrace 000, 001)
2. **Jedina datova migrace**: `scripts/migrations/003_remove_version_suffixes.sql` (cisti `v6_backfill` → `backfill`)
3. **EWMA zustava** jako informacni metrika v Phase B (trend_ratio, scoring bonusy) — jen neni pouzite pro spike detekci
4. **Fallback**: pokud PeakDetector neni dostupny (prazdna DB), Phase C automaticky pouzije EWMA
