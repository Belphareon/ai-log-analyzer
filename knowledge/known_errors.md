# Known Errors

_Last updated: 2026-01-23_

**Total:** 1 known error

---

## KE-001 – Order-service DB pool exhaustion

**Category:** DATABASE  
**Affected apps:** order-service, payment-service  
**First seen:** 2025-11-12  
**Jira:** OPS-431  
**Status:** OPEN  
**Owner:** platform-team

### Description

Order-service DB connection pool exhaustion during traffic spikes.
Happens when incoming request rate exceeds pool capacity.

### Workaround

- Restart order-service pod
- Scale up replicas temporarily

### Permanent Fix

- Increase pool size to 25
- Optimize slow queries
- Add connection timeout

### Notes

Happens during morning traffic peak (8-9 AM)

---

