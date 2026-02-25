# Pipeline Architecture

## Přehled

Systém se skládá ze dvou hlavních částí:

1. **Detection Pipeline** - statistická detekce anomálií (6 fází: A-F)
2. **Incident Analysis** - kauzální analýza a reporting

## Celková architektura

```
┌─────────────────────────────────────────────────────────────────┐
│                    ELASTICSEARCH                                │
│                    (aplikační logy)                              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                     fetch_unlimited()
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                DETECTION PIPELINE                                │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │ Phase A │→ │ Phase B │→ │ Phase C │→ │ Phase D │           │
│  │ Parse   │  │ Measure │  │ Detect  │  │ Score   │           │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘           │
│       ↓            ↓            ↓            ↓                  │
│  ┌─────────┐  ┌─────────┐                                      │
│  │ Phase E │→ │ Phase F │                                      │
│  │Classify │  │ Report  │                                      │
│  └─────────┘  └─────────┘                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    IncidentCollection
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              INCIDENT ANALYSIS                                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ TimelineBuilder│→ │  ScopeBuilder  │→ │ CausalInference│    │
│  │                │  │ + Propagation  │  │                │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
│           ↓                   ↓                   ↓             │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ FixRecommender │→ │KnowledgeMatcher│→ │    Formatter   │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    OUTPUT                                        │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐    │
│  │ scripts/reports│  │   registry/    │  │  PostgreSQL DB │    │
│  │   (reporty)    │  │ (append-only)  │  │ (peak_invest.) │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Detection Pipeline

Orchestrátor: `scripts/pipeline/pipeline.py` - třída `Pipeline`

### Phase A: Parse & Normalize

**Soubor:** `scripts/pipeline/phase_a_parse.py`
**Třída:** `PhaseA_Parser`

- **Vstup:** Raw log záznamy z Elasticsearch (list of dicts)
- **Výstup:** `List[NormalizedRecord]` + groups by fingerprint
- **Činnost:**
  1. Extrakce polí: timestamp, namespace, app_name, app_version, trace_id, span_id
  2. Normalizace message: nahrazení variabilních částí (UUID->`<UUID>`, IP->`<IP>`, čísla->`<ID>`, atd.)
  3. Extrakce error_type z message (např. `NullPointerException`, `TimeoutException`)
  4. Generování fingerprint: `SHA256(namespace + app_name + error_type + normalized_message)`
  5. Seskupení records podle fingerprint

**Datový model:**
```python
@dataclass
class NormalizedRecord:
    raw_message: str
    timestamp: datetime
    namespace: str
    app_name: str
    app_version: str
    trace_id: str
    normalized_message: str
    error_type: str          # "NullPointerException", "TimeoutException", ...
    fingerprint: str         # SHA256 hash
```

### Phase B: Measure

**Soubor:** `scripts/pipeline/phase_b_measure.py`
**Třída:** `PhaseB_Measure`

- **Vstup:** `List[NormalizedRecord]`
- **Výstup:** `Dict[fingerprint, MeasurementResult]`
- **Činnost:** Výpočet baseline a aktuální statistiky pro každý fingerprint
- **Složitost:** O(n) - jeden průchod pro groupování, pak O(fingerprints x windows)

**Algoritmus:**

1. **Groupování** (O(n)): Projdi všechny records a seskup je podle `(fingerprint, window_idx)`.
   Window index = `(timestamp - base) / window_minutes` (default: 15 min).

2. **Pro každý fingerprint:**
   - Vytvoř chronologický array rates: `[count_window_0, count_window_1, ..., count_window_N]`
   - `current_rate` = rate v posledním okně
   - `historical_rates` = rates z předchozích oken (bez posledního)

3. **Historický baseline z DB** (regular phase):
   - `BaselineLoader` (soubor `scripts/core/baseline_loader.py`) načte baseline z tabulky
     `peak_investigation` za posledních 7 dní
   - Data jsou indexována podle `error_type`
   - Phase B mapuje fingerprint->error_type a přidá DB historii před aktuální data:
     `historical_rates = error_type_baseline[error_type] + current_window_historical`
   - Bez DB baseline (1. spuštění nebo nový error_type) se počítá jen z aktuálního okna

4. **EWMA (Exponential Weighted Moving Average):** (informativni metrika, NE pro spike detekci)
   ```
   ewma[0] = rates[0]
   ewma[i] = alpha * rates[i] + (1-alpha) * ewma[i-1]
   ```
   Default: `alpha = 0.3`. Pouziva se pro trend_ratio a trend_direction.

5. **MAD (Median Absolute Deviation):** (informativni metrika, NE pro spike detekci)
   ```
   median = median(historical_rates)
   MAD = median(|rate_i - median| for each rate_i)
   ```
   Robustnejsi nez stddev. Pouziva se jako informativni metrika.

**Datový model:**
```python
@dataclass
class MeasurementResult:
    fingerprint: str
    current_count: int        # Počet events v aktuálním okně
    current_rate: float       # Rate v aktuálním okně
    baseline_ewma: float      # EWMA baseline (historical)
    baseline_mad: float       # MAD (robustní variabilita)
    baseline_median: float    # Medián historických rates
    trend_ratio: float        # current_rate / baseline_ewma
    trend_direction: str      # "increasing" / "stable" / "decreasing"
    namespaces: List[str]
    namespace_count: int
    apps: List[str]
    first_seen: datetime
    last_seen: datetime
```

### Phase C: Detect

**Soubor:** `scripts/pipeline/phase_c_detect.py`
**Třída:** `PhaseC_Detect`

- **Vstup:** `Dict[fingerprint, MeasurementResult]` + records + registry + PeakDetector
- **Výstup:** `Dict[fingerprint, DetectionResult]` s boolean flagy
- **Činnost:** Spike detekce na urovni namespace (P93/CAP), ostatni pravidla per fingerprint

**Spike detekce (P93/CAP):**
1. `detect_batch()` agreguje error count per namespace
2. `PeakDetector.is_peak(ns_total, namespace, day_of_week)` per namespace
3. Fingerprinty v "peak" namespace -> `is_spike=True`

Podrobny popis viz [PEAK_DETECTION.md](PEAK_DETECTION.md).

**Detection flags:**

| Flag | Pravidlo | Popis |
|------|----------|-------|
| `is_spike` | P93/CAP (namespace-level) | Namespace ma celkovy error rate nad P93 percentilem |
| `is_burst` | Sliding window | Nahla lokalni koncentrace v kratkem casovem okne |
| `is_new` | Registry lookup | Fingerprint/problem_key dosud nebyl viden |
| `is_cross_namespace` | NS count | Stejny error se objevuje v >=2 namespacech |
| `is_silence` | Absence check | Ocekavany error se neobjevil (baseline > 5, current = 0) |
| `is_regression` | Version check | Error, ktery byl opraven, se znovu objevil |

### Phase D: Score

**Soubor:** `scripts/pipeline/phase_d_score.py`
**Třída:** `PhaseD_Score`

- **Vstup:** `Dict[fingerprint, DetectionResult]` + measurements
- **Výstup:** `Dict[fingerprint, ScoreResult]` (score 0-100)
- **Činnost:** Deterministická váhová funkce

**Výpočet:**
```
score = base_score + sum(flag_bonuses)

base_score = min(current_count / 10, 30)    # max 30 bodů

Flag bonuses:
  spike:           +25
  burst:           +20
  new:             +15
  regression:      +35
  cascade:         +20
  cross_namespace: +15

Scaling bonuses:
  trend_ratio:     +2 per 1.0 above 2.0
  namespace_count: +3 per namespace above 2

score = min(score, 100)
```

**Severity mapping:**
```
score >= 80  →  CRITICAL
score >= 60  →  HIGH
score >= 40  →  MEDIUM
score >= 20  →  LOW
score < 20   →  INFO
```

### Phase E: Classify

**Soubor:** `scripts/pipeline/phase_e_classify.py`
**Třída:** `PhaseE_Classify`

- **Vstup:** fingerprint + normalized_message + error_type
- **Výstup:** `Dict[fingerprint, ClassificationResult]` (category + subcategory)
- **Činnost:** Deterministická klasifikace pomocí regex pravidel

**Kategorie:**
`MEMORY`, `DATABASE`, `NETWORK`, `AUTH`, `BUSINESS`, `INTEGRATION`, `CONFIGURATION`, `INFRASTRUCTURE`, `UNKNOWN`

Pravidla jsou seřazena podle priority. Každé pravidlo má regex patterns pro matching na normalized_message.

### Phase F: Report

**Soubor:** `scripts/pipeline/phase_f_report.py`
**Třída:** `PhaseF_Report`

- **Vstup:** IncidentCollection
- **Výstup:** Konzolový výstup, JSON, Markdown, snapshots
- **Činnost:** Formátování a export výsledků

---

## Incident Analysis

### Datový model

```python
class IncidentAnalysis:
    incident_id: str
    scope: IncidentScope          # KDE (apps, root_apps, downstream_apps)
    propagation: IncidentPropagation  # JAK (propagated, propagation_time_sec)
    timeline: List[TimelineEvent]  # Časová osa (FACTS)
    causal_chain: CausalChain     # Root cause (HYPOTHESIS)
    priority: IncidentPriority    # P1-P4
    recommended_actions: List[RecommendedAction]
```

### Komponenty

| Komponenta | Vstup | Výstup |
|------------|-------|--------|
| TimelineBuilder | Events | Timeline (FACTS) |
| ScopeBuilder | Events | IncidentScope + IncidentPropagation |
| CausalInferenceEngine | Timeline + Scope | CausalChain (HYPOTHESIS) |
| FixRecommender | Analysis | RecommendedAction[] |
| KnowledgeMatcher | fingerprint | Known issue match |
| Formatter | IncidentAnalysis | Report string |

---

## Orchestrace

### regular_phase.py (15min)

```python
def run_regular_pipeline():
    # 1. Fetch z ES (posledních 15 min)
    errors = fetch_unlimited(window_start, window_end)

    # 2. Load historický baseline z DB (7 dní)
    baseline_loader = BaselineLoader(db_conn)
    historical_baseline = baseline_loader.load_historical_rates(...)
    # historical_baseline = {error_type: [rate1, rate2, ...]}

    # 3. Create PeakDetector (P93/CAP thresholds z DB)
    peak_detector = PeakDetector(conn=get_db_connection())

    # 4. Detection pipeline
    pipeline = Pipeline(peak_detector=peak_detector, ewma_alpha=0.3)
    pipeline.phase_b.error_type_baseline = historical_baseline
    pipeline.phase_c.registry = registry
    collection = pipeline.run(errors)

    # 5. Save to DB
    save_incidents_to_db(collection)

    # 6. Save namespace totals to peak_raw_data (pro P93 přepočet)
    save_namespace_totals_to_raw_data(collection)

    # 7. Registry update
    registry.update_from_incidents(collection.incidents)

    # 8. Problem Analysis + Reporting
    problems = aggregate_by_problem_key(collection.incidents)
    report = ProblemReportGenerator(problems, ...).generate_text_report()

    # 9. Notifikace (Teams/Email) - jen při detekci peaků
```

### backfill.py (daily)

```python
def run_backfill():
    # Pro každý den:
    #   1. Fetch 24h dat po 15-min oknech
    #   2. Create PeakDetector(conn=get_db_connection())
    #   3. Pipeline = Pipeline(peak_detector=peak_detector, ...)
    #   4. Pipeline pro každé okno
    #   5. DB save
    #   6. Registry update
    # Na konci: daily report + Teams notifikace
```

### calculate_peak_thresholds.py (týdně)

```python
def recalculate_thresholds():
    # 1. Čte peak_raw_data za posledních N týdnů
    # 2. Počítá P93 per (namespace, day_of_week)
    # 3. Počítá CAP = (median_P93 + avg_P93) / 2 per namespace
    # 4. Ukládá do peak_thresholds + peak_threshold_caps
    # Viz: python3 scripts/core/calculate_peak_thresholds.py --weeks 4
```

---

## Výstupní soubory

```
scripts/reports/
├── problem_report_15min_*.txt       # 15-min problem report
├── problem_report_15min_*.json      # 15-min JSON
├── incident_analysis_daily_*.txt    # Daily report
└── ...

registry/
├── known_problems.yaml    # Strojový formát (problem_key -> metadata)
├── known_problems.md      # Human-readable
├── known_peaks.yaml       # Detekované peaky
├── known_peaks.md
└── fingerprint_index.yaml # fingerprint -> problem_key mapping

scripts/exports/latest/
├── errors_table.csv       # Pro Confluence upload
├── errors_table.md
├── peaks_table.csv
└── peaks_table.md
```

---

## Klíčové principy

1. **6 fází, každá přidává data** - žádná fáze neodstraňuje výstup předchozí
2. **Deterministické** - žádné ML/LLM, jen statistika a pravidla
3. **Report VŽDY** - generuje se i prázdný
4. **Registry = append-only** - nikdy se nemaže
5. **Scope != Propagation** - oddělené datové struktury
6. **FACT vs HYPOTHESIS** - jasně oddělené v reportech
7. **Baseline z DB** - regular phase načítá 7-denní historii pro EWMA/MAD informativní metriky
8. **P93/CAP spike detekce** - na úrovni namespace, thresholds z DB (peak_thresholds + peak_threshold_caps)
9. **Samozdokonalovací smyčka** - regular phase ukládá namespace totaly do peak_raw_data, periodický přepočet P93/CAP
