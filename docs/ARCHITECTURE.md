# Architektura — AI Log Analyzer

Technická struktura systému: komponenty, datové toky, persistence a integrační body.

---

## Přehled

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
│  │   Email/Teams  │  │   registry/    │  │  PostgreSQL DB │    │
│  │    Confluence   │  │ (append-only)  │  │ (peak_invest.) │    │
│  └────────────────┘  └────────────────┘  └────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

Dva vstupní body:
- **`scripts/regular_phase.py`** — každých 15 minut jako K8s CronJob; čte logy za aktuální okno, běží pipeline, případně odesílá alert
- **`scripts/backfill.py`** — zpracovává historická data po dnech; slouží k doplnění chybějících dat nebo inicializaci nové instance

---

## Datový tok (regular phase)

```
Elasticsearch
      │  fetch_unlimited() — stránkované, bez limitu
      ▼
[ FÁZE A: Parse & Normalize ]
      │  NormalizedRecord: timestamp, namespace, app_name, error_type,
      │  normalized_message, fingerprint, trace_id, environment
      ▼
[ FÁZE B: Measure ]
      │  MeasurementResult: current_count, baseline, ewma, mad, trend_ratio
      │  (baseline se načítá z DB peak_raw_data — 7 dní historie)
      ▼
[ FÁZE C: Detect ]
      │  DetectionResult: is_spike, is_burst, is_new, is_regression,
      │  is_cross_namespace + evidence (proč byl flag nastaven)
      │  (spike detekce: P93/CAP z DB ailog_peak.peak_thresholds)
      ▼
[ FÁZE D: Score ]
      │  score 0–100 (váhový součet flagů + škálovací bonusy)
      ▼
[ FÁZE E: Classify ]
      │  category (BUSINESS, AUTH, DATABASE, ...) + subcategory
      ▼
[ FÁZE F: Report ]
      │  IncidentCollection — strukturovaná kolekce incidentů
      ▼
[ Incident Analysis Engine ]
      │  IncidentAnalysis: timeline, scope, causal_chain, recommended_actions
      ▼
[ Persistence ]
      ├── DB: peak_raw_data (surové počty → vstup pro P93/CAP výpočet)
      ├── DB: peak_investigation (evidované peaky pro Confluence)
      ├── YAML: registry/known_problems.yaml + known_peaks.yaml (append-only)
      └── JSON: registry/alert_state_regular_phase.json (stav alertů)
      ▼
[ Notifikace ]
      ├── Email digest (SMTP)
      └── Teams webhook
      ▼
[ Confluence export ]
      └── table_exporter.py → Known Errors + Known Peaks stránky
```

---

## Detection Pipeline

Orchestrátor: `scripts/pipeline/pipeline.py` — třída `Pipeline`

### Phase A: Parse & Normalize

**Soubor:** `scripts/pipeline/phase_a_parse.py` — třída `PhaseA_Parser`

- **Vstup:** Raw log záznamy z Elasticsearch (list of dicts)
- **Výstup:** `List[NormalizedRecord]` + groups by fingerprint
- **Činnost:**
  1. Extrakce polí: timestamp, namespace, app_name, app_version, trace_id, span_id
  2. Normalizace message: nahrazení variabilních částí (UUID→`<UUID>`, IP→`<IP>`, čísla→`<ID>`)
  3. Extrakce error_type z message (např. `NullPointerException`, `TimeoutException`)
  4. Generování fingerprint: `MD5(error_type:normalized_message)[:16]`
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
    fingerprint: str         # MD5 hash (16 chars)
```

### Phase B: Measure

**Soubor:** `scripts/pipeline/phase_b_measure.py` — třída `PhaseB_Measure`

- **Vstup:** `List[NormalizedRecord]`
- **Výstup:** `Dict[fingerprint, MeasurementResult]`
- **Činnost:** Výpočet baseline a aktuálních statistik pro každý fingerprint

**Algoritmus:**

1. **Groupování** (O(n)): Seskup records podle `(fingerprint, window_idx)`. Window = 15 min.
2. **Pro každý fingerprint:** Chronologický array rates `[count_w0, count_w1, ...]`
3. **Historický baseline z DB** (`BaselineLoader` → tabulka `peak_raw_data`, 7 dní)
4. **EWMA** (alpha=0.3): `ewma[i] = alpha * rates[i] + (1-alpha) * ewma[i-1]` — informativní metrika pro trend, NE pro spike detekci
5. **MAD** (Median Absolute Deviation): robustnější než stddev — informativní metrika

**Datový model:**
```python
@dataclass
class MeasurementResult:
    fingerprint: str
    current_count: int
    current_rate: float
    baseline_ewma: float
    baseline_mad: float
    baseline_median: float
    trend_ratio: float        # current_rate / baseline_ewma
    trend_direction: str      # "increasing" / "stable" / "decreasing"
    namespaces: List[str]
    namespace_count: int
    apps: List[str]
    first_seen: datetime
    last_seen: datetime
```

### Phase C: Detect

**Soubor:** `scripts/pipeline/phase_c_detect.py` — třída `PhaseC_Detect`

- **Vstup:** `Dict[fingerprint, MeasurementResult]` + records + registry + PeakDetector
- **Výstup:** `Dict[fingerprint, DetectionResult]` s boolean flagy
- **Činnost:** Spike detekce na úrovni namespace (P93/CAP), ostatní pravidla per fingerprint

**Detection flags:**

| Flag | Pravidlo | Popis |
|------|----------|-------|
| `is_spike` | P93/CAP (namespace-level) | Namespace má celkový error rate nad P93 percentilem |
| `is_burst` | Sliding window (60s), rate > 5.0× | Náhlá lokální koncentrace v krátkém okně |
| `is_new` | Registry lookup | Fingerprint/problem_key dosud nebyl viděn |
| `is_cross_namespace` | NS count ≥ 2 | Stejný error se objevuje ve více prostředích |
| `is_silence` | Absence check | Očekávaný error se neobjevil (baseline > 5, current = 0) |
| `is_regression` | Version check | Error, který byl opraven, se znovu objevil |

Podrobný popis spike detekce viz [HOW_IT_WORKS.md](HOW_IT_WORKS.md#5-detekce-anomálií--p93cap).

### Phase D: Score

**Soubor:** `scripts/pipeline/phase_d_score.py` — třída `PhaseD_Score`

```
score = base_score + Σ(flag_bonus)
base_score = min(count / 10, 30)
```

| Flag | Bonus |   | Score | Severity |
|------|------:|---|------:|----------|
| spike | +25  |   | ≥ 80  | critical |
| burst | +20  |   | ≥ 60  | high     |
| new   | +15  |   | ≥ 40  | medium   |
| regression | +35 | | ≥ 20 | low     |
| cascade | +20 |  | < 20  | info     |
| cross-ns | +15 | |       |          |

Scaling bonusy: `trend_ratio` nad 2.0 → +2 per 1.0; `namespace_count` nad 2 → +3 per NS.

### Phase E: Classify

**Soubor:** `scripts/pipeline/phase_e_classify.py` — třída `PhaseE_Classify`

Deterministická klasifikace pomocí regex pravidel (žádné ML/LLM):

| Kategorie | Příklady subcategory |
|------------|------------------------------------------------------|
| BUSINESS | not_found, validation, constraint_violation |
| AUTH | unauthorized, forbidden, token_expired |
| DATABASE | connection, deadlock, query_error |
| NETWORK | connection_refused, connection_reset, dns, ssl |
| TIMEOUT | read_timeout, connect_timeout, request_timeout |
| MEMORY | out_of_memory, memory_leak |
| EXTERNAL | api_error, service_unavailable, gateway_error |

Pravidla: `phase_e_classify.py` (DEFAULT_RULES, 30+) + `core/problem_registry.py` (ERROR_CLASS_PATTERNS, 40+).

### Phase F: Report

**Soubor:** `scripts/pipeline/phase_f_report.py` — třída `PhaseF_Report`

Formátování a export IncidentCollection: konzolový výstup, JSON, Markdown, snapshots.

---

## Incident Analysis

**Adresář:** `incident_analysis/`

| Komponenta | Vstup | Výstup |
|------------|-------|--------|
| `analyzer.py` — IncidentAnalysisEngine | Events | IncidentAnalysis |
| `timeline_builder.py` — TimelineBuilder | Events | Timeline (FACTS) |
| `causal_inference.py` — CausalInferenceEngine | Timeline + Scope | CausalChain (HYPOTHESIS) |
| `fix_recommender.py` — FixRecommender | Analysis | RecommendedAction[] |

**Datový model:**
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

---

## Problem Registry

**Soubor:** `scripts/core/problem_registry.py`

Dvouúrovňová identita problémů:

```
PROBLEM REGISTRY (stabilní, málo záznamů)     1:N     FINGERPRINT INDEX (technický)
  problem_key                              ◄────────   fingerprint → problem_key
  first_seen / last_seen                               sample_messages
  occurrences, behavior, root_cause
```

**Problem Key** — trvalý identifikátor: `CATEGORY:flow:error_class` (např. `BUSINESS:card_servicing:validation_error`)

**Peak Key** — identifikátor: `PEAK:category:flow:peak_type` (např. `PEAK:business:card_servicing:spike`)

**Flow** se extrahuje z názvu aplikace pomocí FLOW_PATTERNS (14 definovaných vzorů):
- `bff-pcb-ch-card-servicing-v1` → `card_servicing`
- `bl-pcb-billing-v1` → `billing`

---

## Notifikace

### Email Notifier (`scripts/core/email_notifier.py`)

Dvě varianty (řízeno `ALERT_DIGEST_ENABLED`):

- **Digest** (`send_regular_phase_peak_digest`) — jeden email per cron okno; HTML tabulka všech aktivních peaků s NS, app counts, trace flow, inferred root cause; korelované alerty (stejný trace_id + namespace) se seskupí do jednoho detail bloku
- **Detail** (`send_regular_phase_peak_alert_detailed`) — jeden email per peak; fallback/specifické případy

### Confluence Export (`scripts/exports/table_exporter.py`)

- **Known Errors** — tabulka `ErrorTableRow`: kategorie, root cause, behavior, activity status (ACTIVE/STALE/OLD)
- **Known Peaks** — tabulka `PeakTableRow`: peak_count, peak_ratio, occurrences, first/last seen, status + Peak Details

---

## Databáze

Schema: `ailog_peak`

| Tabulka | Popis | Klíč |
|---------|-------|------|
| `peak_raw_data` | 15-min error counts per namespace | `(namespace, window_start, window_end, day_of_week)` |
| `peak_thresholds` | P93 per (namespace, day_of_week) | `(namespace, day_of_week)` |
| `peak_threshold_caps` | CAP per namespace | `(namespace)` |
| `peak_investigation` | Detekované incidenty | `(peak_key, problem_key, namespace, ...)` |

**Zápis do DB** vyžaduje sekvenci:
1. Připojit se jako DDL user (`DB_DDL_USER`)
2. `SET ROLE role_ailog_analyzer_ddl`
3. Teprve pak `INSERT / UPDATE`

---

## YAML Registry (persistence)

Adresář `registry/` — **append-only, nikdy se nemaže**.

| Soubor | Popis |
|--------|-------|
| `known_problems.yaml` | Všechny dříve viděné problémy (problem_key, category, flow, behavior, root_cause) |
| `known_peaks.yaml` | Všechny detekované peaky (peak_type, affected_apps, affected_namespaces) |
| `fingerprint_index.yaml` | Inverzní index: fingerprint → problem_key |
| `alert_state_regular_phase.json` | Stav alertů: cooldown, heartbeat, trend, počet alertů per okno |

---

## Konfigurační soubory

| Soubor | Popis |
|--------|-------|
| `.env` | Hlavní konfigurace (ES, DB, SMTP, Teams, Confluence, alertování, detekce) |
| `config/namespaces.yaml` | Seznam monitorovaných K8s namespace |
| `config/known_issues/known_errors.yaml` | Manuální knowledge base (popis, workaround, JIRA ticket) |

---

## Integrace

| Systém | Typ | Použití |
|--------|-----|---------|
| Elasticsearch | HTTP REST (čtení) | Zdrojová data — error logy aplikací |
| PostgreSQL | psycopg2 | Persistence thresholdů, raw dat, peaků |
| SMTP / Teams | HTTP/email (zápis) | Notifikace při detekci peaku |
| Confluence | HTTP REST (zápis) | Known Errors a Known Peaks stránky |

Všechny integrace jsou **non-blocking** — selhání Teams nebo Confluence neblokuje pipeline.

---

## Orchestrace

### regular_phase.py (15min)

```python
def run_regular_pipeline():
    errors = fetch_unlimited(window_start, window_end)
    baseline_loader = BaselineLoader(db_conn)
    peak_detector = PeakDetector(conn=get_db_connection())
    pipeline = Pipeline(peak_detector=peak_detector, ewma_alpha=0.3)
    pipeline.phase_b.error_type_baseline = baseline_loader.load_historical_rates(...)
    pipeline.phase_c.registry = registry
    collection = pipeline.run(errors)
    save_incidents_to_db(collection)
    save_namespace_totals_to_raw_data(collection)
    registry.update_from_incidents(collection.incidents)
    # dispatch alerts, reports, Confluence export
```

### backfill.py (daily)

Pro každý den: fetch 24h dat po 15-min oknech → pipeline → DB save → registry update → daily report

### calculate_peak_thresholds.py (týdně)

Čte `peak_raw_data` za N týdnů → počítá P93 per (namespace, DOW) → CAP per namespace → ukládá do DB.

---

## Výstupní soubory

```
scripts/reports/            # Reporty (text, JSON)
registry/                   # Append-only YAML evidence (live data, není v gitu)
scripts/exports/latest/     # CSV/MD pro Confluence upload
```

---

## Klíčové principy

1. **6 fází, každá přidává data** — žádná fáze neodstraňuje výstup předchozí
2. **Deterministické** — žádné ML/LLM, jen statistika a pravidla
3. **Report VŽDY** — generuje se i prázdný
4. **Registry = append-only** — nikdy se nemaže
5. **Scope ≠ Propagation** — oddělené datové struktury
6. **FACT vs HYPOTHESIS** — jasně oddělené v reportech
7. **P93/CAP spike detekce** — na úrovni namespace, thresholds z DB
8. **Samozdokonalovací smyčka** — regular phase ukládá namespace totaly do `peak_raw_data`, periodický přepočet P93/CAP

---

## Kubernetes nasazení

| Job | Schedule | Skript |
|-----|----------|--------|
| `log-analyzer-regular` | `*/15 * * * *` | `scripts/regular_phase.py` |
| `log-analyzer-backfill` | `0 2 * * *` | `scripts/backfill.py --days 1` |
| `log-analyzer-thresholds` | `0 3 * * 0` | `scripts/core/calculate_peak_thresholds.py --weeks 4` |

Image: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:<tag>`
