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
      │  (baseline se načítá z complete DB facts — 7 dní historie)
      ▼
[ FÁZE C: Detect ]
      │  DetectionResult: is_spike, is_burst, is_new, is_regression,
      │  is_cross_namespace + evidence (proč byl flag nastaven)
      │  (spike detekce: robustní Pxx/CAP + namespace/fingerprint family gate z DB)
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
      ├── DB: complete 15min facts (vstup pro Pxx/CAP a family baseline)
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
3. **Historický baseline z DB** (`BaselineLoader` → complete facts, 7 dní)
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
- **Činnost:** Spike detekce na úrovni namespace (robustní Pxx/CAP) a automatický gate pro `(namespace, fingerprint)` cause family; ostatní pravidla per fingerprint

**Detection flags:**

| Flag | Pravidlo | Popis |
|------|----------|-------|
| `is_spike` | Pxx/CAP + family gate | Namespace total překročí robustní Pxx/CAP a family překročí vlastní namespace historii |
| `is_burst` | Sliding window (60s), rate > 5.0× | Náhlá lokální koncentrace v krátkém okně |
| `is_new` | Registry lookup | Fingerprint/problem_key dosud nebyl viděn |
| `is_cross_namespace` | NS count ≥ 2 | Stejný error se objevuje ve více prostředích |
| `is_silence` | Absence check | Očekávaný error se neobjevil (baseline > 5, current = 0) |
| `is_regression` | Version check | Error, který byl opraven, se znovu objevil |

Podrobný popis spike detekce viz [HOW_IT_WORKS.md](HOW_IT_WORKS.md#5-detekce-anomálií--pxxcap-a-cause-family-gate).

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

- **Digest** (`send_regular_phase_peak_digest`) — jeden email per cron okno; souhrn unikátních aplikací a namespaces, HTML tabulka aktivních peaků a detail s deduplikovaným behavior a inferred root cause
- **Detail** (`send_regular_phase_peak_alert_detailed`) — jeden email per peak; fallback/specifické případy

### Workflow Lifecycle Diagnostics

`run_regular_phase()` spouští před ERROR-only fetchem oddělenou, defaultně vypnutou větev `run_workflow_lifecycle_diagnostics()`. Její probe hledá raw INFO lifecycle zprávy bez závislosti na ERROR nebo trace ID, následuje bounded PIT/search_after fetch pro topic/namespace a predecessor evidence.

Výsledek se vždy nejdřív uloží jako `complete` nebo `partial` run. Pouze complete fetch, high-confidence hot loop a úspěšný commit mohou vyústit v `send_workflow_lifecycle_alert()`. Cap, timeout, chybějící PIT nebo neúplný probe jsou auditovatelné jako partial a fail-closed potlačí alert.

### Confluence Export (`scripts/exports/table_exporter.py`)

- **Known Errors** — tabulka `ErrorTableRow`: kategorie, root cause, behavior, activity status (ACTIVE/STALE/OLD)
- **Known Peaks** — tabulka `PeakTableRow`: peak_count, peak_ratio, occurrences, first/last seen, status + Peak Details

---

## Databáze

Schema: `ailog_peak`

| Tabulka | Popis | Klíč |
|---------|-------|------|
| `analysis_runs` | Ledger úplnosti a zdrojových počtů | `(run_type, window_start, window_end, query_hash)` |
| `error_kind_counts` | 15min facts per namespace/app/fingerprint | `(run_id, window_start, namespace, application, fingerprint)` |
| `v_complete_namespace_error_counts` | Autoritativní úplné namespace facts | `(namespace, window_start)` |
| `v_complete_error_kind_counts` | Autoritativní complete family facts | `(namespace, fingerprint, window_start)` |
| `peak_thresholds` | Robustní Pxx per (namespace, day_of_week) | `(namespace, day_of_week)` |
| `peak_threshold_caps` | CAP per namespace | `(namespace)` |
| `peak_investigation` | Detekované incidenty | `(peak_key, problem_key, namespace, ...)` |
| `workflow_lifecycle_runs` | Complete/partial lifecycle fetch ledger | `run_id` |
| `workflow_lifecycle_incidents` | Lifecycle hot-loop evidence a confidence | `(run_id, topic, namespace, queue_event_id)` |
| `workflow_lifecycle_evidence` | ES evidence použitá pro incident | `(run_id, topic, namespace, queue_event_id, es_index, es_id)` |

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

### Kde se registry persistuje (kritické)

Cesta k registry je řízena proměnnou **`REGISTRY_DIR`** (default lokálně
`<repo>/registry`, v podu **`/data/registry`**).

- **V Kubernetes je `/data` namountovaný na PVC `log-analyzer-data` (20 Gi, RWO)**
  — viz `infra-apps/ai-log-analyzer/templates/pvc.yaml` + `values.yaml`
  (`storage.claimName`, `env.REGISTRY_DIR`). PVC sdílí všechny joby (regular,
  backfill, init), proto je registry **perzistentní napříč restarty podů i
  napříč joby** — NENÍ ephemeral.
- Důsledek: cokoli uloženého do `REGISTRY_DIR` (registry, alert state a
  budoucí self-learning korpus) přežije restart podu. Bez PVC (jen image) by se
  data při každém běhu ztrácela.
- PVC je třeba zálohovat (Velero / KB backup) — obsahuje historické patterny.

---

## Konfigurační soubory

| Soubor | Popis |
|--------|-------|
| `.env` | Lokální/instalační vstup pro non-secret hodnoty a CyberArk account names; prod runtime čte konfiguraci z infra-apps `values.yaml` a secrets z Conjuru |
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
      pipeline.phase_b.historical_baseline = baseline_loader.load_fingerprint_rates(...)
      pipeline.phase_c.namespace_fingerprint_baselines = baseline_loader.load_namespace_fingerprint_rates(...)
    pipeline.phase_c.registry = registry
    collection = pipeline.run(errors)
    save_incidents_to_db(collection)
      persist_analysis_run(collection)
    registry.update_from_incidents(collection.incidents)
    # dispatch alerts, reports, Confluence export
```

### backfill.py (daily)

Pro každý den: fetch 24h dat po 15-min oknech → pipeline → DB save → registry update → daily report

### calculate_peak_thresholds.py (týdně)

Čte complete namespace facts za N týdnů → počítá robustní Pxx per (namespace, DOW) → CAP per namespace → ukládá kompatibilní snapshot do DB.

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
7. **Pxx/CAP + family gate** — namespace volume i vlastní history cause family musí projít DB-backed prahy
8. **Fail-closed baseline** — nekompatibilní snapshot nebo nedostupná authoritative baseline ukončí job bez legacy EWMA fallbacku

---

## Kubernetes nasazení

| Job | Schedule | Skript |
|-----|----------|--------|
| `log-analyzer` | `*/15 * * * *` | `scripts/regular_phase.py` |
| `log-analyzer-backfill` | `0 9 * * *` | `scripts/backfill.py --days 1` |
| `log-analyzer-thresholds` | `0 3 * * 0` | `scripts/core/calculate_peak_thresholds.py --weeks 4` |
| `log-analyzer-maintenance` | `30 2 * * *` | `scripts/core/run_data_maintenance.py` |

Image: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:<tag>`

**Perzistence:** všechny joby mountují PVC `log-analyzer-data` (20 Gi) na `/data`
(`REGISTRY_DIR=/data/registry`). Registry, alert state, exporty a reporty tak
přežívají restarty podů a sdílí se mezi joby (regular ↔ backfill ↔ init).
