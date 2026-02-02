# Instalace AI Log Analyzer v5.3.1

## Rychlá instalace

```bash
# 1. Závislosti
pip install psycopg2-binary python-dotenv requests pyyaml

# 2. Konfigurace
cp config/.env.example config/.env
# Upravit: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD

# 3. Inicializace registry (automaticky při prvním běhu)
mkdir -p registry scripts/reports

# 4. Test
python scripts/regular_phase_v5.3.py --help
```

## Prerekvizity

- Python 3.8+
- PostgreSQL přístup (read pro analýzu, write pro DDL)
- Elasticsearch přístup (pro fetch logů)

## Konfigurace

### .env soubor

```bash
# Database
DB_HOST=p050td01.dev.kb.cz
DB_PORT=5432
DB_NAME=d_ailog
DB_USER=user_ailog_analyzer
DB_PASSWORD=xxx

# DDL user (pro zápis do DB)
DB_DDL_USER=user_ailog_analyzer_ddl
DB_DDL_PASSWORD=xxx

# Elasticsearch
ES_HOST=https://elk-search.kb.cz
ES_USER=xxx
ES_PASSWORD=xxx

# Optional: Slack/Teams webhooks
SLACK_WEBHOOK_URL=
TEAMS_WEBHOOK_URL=
```

### Knowledge Base

```bash
# Šablony pro známé errory
config/known_issues/
├── known_errors.yaml
├── known_peaks.yaml
└── known_issues.yaml
```

## Adresářová struktura po instalaci

```
ai-log-analyzer/
├── config/
│   ├── .env                 # Vaše konfigurace
│   └── known_issues/        # Knowledge base
├── registry/                # Automaticky aktualizováno
│   ├── known_errors.yaml
│   └── known_errors.md
├── scripts/
│   ├── reports/             # Výstupní reporty
│   ├── regular_phase_v5.3.py
│   └── backfill_v5.3.py
└── incident_analysis/       # Modul
```

## Spuštění

### 15min cyklus

```bash
python scripts/regular_phase_v5.3.py

# Výstup:
# - scripts/reports/incident_analysis_15min_*.txt
# - registry/known_errors.yaml (aktualizováno)
```

### Backfill

```bash
python scripts/backfill_v5.3.py --days 7

# Výstup:
# - scripts/reports/incident_analysis_daily_*.txt
```

### Cron

```bash
# /etc/cron.d/ai-log-analyzer
*/15 * * * * cd /opt/ai-log-analyzer && python scripts/regular_phase_v5.3.py --quiet
```

## Ověření instalace

```bash
# 1. Test importů
python -c "from incident_analysis import IncidentAnalysisEngine, IncidentPropagation; print('OK')"

# 2. Test DB připojení
python -c "import psycopg2; print('DB OK')"

# 3. Suchý běh
python scripts/regular_phase_v5.3.py --dry-run
```

## Troubleshooting

### ❌ Error: `ModuleNotFoundError: No module named 'psycopg2'`

**Příčina:** psycopg2 není nainstalován

**Řešení:**
```bash
# Systémová instalace (doporučeno pro production):
apt-get install python3-psycopg2

# NEBO pip instalace:
pip install psycopg2-binary

# Pokud backfill nefunguje - vytvořit fresh venv:
rm -rf venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
apt-get install python3-psycopg2  # Naimportuje se z systému
```

### ❌ Error: `'PeakEntry' object has no attribute 'category'` (Export)

**Příčina:** Export feature - PeakEntry dataclass chybí category field

**Impact:** Export funkce (scripts/exports/table_exporter.py) nefunguje

**Workaround:** Core functionality (DB save, registry update) funguje bez exportu

**TODO:** Opravit PeakEntry dataclass definici

### ⚠️ Warning: Teams notifications not sending

**Příčina:** Import `core/teams_notifier.py` v `backfill_v6.py` main() nefunguje

**Impact:** Backfill běží a ukládá data ✅, ale Teams zprávy se neposílají ⚠️

**Logs:** Backfill output obsahuje `⚠️ Teams notification failed: No module named 'core.teams_notifier'`

**Workaround:** Core functionality (DB storage) funguje normálně

**TODO:** Vyřešit sys.path konfiguraci pro dynamic import v main()



### ModuleNotFoundError

```bash
# Přidejte projekt do PYTHONPATH
export PYTHONPATH=/path/to/ai-log-analyzer:$PYTHONPATH
```

### Registry se neaktualizuje

- Zkontrolujte oprávnění k zápisu do `registry/`
- Zkontrolujte logy na chyby

### Reporty se negenerují

v5.3.1 opravuje tento bug - report se generuje VŽDY, i když nejsou incidenty.

## Upgrade z v5.3 na v5.3.1

```bash
# 1. Nahraďte soubory
cp -r new_version/incident_analysis/* incident_analysis/
cp new_version/scripts/*_v5.3.py scripts/

# 2. Vytvořte registry adresář
mkdir -p registry

# 3. Test
python -c "from incident_analysis import IncidentPropagation; print('OK')"
```

## Kontakt

Pro problémy s instalací kontaktujte tým Platform Engineering.
