# 🔧 V4 Installation - Step-by-Step Execution Checklist

**Purpose:** Jednotlivé příkazy ke spuštění v přesném pořadí  
**Status:** Ready for execution  
**Updated:** 2026-01-21

---

## PHASE 1: Environment & Configuration (10 min)

### Step 1.1: Create .env File

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
cp config/.env.example .env
echo "✅ .env created"
```

### Step 1.2: Verify Config Files Exist

```bash
ls -la config/namespaces.yaml
ls -la .env
echo "✅ Config files exist"
```

### Step 1.3: Create Log Directory

```bash
mkdir -p /var/log/ailog/
chmod 755 /var/log/ailog/
echo "✅ Log directory created"
```

---

## PHASE 2: Database Setup (15 min)

### Step 2.1: Verify DB Connectivity

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer -c "SELECT 1 as connectivity_ok;"
echo "✅ Database connectivity verified"
```

### Step 2.2: Create Schema

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;
CREATE SCHEMA IF NOT EXISTS ailog_peak;
GRANT ALL PRIVILEGES ON SCHEMA ailog_peak TO role_ailog_analyzer_ddl;
GRANT USAGE ON SCHEMA ailog_peak TO role_ailog_analyzer_app;
EOF
echo "✅ Schema created"
```

### Step 2.3: Run Migration 000 - Base Tables

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/000_create_base_tables.sql
echo "✅ Migration 000 complete"
```

### Step 2.4: Run Migration 001 - Peak Thresholds

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/001_create_peak_thresholds.sql
echo "✅ Migration 001 complete"
```

### Step 2.5: Run Migration 002 - Enhanced Analysis Tables

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/002_create_enhanced_analysis_tables.sql
echo "✅ Migration 002 complete"
```

### Step 2.6: Run Migration 003 - V4 Upgrade

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer \
  -f scripts/migrations/upgrade_v3_to_v4.sql
echo "✅ Migration 003 (V4 upgrade) complete"
```

### Step 2.7: Verify All Tables Created

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
\dt ailog_peak.*;
EOF
echo "✅ All tables verified"
```

---

## PHASE 3: Permissions Setup (10 min)

### Step 3.1: Grant Table Permissions

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOF'
SET ROLE role_ailog_analyzer_ddl;

-- Default permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;

-- Explicit table permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_raw_data TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_investigation TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_thresholds TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_threshold_caps TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.aggregation_data TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.known_issues TO ailog_analyzer_user_d1;

-- Sequence permissions
GRANT USAGE ON SEQUENCE ailog_peak.peak_raw_data_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_investigation_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_thresholds_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.peak_threshold_caps_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.aggregation_data_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE ON SEQUENCE ailog_peak.known_issues_id_seq TO ailog_analyzer_user_d1;
EOF
echo "✅ Permissions granted"
```

### Step 3.2: Verify Permissions

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
INSERT INTO ailog_peak.peak_raw_data (timestamp, namespace, error_count, day_of_week, hour_of_day, quarter_hour)
VALUES (NOW(), 'test-ns', 1, 3, 12, 0);

DELETE FROM ailog_peak.peak_raw_data WHERE namespace = 'test-ns';
EOF
echo "✅ Permissions verified - INSERT works"
```

---

## PHASE 4: Python Environment (5 min)

### Step 4.1: Install Dependencies

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
pip install -r requirements.txt
echo "✅ Python dependencies installed"
```

### Step 4.2: Verify Imports

```bash
python3 << 'EOF'
import psycopg2
import yaml
print("✅ All imports OK")
EOF
```

---

## PHASE 5: Initial Data Collection - INIT (30-60 min)

### Step 5.1: Run INIT Phase (12 days)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/init_phase.py --days 12
echo "✅ INIT phase complete"
```

### Step 5.2: Verify Data Collected

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as total_rows FROM ailog_peak.peak_raw_data;
SELECT COUNT(DISTINCT namespace) as namespaces FROM ailog_peak.peak_raw_data;
SELECT COUNT(DISTINCT DATE(timestamp)) as days_collected FROM ailog_peak.peak_raw_data;
SELECT namespace, COUNT(*) as row_count FROM ailog_peak.peak_raw_data GROUP BY namespace ORDER BY namespace;
EOF
echo "✅ Data collection verified"
```

---

## PHASE 6: Threshold Calculation (10 min)

### Step 6.1: Calculate P93 Thresholds

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/core/calculate_peak_thresholds.py
echo "✅ Threshold calculation complete"
```

### Step 6.2: Verify Thresholds Stored

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as threshold_rows FROM ailog_peak.peak_thresholds;
SELECT COUNT(*) as cap_rows FROM ailog_peak.peak_threshold_caps;

-- Show sample thresholds per namespace
SELECT namespace, COUNT(*) as threshold_count
FROM ailog_peak.peak_thresholds
GROUP BY namespace
ORDER BY namespace;

-- Show CAP values
SELECT namespace, cap_value FROM ailog_peak.peak_threshold_caps ORDER BY namespace;
EOF
echo "✅ Thresholds verified"
```

---

## PHASE 7: Run Scripts Setup (5 min)

### Step 7.1: Create run_init.sh

```bash
cat > /home/jvsete/git/sas/ai-log-analyzer/run_init.sh << 'EOF'
#!/bin/bash
set -e
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/init_phase.py "$@"
EOF
chmod +x /home/jvsete/git/sas/ai-log-analyzer/run_init.sh
echo "✅ run_init.sh created"
```

### Step 7.2: Create run_regular.sh

```bash
cat > /home/jvsete/git/sas/ai-log-analyzer/run_regular.sh << 'EOF'
#!/bin/bash
set -e
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/regular_phase.py --from "$(date -d '30 minutes ago' -u +%Y-%m-%dT%H:%M:%SZ)" \
  --to "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$@"
EOF
chmod +x /home/jvsete/git/sas/ai-log-analyzer/run_regular.sh
echo "✅ run_regular.sh created"
```

### Step 7.3: Create run_backfill.sh

```bash
cat > /home/jvsete/git/sas/ai-log-analyzer/run_backfill.sh << 'EOF'
#!/bin/bash
set -e
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/backfill.py "$@"
EOF
chmod +x /home/jvsete/git/sas/ai-log-analyzer/run_backfill.sh
echo "✅ run_backfill.sh created"
```

### Step 7.4: Verify Run Scripts

```bash
ls -la /home/jvsete/git/sas/ai-log-analyzer/run_*.sh
echo "✅ All run scripts exist and are executable"
```

---

## PHASE 8: Backfill (Optional but Recommended - 30-60 min)

### Step 8.1: Run Backfill Phase (14 days)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/backfill.py --days 14
echo "✅ Backfill phase complete"
```

### Step 8.2: Verify Incidents Detected

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as incident_rows FROM ailog_peak.peak_investigation;
SELECT COUNT(*) as with_flags FROM ailog_peak.peak_investigation 
  WHERE is_spike OR is_burst OR is_new OR is_cross_namespace OR is_regression OR is_cascade;

-- Show sample incidents
SELECT timestamp, namespace, actual_value, severity, status, is_spike, is_burst
FROM ailog_peak.peak_investigation
WHERE actual_value IS NOT NULL
LIMIT 20;
EOF
echo "✅ Incidents verified"
```

---

## PHASE 9: Cron Setup (5 min)

### Step 9.1: Add Cron Job

```bash
# Add to crontab
(crontab -l 2>/dev/null | grep -v "ai-log-analyzer" || true; \
echo "*/15 * * * * cd /home/jvsete/git/sas/ai-log-analyzer && ./run_regular.sh >> /var/log/ailog/cron.log 2>&1") | crontab -
echo "✅ Cron job added"
```

### Step 9.2: Verify Cron Job

```bash
crontab -l | grep ai-log-analyzer
echo "✅ Cron job verified"
```

---

## PHASE 10: Final Verification (10 min)

### Step 10.1: Full System Status Check

```bash
cat << 'EOFCHECK'
🔍 V4 System Status Check
===========================

echo "1. Python Environment:"
python3 --version
python3 -c "import psycopg2; print('✅ psycopg2')"
python3 -c "import yaml; print('✅ PyYAML')"

echo ""
echo "2. Configuration Files:"
[ -f ".env" ] && echo "✅ .env" || echo "❌ .env"
[ -f "config/namespaces.yaml" ] && echo "✅ namespaces.yaml" || echo "❌ namespaces.yaml"

echo ""
echo "3. Database Tables:"
export PGPASSWORD="WWvkHhyjje8YSgvU"
TABLES=$(psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -t -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ailog_peak'")
echo "✅ Database tables: $TABLES"

echo ""
echo "4. Data Status:"
INIT_ROWS=$(psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -t -c \
  "SELECT COUNT(*) FROM ailog_peak.peak_raw_data")
THRESHOLD_ROWS=$(psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer -t -c \
  "SELECT COUNT(*) FROM ailog_peak.peak_thresholds")
echo "✅ INIT data rows: $INIT_ROWS"
echo "✅ Threshold rows: $THRESHOLD_ROWS"

echo ""
echo "5. Run Scripts:"
[ -x "run_init.sh" ] && echo "✅ run_init.sh" || echo "❌ run_init.sh"
[ -x "run_regular.sh" ] && echo "✅ run_regular.sh" || echo "❌ run_regular.sh"
[ -x "run_backfill.sh" ] && echo "✅ run_backfill.sh" || echo "❌ run_backfill.sh"

echo ""
echo "6. Cron Job:"
crontab -l | grep -q "ai-log-analyzer" && echo "✅ Cron job configured" || echo "❌ Cron job"

echo ""
echo "✅ Full system verification complete!"
EOFCHECK
```

---

## PHASE 11: Test Regular Phase (10 min)

### Step 11.1: Run Regular Phase Dry-Run

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
./run_regular.sh --dry-run
echo "✅ Regular phase dry-run successful"
```

### Step 11.2: Run Regular Phase (Actual)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
./run_regular.sh
echo "✅ Regular phase completed"
```

### Step 11.3: Check New Incidents

```bash
export PGPASSWORD="WWvkHhyjje8YSgvU"
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_user_d1 -d ailog_analyzer << 'EOF'
SELECT COUNT(*) as recent_incidents FROM ailog_peak.peak_investigation
WHERE created_at > NOW() - INTERVAL '1 hour';

SELECT timestamp, namespace, actual_value, severity
FROM ailog_peak.peak_investigation
WHERE created_at > NOW() - INTERVAL '1 hour'
LIMIT 10;
EOF
echo "✅ Incidents verified"
```

---

## 🎯 Quick Reference - All Commands in One Script

Save this as `install_v4_full.sh`:

```bash
#!/bin/bash
set -e

cd /home/jvsete/git/sas/ai-log-analyzer
export PGPASSWORD="WWvkHhyjje8YSgvU"

echo "📦 V4 Full Installation Script"
echo "=============================="

# PHASE 1: Config
echo "PHASE 1: Configuration..."
mkdir -p /var/log/ailog/
echo "✅ Phase 1 done"

# PHASE 2: Database
echo ""
echo "PHASE 2: Database..."
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer -f scripts/migrations/000_create_base_tables.sql
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer -f scripts/migrations/001_create_peak_thresholds.sql
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer -f scripts/migrations/002_create_enhanced_analysis_tables.sql
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer -f scripts/migrations/upgrade_v3_to_v4.sql
echo "✅ Phase 2 done"

# PHASE 3: Permissions
echo ""
echo "PHASE 3: Permissions..."
psql -h P050TD01.DEV.KB.CZ -p 5432 -U ailog_analyzer_ddl_user_d1 -d ailog_analyzer << 'EOFPERM'
SET ROLE role_ailog_analyzer_ddl;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;
EOFPERM
echo "✅ Phase 3 done"

# PHASE 4: Python
echo ""
echo "PHASE 4: Python Environment..."
pip install -r requirements.txt
echo "✅ Phase 4 done"

# PHASE 5: INIT
echo ""
echo "PHASE 5: Initial Data Collection..."
python3 scripts/init_phase.py --days 12
echo "✅ Phase 5 done"

# PHASE 6: Thresholds
echo ""
echo "PHASE 6: Threshold Calculation..."
python3 scripts/core/calculate_peak_thresholds.py
echo "✅ Phase 6 done"

# PHASE 7: Run Scripts
echo ""
echo "PHASE 7: Run Scripts..."
chmod +x run_init.sh run_regular.sh run_backfill.sh
echo "✅ Phase 7 done"

# PHASE 8: Cron
echo ""
echo "PHASE 8: Cron Setup..."
(crontab -l 2>/dev/null | grep -v "ai-log-analyzer" || true; \
echo "*/15 * * * * cd $(pwd) && ./run_regular.sh >> /var/log/ailog/cron.log 2>&1") | crontab -
echo "✅ Phase 8 done"

echo ""
echo "✅✅✅ V4 INSTALLATION COMPLETE ✅✅✅"
echo ""
echo "Next steps:"
echo "1. Run backfill: ./run_backfill.sh --days 14"
echo "2. Check regular phase: ./run_regular.sh --dry-run"
echo "3. Monitor logs: tail -f /var/log/ailog/cron.log"
```

---

## ⚠️ Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `permission denied for sequence` | Missing GRANT on sequence | Run Step 3.1 |
| `No data collected` | INIT phase not run | Run Step 5.1 |
| `No thresholds calculated` | Insufficient data | Run INIT first (min 7 days) |
| `Connection refused` | Wrong DB credentials | Check .env and Step 2.1 |
| `table ailog_peak.peak_raw_data does not exist` | Migrations not run | Run Step 2.3-2.6 |

---

## 📊 Completion Checklist

After completing all phases:

- [ ] .env configured
- [ ] Log directory created
- [ ] Database schema created (migrations 000-003)
- [ ] Permissions granted
- [ ] Python dependencies installed
- [ ] INIT phase completed (5,000+ rows)
- [ ] Thresholds calculated (60+ rows)
- [ ] Run scripts created and executable
- [ ] Cron job configured
- [ ] Backfill completed (optional)
- [ ] Regular phase tested
- [ ] Incidents being detected

---

**Installation time estimate: 2-3 hours total (mostly automated)**

For questions, see [INSTALLATION.md](INSTALLATION.md)
