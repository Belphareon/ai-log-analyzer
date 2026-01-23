# Known Peaks

_Last updated: 2026-01-23_

**Total:** 1 known peak

---

## KP-001 – Order-service error spike during DB pool exhaustion

**Type:** error  
**Affected apps:** order-service  
**First seen:** 2025-11-12  
**Typical duration:** 15 min  
**Jira:** OPS-431  
**Status:** OPEN  
**Linked Error:** KE-001

### Description

Error spike that occurs when order-service DB connection pool is exhausted.

### Mitigation

- Scale up pods
- Restart affected service

---

