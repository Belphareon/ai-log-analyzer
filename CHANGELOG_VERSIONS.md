# AI Log Analyzer - Version Changelog

## r45 (March 6, 2026) - Email Template Redesign
**Status:** Built & Pushed

- **Email Template Redesign**
  - New cleaner header format: `ERROR_CLASS | Status: STATUS | Trend: TREND_ICON`
  - Consolidated Summary section with: This window errors, Previous window avg + %, Peak ID
  - Removed duplicated status and peak key fields from body
  - Reordered sections: Summary → Error Details → Affected Scope → Root Cause → Behavior → Propagation
  - No trend duplication (trend now only in header)
  - Improved visual hierarchy and spacing
  
**Files Modified:**
- `scripts/core/email_notifier.py` - Email template restructuring
- `core/email_notifier.py` - Synced with scripts/core/

**Related Fixes from r44:**
- Fixed `is_continues` logic to check: `last_seen < window_start AND last_seen >= (window_start - 15min)`
  - Ensures peak marked "continued" only if seen in PREVIOUS window, not current
  - Previous bug: NEW peaks detected now had `last_seen=NOW`, incorrectly matching continue condition
- Fixed `peak_window_start` to use `window_start` instead of `first_seen`
- Removed UTC time from email notifications (CET only)
- Split trend into `trend_2h` and `trend_24h` columns in table exports

---

## r44 (March 2-5, 2026) - Peak Continuation & Time Window Fixes
**Status:** Built & Deployed

**Critical Fixes:**
1. **Time Window Calculation** (regular_phase.py:304)
   - Changed: `peak_window_start = _floor_to_window(known_peak.first_seen)`
   - To: `peak_window_start = window_start`
   - Impact: Peak time ranges now correctly show current detection window, not historical first-seen

2. **Peak Continuation Detection Logic** (regular_phase.py:298-305)
   - Changed: `is_continues = last_seen >= window_start - 15min`
   - To: `is_continues = (last_seen < window_start) AND (last_seen >= window_start - 15min)`
   - Impact: Only peaks seen in PREVIOUS window are marked "continued", NEW peaks no longer mislabeled
   - Fixed bug where all NEW peaks were marked as "KNOWN (continued)"

3. **Email Notification Updates** (email_notifier.py:339)
   - Removed UTC time display, kept CET only
   - Added comment marking UTC removal

4. **Trend Column Split** (table_exporter.py)
   - Split single `trend` field into `trend_2h` and `trend_24h`
   - Updated ErrorTableRow definition (lines 75-78)
   - Updated CSV export fieldnames (line 322)

**K8s Manifests:**
- Fixed job-init.yaml job naming: Changed from `generateName` to `name` with image version hash
  - Reason: `generateName` doesn't work with `kubectl apply`, only `kubectl create`
  - This approach creates unique job per image version, avoiding immutable spec.template error

**Commits:**
- `651a9b6` - r43: exported peaks with root-cause+behavior and dual-window trend
- Previous r44 changes committed and built as Docker r44

---

## r43 (Nov 13-14, 2025) - Known Peaks Export & Root Cause
**Status:** Previous stable release

- Clean exports of known peaks/errors
- Added root-cause and behavior tracking
- Dual-window trend analysis
- Known peaks wiki integration

---

## r42 Series (Oct-Nov 2025)
### r42c - 4th Wave Category Mapping
- Targeted category mapping for unknown top signatures

### r42b - Trace Quality Improvements  
- Tuned trace root-cause and behavior step detection

### r42 - CET Notifications & Continuation
- CET timezone notifications  
- Continuation summary in alerts
- Peak key alignment
- 3-wave unknown error reduction

---

## r41 (Earlier) - Baseline Work
- Various baseline adjustments and refinements

---

## r40 (Earlier) - Core Detection
- P93/CAP peak detection implementation
- Backfill and registry foundation

---

## Key Features by Version

| Feature | r45 | r44 | r43+ |
|---------|-----|-----|------|
| Email template redesign | ✅ | - | - |
| Fixed peak continuation logic | ✅ | ✅ | - |
| Fixed time window calculation | ✅ | ✅ | - |
| Trend 2h + 24h split | ✅ | ✅ | - |
| CET notifications | ✅ | ✅ | ✅ |
| Root cause tracking | ✅ | ✅ | ✅ |
| P93/CAP detection | ✅ | ✅ | ✅ |
| Wiki integration | ✅ | ✅ | ✅ |

---

## Deployment Notes

### r45 Deployment Checklist
- [ ] Docker image `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r45` built and pushed
- [ ] Update K8s values.yaml image version from r44 to r45
- [ ] Verify regular phase alert emails display new template
- [ ] Check email headers show format: `ERROR_CLASS | Status | Trend`
- [ ] Confirm Peak ID only shows for known peaks
- [ ] Validate root cause sections appear prominently

### Breaking Changes
- None (backward compatible)

### Migration from r44 to r45
- No database schema changes
- No new dependencies
- Email template layout changes are visual only
- Full backward compatibility maintained
