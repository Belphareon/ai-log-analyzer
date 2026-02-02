# 🧪 Testing Guide - AI Log Analyzer v6

## Quick Reference

| Test | Command | Expected | Status |
|------|---------|----------|--------|
| DB Connection | `python3 -c "import psycopg2; psycopg2.connect(...)"` | No error | ✅ |
| Backfill 1-day | `python3 scripts/backfill_v6.py --days 1 --workers 1` | 50K+ incidents | ✅ |
| Backfill 4-day | `python3 scripts/backfill_v6.py --days 4 --workers 4` | 200K+ incidents | ✅ |
| Regular phase | `python3 scripts/regular_phase_v6.py --history 15m` | Report generated | ⚠️ Untested |
| Export | `python3 scripts/exports/table_exporter.py` | CSV/JSON files | ❌ Broken |
| Teams webhook | Check backfill output | Notification sent | ❌ Import fails |

---

## Test 1: Database Connection

**Verify PostgreSQL is accessible:**

```bash
# Option A: Direct psql
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT VERSION();"

# Option B: Python test
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
print("✅ Database connection successful")
conn.close()
EOF
```

**Expected Result:**
```
✅ Database connection successful
```

**If fails:**
- Check .env file: `cat ai-log-analyzer/.env | grep DB_`
- Verify network: `ping $DB_HOST`
- Verify user has read/write privileges

---

## Test 2: Elasticsearch Connection

**Verify Elasticsearch is accessible:**

```bash
# Test ES connection
python3 << 'EOF'
from core.fetch_unlimited import fetch_all_errors
import os
from datetime import datetime, timedelta, timezone

# Fetch last hour
end_time = datetime.now(timezone.utc)
start_time = end_time - timedelta(hours=1)

count = 0
for batch in fetch_all_errors(start_time, end_time, limit=100):
    count += len(batch)
    if count >= 100:
        break

print(f"✅ Fetched {count} incidents from ES")
EOF
```

**Expected Result:**
```
✅ Fetched 100+ incidents from ES
```

**If fails:**
- Check .env: `cat ai-log-analyzer/.env | grep ES_`
- Verify Elasticsearch is running
- Check credentials in configuration

---

## Test 3: Backfill Pipeline (Full)

### Test 3A: 1-Day Backfill (Quick)

```bash
cd /home/jvsete/git/ai-log-analyzer

python3 scripts/backfill_v6.py --days 1 --workers 1 --force

# Expected: ~50-60K incidents
```

**What it tests:**
- ✅ Phase A: Elasticsearch fetch
- ✅ Phase B: Incident pipeline processing
- ✅ Phase C: Database storage
- ⚠️ Phase D: Export (may fail with PeakEntry.category)
- ✅ Phase E: Report generation
- ✅ Phase F: Registry update

**Expected Output:**
```
[backfill_v6.py] Starting backfill for 1 day(s) with 1 worker(s)
[backfill_v6.py] Processed day 1 of 1
[backfill_v6.py] Total fetched: 58,692
[backfill_v6.py] Total saved: 58,692
[backfill_v6.py] Registry: 299 problems (0 new), 65 peaks (0 new)
[backfill_v6.py] ✅ Backfill completed successfully
⚠️ Teams notification failed: No module named 'core.teams_notifier'
```

**Success Criteria:**
- [ ] "Total saved" > 0
- [ ] Registry updated (0 new is OK)
- [ ] Report file created: `scripts/reports/report_*.md`

---

### Test 3B: 4-Day Backfill (Full Validation)

```bash
python3 scripts/backfill_v6.py --days 4 --workers 4

# Expected: ~220-250K incidents
# Duration: ~5-10 minutes on typical server
```

**Success Criteria (from last run):**
```
✅ Total saved: 236,419
✅ Registry: 299 problems, 65 peaks
✅ Report generated
✅ All 4 days processed
```

**If different:**
- Check if ES has new data
- Verify all 4 workers executed: `ps aux | grep backfill_v6`
- Check error log at end

---

## Test 4: Database Verification

**Verify incidents were actually saved:**

```bash
# Check incident count
psql -h $DB_HOST -U $DB_USER -d $DB_NAME << 'EOF'
SELECT 
  COUNT(*) as total_incidents,
  COUNT(DISTINCT DATE(occurred_at)) as unique_days,
  MIN(occurred_at) as oldest,
  MAX(occurred_at) as newest
FROM incidents;
EOF
```

**Expected Output:**
```
 total_incidents | unique_days | oldest | newest
-----------------+-------------+--------+--------
      236419     |      4      | ...    | ...
```

**Verification Queries:**

```sql
-- Check recent incidents
SELECT COUNT(*) FROM incidents 
WHERE occurred_at > NOW() - INTERVAL '4 days'
LIMIT 5;

-- Check data distribution
SELECT 
  DATE(occurred_at), 
  COUNT(*) 
FROM incidents 
GROUP BY DATE(occurred_at)
ORDER BY DATE(occurred_at) DESC;

-- Check registry
SELECT COUNT(*) FROM problem_registry;
SELECT COUNT(*) FROM peak_registry;
```

---

## Test 5: Registry System

**Verify registry updates correctly:**

```bash
# Check registry files
ls -lah registry/

# Expected files:
# - problem_registry.yaml
# - peak_registry.yaml  
# - problem_registry.md
# - peak_registry.md

# Check YAML structure
head -20 registry/problem_registry.yaml
```

**Expected Output:**
```yaml
problems:
  - problem_key: CATEGORY:flow:error
    first_seen: 2026-02-01T10:00:00Z
    last_seen: 2026-02-05T14:30:00Z
    occurrences: 1024
    scope: BUSINESS
    root_cause: "Connection timeout"
    ...
```

---

## Test 6: Regular Phase (Local)

**Test 15-minute processing cycle:**

```bash
python3 scripts/regular_phase_v6.py --history 15m

# Expected: Analysis + Report
# Duration: ~1-2 minutes
```

**Expected Output:**
```
[regular_phase_v6.py] Starting regular phase...
[regular_phase_v6.py] Fetched 500-1000 incidents from last 15 minutes
[regular_phase_v6.py] Detected X new incidents
[regular_phase_v6.py] Updated registry
[regular_phase_v6.py] ✅ Regular phase completed
✅ Report generated: scripts/reports/report_TIMESTAMP.md
```

**Check Report:**
```bash
cat scripts/reports/report_*.md | head -50
```

---

## Test 7: K8s Deployment Verification

**After deploying to K8s:**

```bash
# 1. Check CronJob is configured
kubectl get cronjob ai-log-analyzer-regular -n ai-log-analyzer

# 2. Check next run time
kubectl get cronjob ai-log-analyzer-regular -n ai-log-analyzer -o wide

# 3. Monitor job execution
kubectl logs -f job/ai-log-analyzer-regular-*** -n ai-log-analyzer

# 4. Verify environment variables
kubectl get cronjob ai-log-analyzer-regular -n ai-log-analyzer -o yaml | grep -A10 env:

# 5. Check database for recent incidents
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
  "SELECT COUNT(*) FROM incidents WHERE occurred_at > NOW() - INTERVAL '1 hour';"
```

---

## Test 8: Teams Webhook (When Fixed)

**After fixing Teams notifications:**

```bash
# 1. Verify webhook URL is set
echo $TEAMS_WEBHOOK_URL

# 2. Manual webhook test
curl -X POST $TEAMS_WEBHOOK_URL \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Test message from AI Log Analyzer",
    "title": "Connection test",
    "@type": "MessageCard",
    "@context": "https://schema.org/extensions"
  }'

# Expected: HTTP 200 OK

# 3. Run backfill and check Teams channel
python3 scripts/backfill_v6.py --days 1 --workers 1
# Check Teams for notification in channel
```

---

## Troubleshooting Matrix

### Issue: "No module named 'psycopg2'"
```bash
# Solution:
apt-get install python3-psycopg2
# OR
pip install psycopg2-binary
```

### Issue: "PeakEntry has no attribute 'category'"
```bash
# This is expected with current code
# Workaround: Ignore export errors, core DB storage still works
# TODO: Fix PeakEntry dataclass in incident_analysis/models.py
```

### Issue: "Teams notification failed: No module named 'core.teams_notifier'"
```bash
# This is expected with current code
# Workaround: Backfill still saves to DB, just no notification
# TODO: Fix sys.path in main() or move import to module level
```

### Issue: "No such table: incidents"
```bash
# Solution: Run initialization script
python3 scripts/backfill_v6.py --init
# This creates tables automatically on first run
```

### Issue: "Connection refused" (Elasticsearch)
```bash
# Check ES is running:
curl -u $ES_USER:$ES_PASSWORD $ES_HOST/_cluster/health
# Check .env ES_ variables
```

---

## Performance Benchmarks

**Expected Performance (from last session):**

| Test | Data Size | Duration | Throughput |
|------|-----------|----------|-----------|
| 1-day backfill (1 worker) | 58,692 incidents | ~1-2 min | 500-1000 inc/sec |
| 4-day backfill (4 workers) | 236,419 incidents | ~5-10 min | 400-800 inc/sec |
| Regular phase (15m window) | 500-2000 incidents | ~30-60 sec | 500-2000 inc/sec |

---

## Debug Commands

**Enable verbose logging:**

```bash
# Set debug environment variable
export DEBUG=1
python3 scripts/backfill_v6.py --days 1 --workers 1

# Or modify log level in scripts temporarily
# Change: logging.basicConfig(level=logging.INFO)
# To: logging.basicConfig(level=logging.DEBUG)
```

**Check database state after backfill:**

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME << 'EOF'
-- Last inserted incidents
SELECT occurred_at, message, root_cause 
FROM incidents 
ORDER BY occurred_at DESC 
LIMIT 10;

-- Problem registry changes
SELECT problem_key, occurrences, last_seen 
FROM problem_registry 
ORDER BY last_seen DESC 
LIMIT 10;
EOF
```

---

## Test Checklist (Before Deployment)

- [ ] Test 1: Database connection working
- [ ] Test 2: Elasticsearch connection working
- [ ] Test 3A: 1-day backfill completes successfully
- [ ] Test 3B: 4-day backfill completes successfully
- [ ] Test 4: Database has incidents
- [ ] Test 5: Registry files updated
- [ ] Test 6: Regular phase produces reports
- [ ] (After fix) Test 7: K8s deployment verified
- [ ] (After fix) Test 8: Teams webhook sends message

---

**Last Updated:** February 2026 - Session Documentation
**Status:** Ready for testing in next session
