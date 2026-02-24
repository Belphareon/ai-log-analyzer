# Peak Detection - Detailní popis algoritmů

Tento dokument popisuje jak systém detekuje anomálie (peaky) v error logu.
Detekce probíhá v Phase C pipeline (`scripts/pipeline/phase_c_detect.py`),
ale závisí na datech z Phase B (`scripts/pipeline/phase_b_measure.py`)
a na historickém baseline z DB (`scripts/core/baseline_loader.py`).

---

## Přehled detekčních pravidel

Phase C aplikuje na každý fingerprint sadu nezávislých detekčních pravidel.
Každé pravidlo nastaví boolean flag a přidá evidence (důkaz).
Jeden fingerprint může mít více flagů současně (např. `is_spike + is_new`).

```
Pro každý fingerprint:
  1. _detect_spike()          → is_spike
  2. _detect_burst()          → is_burst
  3. _detect_new()            → is_new
  4. _detect_cross_namespace()→ is_cross_namespace
  5. _detect_silence()        → is_silence
  6. _detect_regression()     → is_regression
```

---

## 1. Spike Detection (`_detect_spike`)

**Účel:** Detekuje, že aktuální error rate výrazně převyšuje historický průměr.

**Tři testy (aplikovány postupně, první úspěšný vyhrává):**

### Test 1: EWMA ratio

```
Podmínka: baseline_ewma > 0
Výpočet:  ratio = current_rate / baseline_ewma
Pravidlo:  ratio > spike_threshold (default: 3.0)
```

Pokud aktuální rate je 3x vyšší než EWMA baseline, je to spike.

**Příklad:**
- baseline_ewma = 10 errors/window, current_rate = 45 errors/window
- ratio = 45/10 = 4.5 > 3.0 -> SPIKE

### Test 2: MAD (Median Absolute Deviation)

```
Podmínka: baseline_mad > 0
Výpočet:  mad_upper = baseline_median + (baseline_mad * spike_mad_threshold)
Pravidlo:  current_rate > mad_upper
```

Default: `spike_mad_threshold = 3.0`

Robustnější test, který odolává outlierům v historických datech.
MAD se počítá jako medián absolutních odchylek od mediánu.

**Příklad:**
- baseline_median = 8, baseline_mad = 2
- mad_upper = 8 + (2 * 3.0) = 14
- current_rate = 20 > 14 -> SPIKE

### Test 3: Fallback pro nové error typy

```
Podmínka: baseline_ewma == 0 AND baseline_median == 0
Pravidlo:  current_count >= 5
```

Pokud error typ nemá žádnou historii (baseline = 0), a v aktuálním okně
je alespoň 5 výskytů, klasifikuje se jako spike. Tento fallback zajišťuje,
že nové error typy s významným počtem výskytů nejsou ignorovány.

---

## 2. Burst Detection (`_detect_burst`)

**Účel:** Detekuje náhlou LOKÁLNÍ koncentraci chyb v krátkém časovém okně.

**Rozdíl od spike:** Spike porovnává aktuální rate s historickým baseline.
Burst porovnává distribuci eventů UVNITŘ aktuálního okna - hledá,
zda se velká část eventů nahromadila v krátkém časovém úseku.

**Algoritmus:**

```
1. Seřaď records podle timestamp
2. Sliding window (default: 60s):
   Pro každý record i:
     - Spočítej kolik records je v okně [timestamp_i - 60s, timestamp_i]
     - Ulož jako window_count[i]
3. Výpočet:
   max_count = max(window_counts)
   avg_count = mean(window_counts)
   ratio = max_count / avg_count
4. Pravidlo:
   ratio > burst_threshold (default: 5.0)
```

**Příklad:**
- 100 errors v 15-min okně, ale 80 z nich přišlo během 30 sekund
- max_count = 80 (v sliding window 60s)
- avg_count = 15
- ratio = 80/15 = 5.3 > 5.0 -> BURST

**Minimální podmínka:** Alespoň 2 records s validním timestamp.

---

## 3. New Detection (`_detect_new`)

**Účel:** Detekuje fingerprint/problem_key, který dosud nebyl viděn.

**Algoritmus (V2 s Registry integrací):**

```
1. Check fingerprint:
   IF fingerprint IN known_fingerprints -> KNOWN (ne new)

2. Check problem_key (pokud registry je dostupný):
   problem_key = compute_problem_key(category, apps, error_type, message, namespaces)
   IF registry.is_problem_key_known(problem_key):
     -> Fingerprint je nový, ale problém je známý (nová varianta)
     -> Přidej fingerprint do known_fingerprints pro tuto session
     -> KNOWN (ne new)

3. Pokud ani fingerprint ani problem_key nejsou známé:
   -> is_new = True
   -> Přidej fingerprint do known_fingerprints pro tuto session
```

**Registry se načítá PŘED spuštěním pipeline** (v regular_phase_v6.py):
```python
pipeline.phase_c.registry = registry
pipeline.phase_c.known_fingerprints = registry.get_all_known_fingerprints()
```

---

## 4. Cross-Namespace Detection (`_detect_cross_namespace`)

**Účel:** Detekuje, že stejný error pattern se vyskytuje ve více namespacech.

```
Pravidlo: namespace_count >= cross_ns_threshold (default: 2)
```

Cross-namespace error typicky indikuje systémový problém (shared dependency,
infra issue), ne lokální bug v jedné aplikaci.

---

## 5. Silence Detection (`_detect_silence`)

**Účel:** Detekuje neočekávanou ABSENCI errorů.

```
Podmínka: current_rate == 0 AND baseline_ewma > 5
```

Pokud error typ, který normálně produkuje 5+ errors/window, najednou
nemá žádné výskyty, může to indikovat problém (např. aplikace spadla
a neprodukuje ani error logy).

---

## 6. Regression Detection (`_detect_regression`)

**Účel:** Detekuje, že error, který byl opraven, se znovu objevil.

```
Podmínka: fingerprint IN known_fixes
         AND current_version >= fixed_in_version
```

Pokud error byl opraven ve verzi 1.5.0, ale objevuje se ve verzi 1.6.0,
je to regrese.

---

## Baseline - Odkud se bere

Kvalita detekce závisí na kvalitě baseline. Baseline se skládá ze dvou zdrojů:

### Zdroj 1: Aktuální okno (vždy dostupné)

Phase B rozdělí aktuální data na sub-okna (po 15 min) a z nich vypočítá rates.
Pro 15-min regular phase je ale typicky jen 1 okno -> žádný intra-window baseline.
Pro 24h backfill je k dispozici až 96 oken -> dobrý intra-window baseline.

### Zdroj 2: Historický baseline z DB (regular phase)

`BaselineLoader` (`scripts/core/baseline_loader.py`) načte historická data
z tabulky `ailog_peak.peak_investigation`:

```sql
SELECT error_type, reference_value, timestamp
FROM ailog_peak.peak_investigation
WHERE error_type = ANY(error_types)
  AND timestamp > now() - interval '7 days'
  AND (is_spike OR is_burst OR score >= 30)
ORDER BY error_type, timestamp ASC
```

**Vrací:** `{error_type: [reference_value_1, reference_value_2, ...]}`

Phase B pak kombinuje oba zdroje:
```python
if error_type in error_type_baseline:
    historical_rates = error_type_baseline[error_type] + current_window_rates
```

**Omezení:**
- Nový error_type bez historie v DB -> baseline = 0 -> spike detekce
  projde jen přes fallback test (current_count >= 5)
- DB query filtruje jen záznamy s `is_spike OR is_burst OR score >= 30`,
  takže error typy s nízkou závažností nemusí mít historii

---

## End-to-End Flow (Regular Phase)

```
1. fetch_unlimited() → raw errors z ES (15 min)
       ↓
2. BaselineLoader.load_historical_rates() → {error_type: [rates]} z DB (7 dní)
       ↓
3. Phase A: Parse → NormalizedRecord[] (fingerprint, error_type, ...)
       ↓
4. Phase B: Measure → MeasurementResult[] (baseline_ewma, current_rate, ...)
   │  Pro každý fingerprint:
   │    - Zkus najít DB baseline přes error_type_baseline[error_type]
   │    - Kombinuj s intra-window rates
   │    - Spočítej EWMA a MAD
       ↓
5. Phase C: Detect → DetectionResult[] (is_spike, is_burst, is_new, ...)
   │  Pro každý fingerprint:
   │    - Aplikuj spike test (EWMA → MAD → fallback)
   │    - Aplikuj burst test (sliding window)
   │    - Zkontroluj v registry (new vs known)
   │    - Zkontroluj cross-namespace
       ↓
6. Phase D: Score → score 0-100
   │  base + spike(+25) + burst(+20) + new(+15) + ...
       ↓
7. Phase E: Classify → category (DATABASE, NETWORK, AUTH, ...)
       ↓
8. Build IncidentCollection
       ↓
9. Save to DB (peak_investigation)
       ↓
10. Update Registry (known_problems, known_peaks, fingerprint_index)
       ↓
11. Problem Analysis → agregace incidentů do problémů
       ↓
12. Notifikace (Teams/Email) - pokud peaks_detected > 0 nebo score >= 70
```

---

## Konfigurace

| Parametr | Default | Env var | Popis |
|----------|---------|---------|-------|
| `spike_threshold` | 3.0 | `SPIKE_THRESHOLD` | EWMA ratio pro spike |
| `spike_mad_threshold` | 3.0 | - | MAD násobek pro spike |
| `burst_threshold` | 5.0 | - | max/avg ratio pro burst |
| `burst_window_sec` | 60 | - | Sliding window pro burst (sekundy) |
| `cross_ns_threshold` | 2 | - | Min. namespaců pro cross-NS flag |
| `ewma_alpha` | 0.3 | `EWMA_ALPHA` | EWMA citlivost (0-1) |
| `baseline_windows` | 20 | - | Max. počet historických oken |
| `lookback_days` | 7 | - | Kolik dní historie z DB |

---

## Časté problémy

### baseline_ewma = 0 pro všechny fingerprints

**Příčina:** Historický baseline se nenačetl z DB, nebo se nepředal správně do Phase B.

**Kontrola:**
- Ověř, že `BaselineLoader` vrací neprázdný dict
- Ověř, že se injektuje do `pipeline.phase_b.error_type_baseline` (ne `historical_baseline`)
- Ověř, že DB obsahuje data za posledních 7 dní

### Žádné spike detekce, přestože error rate je vysoký

**Příčiny:**
1. baseline = 0 -> EWMA test a MAD test se přeskočí
2. Fallback test vyžaduje current_count >= 5
3. Ratio nepřekročí threshold (aktuální rate < 3x baseline)

### False positive bursts

**Příčina:** Burst test je nezávislý na baseline a závisí jen na distribuci
eventů uvnitř okna. Málo eventů (< 5) s nerovnoměrnou distribucí
může vygenerovat high ratio.
