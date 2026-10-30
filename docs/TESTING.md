# Testing Guide - AI Log Analyzer

## r111 Regression Gate

Automated tests are the release gate; the legacy smoke commands below may contact services, mutate registries or publish notifications. Do not run legacy backfill as a second writer in the deployed PostgreSQL mode. Direct regular invocation in that mode requires `--scheduled` and its DB lease.

Use only a disposable PostgreSQL database whose name contains `test`. The integration fixture drops/recreates the entire `ailog_peak` schema; never point these variables at the application database. Set `TEST_POSTGRES_DSN` privately before running from the repository root, and pass the same disposable DSN to runtime-state tests:

```bash
export AILOG_TEST_POSTGRES_DSN="$TEST_POSTGRES_DSN"
python3 -m pytest scripts/tests/test_runtime_state.py scripts/tests/test_postgres_integration.py scripts/tests/test_install_values_yaml.py scripts/tests/test_report_from_facts.py scripts/tests/test_confluence_csv_delivery.py -q
python3 -m pytest scripts/tests -q --junitxml=/tmp/ai-log-analyzer-results.xml
```

Without both DSNs, DB tests may be skipped; a green offline result alone is not the full PostgreSQL gate. Helm must be installed for chart contracts. Covered risks include pod replacement with registry/fingerprint/ID/cooldown preservation, immediate checkpoints, competing writers, bootstrap idempotency, stale/missing-state refusal, PVC-free regular rendering, complete CSV preservation, Unicode/escaping byte sizes and oversized-request rejection before PUT.

The isolated r111 source `41d1a12` passed 256 tests and 2 subtests against PostgreSQL 16 with zero skips. The actual Python 3.11 image passed an offline import smoke test; nprod separately verified one complete eight-window collector Job and all three Confluence publications. That live run did not exercise a peak-alert branch or prove historical daily completeness. Timestamped results and backlog are recorded in [OPERATIONS.md](OPERATIONS.md#overene-nasazeni-r111).

For deployment validation, render the actual GitOps chart with its existing Helm parameter overrides, not just the source chart. Verify no PVC volume in regular/init/reporter, no duplicate env names, valid embedded quiesce Python, rejection of running/restarted containers by the never-started policy, no DB-mode SyncFail resume hook, preserved percentile and suspended legacy backfill. Do not send live reports merely as an unapproved test; normal reporter execution publishes externally.

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
