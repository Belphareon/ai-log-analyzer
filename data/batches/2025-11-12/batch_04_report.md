# Daily Error Report

**Period:** 2025-11-12T09:30:00 → 2025-11-12T10:00:00

**Total Errors:** 311

**Sample Size:** 311 (100.0% coverage)

**Unique Patterns Found:** 19

---

## Top 20 Error Patterns

### 1. NotFoundException error handled.

**Estimated Total:** ~45 occurrences

**Sample Count:** 45

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~45

**Sample Message:**
```
NotFoundException error handled.
```

**First seen:** 2025-11-12 09:31:48.120000+00:00

**Last seen:** 2025-11-12 09:59:57.884000+00:00

---

### 2. jakarta.ws.rs.NotFoundException: HTTP {ID} Not Found
	at org.glassfish.jersey.se

**Estimated Total:** ~45 occurrences

**Sample Count:** 45

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~45

**Sample Message:**
```
jakarta.ws.rs.NotFoundException: HTTP 404 Not Found
	at org.glassfish.jersey.server.ServerRuntime$1.run(ServerRuntime.java:271)
	at org.glassfish.jers
```

**First seen:** 2025-11-12 09:31:48.120000+00:00

**Last seen:** 2025-11-12 09:59:57.884000+00:00

---

### 3. ServiceBusinessException error handled.

**Estimated Total:** ~25 occurrences

**Sample Count:** 25

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9
- `pcb-uat-01-app`: ~8
- `pcb-sit-01-app`: ~8

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 09:30:30.818000+00:00

**Last seen:** 2025-11-12 09:58:59.270000+00:00

---

### 4. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~18 occurrences

**Sample Count:** 18

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9
- `pcb-uat-01-app`: ~8
- `pcb-sit-01-app`: ~1

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-12 09:30:30.816000+00:00

**Last seen:** 2025-11-12 09:58:59.270000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~10 occurrences

**Sample Count:** 10

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~10

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/87684#503#
```

**First seen:** 2025-11-12 09:30:30.800000+00:00

**Last seen:** 2025-11-12 09:58:59.235000+00:00

---

### 6. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/87684#404#
```

**First seen:** 2025-11-12 09:30:30.824000+00:00

**Last seen:** 2025-11-12 09:58:59.278000+00:00

---

### 7. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#{ID}#

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~9

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#404#
```

**First seen:** 2025-11-12 09:30:30.820000+00:00

**Last seen:** 2025-11-12 09:58:59.272000+00:00

---

### 8. Queued event {ID} was not processed.

**Estimated Total:** ~9 occurrences

**Sample Count:** 9

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-fat-01-app`: ~3
- `pcb-dev-01-app`: ~3
- `pcb-uat-01-app`: ~3

**Sample Message:**
```
Queued event 77467 was not processed.
```

**First seen:** 2025-11-12 09:30:30.944000+00:00

**Last seen:** 2025-11-12 09:30:41.881000+00:00

---

### 9. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~8 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~8

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/87684#404#
```

**First seen:** 2025-11-12 09:30:30.879000+00:00

**Last seen:** 2025-11-12 09:58:59.273000+00:00

---

### 10. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~8 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~8

**Sample Message:**
```
ITO-131#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#131#Some problems in critical account balances transfer to CMS occurred. 
```

**First seen:** 2025-11-12 09:30:05.810000+00:00

**Last seen:** 2025-11-12 09:55:02.550000+00:00

---

### 11. An error occurred during job processing, job BatchJobIdentification(jobName=acco

**Estimated Total:** ~6 occurrences

**Sample Count:** 6

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~6

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=accountBalancesCzExport, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 09:30:07.265000+00:00

**Last seen:** 2025-11-12 09:55:02.549000+00:00

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

**First seen:** 2025-11-12 09:37:25.724000+00:00

**Last seen:** 2025-11-12 09:37:55.961000+00:00

---

### 13. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/star

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/start#500#
```

**First seen:** 2025-11-12 09:37:25.719000+00:00

**Last seen:** 2025-11-12 09:37:55.959000+00:00

---

### 14. cz.kb.common.speed.exception.ServiceBusinessException: Called service DoGS.cases

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

**First seen:** 2025-11-12 09:37:25.728000+00:00

**Last seen:** 2025-11-12 09:37:55.964000+00:00

---

### 15. Error occurred null - null, null.

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
Error occurred null - null, null.
```

**First seen:** 2025-11-12 09:37:25.722000+00:00

**Last seen:** 2025-11-12 09:37:55.960000+00:00

---

### 16. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1, bl-pcb-v1-processing

**Namespaces:**
- `pcb-fat-01-app`: ~3

**Sample Message:**
```
SPEED-002#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck#OUT_OF_SERVICE#
```

**First seen:** 2025-11-12 09:44:12.423000+00:00

**Last seen:** 2025-11-12 09:58:55.468000+00:00

---

### 17. Encountered an error executing step processAccountChange.accountChangeStep in jo

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
Encountered an error executing step processAccountChange.accountChangeStep in job processAccountChange
```

**First seen:** 2025-11-12 09:30:06.966000+00:00

**Last seen:** 2025-11-12 09:50:03.097000+00:00

---

### 18. An error occurred during job processing, job BatchJobIdentification(jobName=proc

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=processAccountChange, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 09:30:06.989000+00:00

**Last seen:** 2025-11-12 09:50:03.126000+00:00

---

### 19. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
ITO-135#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#135#Some problems in critical account change processing occurred. Process
```

**First seen:** 2025-11-12 09:30:06.989000+00:00

**Last seen:** 2025-11-12 09:50:03.126000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T09:30:05.810000+00:00

**Burst Size:** ~191 errors (sample: 191)

**Affected Apps (7):** bl-pcb-billing-v1, bl-pcb-v1, bl-pcb-client-rainbow-status-v1, bl-pcb-event-processor-relay-v1, bl-pcb-batch-processor-v1, bl-pcb-v1-processing, bl-pcb-click2pay-v1

**Namespaces:**
- `pcb-sit-01-app`: ~113
- `pcb-dev-01-app`: ~43
- `pcb-uat-01-app`: ~23

### Cluster 2: 2025-11-12T09:45:46.031000+00:00

**Burst Size:** ~119 errors (sample: 120)

**Affected Apps (4):** bl-pcb-batch-processor-v1, bl-pcb-v1, bl-pcb-event-processor-relay-v1, bl-pcb-design-lifecycle-v1

**Namespaces:**
- `pcb-sit-01-app`: ~80
- `pcb-dev-01-app`: ~19
- `pcb-uat-01-app`: ~12


---

## 💳 Related Errors - Card IDs

### Card ID 71392

**Occurrences:** ~24

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@11934761[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 87684

**Occurrences:** ~16

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 13000

**Occurrences:** ~12

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 13000 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 61738

**Occurrences:** ~8

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@64800f78[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 62988

**Occurrences:** ~4

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62988 and product instance null not found.
	at cz.kb.common.sp`

