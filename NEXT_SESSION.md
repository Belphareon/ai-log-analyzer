# 📝 NEXT SESSION - Action Items

## ✅ Session 2 Completed (Feb 9, 2026)

### Fixed: Recent Incidents Confluence Publishing ✅
- Changed from DAILY_INCIDENT_REPORT to PROBLEM_ANALYSIS_REPORT V6
- Now shows EXECUTIVE_SUMMARY + top 20 PROBLEM_DETAILS
- Fixed HTML dark mode formatting (removed white background)
- All three Confluence pages working:
  - Known Errors ✅
  - Known Peaks ✅
  - Recent Incidents ✅

### Fixed: Teams Notifications ✅
- Fixed import path issue for core.teams_notifier
- Added fallback using importlib.util for explicit file loading
- Teams notification now sends after backfill completes
- Updated CronJob manifest with --output flag
- All commits local (push blocked by network - needs retry)

---

## 🎯 Next Session Objectives

### Issue #1: Git Push + K8s Deployment

**Status**: Commits ready, push blocked by network

**Steps**:
1. Retry git push:
   ```bash
   cd /home/jvsete/git/ai-log-analyzer
   git push origin main
   ```

2. Deploy CronJobs to K8s (docs/CRONJOB_SCHEDULING.md):
   ```bash
   # Create namespace
   kubectl create namespace ai-log-analyzer
   
   # Create ConfigMap with .env
   kubectl create configmap ai-log-analyzer-env --from-env-file=.env \
     -n ai-log-analyzer
   
   # Apply CronJob manifests
   kubectl apply -f - << 'EOF'
   # (Contents from docs/CRONJOB_SCHEDULING.md)
   EOF
   
   # Verify
   kubectl get cronjobs -n ai-log-analyzer
   ```

**Files to check**:
- docs/CRONJOB_SCHEDULING.md (has K8s manifests)

---

### Issue #2: Verify End-to-End Workflow

**Test steps**:
```bash
cd /home/jvsete/git/ai-log-analyzer

# 1. Run backfill with force
python3 scripts/backfill_v6.py --days 1 --force --output scripts/reports

# 2. Run publish
bash scripts/publish_daily_reports.sh

# 3. Check Confluence pages
# - page 1334314201 (Known Errors)
# - page 1334314203 (Known Peaks)
# - page 1334314207 (Recent Incidents with top 20 problems)

# 4. Check Teams channel (if webhook configured)
```

---

### Issue #3: Update Backfill Default Output Path (Optional)

**Current**: `--output` flag required to save problem_report files

**Suggested**: Make it default in backfill_v6.py

**File**: scripts/backfill_v6.py line ~484
```python
# Current:
output_dir = args.output if args.output else None

# Better:
output_dir = args.output or (SCRIPT_DIR / 'reports')
```

---

## 📋 Configuration Checklist

### Required Environment Variables
```bash
# Database
DB_USER=ailog_analyzer_app_user_d1
DB_PASSWORD=...
DB_DDL_USER=ailog_analyzer_ddl_user_d1
DB_DDL_PASSWORD=...
DB_HOST=...
DB_PORT=5432
DB_NAME=ailog

# Confluence
CONFLUENCE_URL=https://wiki.kb.cz
CONFLUENCE_USERNAME=...
CONFLUENCE_PASSWORD=...  # Works as API token

# Teams (optional)
TEAMS_WEBHOOK_URL=https://outlook.webhook.office.com/webhookb2/...
```

### Confluence Page IDs
```
1334314201 - Known Errors
1334314203 - Known Peaks
1334314207 - Recent Incidents (FIXED ✅)
```

---

## 🔄 Files Modified This Session

```
Modified:
  scripts/recent_incidents_publisher.py (FIXED - now uses PROBLEM_ANALYSIS_REPORT V6)
  scripts/publish_daily_reports.sh (UPDATED - calls new publisher)

Created:
  scripts/backfill_report_publisher.py (archived, not used)
  scripts/recent_incidents_exporter.py (archived, not used)

Registry:
  registry/fingerprint_index.yaml
  registry/known_peaks.yaml
  registry/known_problems.yaml
  exports/latest/*.csv, *.md
```

---

## 🎯 Success Criteria

- [ ] git push successful
- [ ] E2E workflow tested (backfill → publish → Confluence updated)
- [ ] K8s CronJobs deployed
- [ ] All three Confluence pages auto-update daily
- [ ] Teams notifications working (if enabled)
- [ ] Problem Analysis report top 20 shows in Recent Incidents page

**Decision Point:**
- If fixed: Test with `--days 4 --workers 4` and verify all notifications sent
- If not fixable: Document as known limitation, move to next issue

---

### Issue #2: Fix PeakEntry.category Bug

**Current State:**
- Error: `'PeakEntry' object has no attribute 'category'`
- Location: `scripts/exports/table_exporter.py`
- Impact: Export feature broken (non-critical)

**Investigation Steps:**

1. **Find where error occurs:**
   ```bash
   grep -n "PeakEntry" scripts/exports/table_exporter.py | head -20
   grep -n "\.category" scripts/exports/table_exporter.py | head -20
   ```

2. **Locate PeakEntry definition:**
   ```bash
   grep -r "class PeakEntry" ai-log-analyzer/
   grep -r "PeakEntry =" ai-log-analyzer/
   ```
   - Look in: `core/`, `incident_analysis/`, `registry/`

3. **Understand the issue:**
   - Is PeakEntry a dataclass? What fields does it have?
   - Should it have a 'category' field?
   - Or is table_exporter.py using wrong field name?

4. **Fix approach:**
   
   **Option A: Add category field to PeakEntry**
   ```python
   @dataclass
   class PeakEntry:
       # ... existing fields ...
       category: str = ""  # Add this field
   ```

   **Option B: Change table_exporter.py to not use category**
   ```python
   # Before:
   row['category'] = entry.category
   
   # After (use different field or skip):
   # row['category'] = entry.peak_type  # if this field exists
   # OR skip entirely
   ```

5. **Test solution:**
   ```bash
   python3 scripts/backfill_v6.py --days 1 --workers 1
   # Export should complete without errors
   ```

**Success Criteria:**
- [ ] No AttributeError on PeakEntry.category
- [ ] CSV/JSON/Markdown files generated successfully
- [ ] Export report contains peak data

---

### Issue #3: Test regular_phase_v6.py in K8s

**Current State:**
- Code has Teams integration added
- Never tested in production K8s cluster
- CronJob manifest ready to deploy

**Testing Steps:**

1. **Deploy to K8s:**
   ```bash
   cd sas/k8s-infra-apps-nprod
   helm upgrade --install ai-log-analyzer infra-apps/ai-log-analyzer/ --values values.yaml
   ```

2. **Verify deployment:**
   ```bash
   kubectl get cronjob ai-log-analyzer-regular -n ai-log-analyzer
   kubectl get pod -n ai-log-analyzer | grep ai-log-analyzer
   ```

3. **Check environment variables:**
   ```bash
   kubectl get cronjob ai-log-analyzer-regular -n ai-log-analyzer -o yaml | grep -A20 "env:"
   # Should see: TEAMS_WEBHOOK_URL, DB_HOST, ES_HOST, etc.
   ```

4. **Monitor first run:**
   ```bash
   # Trigger manual job run
   kubectl create job --from=cronjob/ai-log-analyzer-regular \
     ai-log-analyzer-test -n ai-log-analyzer
   
   # Watch logs
   kubectl logs -f job/ai-log-analyzer-test -n ai-log-analyzer
   ```

5. **Verify database:**
   ```bash
   psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
     "SELECT COUNT(*) FROM incidents WHERE occurred_at > NOW() - INTERVAL '1 hour';"
   ```

6. **Check Teams notifications:**
   - Verify message appears in Teams channel
   - Check message format and content

**Success Criteria:**
- [ ] CronJob deployed successfully
- [ ] Job executes on schedule (every 15 minutes)
- [ ] New incidents detected and saved to DB
- [ ] Teams notifications sent
- [ ] No errors in logs

---

## 🔍 Diagnostic Commands (Keep for Reference)

```bash
# Quick status check
cd /home/jvsete/git/ai-log-analyzer

# Check processes
ps aux | grep -E "python3|backfill|regular_phase"

# Check recent logs
tail -100 scripts/reports/report_*.md

# Check registry
wc -l registry/*.yaml
head -5 registry/problem_registry.yaml

# Database quick check
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \
  "SELECT COUNT(*) FROM incidents WHERE occurred_at > NOW() - INTERVAL '1 day';"

# Check if all workers ran (4-day backfill)
ls -lt /tmp/backfill_worker_*.log | head -4
```

---

## 📊 Decision Matrix

**If Teams Fix Works:**
→ Test with 4-day backfill
→ Verify all 4 notifications sent correctly
→ Deploy to K8s
→ Mark as ✅ READY

**If Teams Fix Doesn't Work:**
→ Disable Teams notifications (graceful fallback)
→ Document as known limitation
→ Create JIRA ticket for future investigation
→ Core functionality still works (DB saving)

**If PeakEntry Fix Works:**
→ Test export with regular phase
→ Verify CSV/JSON/Markdown files generated
→ Include in K8s deployment

**If PeakEntry Fix Doesn't Work:**
→ Mark export as broken feature
→ Document workaround (manual export if needed)
→ Note for future refactoring

---

## 📋 Deployment Checklist

After all fixes:

- [ ] Teams import working (or gracefully disabled)
- [ ] PeakEntry bug fixed (or documented as limitation)
- [ ] 4-day backfill test passed
- [ ] Regular phase tested locally
- [ ] K8s CronJob deployed
- [ ] First 3 K8s runs monitored successfully
- [ ] Database shows recent incidents
- [ ] Teams channel shows notifications
- [ ] All .md files updated with latest status

---

## 🎬 Quick Start (Next Session)

```bash
# 1. Review status
cat /home/jvsete/git/ai-log-analyzer/STATUS.md

# 2. Check what changed
cd /home/jvsete/git/ai-log-analyzer
git diff HEAD~5

# 3. Review issues
grep -r "TODO\|FIXME\|BUG" scripts/ core/ | head -20

# 4. Run quick test
python3 scripts/backfill_v6.py --days 1 --workers 1 --force

# 5. Check output
tail -50 scripts/reports/report_*.md
```

---

## 📞 Questions for Next Session

1. Should Teams notifications be enabled (Option A) or gracefully disabled (Option C)?
2. Is PeakEntry.category a real field that should be added, or is the export code wrong?
3. What's the priority for K8s deployment after fixes?
4. Should we set up automated testing for future changes?

---

**Created:** February 2026 - End of session
**For:** Next session continuation
**Status:** All information current as of last test
