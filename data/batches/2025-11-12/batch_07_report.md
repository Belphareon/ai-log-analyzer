# Daily Error Report

**Period:** 2025-11-12T11:00:00 → 2025-11-12T11:30:00

**Total Errors:** 331

**Sample Size:** 331 (100.0% coverage)

**Unique Patterns Found:** 44

---

## Top 20 Error Patterns

### 1. ServiceBusinessException error handled.

**Estimated Total:** ~34 occurrences

**Sample Count:** 34

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~15
- `pcb-dev-01-app`: ~11
- `pcb-sit-01-app`: ~8

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 11:03:40.828000+00:00

**Last seen:** 2025-11-12 11:13:34.789000+00:00

---

### 2. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~24 occurrences

**Sample Count:** 24

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~15
- `pcb-dev-01-app`: ~7
- `pcb-sit-01-app`: ~2

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62060 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-12 11:03:40.824000+00:00

**Last seen:** 2025-11-12 11:07:01.428000+00:00

---

### 3. Queued event {ID} was not processed.

**Estimated Total:** ~21 occurrences

**Sample Count:** 21

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-fat-01-app`: ~7
- `pcb-dev-01-app`: ~7
- `pcb-uat-01-app`: ~7

**Sample Message:**
```
Queued event 77479 was not processed.
```

**First seen:** 2025-11-12 11:03:40.997000+00:00

**Last seen:** 2025-11-12 11:05:12.055000+00:00

---

### 4. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~15 occurrences

**Sample Count:** 15

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~15

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/62060#503#
```

**First seen:** 2025-11-12 11:03:40.760000+00:00

**Last seen:** 2025-11-12 11:07:02.381000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~15 occurrences

**Sample Count:** 15

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~15

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/62060#404#
```

**First seen:** 2025-11-12 11:03:40.851000+00:00

**Last seen:** 2025-11-12 11:07:01.411000+00:00

---

### 6. AccessDeniedException error handled.

**Estimated Total:** ~10 occurrences

**Sample Count:** 10

**Affected Apps:** bl-pcb-document-signing-v1, bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~10

**Sample Message:**
```
AccessDeniedException error handled.
```

**First seen:** 2025-11-12 11:11:59.696000+00:00

**Last seen:** 2025-11-12 11:12:14.467000+00:00

---

### 7. SPEED-{ID}#PCB#bl-pcb-document-signing#bl-pcb-document-signing-v1#GET#DocumentSi

**Estimated Total:** ~8 occurrences

**Sample Count:** 8

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~8

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-document-signing#bl-pcb-document-signing-v1#GET#DocumentSigningServiceImpl#getDocumentSigningState#403#
```

**First seen:** 2025-11-12 11:11:59.698000+00:00

**Last seen:** 2025-11-12 11:12:04.510000+00:00

---

### 8. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~7 occurrences

**Sample Count:** 7

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/121076#404#
```

**First seen:** 2025-11-12 11:03:40.835000+00:00

**Last seen:** 2025-11-12 11:05:11.040000+00:00

---

### 9. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#{ID}#

**Estimated Total:** ~7 occurrences

**Sample Count:** 7

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~7

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#404#
```

**First seen:** 2025-11-12 11:03:40.829000+00:00

**Last seen:** 2025-11-12 11:05:11.038000+00:00

---

### 10. An error occurred during job processing, job BatchJobIdentification(jobName=proc

**Estimated Total:** ~6 occurrences

**Sample Count:** 6

**Affected Apps:** bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3
- `pcb-fat-01-app`: ~1
- `pcb-sit-01-app`: ~1
- `pcb-uat-01-app`: ~1

**Sample Message:**
```
An error occurred during job processing, job BatchJobIdentification(jobName=processAccountChange, effectiveDate=2025-11-11).
```

**First seen:** 2025-11-12 11:00:02.693000+00:00

**Last seen:** 2025-11-12 11:20:04.935000+00:00

---

### 11. The header 'X-KB-Orig-System-Identity' is empty!!!

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

**First seen:** 2025-11-12 11:16:18.270000+00:00

**Last seen:** 2025-11-12 11:21:20.535000+00:00

---

### 12. org.springframework.security.access.AccessDeniedException: Cannot access card ca

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
org.springframework.security.access.AccessDeniedException: Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6a
```

**First seen:** 2025-11-12 11:11:59.694000+00:00

**Last seen:** 2025-11-12 11:12:03.510000+00:00

---

### 13. Cannot access card case document for msc signing case id {UUID} and user {ID}.

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6ae8 and user 970976514.
```

**First seen:** 2025-11-12 11:11:59.690000+00:00

**Last seen:** 2025-11-12 11:12:03.509000+00:00

---

### 14. Anonymize original error detail: Cannot access card case document for msc signin

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
Anonymize original error detail: Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6ae8 and user 970976514..
```

**First seen:** 2025-11-12 11:11:59.696000+00:00

**Last seen:** 2025-11-12 11:12:03.511000+00:00

---

### 15. Cannot access card case document for msc signing case id {UUID} and user A09V9S.

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6ae8 and user A09V9S.
```

**First seen:** 2025-11-12 11:12:03.873000+00:00

**Last seen:** 2025-11-12 11:12:04.508000+00:00

---

### 16. org.springframework.security.access.AccessDeniedException: Cannot access card ca

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
org.springframework.security.access.AccessDeniedException: Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6a
```

**First seen:** 2025-11-12 11:12:03.875000+00:00

**Last seen:** 2025-11-12 11:12:04.509000+00:00

---

### 17. Anonymize original error detail: Cannot access card case document for msc signin

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-document-signing-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
Anonymize original error detail: Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6ae8 and user A09V9S..
```

**First seen:** 2025-11-12 11:12:03.875000+00:00

**Last seen:** 2025-11-12 11:12:04.509000+00:00

---

### 18. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Configuration error. Code 'B4

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
ITO-004#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#004#Configuration error. Code 'B4' was not found in RDM codelist CB_PaymentCardSpecsName for locale cs.
```

**First seen:** 2025-11-12 11:02:18.904000+00:00

**Last seen:** 2025-11-12 11:02:27.697000+00:00

---

### 19. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Configuration error. Code 'B4

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
ITO-004#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#004#Configuration error. Code 'B4' was not found in RDM codelist CB_PaymentCardSpecsName for locale cs_CZ
```

**First seen:** 2025-11-12 11:02:18.904000+00:00

**Last seen:** 2025-11-12 11:02:27.697000+00:00

---

### 20. There is not codelist value for key B4 in codelist PAYMENT_CARD_SPECS_NAME and l

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
There is not codelist value for key B4 in codelist PAYMENT_CARD_SPECS_NAME and locale cs_CZ. Will not be translated.
```

**First seen:** 2025-11-12 11:02:18.904000+00:00

**Last seen:** 2025-11-12 11:02:27.697000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T11:00:01.683000+00:00

**Burst Size:** ~310 errors (sample: 310)

**Affected Apps (9):** bl-pcb-document-signing-v1, bl-pcb-billing-v1, bl-pcb-event-processor-relay-v1, bl-pcb-v1, bl-pcb-client-rainbow-status-v1, bl-pcb-design-lifecycle-v1, bl-pcb-batch-processor-v1, bl-pcb-click2pay-v1, bl-pcb-notification-v1

**Namespaces:**
- `pcb-sit-01-app`: ~113
- `pcb-dev-01-app`: ~96
- `pcb-uat-01-app`: ~71

### Cluster 2: 2025-11-12T11:15:01.823000+00:00

**Burst Size:** ~21 errors (sample: 21)

**Affected Apps (6):** bl-pcb-document-signing-v1, bl-pcb-atm-locator-v1, bl-pcb-card-georisk-v1, bl-pcb-batch-processor-v1, bl-pcb-v1-processing, bl-pcb-notification-v1

**Namespaces:**
- `pcb-dev-01-app`: ~10
- `pcb-sit-01-app`: ~5
- `pcb-uat-01-app`: ~4


---

## 💳 Related Errors - Card IDs

### Card ID 121076

**Occurrences:** ~56

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@1b181fbb[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 3

**Occurrences:** ~24

**Sample:** `org.springframework.security.access.AccessDeniedException: Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6a`

### Card ID 62060

**Occurrences:** ~16

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62060 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62396

**Occurrences:** ~8

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@6b9b60c2[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

### Card ID 47028

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 47028 and product instance null not found.
	at cz.kb.common.sp`

