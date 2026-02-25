# Peak Detection - P93/CAP Percentile System

Systém detekuje anomalie (peaky) v error logu pomocí **P93/CAP percentilového systemu**.
Spike detekce probihá na urovni **namespace** (celkovy error count), ne per-fingerprint.

**Klicove soubory:**
- `scripts/pipeline/phase_c_detect.py` - spike detekce (Phase C pipeline)
- `scripts/core/peak_detection.py` - PeakDetector (P93/CAP thresholds z DB)
- `scripts/core/calculate_peak_thresholds.py` - prepocet P93/CAP z peak_raw_data
- `scripts/pipeline/phase_b_measure.py` - EWMA/MAD (pouze informativni metriky)

---

## Prehled detekčnich pravidel

Phase C aplikuje na kazdy fingerprint sadu nezavislych pravidel.
Kazde pravidlo nastavi boolean flag a prida evidence.

```
detect_batch():
  1. Agreguj error count per namespace
  2. PeakDetector.is_peak(ns_total, namespace, dow) pro kazdy namespace

Pro kazdy fingerprint:
  1. _detect_spike()          -> is_spike  (P93/CAP namespace-level)
  2. _detect_burst()          -> is_burst  (sliding window)
  3. _detect_new()            -> is_new    (registry lookup)
  4. _detect_cross_namespace()-> is_cross_namespace
  5. _detect_silence()        -> is_silence
  6. _detect_regression()     -> is_regression
```

---

## 1. Spike Detection (`_detect_spike`) - P93/CAP

**Ucel:** Detekuje, ze namespace ma neobvykle vysoky error rate (peak).

**Algoritmus: P93 OR CAP**

```
is_peak = (ns_total > P93_per_DOW) OR (ns_total > CAP)

P93_per_DOW = 93. percentil error countu pro (namespace, den_tydne)
              Zdroj: tabulka ailog_peak.peak_thresholds

CAP = (median_P93 + avg_P93) / 2 per namespace
      Zdroj: tabulka ailog_peak.peak_threshold_caps
```

### Jak to funguje v pipeline

1. **detect_batch()** agreguje total error count per namespace:
   - Regular phase (1 okno): sum current_count per namespace
   - Backfill (96 oken): total_count / active_windows (prumer per okno)

2. **PeakDetector.is_peak()** zkontroluje kazdy namespace proti P93/CAP

3. **_detect_spike()** per fingerprint:
   - Pokud namespace fingerprintu je v peaku -> `is_spike=True`
   - Evidence: `rule="spike_p93_cap"` s P93/CAP hodnotami

### Priklad

```
Namespace: pcb-sit-01-app, Pondeli
P93 threshold: 360 errors/window
CAP threshold: 373 errors/window
Aktualni celkovy count: 487 errors

487 > 360 (P93) -> SPIKE (triggered_by=p93)
```

### Fallback: Novy error typ

```
Podminka: baseline_ewma == 0 AND baseline_median == 0
Pravidlo: current_count >= 5
```

Novy error typ bez historie s 5+ vyskyty = spike. Konfigurovatelne pres
`new_error_min_count`.

### Legacy fallback (bez PeakDetectoru)

Pokud PeakDetector neni dostupny (chybi DB thresholds), pouzije se
puvodni EWMA ratio test jako fallback. Tento stav nastane jen pri
prvnim nasazeni pred naplnenim peak_raw_data.

---

## 2. EWMA/MAD - Informativni metriky

EWMA a MAD se **NEPOUZIVAJI pro spike detekci**. Zustavaji v Phase B
jako informativni metriky:

- `trend_ratio` = current_rate / baseline_ewma -> indikuje trend
- `trend_direction` = "increasing" / "stable" / "decreasing"
- `baseline_ewma` = exponencialne vazeny prumer historickych rates
- `baseline_mad` = median absolutnich odchylek

Tyto metriky se ukladaji do DB (peak_investigation) a pouzivaji
v Phase D pro bonus scoring (trend_ratio > 2.0 pridava body).

**Proc ne EWMA pro spike detekci:**
- EWMA produkuje 17.8% false positive rate (vs 7.8% P93)
- EWMA se adaptuje na vysoke hodnoty a pak misi realne peaky
- MAD test generuje masivni false positives u nizkych hodnot

---

## 3-6. Ostatni detekce

### Burst Detection (`_detect_burst`)

Detekuje nahlou LOKALNI koncentraci chyb v kratkem casovem okne.

```
Sliding window (60s): max_count / avg_count > burst_threshold (5.0)
```

### New Detection (`_detect_new`)

Detekuje novy fingerprint/problem_key (registry lookup).

### Cross-Namespace Detection (`_detect_cross_namespace`)

```
namespace_count >= cross_ns_threshold (2)
```

### Silence Detection (`_detect_silence`)

```
current_rate == 0 AND baseline_ewma > 5
```

### Regression Detection (`_detect_regression`)

```
fingerprint IN known_fixes AND current_version >= fixed_in_version
```

---

## P93/CAP Thresholds - Datovy tok

### 1. Sber dat (peak_raw_data)

Tabulka `ailog_peak.peak_raw_data` uchovava surove error county
per (namespace, 15-min okno). Plni se ze dvou zdroju:

- **init_phase.py** - inicializacni sber 21+ dni z ES (jednorázove)
- **regular_phase.py** - kazdy 15-min beh ulozi namespace totaly (průběžne)

```sql
-- Schéma peak_raw_data:
timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
error_count, original_value
-- UNIQUE(timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
```

### 2. Prepocet thresholds (calculate_peak_thresholds.py)

Spousti se periodicky (doporuceno tydne). Cte peak_raw_data a pocita:

```bash
python3 scripts/core/calculate_peak_thresholds.py
  --weeks 4            # Jen posledni 4 tydny dat
  --percentile 0.93    # Default z env PERCENTILE_LEVEL
  --dry-run            # Ukazat bez ulozeni
```

**Vystup:**
- `peak_thresholds` - P93 per (namespace, day_of_week)
- `peak_threshold_caps` - CAP per namespace

### 3. Pouziti v pipeline (PeakDetector)

PeakDetector nactě thresholds z DB (5-min cache) a vystavuje:

```python
detector = PeakDetector(conn=db_connection)
result = detector.is_peak(value=487, namespace='pcb-sit-01-app', day_of_week=0)
# {'is_peak': True, 'triggered_by': 'p93', 'p93_threshold': 360, 'cap_threshold': 373}
```

### Samozdokonalovaci smycka

```
Regular Phase (kazdych 15 min)
  -> uklada namespace totaly do peak_raw_data
  -> peak_raw_data roste
  -> calculate_peak_thresholds (tydne) prepocita P93/CAP
  -> PeakDetector nacte nove thresholds
  -> presnejsi detekce
```

---

## End-to-End Flow (Regular Phase)

```
1. fetch_unlimited() -> raw errors z ES (15 min)
       |
2. BaselineLoader.load_historical_rates() -> {error_type: [rates]} z DB
       |
3. Phase A: Parse -> NormalizedRecord[]
       |
4. Phase B: Measure -> MeasurementResult[]
   |  EWMA, MAD, trend_ratio (informativni metriky)
       |
5. Phase C: Detect
   |  5a. Agreguj error count per namespace
   |  5b. PeakDetector.is_peak() per namespace (P93 OR CAP)
   |  5c. Per fingerprint: spike + burst + new + cross_ns
       |
6. Phase D: Score -> 0-100
   |  base + spike(+25) + burst(+20) + new(+15) + ...
       |
7. Phase E: Classify -> category
       |
8. Build IncidentCollection
       |
9. Save to DB:
   |  - peak_investigation (per incident)
   |  - peak_raw_data (namespace totaly pro P93 prepocet)
       |
10. Update Registry
       |
11. Problem Analysis + Notifikace
```

---

## Konfigurace

Konfigurace se nacita z env vars (nastaveno K8s z `k8s/values.yaml`):

| Parametr | Default | Env var | Popis |
|----------|---------|---------|-------|
| `percentile_level` | 0.93 | `PERCENTILE_LEVEL` | Percentil pro thresholds (P93) |
| `default_threshold` | 100 | `DEFAULT_THRESHOLD` | Fallback kdyz chybi data |
| `min_samples` | 10 | `MIN_SAMPLES_FOR_THRESHOLD` | Min vzorku pro spolehlivy P93 |
| `ewma_alpha` | 0.3 | `EWMA_ALPHA` | EWMA citlivost (jen informativni) |
| `burst_threshold` | 5.0 | - | max/avg ratio pro burst |
| `cross_ns_threshold` | 2 | - | Min. namespace pro cross-NS flag |

---

## Zpetne dohrání dat z ES

Pro zlepseni percentiloveho odhadu:

```bash
# 1. Sber historickych dat do peak_raw_data (21+ dni)
python3 scripts/init_phase.py --days 30

# 2. Prepocet P93/CAP thresholds
python3 scripts/core/calculate_peak_thresholds.py --verbose

# 3. Overeni (optional)
python3 scripts/core/peak_detection.py --show-thresholds
```

Vice dat = presnejsi P93. Doporucuje se min. 14 dni, idealne 30+.

---

## Caste problemy

### P93 thresholds chybi v DB

**Pricina:** `peak_raw_data` je prazdna, nebo `calculate_peak_thresholds.py` nebyl spusten.

**Reseni:**
1. `python3 scripts/init_phase.py --days 21` (sber dat z ES)
2. `python3 scripts/core/calculate_peak_thresholds.py` (prepocet)

### PeakDetector neni dostupny

**Pricina:** DB connection failed, nebo thresholds tabulky neexistuji.

**Dsledek:** Pipeline pouzije legacy EWMA fallback (vyssi false positive rate).

**Reseni:** Zkontroluj DB connection a migrace (001_create_peak_thresholds.sql).

### False positive bursts

**Pricina:** Burst test je nezavisly na P93 - zalezi jen na distribuci
eventu uvnitr okna. Malo eventu (< 5) s nerovnomernou distribuci
muze vygenerovat high ratio.
