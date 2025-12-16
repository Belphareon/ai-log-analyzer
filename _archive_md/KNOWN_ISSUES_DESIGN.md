# Known Issues Management - Design

## Overview
System to track, identify, and contextualize known/recurring errors across clusters.

---

## Storage Strategy

### Option A: Hybrid (Recommended)
- **Development/Testing:** `data/known_issues.json` (repo, version controlled)
- **Production:** PostgreSQL table `known_issues` (DB)
- **Sync:** Script to sync JSON → DB on deploy

### Option B: DB Only
- **All environments:** PostgreSQL table `known_issues`
- **Advantage:** Single source of truth, real-time updates
- **Disadvantage:** Need DB access to manage issues

### Option C: File Only (Simple)
- **All environments:** `data/known_issues.json`
- **Advantage:** Simple, version control friendly
- **Disadvantage:** Manual sync in distributed setups

**Decision:** Option A (Hybrid) - flexibility for dev, consistency for prod

---

## Data Structure

### JSON Format (for development)

```json
{
  "version": "1.0",
  "last_updated": "2025-11-18T11:30:00Z",
  "known_issues": [
    {
      "id": "ki-001",
      "pattern_fingerprint": "Card {ID} not found",
      "apps": ["bl-pcb-v1", "bl-pcb-v1-processing"],
      "namespaces": ["pcb-sit-01-app", "pcb-fat-01-app"],
      "severity": "medium",
      "status": "known",
      "first_seen": "2025-11-12",
      "last_confirmed": "2025-11-18",
      "jira_ticket": "PCB-5423",
      "description": "Card lookup service timeout or unavailable",
      "root_cause": "External card service failure",
      "solution": [
        "1. Check card service health: `systemctl status card-svc`",
        "2. Check network connectivity to card-db",
        "3. Restart service if needed",
        "4. Monitor card processing latency"
      ],
      "workaround": "Retry after 2-3 minutes, service recovers automatically",
      "impact": "Card processing delayed, users see generic error",
      "owner": "pcb-squad@kb.cz",
      "tags": ["card-lookup", "external-service", "timeout"]
    }
  ]
}
```

### DB Schema (PostgreSQL)

```sql
CREATE TABLE known_issues (
    id VARCHAR(50) PRIMARY KEY,
    pattern_fingerprint VARCHAR(500),
    apps TEXT[], -- array of app names
    namespaces TEXT[], -- array of namespaces
    severity VARCHAR(50), -- low, medium, high, critical
    status VARCHAR(50), -- known, investigating, resolved
    first_seen TIMESTAMP,
    last_confirmed TIMESTAMP,
    jira_ticket VARCHAR(50),
    description TEXT,
    root_cause TEXT,
    solution TEXT[], -- array of steps
    workaround TEXT,
    impact TEXT,
    owner VARCHAR(100),
    tags TEXT[], -- array of tags
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX idx_known_issues_status ON known_issues(status);
CREATE INDEX idx_known_issues_apps ON known_issues USING GIN(apps);
```

---

## Integration with Pipeline

### analyze_daily.py Enhancement

```python
def identify_known_issues(root_causes, known_issues_db):
    """Match detected root causes against known issues"""
    
    for cause in root_causes:
        # Match by pattern fingerprint
        known = find_matching_known_issue(cause['message'], known_issues_db)
        
        if known:
            # Append known issue info
            cause['known_issue_id'] = known['id']
            cause['jira_ticket'] = known['jira_ticket']
            cause['status'] = 'KNOWN'
            cause['recommended_action'] = known['solution']
        else:
            cause['status'] = 'NEW'
            # Flag for review
            
    return root_causes
```

### Report Integration

**Report now includes:**
- 🟢 **KNOWN Issues** (with JIRA link, solution)
- 🟡 **INVESTIGATING** (being worked on)
- 🔴 **NEW Issues** (needs investigation)

**Example report output:**
```
## Known Issues (1)

🟢 KI-001: Card Lookup Timeout (bl-pcb-v1)
   Status: KNOWN
   JIRA: PCB-5423
   Seen: 42 times today
   Solution: Restart card service, check network
   Owner: pcb-squad@kb.cz
```

---

## Management Workflow

### Adding New Known Issue

1. **Operator detects recurring error in report**
2. **Creates JIRA ticket** (e.g., PCB-5423)
3. **Updates `known_issues.json`:**
   ```bash
   # Add entry with pattern, severity, JIRA ticket, solution
   vi data/known_issues.json
   ```
4. **Tests against historical data:**
   ```bash
   python3 scripts/validate_known_issues.py
   ```
5. **Commits and deploys**
6. **Next analysis automatically recognizes** it

### Updating Status

```bash
# Mark as resolved
python3 scripts/update_known_issue.py ki-001 --status resolved --jira-close

# Mark as investigating
python3 scripts/update_known_issue.py ki-001 --status investigating
```

### Review & Cleanup

**Weekly:**
- Review RESOLVED issues (move to archive)
- Update LAST_CONFIRMED for still-occurring issues
- Add new INVESTIGATING cases

---

## Pattern Matching Strategy

### Exact Match
```python
if cause['message'] == known['pattern_fingerprint']:
    match = True
```

### Fuzzy Match (for variations)
```python
# Already normalized/fingerprinted in trace_extractor.py
# E.g., "Card 12345 not found" → "Card {ID} not found"
# E.g., "Timeout after 30000ms" → "Timeout after {N}ms"

if normalize_message(cause['message']) == known['pattern_fingerprint']:
    match = True
```

### Regex Match (for complex patterns)
```python
import re
if re.search(known['pattern_regex'], cause['message']):
    match = True
```

---

## Data Migration Path

### Phase 1: Development
- `data/known_issues.json` (manual)
- Static list of ~5-10 most common issues
- Tested against historical data

### Phase 2: Production Setup
- Create PostgreSQL table `known_issues`
- Run migration script (JSON → DB)
- Operator access via web UI or API

### Phase 3: Automation
- Auto-create entries for new recurring patterns
- ML model suggests new known issues
- Operator approves → JIRA ticket created

---

## Success Metrics

### Initial (Manual)
- [ ] 10+ known issues catalogued
- [ ] 80%+ of detected errors match known issues
- [ ] Report shows KNOWN vs NEW ratio
- [ ] Operator workflow documented

### Production
- [ ] <5 min to add new known issue
- [ ] >90% pattern match rate
- [ ] MTTR reduced by 30% (due to known solutions)
- [ ] Auto-escalation for NEW issues
- [ ] Weekly digest of new recurring patterns

---

## Next Steps

1. Create initial `data/known_issues.json` with all most common issues
2. Integrate into `analyze_daily.py` for pattern matching
3. Update report generation to show KNOWN vs NEW
4. Test against last week's data
5. Document operator workflow in `HOW_TO_USE.md`
