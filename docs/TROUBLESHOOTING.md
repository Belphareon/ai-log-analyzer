# 🚨 V4 Troubleshooting & Problem-Solving Guide

**Updated:** 2026-01-21  
**Purpose:** Diagnose and fix common issues quickly

---

## 🔍 Quick Diagnostic Script

Run this first to identify issues:

```bash
#!/bin/bash
echo "🔍 V4 System Diagnostic"
echo "======================"

# 1. Python
echo "1. Python checks:"
python3 --version 2>/dev/null || echo "  ❌ Python not installed"
python3 -c "import psycopg2" 2>/dev/null && echo "  ✅ psycopg2" || echo "  ❌ psycopg2 missing"
python3 -c "import yaml" 2>/dev/null && echo "  ✅ PyYAML" || echo "  ❌ PyYAML missing"

# 2. Config
echo ""
echo "2. Configuration:"
[ -f ".env" ] && echo "  ✅ .env exists" || echo "  ❌ .env missing"
[ -f "config/namespaces.yaml" ] && echo "  ✅ namespaces.yaml" || echo "  ❌ namespaces.yaml missing"

# 3. Database
echo ""
echo "3. Database connectivity:"
export PGPASSWORD="WWvkHhyjje8YSgvU"
if psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -c "SELECT 1" 2>/dev/null; then
  echo "  ✅ Connected as ailog_analyzer_user_d1"
else
  echo "  ❌ Cannot connect - check credentials in .env"
fi

# 4. Tables
echo ""
echo "4. Database tables:"
export PGPASSWORD="WWvkHhyjje8YSgvU"
TABLES=$(psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -t -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ailog_peak'" 2>/dev/null)
if [ "$TABLES" -gt 10 ]; then
  echo "  ✅ Database tables exist ($TABLES tables)"
else
  echo "  ❌ Database tables missing or incomplete"
fi

# 5. Data
echo ""
echo "5. Data status:"
export PGPASSWORD="WWvkHhyjje8YSgvU"
ROWS=$(psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -t -c \
  "SELECT COUNT(*) FROM ailog_peak.peak_raw_data" 2>/dev/null | xargs)
echo "  peak_raw_data: $ROWS rows"

THRESHOLDS=$(psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -t -c \
  "SELECT COUNT(*) FROM ailog_peak.peak_thresholds" 2>/dev/null | xargs)
echo "  peak_thresholds: $THRESHOLDS rows"

# 6. Scripts
echo ""
echo "6. Executable scripts:"
[ -x "run_init.sh" ] && echo "  ✅ run_init.sh" || echo "  ❌ run_init.sh"
[ -x "run_regular.sh" ] && echo "  ✅ run_regular.sh" || echo "  ❌ run_regular.sh"
[ -x "run_backfill.sh" ] && echo "  ✅ run_backfill.sh" || echo "  ❌ run_backfill.sh"

# 7. Permissions
echo ""
echo "7. File permissions:"
ls -la .env 2>/dev/null | awk '{print "  .env: " $1}'
ls -la run_init.sh 2>/dev/null | awk '{print "  run_init.sh: " $1}'

echo ""
echo "✅ Diagnostic complete"
```

---

## 🔴 Category A: Python & Dependencies

### A1: ModuleNotFoundError: No module named 'psycopg2'

**Error Message:**
```
ModuleNotFoundError: No module named 'psycopg2'
```

**Causes:**
- Dependencies not installed
- Wrong Python version
- Virtual environment not activated

**Fix:**
```bash
# Option 1: Install requirements
pip install -r requirements.txt

# Option 2: Install specific package
pip install psycopg2-binary

# Option 3: Use system Python
python3 -m pip install -r requirements.txt

# Verify
python3 -c "import psycopg2; print('OK')"
```

---

### A2: ModuleNotFoundError: No module named 'yaml'

**Error Message:**
```
ModuleNotFoundError: No module named 'yaml'
```

**Fix:**
```bash
pip install PyYAML
python3 -c "import yaml; print('OK')"
```

---

### A3: ImportError: cannot import elasticsearch

**Error Message:**
```
ImportError: cannot import name 'Elasticsearch' from 'elasticsearch'
```

**Causes:**
- elasticsearch-py not installed
- Version mismatch with Elasticsearch server

**Fix:**
```bash
# Install specific version
pip install elasticsearch==7.x.x

# Or update all
pip install --upgrade elasticsearch

# Verify
python3 -c "from elasticsearch import Elasticsearch; print('OK')"
```

---

## 🔴 Category B: Database & Connectivity

### B1: psycopg2.OperationalError: connection refused

**Error Message:**
```
psycopg2.OperationalError: could not connect to server: Connection refused
	Is the server running on host "P050TD01.DEV.KB.CZ" (10.x.x.x) and accepting
	TCP/IP connections on port 5432?
```

**Causes:**
- Wrong host/port in .env
- PostgreSQL not running
- Firewall blocking connection

**Fix:**
```bash
# 1. Verify .env contains correct host
grep DB_HOST .env

# 2. Test direct connection
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -c "SELECT 1"

# 3. Check if PostgreSQL is running (from DB server)
# On DB host: ps aux | grep postgres

# 4. Check network connectivity
telnet P050TD01.DEV.KB.CZ 5432
# Should see: Connected to P050TD01.DEV.KB.CZ.
```

---

### B2: psycopg2.errors.AuthenticationFailed

**Error Message:**
```
psycopg2.errors.AuthenticationFailed: FATAL: password authentication failed for user "ailog_analyzer_user_d1"
```

**Causes:**
- Wrong password in .env
- User doesn't exist
- User locked/disabled

**Fix:**
```bash
# 1. Verify .env password
grep DB_PASSWORD .env

# 2. Test with correct password
export PGPASSWORD="<your_password>"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -c "SELECT 1"

# 3. Reset password (as admin)
export PGPASSWORD="<admin_password>"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U postgres -d ailog_analyzer << 'EOF'
ALTER USER ailog_analyzer_user_d1 WITH PASSWORD 'new_password';
EOF

# 4. Update .env with new password
# Then test again
```

---

### B3: psycopg2.errors.InsufficientPrivilege: permission denied for sequence

**Error Message:**
```
psycopg2.errors.InsufficientPrivilege: permission denied for sequence peak_thresholds_id_seq
```

**Causes:**
- User doesn't have USAGE grant on sequence
- Missing INSERT permission on table

**Fix:**
```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;

-- Grant on ALL sequences
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1;

-- Grant on specific sequence
GRANT USAGE ON SEQUENCE ailog_peak.peak_thresholds_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_threshold_caps_id_seq TO ailog_analyzer_user_d1;

-- Verify
EOF

# Then retry the operation
```

---

### B4: psycopg2.errors.ProgrammingError: table ailog_peak.peak_raw_data does not exist

**Error Message:**
```
psycopg2.errors.ProgrammingError: (psycopg2.errors.ProgrammingError) relation "ailog_peak.peak_raw_data" does not exist
```

**Causes:**
- Migrations not executed
- Schema not created
- Wrong schema name in queries

**Fix:**
```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

# 1. Verify schema exists
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -c "\dn ailog_peak"

# 2. Create schema if missing
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;
CREATE SCHEMA IF NOT EXISTS ailog_peak;
EOF

# 3. Run migrations
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/000_create_base_tables.sql
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/001_create_peak_thresholds.sql

# 4. Verify tables
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'ailog_peak' 
ORDER BY table_name;
EOF
```

---

### B5: psycopg2.errors.UniqueViolation: duplicate key value

**Error Message:**
```
psycopg2.errors.UniqueViolation: duplicate key value violates unique constraint
```

**Causes:**
- Inserting duplicate data (same namespace, day_of_week)
- Running phase twice on same data

**Fix:**
```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

# 1. Identify duplicates
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT namespace, day_of_week, COUNT(*) 
FROM ailog_peak.peak_thresholds 
GROUP BY namespace, day_of_week 
HAVING COUNT(*) > 1;
EOF

# 2. Clear and recalculate
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
DELETE FROM ailog_peak.peak_thresholds;
DELETE FROM ailog_peak.peak_threshold_caps;
EOF

# 3. Re-run calculation
python3 scripts/core/calculate_peak_thresholds.py
```

---

## 🟡 Category C: Data & INIT Phase

### C1: INIT Phase collects zero rows

**Error:**
```
Found 0 rows
Elasticsearch returned no data
```

**Causes:**
- No data in Elasticsearch for date range
- Wrong namespace names
- Elasticsearch not accessible
- Date range in future

**Diagnosis:**
```bash
# 1. Check Elasticsearch directly
curl -u $ES_USERNAME:$ES_PASSWORD \
  "http://$ES_HOST:$ES_PORT/_cat/indices?v" | grep -i log

# 2. Check if data exists for namespace
curl -u $ES_USERNAME:$ES_PASSWORD \
  "http://$ES_HOST:$ES_PORT/<index>/_search?q=kubernetes.namespace_name:pca-dev-01-app" \
  | jq '.hits.total'

# 3. Verify namespaces in config
python3 -c "
import yaml
with open('config/namespaces.yaml') as f:
    config = yaml.safe_load(f)
    for ns in config['namespaces']:
        print(ns)
"
```

**Fix:**
```bash
# 1. Extend date range (ES might have delayed data)
python3 scripts/init_phase.py --from "2026-01-01T00:00:00Z" --to "2026-01-10T23:59:59Z"

# 2. Verify namespaces match Elasticsearch
# Update config/namespaces.yaml if names are wrong

# 3. Test Elasticsearch connectivity
python3 << 'EOF'
from elasticsearch import Elasticsearch
es = Elasticsearch([{'host': 'ES_HOST', 'port': 9200}])
print(es.info())
EOF

# 4. Try with --verbose flag
python3 scripts/init_phase.py --days 7 --verbose
```

---

### C2: INIT Phase incomplete - stuck/slow

**Symptom:**
- Hangs for long time
- No output after 10+ minutes

**Causes:**
- Elasticsearch slow/unresponsive
- Network timeout
- Large data volume

**Fix:**
```bash
# 1. Check if process is still running
ps aux | grep python3 | grep init_phase

# 2. Check resource usage
top -p $(pgrep -f init_phase)

# 3. Kill if stuck
pkill -f "init_phase.py"

# 4. Restart with smaller dataset
python3 scripts/init_phase.py --days 3

# 5. Increase timeout in script
# Edit scripts/init_phase.py and increase timeout from 30 to 60 seconds
```

---

### C3: Wrong number of rows collected

**Expected:** 5,000-7,000 rows (12 days × 12 namespaces × ~40-50 windows/day)

**Got:** 2,000 rows

**Causes:**
- Some namespaces have no data
- Date range incomplete
- Elasticsearch data sparse

**Diagnosis:**
```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

# Check per-namespace
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT namespace, COUNT(*) as rows, COUNT(DISTINCT DATE(timestamp)) as days
FROM ailog_peak.peak_raw_data
GROUP BY namespace
ORDER BY rows DESC;
EOF

# Check for gaps in data
SELECT namespace, MIN(timestamp), MAX(timestamp), COUNT(*) as rows
FROM ailog_peak.peak_raw_data
GROUP BY namespace;
```

**Fix:** Continue collecting more data or use available data if sufficient

---

## 🟡 Category D: Threshold Calculation

### D1: No thresholds calculated

**Error:**
```
Processed: 0 rows from peak_raw_data
Unique combinations: 0
```

**Causes:**
- peak_raw_data table is empty
- INIT phase didn't complete
- Wrong table name

**Fix:**
```bash
# 1. Verify data in peak_raw_data
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) FROM ailog_peak.peak_raw_data;
EOF

# If 0 rows:
# 2. Run INIT phase
python3 scripts/init_phase.py --days 12

# 3. Retry threshold calculation
python3 scripts/core/calculate_peak_thresholds.py
```

---

### D2: Thresholds calculated but not inserted

**Symptom:**
```
📈 Calculating P93 thresholds...
Processed: 5,794 rows
Unique combinations: 62
(shows table with values)
❌ Error: permission denied for sequence
```

**Fix:**
```bash
# Grant permissions (from admin/DDL user)
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;
GRANT USAGE ON SEQUENCE ailog_peak.peak_thresholds_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_threshold_caps_id_seq TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_thresholds TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_threshold_caps TO ailog_analyzer_user_d1;
EOF

# Retry
python3 scripts/core/calculate_peak_thresholds.py
```

---

### D3: Inconsistent threshold values

**Symptom:**
```
pca-dev-01-app CAP: 64 vs previous 120
pcb-sit-01-app CAP: 376 vs previous 250
```

**Causes:**
- Different data range used
- Recent data spike affecting percentiles
- Recalculation with updated data

**Fix:**
- Document the change reason
- If values seem wrong, review actual data:

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
-- Show distribution for one namespace
SELECT 
  namespace,
  day_of_week,
  MIN(error_count) as min_val,
  PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY error_count) as p25,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY error_count) as p50,
  PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY error_count) as p75,
  PERCENTILE_CONT(0.93) WITHIN GROUP (ORDER BY error_count) as p93,
  MAX(error_count) as max_val,
  COUNT(*) as sample_count
FROM ailog_peak.peak_raw_data
WHERE namespace = 'pca-dev-01-app'
GROUP BY namespace, day_of_week
ORDER BY day_of_week;
EOF
```

---

## 🔴 Category E: Backfill & Regular Phase

### E1: Backfill phase produces no incidents

**Symptom:**
```
Processed: 10,000 rows
Detected incidents: 0
Saved to DB: 0
```

**Causes:**
- Thresholds not loaded
- Thresholds too high (no peaks detected)
- Data below thresholds

**Fix:**
```bash
# 1. Verify thresholds exist and are reasonable
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT namespace, MIN(cap_value) as min_cap, MAX(cap_value) as max_cap
FROM ailog_peak.peak_threshold_caps
GROUP BY namespace;
EOF

# 2. Check actual data values vs thresholds
SELECT namespace, MAX(error_count) as max_count
FROM ailog_peak.peak_raw_data
GROUP BY namespace
ORDER BY namespace;

# Compare to cap_value - if max_count < cap_value, no peaks will be detected

# 3. Lower thresholds if needed (use percentile 85 instead of 93)
# Edit values.yaml and adjust multiplier from 1.0 to 0.9
```

---

### E2: Regular phase produces too many false positives

**Symptom:**
```
Every window flags incidents
Most have is_new = true
Severity = CRITICAL
```

**Causes:**
- Thresholds too low
- multiplier in values.yaml too low
- Data significantly different from baseline

**Fix:**
```bash
# 1. Review multipliers in values.yaml
cat values.yaml | grep -A 10 multipliers

# 2. Increase multipliers to reduce sensitivity
# Edit values.yaml:
# multipliers:
#   spike: 2.0  (increase from 1.5)
#   burst: 3.0  (increase from 2.0)

# 3. Re-run backfill with higher threshold
python3 scripts/backfill.py --days 5 --verbose

# 4. Analyze which incidents are real vs false
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT severity, is_new, is_spike, COUNT(*) 
FROM ailog_peak.peak_investigation
GROUP BY severity, is_new, is_spike
ORDER BY severity, is_new, is_spike;
EOF
```

---

## 🟡 Category F: Cron & Automation

### F1: Cron job not running

**Symptom:**
- /var/log/ailog/cron.log not updating
- Manual ./run_regular.sh works but cron doesn't

**Causes:**
- Cron syntax error
- Environment variables not set in cron
- Permissions issue

**Fix:**
```bash
# 1. Check cron syntax
crontab -l

# Should be:
# */15 * * * * cd /home/jvsete/git/sas/ai-log-analyzer && ./run_regular.sh >> /var/log/ailog/cron.log 2>&1

# 2. If syntax wrong, edit:
crontab -e
# Save and exit

# 3. Verify cron running
ps aux | grep cron

# 4. Check if run script has right shebang
head -1 run_regular.sh
# Should be: #!/bin/bash

# 5. Test manually
cd /home/jvsete/git/sas/ai-log-analyzer && ./run_regular.sh

# 6. Check permissions
ls -la run_regular.sh
# Should have 'x' permissions
chmod +x run_regular.sh
```

---

### F2: Cron runs but produces errors

**Log shows:**
```
python3: No module named psycopg2
```

**Causes:**
- Python modules not installed for cron user
- Different Python version

**Fix:**
```bash
# 1. Install in user context
pip install -r requirements.txt

# 2. In run_regular.sh, use full Python path
which python3
# /usr/bin/python3

# 3. Update script to use absolute path
sed -i 's|python3|/usr/bin/python3|g' run_regular.sh

# 4. Test cron again
bash -c "cd /home/jvsete/git/sas/ai-log-analyzer && /usr/bin/python3 scripts/regular_phase.py --dry-run"
```

---

## 🟢 Category G: Verification & Validation

### G1: How to verify installation is complete

```bash
#!/bin/bash

cat << 'EOF'
📋 V4 Installation Verification Checklist

[ ] 1. Python environment configured
[ ] 2. Dependencies installed (psycopg2, PyYAML, elasticsearch)
[ ] 3. .env file created and populated
[ ] 4. Database accessible and schema exists
[ ] 5. All migrations executed (000-003)
[ ] 6. Permissions granted to app user
[ ] 7. INIT phase completed (5,000+ rows in peak_raw_data)
[ ] 8. Thresholds calculated (60+ rows in peak_thresholds)
[ ] 9. Run scripts created and executable
[ ] 10. Cron job configured and tested
[ ] 11. Backfill completed (0+ incidents detected)
[ ] 12. Regular phase tested successfully

All checked? ✅ Ready for production
EOF
```

---

### G2: How to validate data quality

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"

psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
-- Data completeness
SELECT 
  'peak_raw_data' as table_name,
  COUNT(*) as total_rows,
  COUNT(DISTINCT namespace) as namespaces,
  COUNT(DISTINCT DATE(timestamp)) as days,
  MIN(timestamp) as data_start,
  MAX(timestamp) as data_end
FROM ailog_peak.peak_raw_data
UNION ALL
SELECT
  'peak_thresholds',
  COUNT(*),
  COUNT(DISTINCT namespace),
  COUNT(DISTINCT day_of_week),
  NULL,
  NULL
FROM ailog_peak.peak_thresholds;

-- Data quality
SELECT namespace, 
  COUNT(*) as rows,
  MIN(error_count) as min_count,
  MAX(error_count) as max_count,
  AVG(error_count)::INT as avg_count,
  STDDEV(error_count)::INT as stddev_count
FROM ailog_peak.peak_raw_data
GROUP BY namespace
ORDER BY namespace;
EOF
```

---

## 📞 When to Call Support

Contact DevOps if:

1. **Database host unreachable** - Network/firewall issue
   ```bash
   telnet P050TD01.DEV.KB.CZ 5432
   ```

2. **Elasticsearch no data** - Data ingestion pipeline issue
   ```bash
   curl http://$ES_HOST:$ES_PORT/_cat/indices
   ```

3. **Permission denied (admin)** - Database admin needed
   ```
   psycopg2.errors.InsufficientPrivilege: FATAL: password authentication failed
   ```

4. **Out of disk space** - Storage issue
   ```bash
   df -h /var
   ```

---

**Last Updated:** 2026-01-21

For questions, refer to [INSTALLATION.md](INSTALLATION.md) or [README.md](README.md)
