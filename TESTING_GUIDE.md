# Testing Guide - AI Log Analyzer

## Quick Reference

| Test | Command | Expected |
|------|---------|----------|
| DB Connection | `python3 -c "import psycopg2; ..."` | No error |
| Backfill 1-day | `python3 scripts/backfill.py --days 1 --workers 1` | 50K+ incidents |
| Regular phase | `python3 scripts/regular_phase.py` | Report generated |
| BaselineLoader | `python3 scripts/core/baseline_loader.py --error-types UnknownError --stats` | Historical rates |
| Export | `python3 scripts/exports/table_exporter.py` | CSV/JSON/MD files |

## Test 1: Database Connection

```bash
python3 << 'EOF'
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
print("DB connection OK")
conn.close()
EOF
```

## Test 2: Elasticsearch Connection

```bash
python3 << 'EOF'
from core.fetch_unlimited import fetch_all_errors
from datetime import datetime, timedelta, timezone
end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(hours=1)
count = 0
for batch in fetch_all_errors(start_time, end_time, limit=100):
    count += len(batch)
    if count >= 100:
        break
print(f"Fetched {count} records from ES")
EOF
```

## Test 3: Backfill Pipeline

```bash
# Quick test (1 day, 1 worker)
python3 scripts/backfill.py --days 1 --workers 1

# Full test (4 days, 4 workers)
python3 scripts/backfill.py --days 4 --workers 4
```

Ocekavany vystup:
- Phase A: ES fetch
- Phase B: Measurement s historickym baseline
- Phase C: Detection s registry lookup
- Phase D-F: Scoring, classification, report
- DB save
- Registry update

## Test 4: BaselineLoader

```bash
python3 scripts/core/baseline_loader.py \
    --error-types UnknownError NotFoundError ServiceBusinessException \
    --days 7 --stats
```

Overi ze:
- Historicka data existuji v peak_investigation
- BaselineLoader vraci spravny pocet samplu
- Statistiky jsou rozumne (min, max, avg)

## Test 5: Regular Phase

```bash
python3 scripts/regular_phase.py
```

Ocekavany vystup:
- Baseline loading z DB
- Pipeline processing
- Report generovany
- Registry update

## Test 6: DB Verifikace

```sql
-- Pocet incidentu
SELECT COUNT(*) FROM ailog_peak.peak_investigation;

-- Distribuce po dnech
SELECT DATE(timestamp), COUNT(*)
FROM ailog_peak.peak_investigation
GROUP BY DATE(timestamp)
ORDER BY DATE(timestamp) DESC;

-- Baseline quality
SELECT error_type, COUNT(*), AVG(reference_value)
FROM ailog_peak.peak_investigation
WHERE reference_value IS NOT NULL
GROUP BY error_type
ORDER BY COUNT(*) DESC;
```

## Test 7: Peak Summary

```bash
python3 scripts/generate_peak_summary_table.py --hours 24
```

## Troubleshooting

| Problem | Reseni |
|---------|--------|
| `No module named 'psycopg2'` | `pip install psycopg2-binary` |
| `permission denied for schema` | Zkontrolujte DB_DDL_USER + SET ROLE |
| `Connection refused (ES)` | Zkontrolujte ES_HOST, ES_USER v .env |
| Baseline = 0 | Zkontrolujte BaselineLoader - `python3 scripts/core/baseline_loader.py --error-types ... --stats` |

## Performance Benchmarks

| Test | Data | Doba |
|------|------|------|
| 1-day backfill (1 worker) | ~60K incidents | ~1-2 min |
| 4-day backfill (4 workers) | ~240K incidents | ~5-10 min |
| Regular phase (15min) | ~500-2000 incidents | ~30-60 sec |
