# 📝 NEXT SESSION - Action Items

## 🎯 Primary Objectives

### Issue #1: Fix Teams Notification Import ⚠️ BLOCKING

**Current State:**
- Module exists: `core/teams_notifier.py`
- Integration code present: `backfill_v6.py` line 45 and main()
- Error: `ModuleNotFoundError: No module named 'core.teams_notifier'`
- sys.path fallback attempted in main() but not working

**Investigation Steps:**

1. **Check current implementation:**
   ```bash
   cd /home/jvsete/git/ai-log-analyzer
   grep -n "from core.teams_notifier" scripts/backfill_v6.py
   grep -n "get_notifier" scripts/backfill_v6.py
   ```

2. **Understand the problem:**
   - Is the import at line 45 being reached?
   - Is sys.path manipulation working?
   - Check if sys.path fallback is catching the exception

3. **Try these solutions (in order):**

   **Option A: Move import to module level**
   ```python
   # Current (BROKEN in main):
   def main():
       sys.path.insert(0, '/app')
       from core.teams_notifier import get_notifier
   
   # Try this (module level):
   try:
       from core.teams_notifier import get_notifier
   except ImportError:
       get_notifier = lambda: None
   ```

   **Option B: Use absolute import**
   ```python
   import sys
   import os
   sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')
   from core.teams_notifier import get_notifier
   ```

   **Option C: Use direct path import**
   ```python
   import importlib.util
   spec = importlib.util.spec_from_file_location("teams_notifier", 
       "/app/core/teams_notifier.py")
   teams_notifier = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(teams_notifier)
   get_notifier = teams_notifier.get_notifier
   ```

4. **Test solution:**
   ```bash
   python3 scripts/backfill_v6.py --days 1 --workers 1 --force
   # Look for: ✅ Backfill completed + Teams notification confirmed
   ```

5. **If all fail - disable Teams for now:**
   ```python
   # Wrap the get_notifier call in try/except with graceful fallback
   notifier = None
   try:
       from core.teams_notifier import get_notifier
       notifier = get_notifier()
   except Exception as e:
       print(f"⚠️ Teams notifier not available: {e}")
   
   # In main code:
   if notifier:
       notifier.send_backfill_completed(...)
   ```

**Success Criteria:**
- [ ] Backfill runs without ModuleNotFoundError
- [ ] Teams message appears in channel after backfill completes
- [ ] Backfill still saves to DB (with or without Teams)

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
