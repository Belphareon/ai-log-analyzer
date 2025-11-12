# Daily Error Report

**Period:** 2025-11-12T10:00:00 → 2025-11-12T10:30:00

**Total Errors:** 435

**Sample Size:** 435 (100.0% coverage)

**Unique Patterns Found:** 33

---

## Top 20 Error Patterns

### 1. ServiceBusinessException error handled.

**Estimated Total:** ~49 occurrences

**Sample Count:** 49

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~22
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~9

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 10:03:37.889000+00:00

**Last seen:** 2025-11-12 10:15:06.604000+00:00

---

### 2. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~42 occurrences

**Sample Count:** 42

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~22
- `pcb-dev-01-app`: ~14
- `pcb-sit-01-app`: ~6

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 13000 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-12 10:03:37.888000+00:00

**Last seen:** 2025-11-12 10:15:06.597000+00:00

---

### 3. jakarta.ws.rs.NotFoundException: HTTP {ID} Not Found
	at org.glassfish.jersey.se

**Estimated Total:** ~27 occurrences

**Sample Count:** 27

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~27

**Sample Message:**
```
jakarta.ws.rs.NotFoundException: HTTP 404 Not Found
	at org.glassfish.jersey.server.ServerRuntime$1.run(ServerRuntime.java:271)
	at org.glassfish.jers
```

**First seen:** 2025-11-12 10:00:21.230000+00:00

**Last seen:** 2025-11-12 10:11:17.511000+00:00

---

### 4. NotFoundException error handled.

**Estimated Total:** ~27 occurrences

**Sample Count:** 27

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~27

**Sample Message:**
```
NotFoundException error handled.
```

**First seen:** 2025-11-12 10:00:21.230000+00:00

**Last seen:** 2025-11-12 10:11:17.512000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~22 occurrences

**Sample Count:** 22

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~22

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/13000#503#
```

**First seen:** 2025-11-12 10:03:37.875000+00:00

**Last seen:** 2025-11-12 10:15:06.563000+00:00

---

### 6. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~22 occurrences

**Sample Count:** 22

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~22

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 10:03:37.929000+00:00

**Last seen:** 2025-11-12 10:15:06.608000+00:00

---

### 7. Queued event {ID} was not processed.

**Estimated Total:** ~21 occurrences

**Sample Count:** 21

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-uat-01-app`: ~7
- `pcb-fat-01-app`: ~7
- `pcb-dev-01-app`: ~7

**Sample Message:**
```
Queued event 77529 was not processed.
```

**First seen:** 2025-11-12 10:03:37.961000+00:00

**Last seen:** 2025-11-12 10:05:19.258000+00:00

---

### 8. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~14 occurrences

**Sample Count:** 14

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~14

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 10:03:37.894000+00:00

**Last seen:** 2025-11-12 10:15:06.587000+00:00

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

**First seen:** 2025-11-12 10:03:37.890000+00:00

**Last seen:** 2025-11-12 10:15:06.582000+00:00

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

**First seen:** 2025-11-12 10:00:02.529000+00:00

**Last seen:** 2025-11-12 10:25:01.340000+00:00

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

**First seen:** 2025-11-12 10:00:02.529000+00:00

**Last seen:** 2025-11-12 10:25:01.339000+00:00

---

### 12. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~6 occurrences

**Sample Count:** 6

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-sit-01-app`: ~6

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-sit-01-app:9080#/api/v1/card/13000#404#
```

**First seen:** 2025-11-12 10:04:52.500000+00:00

**Last seen:** 2025-11-12 10:15:06.585000+00:00

---

### 13. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck

**Estimated Total:** ~5 occurrences

**Sample Count:** 5

**Affected Apps:** bl-pcb-v1-processing, bl-pcb-v1

**Namespaces:**
- `pcb-fat-01-app`: ~5

**Sample Message:**
```
SPEED-002#PCB#bl-pcb#bl-pcb-v1#CamelReadinessStateHealthIndicator#doHealthCheck#OUT_OF_SERVICE#
```

**First seen:** 2025-11-12 10:12:12.467000+00:00

**Last seen:** 2025-11-12 10:26:25.071000+00:00

---

### 14. The header 'X-KB-Orig-System-Identity' is empty!!!

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-atm-locator-v1

**Namespaces:**
- `pcb-sit-01-app`: ~2
- `pcb-dev-01-app`: ~2

**Sample Message:**
```
The header 'X-KB-Orig-System-Identity' is empty!!!
```

**First seen:** 2025-11-12 10:16:19.489000+00:00

**Last seen:** 2025-11-12 10:21:21.667000+00:00

---

### 15. There is not codelist value for key B4 in codelist CB_PaymentCardSpecsName and l

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
There is not codelist value for key B4 in codelist CB_PaymentCardSpecsName and locale cs. Will not be translated.
```

**First seen:** 2025-11-12 10:02:15.895000+00:00

**Last seen:** 2025-11-12 10:02:25.995000+00:00

---

### 16. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Configuration error. Code 'B4

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
ITO-004#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#004#Configuration error. Code 'B4' was not found in RDM codelist CB_PaymentCardSpecsName for locale cs.
```

**First seen:** 2025-11-12 10:02:15.896000+00:00

**Last seen:** 2025-11-12 10:02:25.995000+00:00

---

### 17. There is not codelist value for key B4 in codelist PAYMENT_CARD_SPECS_NAME and l

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
There is not codelist value for key B4 in codelist PAYMENT_CARD_SPECS_NAME and locale cs_CZ. Will not be translated.
```

**First seen:** 2025-11-12 10:02:15.896000+00:00

**Last seen:** 2025-11-12 10:02:25.995000+00:00

---

### 18. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Configuration error. Code 'B4

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
ITO-004#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#004#Configuration error. Code 'B4' was not found in RDM codelist CB_PaymentCardSpecsName for locale cs_CZ
```

**First seen:** 2025-11-12 10:02:15.896000+00:00

**Last seen:** 2025-11-12 10:02:25.996000+00:00

---

### 19. Encountered an error executing step processAccountChange.accountChangeStep in jo

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
Encountered an error executing step processAccountChange.accountChangeStep in job processAccountChange
```

**First seen:** 2025-11-12 10:00:05.723000+00:00

**Last seen:** 2025-11-12 10:20:03.899000+00:00

---

### 20. An error occurred during job processing, job BatchJobIdentification(jobName=proc

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=processAccountChange, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 10:00:05.766000+00:00

**Last seen:** 2025-11-12 10:20:03.924000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T10:00:02.529000+00:00

**Burst Size:** ~394 errors (sample: 394)

**Affected Apps (9):** bl-pcb-billing-v1, bl-pcb-notification-v1, bl-pcb-v1-processing, bl-pcb-event-processor-relay-v1, bl-pcb-click2pay-v1, bl-pcb-v1, bl-pcb-batch-processor-v1, bl-pcb-design-lifecycle-v1, bl-pcb-client-rainbow-status-v1

**Namespaces:**
- `pcb-sit-01-app`: ~138
- `pcb-dev-01-app`: ~128
- `pcb-uat-01-app`: ~92

### Cluster 2: 2025-11-12T10:15:02.765000+00:00

**Burst Size:** ~41 errors (sample: 41)

**Affected Apps (8):** bl-pcb-card-georisk-v1, bl-pcb-notification-v1, bl-pcb-document-signing-v1, bl-pcb-v1-processing, bl-pcb-event-processor-relay-v1, bl-pcb-v1, bl-pcb-atm-locator-v1, bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~14
- `pcb-dev-01-app`: ~14
- `pcb-uat-01-app`: ~7


---

## 💳 Related Errors - Card IDs

### Card ID 121076

**Occurrences:** ~56

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 121076 and product instance null not found.
	at cz.kb.common.s`

### Card ID 13000

**Occurrences:** ~48

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 13000 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 87684

**Occurrences:** ~24

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62060

**Occurrences:** ~16

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@444c32d7[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 47028

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 47028 and product instance null not found.
	at cz.kb.common.sp`

