# Daily Error Report

**Period:** 2025-11-12T08:30:00 → 2025-11-12T09:00:00

**Total Errors:** 1,374

**Sample Size:** 1,374 (100.0% coverage)

**Unique Patterns Found:** 75

---

## Top 20 Error Patterns

### 1. ServiceBusinessException error handled.

**Estimated Total:** ~118 occurrences

**Sample Count:** 118

**Affected Apps:** bl-pcb-v1, bl-pcb-card-client-segment-v1

**Namespaces:**
- `pcb-sit-01-app`: ~49
- `pcb-dev-01-app`: ~47
- `pcb-uat-01-app`: ~21

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 08:30:28.089000+00:00

**Last seen:** 2025-11-12 08:55:02.435000+00:00

---

### 2. Error handler threw an exception

**Estimated Total:** ~108 occurrences

**Sample Count:** 108

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~27
- `pcb-fat-01-app`: ~27
- `pcb-uat-01-app`: ~27
- `pcb-sit-01-app`: ~27

**Sample Message:**
```
Error handler threw an exception
```

**First seen:** 2025-11-12 08:36:28.411000+00:00

**Last seen:** 2025-11-12 08:36:43.965000+00:00

---

### 3. NotFoundException error handled.

**Estimated Total:** ~71 occurrences

**Sample Count:** 71

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~71

**Sample Message:**
```
NotFoundException error handled.
```

**First seen:** 2025-11-12 08:31:12.458000+00:00

**Last seen:** 2025-11-12 08:59:47.760000+00:00

---

### 4. jakarta.ws.rs.NotFoundException: HTTP {ID} Not Found
	at org.glassfish.jersey.se

**Estimated Total:** ~71 occurrences

**Sample Count:** 71

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~71

**Sample Message:**
```
jakarta.ws.rs.NotFoundException: HTTP 404 Not Found
	at org.glassfish.jersey.server.ServerRuntime$1.run(ServerRuntime.java:271)
	at org.glassfish.jers
```

**First seen:** 2025-11-12 08:31:12.457000+00:00

**Last seen:** 2025-11-12 08:59:47.760000+00:00

---

### 5. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~45 occurrences

**Sample Count:** 45

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~21
- `pcb-sit-01-app`: ~14
- `pcb-dev-01-app`: ~10

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 999999 and product instance null not found.
	at cz.kb.common.s
```

**First seen:** 2025-11-12 08:30:28.081000+00:00

**Last seen:** 2025-11-12 08:55:00.775000+00:00

---

### 6. ConstraintViolationException error handled.

**Estimated Total:** ~40 occurrences

**Sample Count:** 40

**Affected Apps:** bl-pcb-v1, bl-pcb-card-client-segment-v1

**Namespaces:**
- `pcb-sit-01-app`: ~21
- `pcb-dev-01-app`: ~19

**Sample Message:**
```
ConstraintViolationException error handled.
```

**First seen:** 2025-11-12 08:30:16.178000+00:00

**Last seen:** 2025-11-12 08:57:31.095000+00:00

---

### 7. Queued event {ID} was not processed.

**Estimated Total:** ~38 occurrences

**Sample Count:** 38

**Affected Apps:** bl-pcb-document-signing-v1, bl-pcb-billing-v1

**Namespaces:**
- `pcb-uat-01-app`: ~15
- `pcb-fat-01-app`: ~15
- `pcb-dev-01-app`: ~8

**Sample Message:**
```
Queued event 77513 was not processed.
```

**First seen:** 2025-11-12 08:30:28.167000+00:00

**Last seen:** 2025-11-12 08:44:12.011000+00:00

---

### 8. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#GET#bc-accountservicing-v1.stage.nca.kbcloud#/ap

**Estimated Total:** ~30 occurrences

**Sample Count:** 30

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~12

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#GET#bc-accountservicing-v1.stage.nca.kbcloud#/api/accounts/account-servicing/v2/customers/970393538/current-accounts#40
```

**First seen:** 2025-11-12 08:32:49.385000+00:00

**Last seen:** 2025-11-12 08:41:45.724000+00:00

---

### 9. Cannot get number error code of .

**Estimated Total:** ~30 occurrences

**Sample Count:** 30

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~12

**Sample Message:**
```
Cannot get number error code of .
```

**First seen:** 2025-11-12 08:32:49.386000+00:00

**Last seen:** 2025-11-12 08:41:45.725000+00:00

---

### 10. Handling route exception ServiceBusinessException with error AuthorizationDenied

**Estimated Total:** ~30 occurrences

**Sample Count:** 30

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~12

**Sample Message:**
```
Handling route exception ServiceBusinessException with error AuthorizationDeniedException: Access Denied by ServiceBusinessExceptionProcessor.
```

**First seen:** 2025-11-12 08:32:49.387000+00:00

**Last seen:** 2025-11-12 08:41:45.725000+00:00

---

### 11. cz.kb.common.speed.exception.ServiceBusinessException: AuthorizationDeniedExcept

**Estimated Total:** ~30 occurrences

**Sample Count:** 30

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~12

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: AuthorizationDeniedException: Access Denied
	at cz.kb.common.speed.exception.ServiceBusinessExc
```

**First seen:** 2025-11-12 08:32:49.388000+00:00

**Last seen:** 2025-11-12 08:41:45.726000+00:00

---

### 12. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~23 occurrences

**Sample Count:** 23

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~23

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/13000#503#
```

**First seen:** 2025-11-12 08:30:28.070000+00:00

**Last seen:** 2025-11-12 08:49:16.800000+00:00

---

### 13. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~21 occurrences

**Sample Count:** 21

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~21

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 08:30:28.095000+00:00

**Last seen:** 2025-11-12 08:49:16.838000+00:00

---

### 14. AccessDeniedException error handled.

**Estimated Total:** ~20 occurrences

**Sample Count:** 20

**Affected Apps:** bl-pcb-v1, bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~14
- `pcb-dev-01-app`: ~6

**Sample Message:**
```
AccessDeniedException error handled.
```

**First seen:** 2025-11-12 08:44:23.357000+00:00

**Last seen:** 2025-11-12 08:57:13.840000+00:00

---

### 15. SPEED-{ID}#PCBS#bl-pcb-dispute#bl-pcb-dispute-v1#DocflowRequestServicePortType#c

**Estimated Total:** ~19 occurrences

**Sample Count:** 19

**Affected Apps:** bl-pcb-dispute-v1

**Namespaces:**
- `pcb-dev-01-app`: ~10
- `pcb-sit-01-app`: ~9

**Sample Message:**
```
SPEED-100#PCBS#bl-pcb-dispute#bl-pcb-dispute-v1#DocflowRequestServicePortType#completeValidation#500##Internal Error
```

**First seen:** 2025-11-12 08:55:49.800000+00:00

**Last seen:** 2025-11-12 08:56:35.843000+00:00

---

### 16. Unexpected error occurred in directCompleteValidationOfDisputeCaseRoute#{ID}@cac

**Estimated Total:** ~19 occurrences

**Sample Count:** 19

**Affected Apps:** bl-pcb-dispute-v1

**Namespaces:**
- `pcb-dev-01-app`: ~10
- `pcb-sit-01-app`: ~9

**Sample Message:**
```
Unexpected error occurred in directCompleteValidationOfDisputeCaseRoute#192028175361@cached, service is probably unavailable.
```

**First seen:** 2025-11-12 08:55:49.800000+00:00

**Last seen:** 2025-11-12 08:56:35.843000+00:00

---

### 17. ITO-{ID}#PCBS#bl-pcb-dispute#bl-pcb-dispute-v1#n/a#DocflowRequestService#complet

**Estimated Total:** ~19 occurrences

**Sample Count:** 19

**Affected Apps:** bl-pcb-dispute-v1

**Namespaces:**
- `pcb-dev-01-app`: ~10
- `pcb-sit-01-app`: ~9

**Sample Message:**
```
ITO-005#PCBS#bl-pcb-dispute#bl-pcb-dispute-v1#n/a#DocflowRequestService#completeValidation#n/a#005#Called service DocflowRequestService is probably un
```

**First seen:** 2025-11-12 08:55:49.801000+00:00

**Last seen:** 2025-11-12 08:56:35.844000+00:00

---

### 18. Dispute case {ID} could not be provided to BPM.

**Estimated Total:** ~19 occurrences

**Sample Count:** 19

**Affected Apps:** bl-pcb-dispute-v1

**Namespaces:**
- `pcb-dev-01-app`: ~10
- `pcb-sit-01-app`: ~9

**Sample Message:**
```
Dispute case 1459 could not be provided to BPM.
```

**First seen:** 2025-11-12 08:55:49.802000+00:00

**Last seen:** 2025-11-12 08:56:35.845000+00:00

---

### 19. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#ClientServiceV2Impl#getAccountsForCardSale#

**Estimated Total:** ~18 occurrences

**Sample Count:** 18

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~18

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#ClientServiceV2Impl#getAccountsForCardSale#403#
```

**First seen:** 2025-11-12 08:34:43.206000+00:00

**Last seen:** 2025-11-12 08:41:45.727000+00:00

---

### 20. SPEED-{ID}#PCB#bl-pcb-document-signing#bl-pcb-document-signing-v1#GET#DocumentSi

**Estimated Total:** ~12 occurrences

**Sample Count:** 12

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-dev-01-app`: ~6
- `pcb-sit-01-app`: ~6

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-document-signing#bl-pcb-document-signing-v1#GET#DocumentSigningServiceImpl#getDocumentSigningState#403#
```

**First seen:** 2025-11-12 08:44:23.360000+00:00

**Last seen:** 2025-11-12 08:49:47.491000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T08:30:01.587000+00:00

**Burst Size:** ~867 errors (sample: 867)

**Affected Apps (9):** bl-pcb-batch-processor-v1, bl-pcb-card-client-segment-v1, bl-pcb-atm-locator-v1, bl-pcb-v1-processing, bl-pcb-event-processor-relay-v1, bl-pcb-v1, bl-pcb-document-signing-v1, bl-pcb-billing-v1, bl-pcb-click2pay-v1

**Namespaces:**
- `pcb-sit-01-app`: ~381
- `pcb-dev-01-app`: ~285
- `pcb-uat-01-app`: ~121

### Cluster 2: 2025-11-12T08:45:02.868000+00:00

**Burst Size:** ~507 errors (sample: 507)

**Affected Apps (9):** bl-pcb-batch-processor-v1, bl-pcb-design-lifecycle-v1, bl-pcb-card-client-segment-v1, bl-pcb-v1-processing, bl-pcb-dispute-v1, bl-pcb-event-processor-relay-v1, bl-pcb-v1, bl-pcb-document-signing-v1, bl-pcb-billing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~259
- `pcb-dev-01-app`: ~227
- `pcb-fat-01-app`: ~13


---

## �🔗 Related Errors - Case IDs

Errors grouped by Case ID show error chains and processing failures:

### Case ID 5505223

**Occurrences:** ~3 (sample: 3)

**Affected Namespaces:**
- `pcb-sit-01-app`: ~3

**Error Chain (3 unique patterns):**
1. (~1x) `Case 5505223 could not be processed, it is not in one of expected statuses [CREATED, WAITING_FOR_SIGNATURE], current sta...`
2. (~1x) `cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Case 5505223 could not be processed, not in exp...`
3. (~1x) `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@6d6510eb[category=10,code=err.001,originalCode=<null>,...`

### Case ID 6026744

**Occurrences:** ~3 (sample: 3)

**Affected Namespaces:**
- `pcb-dev-01-app`: ~3

**Error Chain (3 unique patterns):**
1. (~1x) `Case 6026744 could not be processed, it is not in one of expected statuses [CREATED, WAITING_FOR_SIGNATURE], current sta...`
2. (~1x) `cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Case 6026744 could not be processed, not in exp...`
3. (~1x) `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@3711da34[category=10,code=err.001,originalCode=<null>,...`

### Case ID 5546502

**Occurrences:** ~3 (sample: 3)

**Affected Namespaces:**
- `pcb-sit-01-app`: ~3

**Error Chain (3 unique patterns):**
1. (~1x) `Case 5546502 could not be processed, it is not in one of expected statuses [CREATED, WAITING_FOR_SIGNATURE], current sta...`
2. (~1x) `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@3e960677[category=10,code=err.001,originalCode=<null>,...`
3. (~1x) `cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Case 5546502 could not be processed, not in exp...`

### Case ID 5500000

**Occurrences:** ~2 (sample: 2)

**Affected Namespaces:**
- `pcb-sit-01-app`: ~2

**Error Chain (2 unique patterns):**
1. (~1x) `Card case 5500000 could not be processed, requested user 970566654 is not among expected users [A0DASV], processing is f...`
2. (~1x) `Card case 5500000 could not be processed, requested user 970486507 is not among expected users [A0DASV], processing is f...`

### Case ID 1459

**Occurrences:** ~1 (sample: 1)

**Affected Namespaces:**
- `pcb-dev-01-app`: ~1

**Error Chain (1 unique patterns):**
1. (~1x) `Dispute case 1459 could not be provided to BPM....`


---

## 💳 Related Errors - Card IDs

### Card ID 13000

**Occurrences:** ~36

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@56c963da[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 999999

**Occurrences:** ~32

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 999999 and product instance null not found.
	at cz.kb.common.s`

### Card ID 71392

**Occurrences:** ~32

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@3621fd88[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 73834

**Occurrences:** ~24

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 73834 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 3

**Occurrences:** ~18

**Sample:** `org.springframework.security.access.AccessDeniedException: Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6a`

