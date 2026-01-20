# Pipeline V4 - Incident Detection Architecture

**Verze:** 4.0  
**Datum:** 2026-01-20

---

## 🎯 Filozofie

Pipeline V4 je **deterministický incident detektor**, ne log parser.

### Klíčové principy:

1. **Incident Object** = pevné jádro
   - Každý krok pouze přidává pole
   - Nikdy nic nemaže, nepřepisuje

2. **Striktně oddělené fáze**
   - A: Parse (žádná logika)
   - B: Measure (jen čísla)
   - C: Detect (boolean flags)
   - D: Score (váhová funkce)
   - E: Classify (taxonomy)
   - F: Report (jen render)

3. **Evidence log**
   - Každý flag má důvod
   - Report jen renderuje evidence

4. **Replay & regression**
   - Uložení mezi-výstupů
   - Porovnání s předchozím během

---

## 📁 Struktura

```
scripts/v4/
├── __init__.py           # Module exports
├── incident.py           # Incident Object (canonical model)
├── phase_a_parse.py      # Parse & Normalize
├── phase_b_measure.py    # Measure (EWMA, MAD)
├── phase_c_detect.py     # Detect (boolean flags)
├── phase_d_score.py      # Score (váhová funkce)
├── phase_e_classify.py   # Classify (taxonomy)
├── phase_f_report.py     # Report (render)
└── pipeline_v4.py        # Main orchestrator
```

---

## 🔄 Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              PIPELINE V4                                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   INPUT     │     │  PHASE A    │     │  PHASE B    │
│  raw errors │────▶│   PARSE     │────▶│  MEASURE    │
│    JSON     │     │  normalize  │     │  EWMA/MAD   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                   │
                    ┌──────┴──────┐     ┌──────┴──────┐
                    │ fingerprint │     │ baseline    │
                    │ normalized  │     │ current     │
                    │ error_type  │     │ trend       │
                    └─────────────┘     └─────────────┘
                                               │
                                               ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  PHASE F    │     │  PHASE E    │     │  PHASE C    │
│   REPORT    │◀────│  CLASSIFY   │◀────│   DETECT    │
│   render    │     │  taxonomy   │     │   flags     │
└─────────────┘     └─────────────┘     └─────────────┘
       │                   │                   │
┌──────┴──────┐     ┌──────┴──────┐     ┌──────┴──────┐
│ JSON (prim) │     │ category    │     │ is_spike    │
│ MD (sec)    │     │ subcategory │     │ is_new      │
│ console     │     │             │     │ is_burst    │
└─────────────┘     └─────────────┘     │ evidence[]  │
                                        └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │  PHASE D    │
                                        │   SCORE     │
                                        │  weights    │
                                        └─────────────┘
                                               │
                                        ┌──────┴──────┐
                                        │ score 0-100 │
                                        │ breakdown   │
                                        │ severity    │
                                        └─────────────┘
```

---

## 📋 Fáze detail

### FÁZE A: Parse & Normalize

**Vstup:** raw error dict  
**Výstup:** NormalizedRecord

```python
❌ Žádná logika
❌ Žádné prahy

✅ Extrakce polí (timestamp, namespace, app, trace_id)
✅ Normalizace message (odstranění UUIDs, IDs, timestamps)
✅ Extrakce error_type (NullPointerException, TimeoutError, ...)
✅ Generování fingerprint (MD5 hash)
```

**Normalizace:**
```
Input:  "Connection to 192.168.1.100:5432 refused for user 1234567890"
Output: "Connection to <IP>:<PORT> refused for user <ID>"
```

---

### FÁZE B: Measure

**Vstup:** NormalizedRecord[]  
**Výstup:** MeasurementResult

```python
❌ Žádné závěry
❌ Žádné flags

✅ EWMA baseline (exponential weighted moving average)
✅ MAD (median absolute deviation) - robustnější než stddev
✅ Current rate
✅ Trend ratio a direction
```

**EWMA formula:**
```
EWMA_t = α × value_t + (1 - α) × EWMA_{t-1}

α = 0.3 (default)
→ 30% váha nové hodnoty, 70% váha historie
```

**MAD formula:**
```
MAD = median(|X_i - median(X)|)

Výhoda: Jeden outlier nezmění MAD (na rozdíl od stddev)
```

---

### FÁZE C: Detect

**Vstup:** MeasurementResult  
**Výstup:** DetectionResult (flags + evidence)

```python
❌ Žádná interpretace
❌ Žádné skóre

✅ Boolean flags
✅ Evidence pro KAŽDÝ flag
```

**Flags:**
| Flag | Pravidlo | Evidence |
|------|----------|----------|
| is_spike | current > ewma × 3.0 | `{rule: "spike_ewma", baseline: 10, current: 50, threshold: 3.0}` |
| is_new | fingerprint not in known_set | `{rule: "new_fingerprint"}` |
| is_burst | rate_change > 5.0 in 60s | `{rule: "burst", window_sec: 60}` |
| is_cross_namespace | namespace_count >= 2 | `{rule: "cross_namespace", count: 3}` |
| is_regression | fixed_version <= current_version | `{rule: "regression", fixed: "v2.2", current: "v2.3"}` |

---

### FÁZE D: Score

**Vstup:** DetectionResult + MeasurementResult  
**Výstup:** ScoreResult

```python
❌ Žádné if/else v hlavní logice

✅ Deterministická váhová funkce
✅ Transparentní breakdown
```

**Score formula:**
```
score = base + spike_bonus + burst_bonus + new_bonus + ...

base = min(30, count / 10)
spike_bonus = is_spike × 25
burst_bonus = is_burst × 20
new_bonus = is_new × 15
regression_bonus = is_regression × 35
cross_ns_bonus = is_cross_namespace × 15
```

**Severity mapping:**
| Score | Severity |
|-------|----------|
| >= 80 | critical |
| >= 60 | high |
| >= 40 | medium |
| >= 20 | low |
| < 20 | info |

---

### FÁZE E: Classify

**Vstup:** normalized_message, error_type  
**Výstup:** category, subcategory

```python
❌ Žádné heuristiky
❌ Žádné fuzzy matching

✅ Explicitní pravidla (regex patterns)
✅ Priority-based matching
```

**Categories:**
- `memory` (out_of_memory, memory_leak)
- `database` (connection, deadlock, constraint_violation)
- `network` (connection_refused, dns, ssl)
- `timeout` (read_timeout, connect_timeout)
- `auth` (unauthorized, forbidden)
- `business` (not_found, validation)
- `external` (api_error, service_unavailable)
- `unknown`

---

### FÁZE F: Report

**Vstup:** IncidentCollection  
**Výstup:** JSON, Markdown, Console

```python
❌ Žádné počítání
❌ Žádná logika

✅ Pouze renderování
✅ Evidence se jen zobrazuje
```

**Výstupy:**
- JSON (primární) - kompletní data
- Markdown - lidsky čitelný report
- Console - stručný přehled
- Snapshot - pro replay

---

## 🔄 Replay & Regression

```bash
# Běh s uložením snapshotu
python pipeline_v4.py data/batches/ --save-snapshot /tmp/snapshots/

# Pozdější běh s porovnáním
python pipeline_v4.py data/batches/ --replay /tmp/snapshots/summary_20260120.json
```

**Co se porovnává:**
- Počet incidentů
- Změna severity distribution
- Změna score

---

## 📊 Incident Object

```json
{
  "id": "inc-20260120-001",
  "fingerprint": "abc123def456",
  
  "normalized_message": "Connection to <IP>:<PORT> refused",
  "error_type": "ConnectionError",
  
  "time": {
    "first_seen": "2026-01-20T10:00:00Z",
    "last_seen": "2026-01-20T10:15:00Z",
    "duration_sec": 900
  },
  
  "stats": {
    "baseline_rate": 10.5,
    "baseline_mad": 2.3,
    "current_rate": 52.0,
    "trend_direction": "increasing",
    "trend_ratio": 4.95
  },
  
  "flags": {
    "new": false,
    "spike": true,
    "burst": false,
    "cross_namespace": true
  },
  
  "evidence": [
    {
      "rule": "spike_ewma",
      "baseline": 10.5,
      "current": 52.0,
      "threshold": 3.0,
      "message": "current (52) > ewma (10.5) * 3.0"
    }
  ],
  
  "score": 72,
  "score_breakdown": {
    "base": 17,
    "spike": 25,
    "cross_ns": 20,
    "total": 72
  },
  
  "severity": "high",
  "category": "network",
  "subcategory": "connection_refused"
}
```

---

## 🚀 Použití

```python
from v4 import PipelineV4, load_batch_files

# Load data
errors = load_batch_files("data/batches/2026-01-20/")

# Create pipeline
pipeline = PipelineV4(
    spike_threshold=3.0,
    ewma_alpha=0.3,
)

# Run
collection = pipeline.run(errors)

# Report
for incident in collection.incidents:
    if incident.severity.value in ['critical', 'high']:
        print(f"{incident.id}: {incident.category.value} - {incident.score}")
        for ev in incident.evidence:
            print(f"  [{ev.rule}] {ev.message}")
```

---

## ✅ Co V4 DĚLÁ

- Deterministická detekce
- Explicitní pravidla
- Evidence log
- Replay/regression
- Striktně oddělené fáze

## ❌ Co V4 NEDĚLÁ

- Žádné heuristiky ("když text obsahuje X, tak Y")
- Žádné fuzzy matching
- Žádné magické severity bez skóre
- Žádné ML/AI v detekci

---

**Verze:** 4.0 | **Datum:** 2026-01-20
