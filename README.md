# AI Log Analyzer

Automatizovana detekce a analyza incidentu z aplikacnich logu.

**[Changelog](CHANGELOG.md)** | **[Quick Start](docs/QUICKSTART.md)** | **[Troubleshooting](docs/TROUBLESHOOTING.md)** | **[CronJob Scheduling](docs/CRONJOB_SCHEDULING.md)**

## Co to dela

System analyzuje error logy z Elasticsearch a automaticky:
- Detekuje anomalie (spiky, bursty, nove errory) pomoci P93/CAP percentilovych thresholdu
- Seskupuje souvisejici udalosti do incidentu
- Klasifikuje role aplikaci (root, downstream, collateral)
- Sleduje propagaci (jak rychle se incident siril)
- Rozlisuje zname vs nove incidenty (registry + knowledge base)
- Aktualizuje append-only registry (known_problems, known_peaks)
- Generuje operacni reporty (15min / daily / backfill)
- Publikuje do Teams a Confluence

## Architektura

### Detection Pipeline (6 fazi)

```
A: Parse & Normalize  -->  Fingerprinting, error_type extraction
B: Measure             -->  EWMA/MAD (informacni), trend ratio
C: Detect              -->  P93/CAP spike, burst, new, cross_ns, regression
D: Score               -->  Vahova funkce (0-100)
E: Classify            -->  Taxonomie (category, subcategory)
F: Report              -->  Formatovani vystupu
```

### Incident Analysis

```
TimelineBuilder       -->  Jak se problem siril (FACTS)
ScopeBuilder          -->  Klasifikace roli aplikaci
PropagationTracker    -->  Sledovani sireni
CausalInferenceEngine -->  Proc (HYPOTHESIS)
FixRecommender        -->  Konkretni opravy
```

### Problem Registry (dvouurovnova identita)

```
PROBLEM REGISTRY (stabilni)        1:N     FINGERPRINT INDEX (technicky)
  problem_key                  <---------->   fingerprint -> problem_key
  first_seen / last_seen                      sample_messages
  occurrences, scope
```

- **Problem Key**: `CATEGORY:flow:error_class` (napr. `BUSINESS:card_servicing:validation_error`)
- **Peak Key**: `PEAK:category:flow:peak_type` (napr. `PEAK:unknown:card_servicing:burst`)

## Struktura projektu

```
ai-log-analyzer/
├── scripts/
│   ├── backfill.py                 # Denni backfill pipeline
│   ├── regular_phase.py            # 15-min real-time pipeline
│   ├── daily_report_generator.py   # Daily report -> Teams
│   ├── publish_daily_reports.sh    # Orchestrace reportu
│   ├── core/
│   │   ├── problem_registry.py     # Registry modul
│   │   ├── peak_detection.py       # P93/CAP spike detector (DB thresholds)
│   │   ├── calculate_peak_thresholds.py  # Vypocet P93/CAP z peak_raw_data
│   │   ├── baseline_loader.py      # Historicky baseline z DB
│   │   ├── fetch_unlimited.py      # ES data fetcher
│   │   └── teams_notifier.py       # Teams integrace
│   ├── pipeline/
│   │   ├── pipeline.py             # Pipeline orchestrator
│   │   ├── phase_a_parse.py        # Parse & Normalize
│   │   ├── phase_b_measure.py      # EWMA/MAD statistiky
│   │   ├── phase_c_detect.py       # Boolean detekce
│   │   ├── phase_d_score.py        # Scoring (0-100)
│   │   ├── phase_e_classify.py     # Taxonomie
│   │   └── phase_f_report.py       # Report rendering
│   └── exports/
│       └── table_exporter.py       # CSV/MD/JSON export
├── incident_analysis/              # Analyza incidentu
│   ├── models.py                   # IncidentScope, Propagation
│   ├── analyzer.py                 # IncidentAnalysisEngine
│   └── formatter.py                # ReportFormatter
├── registry/                       # Append-only evidence
│   ├── known_problems.yaml
│   ├── known_peaks.yaml
│   └── fingerprint_index.yaml
├── config/known_issues/            # Knowledge base (manualni)
├── k8s/                            # Kubernetes manifesty
└── docs/                           # Dokumentace
    └── PEAK_DETECTION_OPS.md       # P93/CAP provozni prirucka
```

## Instalace

```bash
pip install psycopg2-binary python-dotenv requests pyyaml tqdm
cp config/.env.example config/.env
# Upravit .env: DB_HOST, DB_USER, DB_PASSWORD, ES_HOST, ...
```

Viz [INSTALL.md](INSTALL.md) pro detailni navod.

## Pouziti

```bash
# 15min cyklus
python3 scripts/regular_phase.py

# Backfill N dni
python3 scripts/backfill.py --days 7 --workers 4

# Backfill s force reprocessing
python3 scripts/backfill.py --days 14 --force

# Pipeline standalone
python3 scripts/pipeline/pipeline.py data/batches/2026-01-20/
```

## Konfigurace (.env)

```bash
# Database (read)
DB_HOST=...
DB_PORT=5432
DB_NAME=d_ailog
DB_USER=...
DB_PASSWORD=...

# Database (write - DDL)
DB_DDL_USER=...
DB_DDL_PASSWORD=...
DB_DDL_ROLE=role_ailog_analyzer_ddl

# Elasticsearch
ES_HOST=...
ES_USER=...
ES_PASSWORD=...

# Integrace (optional)
TEAMS_WEBHOOK_URL=...
CONFLUENCE_URL=...
CONFLUENCE_USERNAME=...
CONFLUENCE_API_TOKEN=...
```

## K8s Deployment

```bash
# Regular phase - kazdych 15 minut
kubectl apply -f k8s/cronjob-regular.yaml

# Backfill - denne v 02:00 UTC
kubectl apply -f k8s/cronjob-backfill.yaml
```

Viz [docs/CRONJOB_SCHEDULING.md](docs/CRONJOB_SCHEDULING.md) pro detaily.

## Klicove koncepty

### Detection

| Flag | Popis | Threshold |
|------|-------|-----------|
| `is_spike` | Narust oproti P93/CAP threshold | value > P93_per_DOW OR value > CAP |
| `is_burst` | Nahlý narust v kratkem okne | rate change > 5.0 |
| `is_new` | Fingerprint neni v registry | - |
| `is_cross_namespace` | Vyskyty ve vice NS | >= 2 namespaces |

### Scoring

| Komponenta | Vaha |
|-----------|------|
| Spike | 25 |
| Burst | 20 |
| New | 15 |
| Regression | 35 |
| Cascade | 20 |
| Cross-NS | 15 |

Severity: >= 80 critical, >= 60 high, >= 40 medium, >= 20 low, < 20 info

### Priority

```
P1: NEW AND (CRITICAL OR cross-app >= 3 OR fast_propagation < 30s)
P2: NEW AND not critical
P3: KNOWN AND stable
P4: ostatni
```

### DB Write Flow

Pro zapis do PostgreSQL je nutne:
1. Pripojit se jako DDL user
2. `SET ROLE role_ailog_analyzer_ddl`
3. Teprve pak INSERT/UPDATE operace

## Principy navrhu

1. **Report VZDY** - i prazdny
2. **Registry = append-only** - nikdy se nemaze
3. **Scope != Propagation** - oddelene koncepty
4. **FACT vs HYPOTHESIS** - jasne oddelene
5. **Non-blocking integrace** - selhani Teams/Confluence neblokuje pipeline

## Licence

Internal use only.
