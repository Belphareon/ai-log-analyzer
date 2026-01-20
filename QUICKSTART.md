# AI Log Analyzer V4 - Quick Start Guide

## 📦 Obsah balíku

```
ai-log-analyzer-complete/
├── scripts/
│   ├── v4/                      # V4 Pipeline (hlavní)
│   │   ├── incident.py          # Incident Object
│   │   ├── phase_a_parse.py     # A: Parse & Normalize
│   │   ├── phase_b_measure.py   # B: Measure (EWMA, MAD)
│   │   ├── phase_c_detect.py    # C: Detect (flags)
│   │   ├── phase_d_score.py     # D: Score (0-100)
│   │   ├── phase_e_classify.py  # E: Classify (taxonomy)
│   │   ├── phase_f_report.py    # F: Report (render)
│   │   └── pipeline_v4.py       # Orchestrator
│   │
│   ├── core/                    # Core komponenty
│   │   ├── fetch_unlimited.py   # ES fetcher
│   │   ├── collect_peak_detailed.py
│   │   ├── peak_detection_v3.py
│   │   └── ...
│   │
│   ├── init_phase.py            # INIT workflow
│   ├── regular_phase.py         # REGULAR workflow (cron)
│   ├── backfill.py              # Backfill workflow
│   │
│   ├── utils/                   # Utility skripty
│   └── migrations/              # SQL migrace
│
├── k8s/                         # Kubernetes
│   └── cronjob.yaml
│
├── config/                      # Konfigurace
│   ├── .env.example
│   └── namespaces.yaml
│
├── docs/                        # Dokumentace
├── data/                        # Data (batches, reports, snapshots)
│
├── run_init.sh                  # → INIT fáze
├── run_regular.sh               # → REGULAR fáze
├── run_backfill.sh              # → Backfill
│
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 🚀 Quick Start (5 kroků)

### 1. Rozbal a nastav prostředí

```bash
unzip ai-log-analyzer-v4-complete.zip
cd ai-log-analyzer-complete

# Zkopíruj a uprav .env
cp config/.env.example .env
vim .env  # Vyplň ES a DB credentials
```

### 2. Instalace závislostí

```bash
pip install -r requirements.txt
```

### 3. Databáze - migrace

```bash
# Spusť migrace v pořadí
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f scripts/migrations/000_create_base_tables.sql
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f scripts/migrations/001_create_peak_thresholds.sql
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f scripts/migrations/002_create_enhanced_analysis_tables.sql
```

### 4. INIT fáze (jednorázově, ~21 dní dat)

```bash
# Sběr baseline dat BEZ peak detection
./run_init.sh --days 21

# Po dokončení: výpočet thresholds
python scripts/core/calculate_peak_thresholds.py
```

### 5. Backfill + REGULAR

```bash
# Backfill posledních 14 dní S detection
./run_backfill.sh --days 14

# Setup cron pro regular (každých 15 min)
crontab -e
# Přidej: */15 * * * * /path/to/run_regular.sh --quiet
```

---

## ⏰ Workflow přehled

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           WORKFLOW                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   1. INIT (jednorázově)                                                     │
│      └── Sběr 21+ dní dat BEZ detection                                     │
│      └── Vytvoření baseline                                                 │
│                                                                             │
│   2. Calculate Thresholds                                                    │
│      └── P93 per (namespace, day_of_week)                                   │
│      └── CAP per namespace                                                  │
│                                                                             │
│   3. BACKFILL (jednorázově)                                                 │
│      └── Zpracování posledních 14 dní S detection                           │
│                                                                             │
│   4. REGULAR (cron */15)                                                    │
│      └── Zpracování každých 15 minut                                        │
│      └── Peak detection                                                     │
│      └── Alerting                                                           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Pipeline V4

```
ES Errors → [A] Parse → [B] Measure → [C] Detect → [D] Score → [E] Classify → [F] Report
               │           │            │            │            │             │
               ▼           ▼            ▼            ▼            ▼             ▼
           fingerprint   EWMA/MAD    flags       score      category       JSON/MD
           normalized    baseline    evidence    0-100      taxonomy       console
```

### Fáze:

| Fáze | Popis | Výstup |
|------|-------|--------|
| **A** | Parse & Normalize | fingerprint, normalized_message |
| **B** | Measure (EWMA, MAD) | baseline, current_rate, trend |
| **C** | Detect | is_spike, is_new, is_burst + evidence |
| **D** | Score | score 0-100 (deterministická váhová funkce) |
| **E** | Classify | category, subcategory (taxonomy) |
| **F** | Report | JSON, Markdown, Console |

---

## 🔧 Konfigurace

### .env (kritické)

```bash
# Elasticsearch
ES_HOST=https://elasticsearch.example.com:9500
ES_USER=your_user
ES_PASSWORD=your_password

# PostgreSQL
DB_HOST=postgres.example.com
DB_USER=ailog_user
DB_PASSWORD=your_password

# Pipeline
SPIKE_THRESHOLD=3.0
EWMA_ALPHA=0.3
```

### namespaces.yaml

```yaml
namespaces:
  - pcb-dev-01-app
  - pcb-sit-01-app
  - pcb-prd-01-app
```

---

## 📞 Příkazy

```bash
# INIT (21 dní baseline)
./run_init.sh --days 21

# INIT dry run
./run_init.sh --days 21 --dry-run

# Backfill (14 dní s detection)
./run_backfill.sh --days 14

# Regular (15-min okno)
./run_regular.sh

# Regular quiet (pro cron)
./run_regular.sh --quiet

# Regular s reportem
./run_regular.sh --output data/reports/
```

---

## 🐳 Docker

```bash
# Build
docker build -t ai-log-analyzer:v4 .

# Run regular
docker run --env-file .env ai-log-analyzer:v4

# Run init
docker run --env-file .env ai-log-analyzer:v4 python scripts/init_phase.py --days 21
```

---

## ☸️ Kubernetes

```bash
# Deploy CronJob
kubectl apply -f k8s/cronjob.yaml

# Check
kubectl get cronjobs -n ailog
kubectl logs -n ailog job/ailog-pipeline-xxxxx
```

---

## 🔍 Troubleshooting

```bash
# Check DB connection
python scripts/utils/check_db_data.py

# Validate detection
python scripts/utils/validate_detection.py

# Manual fetch test
python scripts/core/fetch_unlimited.py --from "2026-01-20T10:00:00Z" --to "2026-01-20T10:15:00Z" --output test.json
```

---

**Verze:** 4.0 | **Velikost:** ~100 KB (ZIP)
