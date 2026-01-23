# 🚀 V4 Complete Installation Guide

**Last Updated:** 2026-01-21
**Status:** Production Ready (with known blockers listed)

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Environment Setup](#environment-setup)
3. [Database Preparation](#database-preparation)
4. [Python Environment](#python-environment)
5. [Configuration Files](#configuration-files)
6. [Database Schema](#database-schema)
7. [Permissions Setup](#permissions-setup)
8. [Baseline Data Collection (INIT Phase)](#baseline-data-collection)
9. [Threshold Calculation](#threshold-calculation)
10. [Backfill Phase](#backfill-phase)
11. [Regular Phase & Cron Setup](#regular-phase--cron-setup)
12. [Verification Checklist](#verification-checklist)

---

## Prerequisites

### Required Software
- Python 3.9+
- PostgreSQL 12+
- Elasticsearch 7.x+
- psycopg2
- PyYAML

### Required Credentials
- PostgreSQL DB host, port, credentials
- Elasticsearch host, port
- DB Users with appropriate roles (ddl_user, app_user)

---

## Environment Setup

### 1.1 Create .env File

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
cp config/.env.example .env
```

### 1.2 Update .env with Your Values

```bash
# Database
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER_DDL=ailog_analyzer_ddl_user_d1
DB_PASSWORD_DDL=<your_ddl_password>
DB_USER_APP=ailog_analyzer_user_d1
DB_PASSWORD_APP=<your_app_password>

# Elasticsearch
ES_HOST=elasticsearch.example.com
ES_PORT=9200
ES_USERNAME=<if_required>
ES_PASSWORD=<if_required>

# Logging
LOG_LEVEL=INFO
LOG_DIR=/var/log/ailog/
```

### 1.3 Create Log Directory

```bash
mkdir -p /var/log/ailog/
chmod 755 /var/log/ailog/
```

---

## Database Preparation

### 2.1 Create Database Role & User (if not exists)

```bash
export PGPASSWORD="<postgres_admin_password>"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U postgres -d postgres << 'EOF'
-- Create DDL role (for migrations)
CREATE ROLE role_ailog_analyzer_ddl WITH LOGIN;
ALTER ROLE role_ailog_analyzer_ddl CREATEDB;

-- Create app role (for runtime)
CREATE ROLE role_ailog_analyzer_app WITH LOGIN;

-- Create DDL user
CREATE USER ailog_analyzer_ddl_user_d1 WITH PASSWORD 'WWvkHhyjje8YSgvU';
GRANT role_ailog_analyzer_ddl TO ailog_analyzer_ddl_user_d1;

-- Create app user
CREATE USER ailog_analyzer_user_d1 WITH PASSWORD '<app_password>';
GRANT role_ailog_analyzer_app TO ailog_analyzer_user_d1;

-- Grant schema permissions
GRANT CREATE ON DATABASE ailog_analyzer TO role_ailog_analyzer_ddl;

EOF
```

### 2.2 Create Schema

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;
CREATE SCHEMA IF NOT EXISTS ailog_peak;
GRANT ALL PRIVILEGES ON SCHEMA ailog_peak TO role_ailog_analyzer_ddl;
GRANT USAGE ON SCHEMA ailog_peak TO role_ailog_analyzer_app;
EOF
```

---

## Python Environment

### 3.1 Install Python Dependencies

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
pip install -r requirements.txt
```

### 3.2 Verify Installations

```bash
python3 -c "import psycopg2; print(f'psycopg2: OK')"
python3 -c "import yaml; print(f'PyYAML: OK')"
python3 -c "import elasticsearch; print(f'Elasticsearch: OK')"
```

---

## Configuration Files

### 4.1 Namespaces Configuration

**File:** `config/namespaces.yaml`

Must contain all monitored namespaces(for example):

```yaml
namespaces:
  pca-dev-01-app:
    priority: 30
    groups: [pca, dev]
    alert_rule: WARN
  
  pca-fat-01-app:
    priority: 40
    groups: [pca, fat]
    alert_rule: WARN
  
  pca-sit-01-app:
    priority: 50
    groups: [pca, sit]
    alert_rule: CRITICAL
  
  pca-uat-01-app:
    priority: 60
    groups: [pca, uat]
    alert_rule: CRITICAL
  
  pcb-dev-01-app:
    priority: 30
    groups: [pcb, dev]
    alert_rule: WARN
  
  pcb-fat-01-app:
    priority: 40
    groups: [pcb, fat]
    alert_rule: WARN
  
  pcb-sit-01-app:
    priority: 50
    groups: [pcb, sit]
    alert_rule: CRITICAL
  
  pcb-uat-01-app:
    priority: 60
    groups: [pcb, uat]
    alert_rule: CRITICAL
  
  pcb-ch-dev-01-app:
    priority: 35
    groups: [pcb_ch, dev]
    alert_rule: WARN
  
  pcb-ch-fat-01-app:
    priority: 45
    groups: [pcb_ch, fat]
    alert_rule: WARN
  
  pcb-ch-sit-01-app:
    priority: 55
    groups: [pcb_ch, sit]
    alert_rule: CRITICAL
  
  pcb-ch-uat-01-app:
    priority: 65
    groups: [pcb_ch, uat]
    alert_rule: CRITICAL
```

### 4.2 Verify Config Loading

```bash
python3 -c "
import yaml
with open('config/namespaces.yaml') as f:
    config = yaml.safe_load(f)
    print(f'Loaded {len(config[\"namespaces\"])} namespaces')
    for ns in config['namespaces']:
        print(f'  - {ns}')
"
```

---

## Database Schema

### 5.1 Run All Migrations

**Order matters! Run in sequence:**

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

# Migration 000: Base tables
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/000_create_base_tables.sql

# Migration 001: Peak thresholds
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/001_create_peak_thresholds.sql

# Migration 002: Enhanced analysis tables
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/002_create_enhanced_analysis_tables.sql

# Migration 003: V4 upgrade (adds V4 flags to existing tables)
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/upgrade_v3_to_v4.sql
```

### 5.2 Verify Tables Created

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
\dt ailog_peak.*;
\ds ailog_peak.*;
EOF
```

**Expected tables (13):**
- `peak_raw_data` - Baseline hourly error counts
- `peak_investigation` - Detected incidents with V4 flags
- `peak_thresholds` - P93 percentile thresholds per namespace/dow
- `peak_threshold_caps` - Aggregated CAP values per namespace
- `aggregation_data` - Baseline statistics
- `known_issues` - Known error patterns
- `error_signatures` - Error fingerprints
- `service_health` - Service health metrics
- `cascade_failures` - Cascade failure tracking
- `service_dependencies` - Service dependency graph
- `peak_threshold_dow` - Day-of-week threshold adjustments
- Plus 2 views

---

## Permissions Setup

### 6.1 Grant Table Permissions to App User

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;

-- Default table permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;

-- Sequence permissions for SERIAL columns
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;

-- Specific table grants
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_raw_data TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_investigation TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_thresholds TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_threshold_caps TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.aggregation_data TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.known_issues TO ailog_analyzer_user_d1;

-- Specific sequence grants
GRANT USAGE ON SEQUENCE ailog_peak.peak_raw_data_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_investigation_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_thresholds_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_threshold_caps_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.aggregation_data_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.known_issues_id_seq TO ailog_analyzer_user_d1;

EOF
```

### 6.2 Verify Permissions

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
-- Test INSERT on peak_raw_data
INSERT INTO ailog_peak.peak_raw_data 
  (timestamp, namespace, error_count, day_of_week, hour_of_day, quarter_hour)
VALUES (NOW(), 'pca-dev-01-app', 1, 3, 12, 0);

-- If successful, clean up
DELETE FROM ailog_peak.peak_raw_data WHERE timestamp > NOW() - INTERVAL '1 minute';

SELECT 'Permissions verified OK' as status;
EOF
```

---

## Baseline Data Collection

### 7.1 INIT Phase (12+ days baseline)

Collects error data WITHOUT peak detection. Required before running regular phase.

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Collect 12 days of baseline
python3 scripts/init_phase.py --days 12

# Or collect specific date range
python3 scripts/init_phase.py --from "2026-01-01T00:00:00Z" --to "2026-01-13T23:59:59Z"

# Dry run (no database writes)
python3 scripts/init_phase.py --days 12 --dry-run
```

### 7.2 Verify INIT Completed

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as peak_raw_data_rows FROM ailog_peak.peak_raw_data;
SELECT COUNT(DISTINCT namespace) as namespaces FROM ailog_peak.peak_raw_data;
SELECT COUNT(DISTINCT DATE(timestamp)) as days_collected FROM ailog_peak.peak_raw_data;

-- Show sample data
SELECT timestamp, namespace, error_count, day_of_week 
FROM ailog_peak.peak_raw_data 
LIMIT 5;
EOF
```

**Expected results:**
- Rows: ~5,000-7,000 (12 days × 12 namespaces × ~96 windows/day)
- Namespaces: 12 (all should be present)
- Days: 12-14 (depending on data availability)

---

## Threshold Calculation

### 8.1 Calculate P93 Percentile Thresholds

Requires completed INIT phase with data in `peak_raw_data`.

**What it does:**
- Calculates P93 (93rd percentile) for each namespace + day-of-week combination
- Creates baseline thresholds from INIT data (peak_raw_data)
- Computes CAP values (ceiling anomaly percentile) per namespace
- Stores 62+ threshold rows and ~10 CAP values in database

**Important:** Script uses `DB_DDL_USER` credentials (not regular app user) for INSERT/DELETE operations.

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Standard execution (uses .env DB_DDL_USER)
python3 scripts/core/calculate_peak_thresholds.py

# Or with explicit DDL credentials
DB_DDL_USER=ailog_analyzer_ddl_user_d1 DB_DDL_PASSWORD=WWvkHhyjje8YSgvU \
  python3 scripts/core/calculate_peak_thresholds.py

# Dry run (calculate but don't insert)
python3 scripts/core/calculate_peak_thresholds.py --dry-run

# Different percentile (default: 0.93)
python3 scripts/core/calculate_peak_thresholds.py --percentile 0.95

# Use only last 4 weeks of data
python3 scripts/core/calculate_peak_thresholds.py --weeks 4

# Verbose output
python3 scripts/core/calculate_peak_thresholds.py --verbose
```

**Expected output:**
```
✅ Connected to P050TD01.DEV.KB.CZ:5432/ailog_analyzer
📊 Fetching data from peak_raw_data...
   Found 5,794 rows
   Unique (namespace, dow) combinations: 62
   Date range: 2026-01-09 to 2026-01-20

📈 Calculating P93 thresholds...
📊 Calculating CAP values...

[P93 Thresholds table showing all namespaces × days]
[CAP VALUES table showing aggregated thresholds]

🗑️  Clearing existing thresholds...
📥 Inserting 62 percentile thresholds...
   ✅ Inserted 62 percentile threshold rows

📥 Inserting 10 CAP values...
   ✅ Inserted 10 CAP value rows

================================================================================
✅ Peak thresholds calculation complete!
================================================================================
```

### 8.2 Verify Thresholds Stored

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as threshold_rows FROM ailog_peak.peak_thresholds;
SELECT COUNT(*) as cap_rows FROM ailog_peak.peak_threshold_caps;

-- Show sample thresholds
SELECT namespace, day_of_week, percentile_value, percentile_level, sample_count 
FROM ailog_peak.peak_thresholds 
ORDER BY namespace, day_of_week 
LIMIT 20;

-- Show CAP values (Ceiling Anomaly Percentile per namespace)
SELECT namespace, cap_value, median_percentile, avg_percentile, min_percentile, max_percentile
FROM ailog_peak.peak_threshold_caps
ORDER BY cap_value DESC;
EOF
```

**Expected results:**
- threshold_rows: 62 (12 namespaces with 5-7 days of data each)
- cap_rows: 10 (one aggregated CAP value per namespace)
- percentile_level: 0.9300 (P93)
- percentile_value: ranges from 4.0 (pca-sit) to 606.0 (pcb-sit)

**Sample output:**
```
 total_rows | namespaces | min_p93 | max_p93 | avg_p93
------------+------------+---------+---------+---------
         62 |         10 |    4.00 |  606.00 |  119.27

       namespace      | cap_value
 ─────────────────────────────────
 pcb-sit-01-app       |    375.93
 pcb-dev-01-app       |    181.29
 pcb-ch-dev-01-app    |     84.43
 pcb-ch-sit-01-app    |     99.57
 pcb-fat-01-app       |     70.00
 pcb-uat-01-app       |     76.86
 pca-dev-01-app       |     63.86
 pca-fat-01-app       |     24.00
 pca-sit-01-app       |     17.50
 pca-uat-01-app       |     17.83
```

### 8.3 Understanding Thresholds

**peak_thresholds table:**
- `namespace` - e.g., "pca-dev-01-app"
- `day_of_week` - 0=Mon, 1=Tue, ..., 6=Sun
- `percentile_value` - P93 threshold (errors above this = anomaly)
- `percentile_level` - 0.93 (93rd percentile)
- `sample_count` - How many data points used in calculation
- `median_value`, `mean_value`, `max_value` - Baseline statistics

**peak_threshold_caps table:**
- `namespace` - Unique per namespace
- `cap_value` - Aggregated ceiling value (median of P93 across all days)
- `median_percentile`, `avg_percentile`, `min_percentile`, `max_percentile` - Statistical bounds

**Usage:**
- REGULAR phase uses thresholds to detect: `actual_value > percentile_value`
- CAP values used for normalization and relative scoring

---

## Backfill Phase

### 9.1 Process Historical Data with Peak Detection

Processes recent historical data WITH peak detection using calculated thresholds.

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Backfill last 14 days
python3 scripts/backfill.py --days 14

# Or specific date range
python3 scripts/backfill.py --from "2026-01-07T00:00:00Z" --to "2026-01-20T23:59:59Z"

# With reports
python3 scripts/backfill.py --days 14 --output data/reports/

# Dry run
python3 scripts/backfill.py --days 14 --dry-run
```

### 9.2 Verify Backfill Results

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as incident_rows FROM ailog_peak.peak_investigation;
SELECT COUNT(*) as with_flags FROM ailog_peak.peak_investigation 
  WHERE is_spike OR is_burst OR is_new OR is_cross_namespace OR is_regression OR is_cascade;

-- Show detected incidents
SELECT timestamp, namespace, actual_value, severity, status, is_spike, is_burst
FROM ailog_peak.peak_investigation
WHERE severity IS NOT NULL
LIMIT 20;
EOF
```

---

## Regular Phase & Cron Setup

### 10.1 Create Run Scripts

**File:** `run_init.sh`

```bash
#!/bin/bash
set -e

cd /home/jvsete/git/sas/ai-log-analyzer

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 --days N | --from DATE --to DATE"
  exit 1
fi

python3 scripts/init_phase.py "$@"
```

**File:** `run_regular.sh`

```bash
#!/bin/bash
set -e

cd /home/jvsete/git/sas/ai-log-analyzer

# Run regular phase for last 30 minutes (captures 15-min window)
python3 scripts/regular_phase.py --from "$(date -d '30 minutes ago' -u +%Y-%m-%dT%H:%M:%SZ)" \
  --to "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$@"
```

**File:** `run_backfill.sh`

```bash
#!/bin/bash
set -e

cd /home/jvsete/git/sas/ai-log-analyzer

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 --days N | --from DATE --to DATE"
  exit 1
fi

python3 scripts/backfill.py "$@"
```

### 10.2 Make Scripts Executable

```bash
chmod +x /home/jvsete/git/sas/ai-log-analyzer/run_init.sh
chmod +x /home/jvsete/git/sas/ai-log-analyzer/run_regular.sh
chmod +x /home/jvsete/git/sas/ai-log-analyzer/run_backfill.sh
```

### 10.3 Setup Cron Job (15-minute intervals)

```bash
# Edit crontab
crontab -e

# Add line:
*/15 * * * * cd /home/jvsete/git/sas/ai-log-analyzer && ./run_regular.sh >> /var/log/ailog/cron.log 2>&1

# Verify
crontab -l
```

### 10.4 Test Regular Phase Manually

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
./run_regular.sh --dry-run
```

---

## Verification Checklist

### Final Setup Verification

```bash
#!/bin/bash
set -e

echo "🔍 V4 Installation Verification Checklist"
echo "=========================================="

# 1. Python environment
echo -n "✓ Python 3.9+: "
python3 --version

# 2. Dependencies
echo -n "✓ psycopg2: "
python3 -c "import psycopg2; print('OK')"

echo -n "✓ PyYAML: "
python3 -c "import yaml; print('OK')"

# 3. Config files
echo -n "✓ .env exists: "
[ -f ".env" ] && echo "YES" || echo "NO"

echo -n "✓ namespaces.yaml exists: "
[ -f "config/namespaces.yaml" ] && echo "YES" || echo "NO"

# 4. Database connectivity
echo -n "✓ Database connectivity: "
PGPASSWORD="WWvkHhyjje8YSgvU" psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 \
  -d ailog_analyzer -c "SELECT 1" > /dev/null && echo "OK" || echo "FAILED"

# 5. Database tables
echo -n "✓ peak_raw_data table: "
PGPASSWORD="WWvkHhyjje8YSgvU" psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 \
  -d ailog_analyzer -c "SELECT 1 FROM ailog_peak.peak_raw_data LIMIT 1" > /dev/null 2>&1 && echo "OK" || echo "MISSING"

# 6. Python scripts
echo -n "✓ init_phase.py exists: "
[ -f "scripts/init_phase.py" ] && echo "YES" || echo "NO"

echo -n "✓ regular_phase.py exists: "
[ -f "scripts/regular_phase.py" ] && echo "YES" || echo "NO"

echo -n "✓ backfill.py exists: "
[ -f "scripts/backfill.py" ] && echo "YES" || echo "NO"

# 7. Run scripts
echo -n "✓ run_init.sh executable: "
[ -x "run_init.sh" ] && echo "YES" || echo "NO"

echo -n "✓ run_regular.sh executable: "
[ -x "run_regular.sh" ] && echo "YES" || echo "NO"

# 8. Logs directory
echo -n "✓ /var/log/ailog/ exists: "
[ -d "/var/log/ailog/" ] && echo "YES" || echo "NO"

# 9. Data counts
echo ""
echo "📊 Data Status:"
echo -n "   peak_raw_data rows: "
PGPASSWORD="WWvkHhyjje8YSgvU" psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 \
  -d ailog_analyzer -t -c "SELECT COUNT(*) FROM ailog_peak.peak_raw_data"

echo -n "   peak_thresholds rows: "
PGPASSWORD="WWvkHhyjje8YSgvU" psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 \
  -d ailog_analyzer -t -c "SELECT COUNT(*) FROM ailog_peak.peak_thresholds"

echo ""
echo "✅ Setup verification complete!"
```

---

## Troubleshooting

### Problem: Permission Denied for Sequence

**Error:** `psycopg2.errors.InsufficientPrivilege: permission denied for sequence peak_thresholds_id_seq`

**Cause:** calculate_peak_thresholds.py is using regular app user (ailog_analyzer_user_d1) which lacks INSERT privileges

**Solution:**
```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;
GRANT USAGE ON SEQUENCE ailog_peak.peak_thresholds_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_threshold_caps_id_seq TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_thresholds TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_threshold_caps TO ailog_analyzer_user_d1;
EOF
```

**Prevention:** Ensure .env has correct `DB_DDL_USER` and `DB_DDL_PASSWORD` values, or pass via environment:
```bash
DB_DDL_USER=ailog_analyzer_ddl_user_d1 DB_DDL_PASSWORD=WWvkHhyjje8YSgvU \
  python3 scripts/core/calculate_peak_thresholds.py
```

### Problem: Cannot Connect to Database

**Error:** `psycopg2.OperationalError: could not connect to server: Connection refused`

**Cause:** Database host, port, or credentials incorrect

**Solution:**
1. Verify .env DB_HOST and DB_PORT
2. Test connectivity: `telnet P050TD01.DEV.KB.CZ 5432`
3. Test credentials: 
   ```bash
   PGPASSWORD="WWvkHhyjje8YSgvU" psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -c "SELECT 1"
   ```

### Problem: Permission Denied for Schema

**Error:** `permission denied for schema ailog_peak`

**Cause:** User doesn't have USAGE permission on schema

**Solution:**
```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;
GRANT USAGE ON SCHEMA ailog_peak TO ailog_analyzer_user_d1;
GRANT USAGE ON SCHEMA ailog_peak TO role_ailog_analyzer_app;
EOF
```

### Problem: Elasticsearch Connection Timeout

**Error:** `elasticsearch.exceptions.ConnectionTimeout`

**Solution:**
- Verify ES_HOST and ES_PORT in .env
- Check if ES is running: `curl -u $ES_USERNAME:$ES_PASSWORD http://$ES_HOST:$ES_PORT/`
- Check firewall rules

### Problem: INIT Phase Collects No Data

**Error:** `Found 0 rows`

**Solution:**
- Verify Elasticsearch has data for the requested date range
- Check namespaces.yaml contains expected namespaces
- Test ES query manually to verify data exists

### Problem: Thresholds Not Calculated

**Error:** `No data in peak_raw_data`

**Solution:**
- Run INIT phase first: `python3 scripts/init_phase.py --days 12`
- Verify data was inserted: `SELECT COUNT(*) FROM ailog_peak.peak_raw_data;`
- Ensure at least 7 days of data for statistical significance (P93 needs good sample size)

### Problem: Script Uses Wrong Database User

**Error:** Intermittent permission errors during calculate_peak_thresholds.py

**Cause:** Script reading DB_USER instead of DB_DDL_USER from .env

**Solution:** 
- Ensure .env has both configured:
  ```
  DB_USER=ailog_analyzer_user_d1
  DB_PASSWORD=<app_password>
  DB_DDL_USER=ailog_analyzer_ddl_user_d1
  DB_DDL_PASSWORD=WWvkHhyjje8YSgvU
  ```
- Or pass explicitly:
  ```bash
  DB_DDL_USER=ailog_analyzer_ddl_user_d1 DB_DDL_PASSWORD=WWvkHhyjje8YSgvU \
    python3 scripts/core/calculate_peak_thresholds.py
  ```

---

## Production Deployment Checklist

- [ ] .env configured with production credentials
- [ ] Database backups configured
- [ ] Log rotation configured (/var/log/ailog/)
- [ ] Cron job scheduled and tested
- [ ] Initial run completed without errors
- [ ] Baseline data collected (12+ days)
- [ ] Thresholds calculated and verified
- [ ] Backfill run completed successfully
- [ ] Regular phase producing incidents
- [ ] Monitoring/alerting configured
- [ ] Documentation updated

---

**End of Installation Guide**
