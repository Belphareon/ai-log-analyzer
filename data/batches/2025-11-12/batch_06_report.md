# Daily Error Report

**Period:** 2025-11-12T10:30:00 → 2025-11-12T11:00:00

**Total Errors:** 184

**Sample Size:** 184 (100.0% coverage)

**Unique Patterns Found:** 18

---

## Top 20 Error Patterns

### 1. ServiceBusinessException error handled.

**Estimated Total:** ~27 occurrences

**Sample Count:** 27

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~10
- `pcb-dev-01-app`: ~9
- `pcb-uat-01-app`: ~8

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 10:30:33.611000+00:00

**Last seen:** 2025-11-12 10:42:49.873000+00:00

---

### 2. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~20 occurrences

**Sample Count:** 20

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9
- `pcb-uat-01-app`: ~8
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 13000 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-12 10:30:33.604000+00:00

**Last seen:** 2025-11-12 10:42:49.872000+00:00

---

### 3. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~10 occurrences

**Sample Count:** 10

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~10

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/13000#503#
```

**First seen:** 2025-11-12 10:30:33.568000+00:00

**Last seen:** 2025-11-12 10:42:49.856000+00:00

---

### 4. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 10:30:33.623000+00:00

**Last seen:** 2025-11-12 10:42:49.870000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#{ID}#

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#404#
```

**First seen:** 2025-11-12 10:30:33.619000+00:00

**Last seen:** 2025-11-12 10:42:49.867000+00:00

---

### 6. Queued event {ID} was not processed.

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3
- `pcb-fat-01-app`: ~3
- `pcb-uat-01-app`: ~3

**Sample Message:**
```
Queued event 78689 was not processed.
```

**First seen:** 2025-11-12 10:30:33.726000+00:00

**Last seen:** 2025-11-12 10:30:44.587000+00:00

---

### 7. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~8 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~8

**Sample Message:**
```
ITO-131#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#131#Some problems in critical account balances transfer to CMS occurred. 
```

**First seen:** 2025-11-12 10:30:03.748000+00:00

**Last seen:** 2025-11-12 10:55:01.498000+00:00

---

### 8. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~8 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~8

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 10:30:33.621000+00:00

**Last seen:** 2025-11-12 10:42:49.866000+00:00

---

### 9. An error occurred during job processing, job BatchJobIdentification(jobName=acco

**Estimated Total:** ~6 occurrences

**Sample Count:** 6

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~6

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=accountBalancesCzExport, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 10:30:03.748000+00:00

**Last seen:** 2025-11-12 10:55:01.497000+00:00

---

### 10. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/star

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/start#500#
```

**First seen:** 2025-11-12 10:37:28.363000+00:00

**Last seen:** 2025-11-12 10:37:58.392000+00:00

---

### 11. cz.kb.common.speed.exception.ServiceBusinessException: Called service DoGS.cases

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Called service DoGS.casesStart error occurred. null - null, null
	at cz.kb.common.speed.excepti
```

**First seen:** 2025-11-12 10:37:28.367000+00:00

**Last seen:** 2025-11-12 10:37:58.396000+00:00

---

### 12. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#{ID}#Called service DoGS.c

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
ITO-006#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#006#Called service DoGS.casesStart ends with error. null - null, null
```

**First seen:** 2025-11-12 10:37:28.365000+00:00

**Last seen:** 2025-11-12 10:37:58.394000+00:00

---

### 13. Error occurred null - null, null.

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
Error occurred null - null, null.
```

**First seen:** 2025-11-12 10:37:28.364000+00:00

**Last seen:** 2025-11-12 10:37:58.393000+00:00

---

### 14. Encountered an error executing step processAccountChange.accountChangeStep in jo

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
Encountered an error executing step processAccountChange.accountChangeStep in job processAccountChange
```

**First seen:** 2025-11-12 10:30:07.751000+00:00

**Last seen:** 2025-11-12 10:50:03.844000+00:00

---

### 15. An error occurred during job processing, job BatchJobIdentification(jobName=proc

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=processAccountChange, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 10:30:07.769000+00:00

**Last seen:** 2025-11-12 10:50:03.864000+00:00

---

### 16. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
ITO-135#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#135#Some problems in critical account change processing occurred. Process
```

**First seen:** 2025-11-12 10:30:07.769000+00:00

**Last seen:** 2025-11-12 10:50:03.864000+00:00

---

### 17. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1, bl-pcb-v1-processing

**Namespaces:**
- `pcb-fat-01-app`: ~3

**Sample Message:**
```
SPEED-002#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck#OUT_OF_SERVICE#
```

**First seen:** 2025-11-12 10:30:42.603000+00:00

**Last seen:** 2025-11-12 10:40:55.737000+00:00

---

### 18. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-sit-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 10:42:23.263000+00:00

**Last seen:** 2025-11-12 10:42:49.877000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T10:30:03.748000+00:00

**Burst Size:** ~176 errors (sample: 176)

**Affected Apps (7):** bl-pcb-click2pay-v1, bl-pcb-billing-v1, bl-pcb-v1, bl-pcb-v1-processing, bl-pcb-event-processor-relay-v1, bl-pcb-client-rainbow-status-v1, bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~62
- `pcb-dev-01-app`: ~58
- `pcb-uat-01-app`: ~35

### Cluster 2: 2025-11-12T10:46:03.718000+00:00

**Burst Size:** ~8 errors (sample: 8)

**Affected Apps (2):** bl-pcb-design-lifecycle-v1, bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~4
- `pcb-sit-01-app`: ~4


---

## 💳 Related Errors - Card IDs

### Card ID 13000

**Occurrences:** ~36

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 13000 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 71392

**Occurrences:** ~24

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 71392 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 61738

**Occurrences:** ~8

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@50324ca6[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 62988

**Occurrences:** ~4

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62988 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62948

**Occurrences:** ~4

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62948 and product instance null not found.
	at cz.kb.common.sp`

