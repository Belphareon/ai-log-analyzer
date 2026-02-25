# Instalace AI Log Analyzer

## Prerekvizity

- Python 3.8+
- PostgreSQL pristup (read pro analyzu, write pro DDL)
- Elasticsearch pristup (pro fetch logu)

## Rychla instalace

```bash
# 1. Zavislosti
pip install psycopg2-binary python-dotenv requests pyyaml tqdm

# 2. Konfigurace
cp config/.env.example config/.env
# Upravit: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, ES_HOST, ...

# 3. Inicializace (automaticky pri prvnim behu)
mkdir -p registry scripts/reports

# 4. Test
python3 scripts/regular_phase_v6.py --help
```

## Konfigurace (.env)

```bash
# Database (read)
DB_HOST=...
DB_PORT=5432
DB_NAME=d_ailog
DB_USER=...
DB_PASSWORD=...

# Database (write - DDL user)
DB_DDL_USER=...
DB_DDL_PASSWORD=...
DB_DDL_ROLE=role_ailog_analyzer_ddl

# Elasticsearch
ES_HOST=https://...
ES_USER=...
ES_PASSWORD=...

# Optional: Notifications
TEAMS_WEBHOOK_URL=...
CONFLUENCE_URL=...
CONFLUENCE_USERNAME=...
CONFLUENCE_API_TOKEN=...
```

## Pouziti

```bash
# 15min cyklus
python3 scripts/regular_phase_v6.py

# Backfill N dni
python3 scripts/backfill_v6.py --days 7 --workers 4

# Backfill s force reprocessing
python3 scripts/backfill_v6.py --days 14 --force
```

## Overeni instalace

```bash
# 1. Test DB pripojeni
python3 -c "import psycopg2; print('DB OK')"

# 2. Test importu
python3 -c "from incident_analysis import IncidentAnalysisEngine; print('OK')"

# 3. Suchy beh
python3 scripts/regular_phase_v6.py --dry-run
```

## Troubleshooting

### ModuleNotFoundError: No module named 'psycopg2'

```bash
# Systemova instalace (doporuceno pro production):
apt-get install python3-psycopg2
# NEBO pip:
pip install psycopg2-binary
```

### Permission denied for schema ailog_peak

DB write operace vyzaduji:
1. Pripojeni jako DDL user (DB_DDL_USER)
2. `SET ROLE role_ailog_analyzer_ddl`

Zkontrolujte `.env` promenne `DB_DDL_USER`, `DB_DDL_PASSWORD`, `DB_DDL_ROLE`.

### ModuleNotFoundError (obecne)

```bash
export PYTHONPATH=/path/to/ai-log-analyzer:$PYTHONPATH
```
