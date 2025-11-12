# Daily Error Report

**Period:** 2025-11-12T09:00:00 → 2025-11-12T09:30:00

**Total Errors:** 509

**Sample Size:** 509 (100.0% coverage)

**Unique Patterns Found:** 33

---

## Top 20 Error Patterns

### 1. NotFoundException error handled.

**Estimated Total:** ~58 occurrences

**Sample Count:** 58

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~58

**Sample Message:**
```
NotFoundException error handled.
```

**First seen:** 2025-11-12 09:00:23.233000+00:00

**Last seen:** 2025-11-12 09:29:54.229000+00:00

---

### 2. jakarta.ws.rs.NotFoundException: HTTP {ID} Not Found
	at org.glassfish.jersey.se

**Estimated Total:** ~58 occurrences

**Sample Count:** 58

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~58

**Sample Message:**
```
jakarta.ws.rs.NotFoundException: HTTP 404 Not Found
	at org.glassfish.jersey.server.ServerRuntime$1.run(ServerRuntime.java:271)
	at org.glassfish.jers
```

**First seen:** 2025-11-12 09:00:23.232000+00:00

**Last seen:** 2025-11-12 09:29:54.229000+00:00

---

### 3. ServiceBusinessException error handled.

**Estimated Total:** ~46 occurrences

**Sample Count:** 46

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~22
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~6

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 09:03:35.031000+00:00

**Last seen:** 2025-11-12 09:27:42.199000+00:00

---

### 4. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~39 occurrences

**Sample Count:** 39

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~22
- `pcb-dev-01-app`: ~14
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-12 09:03:35.029000+00:00

**Last seen:** 2025-11-12 09:27:42.199000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~22 occurrences

**Sample Count:** 22

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~22

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/87684#503#
```

**First seen:** 2025-11-12 09:03:35.012000+00:00

**Last seen:** 2025-11-12 09:27:42.182000+00:00

---

### 6. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~22 occurrences

**Sample Count:** 22

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~22

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/87684#404#
```

**First seen:** 2025-11-12 09:03:35.124000+00:00

**Last seen:** 2025-11-12 09:27:42.204000+00:00

---

### 7. Queued event {ID} was not processed.

**Estimated Total:** ~21 occurrences

**Sample Count:** 21

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7
- `pcb-fat-01-app`: ~7
- `pcb-uat-01-app`: ~7

**Sample Message:**
```
Queued event 78672 was not processed.
```

**First seen:** 2025-11-12 09:03:35.131000+00:00

**Last seen:** 2025-11-12 09:05:26.517000+00:00

---

### 8. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~14 occurrences

**Sample Count:** 14

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~14

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/87684#404#
```

**First seen:** 2025-11-12 09:03:35.036000+00:00

**Last seen:** 2025-11-12 09:27:42.198000+00:00

---

### 9. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#{ID}#

**Estimated Total:** ~14 occurrences

**Sample Count:** 14

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~14

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#404#
```

**First seen:** 2025-11-12 09:03:35.032000+00:00

**Last seen:** 2025-11-12 09:27:42.194000+00:00

---

### 10. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~7 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~7

**Sample Message:**
```
ITO-131#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#131#Some problems in critical account balances transfer to CMS occurred. 
```

**First seen:** 2025-11-12 09:00:04.830000+00:00

**Last seen:** 2025-11-12 09:25:01.758000+00:00

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

**First seen:** 2025-11-12 09:00:04.830000+00:00

**Last seen:** 2025-11-12 09:25:01.758000+00:00

---

### 12. Encountered an error executing step processAccountChange.accountChangeStep in jo

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
Encountered an error executing step processAccountChange.accountChangeStep in job processAccountChange
```

**First seen:** 2025-11-12 09:00:09.431000+00:00

**Last seen:** 2025-11-12 09:20:02.237000+00:00

---

### 13. An error occurred during job processing, job BatchJobIdentification(jobName=proc

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=processAccountChange, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 09:00:09.457000+00:00

**Last seen:** 2025-11-12 09:20:02.267000+00:00

---

### 14. ITO-{ID}#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#{I

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
ITO-135#PCB#bl-pcb-batch-processor#bl-pcb-batch-processor-v1#n/a#n/a#n/a#n/a#135#Some problems in critical account change processing occurred. Process
```

**First seen:** 2025-11-12 09:00:09.457000+00:00

**Last seen:** 2025-11-12 09:20:02.268000+00:00

---

### 15. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1-processing, bl-pcb-v1

**Namespaces:**
- `pcb-fat-01-app`: ~3

**Sample Message:**
```
SPEED-002#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck#OUT_OF_SERVICE#
```

**First seen:** 2025-11-12 09:06:27.407000+00:00

**Last seen:** 2025-11-12 09:20:27.470000+00:00

---

### 16. The header 'X-KB-Orig-System-Identity' is empty!!!

**Estimated Total:** ~3 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-atm-locator-v1

**Namespaces:**
- `pcb-sit-01-app`: ~1
- `pcb-dev-01-app`: ~1

**Sample Message:**
```
The header 'X-KB-Orig-System-Identity' is empty!!!
```

**First seen:** 2025-11-12 09:16:21.664000+00:00

**Last seen:** 2025-11-12 09:21:23.001000+00:00

---

### 17. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/star

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/start#500#
```

**First seen:** 2025-11-12 09:07:49.930000+00:00

**Last seen:** 2025-11-12 09:08:10.061000+00:00

---

### 18. Error occurred null - null, null.

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
Error occurred null - null, null.
```

**First seen:** 2025-11-12 09:07:49.931000+00:00

**Last seen:** 2025-11-12 09:08:10.062000+00:00

---

### 19. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#{ID}#Called service DoGS.c

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
ITO-006#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#006#Called service DoGS.casesStart ends with error. null - null, null
```

**First seen:** 2025-11-12 09:07:49.933000+00:00

**Last seen:** 2025-11-12 09:08:10.063000+00:00

---

### 20. cz.kb.common.speed.exception.ServiceBusinessException: Called service DoGS.cases

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Called service DoGS.casesStart error occurred. null - null, null
	at cz.kb.common.speed.excepti
```

**First seen:** 2025-11-12 09:07:49.935000+00:00

**Last seen:** 2025-11-12 09:08:10.065000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T09:00:04.830000+00:00

**Burst Size:** ~350 errors (sample: 350)

**Affected Apps (8):** bl-pcb-design-lifecycle-v1, bl-pcb-notification-v1, bl-pcb-billing-v1, bl-pcb-v1-processing, bl-pcb-event-processor-relay-v1, bl-pcb-click2pay-v1, bl-pcb-batch-processor-v1, bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~129
- `pcb-dev-01-app`: ~112
- `pcb-uat-01-app`: ~80

### Cluster 2: 2025-11-12T09:15:20.051000+00:00

**Burst Size:** ~159 errors (sample: 159)

**Affected Apps (7):** bl-pcb-document-signing-v1, bl-pcb-card-georisk-v1, bl-pcb-v1-processing, bl-pcb-event-processor-relay-v1, bl-pcb-atm-locator-v1, bl-pcb-batch-processor-v1, bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~104
- `pcb-dev-01-app`: ~29
- `pcb-uat-01-app`: ~19


---

## 💳 Related Errors - Card IDs

### Card ID 121076

**Occurrences:** ~56

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 121076 and product instance null not found.
	at cz.kb.common.s`

### Card ID 87684

**Occurrences:** ~48

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62060

**Occurrences:** ~15

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@10bd6a9[category=15,code=err.103,originalCode=<null>,message=Resource not found. Car`

### Card ID 13000

**Occurrences:** ~12

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 13000 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 47028

**Occurrences:** ~7

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@23536f67[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

