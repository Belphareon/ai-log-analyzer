# Daily Error Report

**Period:** 2025-11-12T11:30:00 → 2025-11-12T12:00:00

**Total Errors:** 136

**Sample Size:** 136 (100.0% coverage)

**Unique Patterns Found:** 15

---

## Top 20 Error Patterns

### 1. ServiceBusinessException error handled.

**Estimated Total:** ~20 occurrences

**Sample Count:** 20

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7
- `pcb-sit-01-app`: ~7
- `pcb-uat-01-app`: ~6

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 11:30:26.281000+00:00

**Last seen:** 2025-11-12 11:43:06.673000+00:00

---

### 2. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~13 occurrences

**Sample Count:** 13

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7
- `pcb-uat-01-app`: ~6

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-12 11:30:26.273000+00:00

**Last seen:** 2025-11-12 11:43:06.672000+00:00

---

### 3. Queued event {ID} was not processed.

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3
- `pcb-uat-01-app`: ~3
- `pcb-fat-01-app`: ~3

**Sample Message:**
```
Queued event 78699 was not processed.
```

**First seen:** 2025-11-12 11:30:26.382000+00:00

**Last seen:** 2025-11-12 11:30:37.286000+00:00

---

### 4. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~8 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~8

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/87684#503#
```

**First seen:** 2025-11-12 11:30:26.258000+00:00

**Last seen:** 2025-11-12 11:43:06.622000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~7 occurrences

**Sample Count:** 7

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/87684#404#
```

**First seen:** 2025-11-12 11:30:26.287000+00:00

**Last seen:** 2025-11-12 11:43:06.645000+00:00

---

### 6. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#{ID}#

**Estimated Total:** ~7 occurrences

**Sample Count:** 7

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#404#
```

**First seen:** 2025-11-12 11:30:26.282000+00:00

**Last seen:** 2025-11-12 11:43:06.640000+00:00

---

### 7. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~6 occurrences

**Sample Count:** 6

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~6

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/87684#404#
```

**First seen:** 2025-11-12 11:30:26.405000+00:00

**Last seen:** 2025-11-12 11:43:06.679000+00:00

---

### 8. Error occurred null - null, null.

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
Error occurred null - null, null.
```

**First seen:** 2025-11-12 11:37:26.644000+00:00

**Last seen:** 2025-11-12 11:37:56.510000+00:00

---

### 9. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#{ID}#Called service DoGS.c

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
ITO-006#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#006#Called service DoGS.casesStart ends with error. null - null, null
```

**First seen:** 2025-11-12 11:37:26.645000+00:00

**Last seen:** 2025-11-12 11:37:56.510000+00:00

---

### 10. cz.kb.common.speed.exception.ServiceBusinessException: Called service DoGS.cases

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

**First seen:** 2025-11-12 11:37:26.646000+00:00

**Last seen:** 2025-11-12 11:37:56.512000+00:00

---

### 11. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/star

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/start#500#
```

**First seen:** 2025-11-12 11:37:26.643000+00:00

**Last seen:** 2025-11-12 11:37:56.509000+00:00

---

### 12. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#ReadinessStateHealthIndicator#doHealthCheck#OUT_

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1-processing, bl-pcb-v1

**Namespaces:**
- `pcb-fat-01-app`: ~3

**Sample Message:**
```
SPEED-002#PCB#bl-pcb#bl-pcb-v1#ReadinessStateHealthIndicator#doHealthCheck#OUT_OF_SERVICE#
```

**First seen:** 2025-11-12 11:43:43.610000+00:00

**Last seen:** 2025-11-12 11:53:41.904000+00:00

---

### 13. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
ITO-135#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#135#Some problems in critical account change processing occurred. Process
```

**First seen:** 2025-11-12 11:30:04.498000+00:00

**Last seen:** 2025-11-12 11:50:08.606000+00:00

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

**First seen:** 2025-11-12 11:30:04.476000+00:00

**Last seen:** 2025-11-12 11:50:08.581000+00:00

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

**First seen:** 2025-11-12 11:30:04.497000+00:00

**Last seen:** 2025-11-12 11:50:08.605000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T11:30:04.476000+00:00

**Burst Size:** ~126 errors (sample: 126)

**Affected Apps (7):** bl-pcb-event-processor-relay-v1, bl-pcb-billing-v1, bl-pcb-batch-processor-v1, bl-pcb-v1, bl-pcb-click2pay-v1, bl-pcb-client-rainbow-status-v1, bl-pcb-v1-processing

**Namespaces:**
- `pcb-dev-01-app`: ~48
- `pcb-sit-01-app`: ~38
- `pcb-uat-01-app`: ~27

### Cluster 2: 2025-11-12T11:46:03.949000+00:00

**Burst Size:** ~10 errors (sample: 10)

**Affected Apps (4):** bl-pcb-v1-processing, bl-pcb-v1, bl-pcb-design-lifecycle-v1, bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-fat-01-app`: ~6
- `pcb-dev-01-app`: ~4


---

## 💳 Related Errors - Card IDs

### Card ID 71392

**Occurrences:** ~24

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 71392 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 87684

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 61738

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 61738 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62118

**Occurrences:** ~4

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@674467c2[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 62988

**Occurrences:** ~4

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62988 and product instance null not found.
	at cz.kb.common.sp`

