# Jak to funguje — AI Log Analyzer

Detailní popis celého procesu: od načtení logů přes detekci anomálií až po odeslání notifikace.

---

## Obsah

1. [Spouštění a životní cyklus](#1-spouštění-a-životní-cyklus)
2. [Načítání logů z Elasticsearch](#2-načítání-logů-z-elasticsearch)
3. [Fingerprinting a normalizace](#3-fingerprinting-a-normalizace)
4. [Měření a baseline](#4-měření-a-baseline)
5. [Detekce anomálií — P93/CAP](#5-detekce-anomálií--p93cap)
6. [Ostatní detekční pravidla](#6-ostatní-detekční-pravidla)
7. [Skórování (0–100)](#7-skórování-0100)
8. [Klasifikace](#8-klasifikace)
9. [Registry — nové vs. známé problémy](#9-registry--nové-vs-známé-problémy)
10. [Incident Analysis](#10-incident-analysis)
11. [Rozhodování o alertu](#11-rozhodování-o-alertu)
12. [Email digest](#12-email-digest)
13. [Confluence export](#13-confluence-export)
14. [Write-back — zpětné obohacení dat](#14-write-back--zpětné-obohacení-dat)
15. [Backfill](#15-backfill)
16. [Přepočet thresholdů](#16-přepočet-thresholdů)

---

## 1. Spouštění a životní cyklus

Program `scripts/regular_phase.py` se spouští každých 15 minut jako Kubernetes CronJob.

Při každém spuštění proběhne tento cyklus:

```
 1. Načti konfiguraci (namespaces.yaml, .env)
 2. Načti YAML registry (known_problems, known_peaks, fingerprint_index)
 3. Načti stav alertů (alert_state_regular_phase.json)
 4. Načti historický baseline z DB (posledních 7 dní)
 5. Stáhni logy z Elasticsearch za aktuální okno (15 min)
 6. Spusť Detection Pipeline (fáze A→F) pro každý namespace
 7. Spusť Incident Analysis
 8. Ulož výsledky do DB (peak_raw_data, peak_investigation)
 9. Ulož/aktualizuj YAML registry
10. Rozhodni, zda odeslat alert
11. Pokud ano — odešli email digest
```

---

## 2. Načítání logů z Elasticsearch

Modul `scripts/core/fetch_unlimited.py` stáhne **všechny** logy za aktuální 15min okno.

- Standardní ES limit 10 000 výsledků je obejit pomocí **stránkování přes `search_after`**
- Logy jsou filtrovány na sledované namespace (seznam z `config/namespaces.yaml`)
- Dotaz cílí na index `ES_INDEX` (např. `cluster-app_pcb-*`) — konfigurováno v `.env`
- Výsledek: seznam raw JSON dokumentů z ES

---

## 3. Fingerprinting a normalizace

**Fáze A** (`phase_a_parse.py`) zpracuje každý raw log záznam:

### Co se extrahuje

| Pole | Zdroj v ES dokumentu |
|------|------|
| `namespace` | `kubernetes.namespace_name` |
| `app_name` | `kubernetes.labels.app` nebo `deployment_label` |
| `error_type` | `error_type`, `exception.type`, nebo odvozeno |
| `message` | `message` (raw) |
| `trace_id` | `traceId`, `trace.id` |
| `environment` | z namespace prefixu (dev/sit/uat/prod) |

### Normalizace message

Dynamické hodnoty se před fingerprinting nahradí zástupnými tokeny:
- `card_id=12345678` → `card_id=<NUM>`
- `traceId=abc-def-123` → `traceId=<UUID>`
- `192.168.1.1` → `<IP>`

Tím dostane stejný typ chyby stejný fingerprint bez ohledu na konkrétní data.

### Výpočet fingerprint

```python
fingerprint = MD5(f"{error_type}:{normalized_message}")[:16]
```

Fingerprint identifikuje **typ problému**, ne konkrétní výskyt.

---

## 4. Měření a baseline

**Fáze B** (`phase_b_measure.py`) vypočítá statistiky pro každý fingerprint:

### Baseline

- Načítá se z DB (`ailog_peak.peak_raw_data`) — posledních 7 dní
- Baseline = EWMA (exponenciálně vážený klouzavý průměr, alfa default 0.3)
- Odráží, kolik chyb tohoto typu bylo *obvyklé* v tomto namespace v tuto dobu

### EWMA a MAD — informativní metriky

EWMA a MAD se **NEPOUŽÍVAJÍ pro spike detekci** (viz důvody níže). Zůstávají v Phase B jako informativní metriky:

- `trend_ratio` = `current_rate / baseline_ewma` → indikuje trend
- `trend_direction` = "increasing" / "stable" / "decreasing"
- `baseline_ewma` = exponenciálně vážený průměr historických rates
- `baseline_mad` = medián absolutních odchylek

Tyto metriky se ukládají do DB (`peak_investigation`) a používají v Phase D pro bonus scoring (`trend_ratio > 2.0` přidává body).

**Proč ne EWMA pro spike detekci:**
- EWMA produkuje 17.8% false positive rate (vs 7.8% P93)
- EWMA se adaptuje na vysoké hodnoty a pak missí reálné peaky
- MAD test generuje masivní false positives u nízkých hodnot

---

## 5. Detekce anomálií — P93/CAP

**Fáze C** (`phase_c_detect.py`) rozhoduje, zda je aktuální počet chyb anomální.

### P93/CAP metodika

Spike detekce probíhá na úrovni **namespace** (celkový error count), ne per-fingerprint:

```
is_peak = (namespace_total > P93_per_DOW) OR (namespace_total > CAP)
```

**P93** = 93. percentil historických error countů pro danou kombinaci `(namespace, day_of_week)`.
- Pokud je v pondělí v `pcb-sit-01-app` obvyklých maximálně 500 chyb, P93 = 500.
- Výskyt 600 chyb = spike.

**CAP** = `(median_P93 + avg_P93) / 2` přes všechny dny týdne pro daný namespace.
- Záložní práh, pokud pro konkrétní den není dostatek historických dat.

### Jak to funguje v pipeline

1. **`detect_batch()`** agreguje total error count per namespace
2. **`PeakDetector.is_peak()`** zkontroluje každý namespace proti P93/CAP
3. **`_detect_spike()`** per fingerprint: pokud namespace fingerprintu je v peaku → `is_spike=True`

### Příklad

```
Namespace: pcb-sit-01-app, Pondělí
P93 threshold: 360 errors/window
CAP threshold: 373 errors/window
Aktuální celkový count: 487 errors

487 > 360 (P93) → SPIKE (triggered_by=p93)
```

### Jak se thresholdy počítají

```
Regular phase (15 min)
  └─ ukládá namespace totals → peak_raw_data

Backfill (historická data)
  └─ ukládá 15-min namespace totals → peak_raw_data

calculate_peak_thresholds.py (týdně)
  └─ čte peak_raw_data
  └─ počítá P93 per (namespace, DOW)
  └─ počítá CAP per namespace
  └─ ukládá → peak_thresholds + peak_threshold_caps

Pipeline (Phase C)
  └─ PeakDetector čte thresholdy z DB
  └─ porovnává aktuální namespace total vs P93/CAP
```

### DB tabulky pro spike detekci

| Tabulka | Účel | Kdo plní |
|---------|------|----------|
| `peak_raw_data` | 15-min error counts per namespace | regular_phase, backfill |
| `peak_thresholds` | P93 per (namespace, DOW) | calculate_peak_thresholds.py |
| `peak_threshold_caps` | CAP per namespace | calculate_peak_thresholds.py |

### Fallback: nový error typ

Nový error typ bez historie s ≥5 výskyty = spike (`new_error_min_count`):
```
baseline_ewma == 0 AND baseline_median == 0 AND current_count >= 5
```

### Legacy fallback (bez PeakDetectoru)

Pokud PeakDetector není dostupný (chybí DB thresholds), použije se EWMA ratio test. Tento stav nastane jen při prvním nasazení před naplněním `peak_raw_data`.

---

## 6. Ostatní detekční pravidla

| Flag | Pravidlo | Popis |
|------|----------|-------|
| `is_burst` | Sliding window (60s), `max_count / avg_count > 5.0` | Náhlá lokální koncentrace chyb |
| `is_new` | Fingerprint/problem_key není v registry + count ≥ min | Nový typ chyby, dosud neviděný |
| `is_regression` | Fingerprint byl znám, zobrazoval se < lookback_min | Regrese — chyba se vrátila |
| `is_cross_namespace` | Fingerprint ve ≥ 2 namespace | Problém se šíří přes více prostředí |
| `is_silence` | `current_rate == 0 AND baseline_ewma > 5` | Očekávaný error se neobjevil |

---

## 7. Skórování (0–100)

**Fáze D** (`phase_d_score.py`) vypočítá numerické skóre:

```
score = min(count / 10, 30)     # základní skóre z počtu chyb (max 30)
      + 25 if is_spike
      + 20 if is_burst
      + 15 if is_new
      + 35 if is_regression
      + 20 if is_cascade
      + 15 if is_cross_namespace
      + (trend_ratio - 2.0) * 2.0    # bonus za trend nad 2.0×
      + (namespace_count - 2) * 3.0  # bonus za každý NS nad 2
```

Skóre je **deterministické** — stejný vstup vždy dá stejný výstup.

| Score | Severity |
|------:|----------|
| ≥ 80  | critical |
| ≥ 60  | high     |
| ≥ 40  | medium   |
| ≥ 20  | low      |
| < 20  | info     |

---

## 8. Klasifikace

**Fáze E** (`phase_e_classify.py`) přiřadí každému incidentu **kategorii** a **subcategory** pomocí regexových pravidel seřazených dle priority.

Kategorie: `MEMORY`, `DATABASE`, `NETWORK`, `AUTH`, `BUSINESS`, `INTEGRATION`, `CONFIGURATION`, `INFRASTRUCTURE`, `UNKNOWN`

---

## 9. Registry — nové vs. známé problémy

Problem Registry (`scripts/core/problem_registry.py`) zajišťuje identifikaci:

- **Nový problém**: fingerprint dosud neviděný → vytvoří se nový záznam, `is_new=True`
- **Známý problém**: fingerprint nalezen → aktualizuje se `last_seen`, `occurrences`, behavior, root_cause

Registry soubory (`registry/`) jsou append-only — nikdy se z nich nemaže.

---

## 10. Incident Analysis

Vrstva `incident_analysis/` poskytuje kauzální analýzu:

1. **TimelineBuilder** — sestaví chronologickou osu: kdy se co objevilo a v jakém pořadí
2. **ScopeBuilder + Propagation** — identifikuje root_apps, downstream_apps, detekuje propagaci
3. **CausalInferenceEngine** — deterministicky inferuje kořenovou příčinu z trace kroků (žádné ML)
4. **FixRecommender** — generuje konkrétní doporučené akce pro SRE

Report jasně odděluje **FACTS** (co se stalo) od **HYPOTHESIS** (možná příčina).

---

## 11. Rozhodování o alertu

Regular phase rozhoduje, zda odeslat notifikaci:

| Podmínka | Hodnota (default) | Popis |
|----------|--------------------|-------|
| `ALERT_COOLDOWN_MIN` | 45 | Min. interval mezi alerty pro stejný peak |
| `ALERT_HEARTBEAT_MIN` | 120 | Opakovaný alert i pro pokračující peak |
| `ALERT_MIN_DELTA_PCT` | 30 | Min. změna error_count pro znovu-odeslání |
| `MAX_PEAK_ALERTS_PER_WINDOW` | 3 | Max. počet peaků v jednom digest emailu |
| `ALERT_CONTINUATION_LOOKBACK_MIN` | 60 | Lookback pro detekci pokračujícího peaku |

Continuation: peak detekovaný v předchozím okně se považuje za pokračující. Potlačuje se, pokud nedošlo k materiální změně.

---

## 12. Email digest

Když jsou peaky k odeslání, `send_regular_phase_peak_digest()`:

1. **Summary tabulka** — všechny peaky v cron okně (error_class, type, status, NS, trend, count)
2. **Detail bloky** — korelované alerty (stejný trace_id + namespace set) se seskupí do jednoho bloku
3. **Trace flow** — číslované kroky s názvem aplikace a zprávou; merged ze všech alertů ve skupině
4. **Inferred root cause** — s confidence labelem
5. **Propagation info** — počet services, typ propagace, délka trvání

Subject: `AI Log Analyzer | HH:MM - HH:MM | D.M.YYYY`

---

## 13. Confluence export

`table_exporter.py` generuje tabulky pro Confluence:

- **Known Errors** — `ErrorTableRow` s kategoriemi, root cause, behavior, activity status
- **Known Peaks** — `PeakTableRow` s peak_count, peak_ratio, occurrences, first/last seen, Peak Details

---

## 14. Write-back — zpětné obohacení dat

Regular phase po analýze zapíše zpět do registry:
- `entry.behavior` — strukturovaný text s trace kroky, root cause, propagation
- `entry.root_cause` — inferred root cause text

Toto obohacení se pak zobrazí v Confluence tabulkách.

---

## 15. Backfill

`scripts/backfill.py` zpracovává historická data:

```bash
# Zpracovat posledních 7 dní
python3 scripts/backfill.py --days 7

# Zpracovat konkrétní období
python3 scripts/backfill.py --from "2026-02-01" --to "2026-02-14" --workers 4
```

Pro každý den: fetch 24h dat po 15min oknech → pipeline → DB save → registry update.
Na konci: daily report + Teams notifikace.

---

## 16. Přepočet thresholdů

`scripts/core/calculate_peak_thresholds.py` přepočítá P93/CAP z nasbíraných dat:

```bash
# Přepočítat z posledních 4 týdnů
python3 scripts/core/calculate_peak_thresholds.py --weeks 4

# Dry-run (jen zobrazí, neuloží)
python3 scripts/core/calculate_peak_thresholds.py --weeks 4 --dry-run
```

V K8s běží automaticky jako CronJob `log-analyzer-thresholds` každou neděli 03:00 UTC.

### Edge cases

- **Nový namespace** (bez thresholdů): PeakDetector použije CAP (pokud existuje pro jiný DOW) nebo `default_threshold` (100)
- **Málo dat** (< 7 dní): P93 bude méně přesný, CAP slouží jako bezpečná fallback
- **Víkend vs pracovní den**: thresholdy se liší per day_of_week
