# AI Log Analyzer V4

**Deterministický incident detektor pro Elasticsearch logy**

## 📁 Struktura projektu

```
ai-log-analyzer/
├── scripts/
│   ├── v4/                    # Pipeline V4 (hlavní)
│   │   ├── incident.py        # Incident Object
│   │   ├── phase_a_parse.py   # Parse & Normalize
│   │   ├── phase_b_measure.py # Measure (EWMA, MAD)
│   │   ├── phase_c_detect.py  # Detect (boolean flags)
│   │   ├── phase_d_score.py   # Score (váhová funkce)
│   │   ├── phase_e_classify.py# Classify (taxonomy)
│   │   ├── phase_f_report.py  # Report (render)
│   │   └── pipeline_v4.py     # Main orchestrator
│   ├── core/                  # Core komponenty
│   │   ├── fetch_unlimited.py # ES fetcher (search_after)
│   │   ├── collect_peak_detailed.py
│   │   ├── peak_detection_v3.py
│   │   └── ...
│   ├── utils/                 # Utility skripty
│   └── migrations/            # SQL migrace
├── k8s/                       # Kubernetes manifests
├── config/                    # Konfigurace
├── docs/                      # Dokumentace
├── data/                      # Data adresáře
│   ├── batches/              # Dočasné batch soubory
│   ├── reports/              # Generované reporty
│   └── snapshots/            # Snapshoty pro replay
├── run_init.sh               # Spustí INIT fázi
├── run_regular.sh            # Spustí REGULAR fázi
├── run_backfill.sh           # Backfill posledních N dní
└── requirements.txt
```

## 🚀 Quick Start

### 1. Nastavení prostředí

```bash
# Vytvoř .env soubor
cp config/.env.example .env

# Uprav .env s tvými credentials
vim .env

# Instalace závislostí
pip install -r requirements.txt
```

### 2. Databáze - migrace

```bash
# Připojení k DB
export PGPASSWORD=$DB_PASSWORD

# Spusť migrace
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f scripts/migrations/000_create_base_tables.sql
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f scripts/migrations/001_create_peak_thresholds.sql
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f scripts/migrations/002_create_enhanced_analysis_tables.sql
```

### 3. INIT Fáze (jednorázově)

Sbírá baseline data za 21+ dní BEZ peak detection:

```bash
# Sběr dat za poslední 3 týdny
./run_init.sh --days 21

# Nebo konkrétní období
./run_init.sh --from "2025-12-01T00:00:00Z" --to "2025-12-21T23:59:59Z"

# Dry run (bez zápisu do DB)
./run_init.sh --days 21 --dry-run
```

### 4. Výpočet thresholds (po INIT)

```bash
python scripts/core/calculate_peak_thresholds.py
```

### 5. Backfill (zpracování historických dat)

Zpracuje posledních N dní S peak detection:

```bash
# Backfill posledních 14 dní
./run_backfill.sh --days 14

# S uložením reportů
./run_backfill.sh --days 14 --output data/reports/
```

### 6. REGULAR Fáze (cron každých 15 minut)

```bash
# Manuální spuštění
./run_regular.sh

# S uložením reportu
./run_regular.sh --output data/reports/

# Quiet mode (pro cron)
./run_regular.sh --quiet
```

## ⏰ Cron Setup

### Linux crontab

```cron
# Každých 15 minut
*/15 * * * * cd /path/to/ai-log-analyzer && ./run_regular.sh --quiet >> /var/log/ailog/cron.log 2>&1
```

### Kubernetes CronJob

```bash
kubectl apply -f k8s/cronjob.yaml
```

## 📊 Pipeline V4 Architektura

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│ PHASE A │────▶│ PHASE B │────▶│ PHASE C │────▶│ PHASE D │────▶│ PHASE E │────▶│ PHASE F │
│  PARSE  │     │ MEASURE │     │ DETECT  │     │  SCORE  │     │CLASSIFY │     │ REPORT  │
└─────────┘     └─────────┘     └─────────┘     └─────────┘     └─────────┘     └─────────┘
     │               │               │               │               │               │
     ▼               ▼               ▼               ▼               ▼               ▼
 fingerprint    EWMA/MAD        boolean         score          category         JSON/MD
 normalized     baseline        flags           0-100          taxonomy         console
```

| Fáze | Vstup | Výstup | Popis |
|------|-------|--------|-------|
| A | raw errors | normalized records | Normalizace, fingerprint |
| B | records | measurements | EWMA baseline, MAD, trend |
| C | measurements | flags + evidence | is_spike, is_new, is_burst |
| D | flags | score | Deterministická váhová funkce |
| E | message | category | Taxonomy klasifikace |
| F | incidents | report | JSON, MD, console |

## 🔧 Konfigurace

### Environment variables (.env)

```bash
# Elasticsearch
ES_HOST=https://elasticsearch.example.com:9500
ES_USER=your_user
ES_PASSWORD=your_password
ES_INDEX=cluster-app_pcb-*

# PostgreSQL
DB_HOST=postgres.example.com
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_user
DB_PASSWORD=your_password

# Pipeline
SPIKE_THRESHOLD=3.0
EWMA_ALPHA=0.3

# Notifications (optional)
TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
```

### config/namespaces.yaml

```yaml
namespaces:
  - pcb-dev-01-app
  - pcb-sit-01-app
  - pcb-uat-01-app
  - pcb-prd-01-app
```

## 📈 Výstupy

### Incident Object (JSON)

```json
{
  "id": "inc-20260120-001",
  "fingerprint": "abc123def456",
  "score": 72,
  "severity": "high",
  "category": "network",
  "flags": {
    "spike": true,
    "new": false,
    "cross_namespace": true
  },
  "evidence": [
    {
      "rule": "spike_ewma",
      "baseline": 10.5,
      "current": 52.0,
      "threshold": 3.0
    }
  ]
}
```

### Replay (regression testing)

```bash
# Uložení snapshotu
./run_regular.sh --output data/snapshots/

# Pozdější porovnání
python scripts/v4/pipeline_v4.py data/batches/ --replay data/snapshots/summary_20260120.json
```

## 📚 Dokumentace

- [Pipeline V4 Architecture](docs/PIPELINE_V4_ARCHITECTURE.md)
- [Incident Object Reference](docs/INCIDENT_OBJECT.md)
- [Database Schema](docs/DATABASE_SCHEMA.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

## 🔒 Požadavky

- Python 3.10+
- PostgreSQL 13+
- Elasticsearch 7.x/8.x
- Kubernetes 1.24+ (pro K8s deployment)

## 📦 Závislosti

```
psycopg2-binary>=2.9.0
python-dotenv>=1.0.0
requests>=2.28.0
PyYAML>=6.0
```

---

**Verze:** 4.0 | **Datum:** 2026-01-20
