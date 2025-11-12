# Daily Error Report

**Period:** 2025-11-12T12:00:00 → 2025-11-12T12:30:00

**Total Errors:** 220

**Sample Size:** 220 (100.0% coverage)

**Unique Patterns Found:** 21

---

## Top 20 Error Patterns

### 1. ServiceBusinessException error handled.

**Estimated Total:** ~28 occurrences

**Sample Count:** 29

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~14
- `pcb-dev-01-app`: ~11
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-12 12:03:42.978000+00:00

**Last seen:** 2025-11-12 12:08:59.097000+00:00

---

### 2. cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Estimated Total:** ~24 occurrences

**Sample Count:** 24

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-uat-01-app`: ~14
- `pcb-dev-01-app`: ~6
- `pcb-sit-01-app`: ~2

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 121076 and product instance null not found.
	at cz.kb.common.s
```

**First seen:** 2025-11-12 12:03:42.973000+00:00

**Last seen:** 2025-11-12 12:07:03.609000+00:00

---

### 3. Queued event {ID} was not processed.

**Estimated Total:** ~21 occurrences

**Sample Count:** 21

**Affected Apps:** bl-pcb-billing-v1

**Namespaces:**
- `pcb-dev-01-app`: ~6
- `pcb-fat-01-app`: ~6
- `pcb-uat-01-app`: ~6

**Sample Message:**
```
Queued event 78702 was not processed.
```

**First seen:** 2025-11-12 12:03:43.045000+00:00

**Last seen:** 2025-11-12 12:05:14.230000+00:00

---

### 4. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~14 occurrences

**Sample Count:** 15

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-fat-01-app`: ~14

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-fat-01-app:9080#/api/v1/card/121076#503#
```

**First seen:** 2025-11-12 12:03:42.940000+00:00

**Last seen:** 2025-11-12 12:07:03.601000+00:00

---

### 5. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~14 occurrences

**Sample Count:** 15

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-uat-01-app`: ~14

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-uat-01-app:9080#/api/v1/card/121076#404#
```

**First seen:** 2025-11-12 12:03:42.983000+00:00

**Last seen:** 2025-11-12 12:07:03.612000+00:00

---

### 6. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#{ID}#

**Estimated Total:** ~6 occurrences

**Sample Count:** 7

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~6

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#CardServiceImpl#getCardDetail#404#
```

**First seen:** 2025-11-12 12:03:43.160000+00:00

**Last seen:** 2025-11-12 12:05:13.220000+00:00

---

### 7. SPEED-{ID}#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST

**Estimated Total:** ~6 occurrences

**Sample Count:** 7

**Affected Apps:** bl-pcb-event-processor-relay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~6

**Sample Message:**
```
SPEED-101#PCB#bl-pcb-event-processor-relay#bl-pcb-event-processor-relay-v1#POST#bl-pcb-v1.pcb-dev-01-app:9080#/api/v1/card/121076#404#
```

**First seen:** 2025-11-12 12:03:43.167000+00:00

**Last seen:** 2025-11-12 12:05:13.224000+00:00

---

### 8. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Configuration error. Code 'B4

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
ITO-004#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#004#Configuration error. Code 'B4' was not found in RDM codelist CB_PaymentCardSpecsName for locale cs.
```

**First seen:** 2025-11-12 12:02:16.212000+00:00

**Last seen:** 2025-11-12 12:02:22.797000+00:00

---

### 9. There is not codelist value for key B4 in codelist PAYMENT_CARD_SPECS_NAME and l

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
There is not codelist value for key B4 in codelist PAYMENT_CARD_SPECS_NAME and locale cs_CZ. Will not be translated.
```

**First seen:** 2025-11-12 12:02:16.213000+00:00

**Last seen:** 2025-11-12 12:02:22.797000+00:00

---

### 10. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Configuration error. Code 'B4

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
ITO-004#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#004#Configuration error. Code 'B4' was not found in RDM codelist CB_PaymentCardSpecsName for locale cs_CZ
```

**First seen:** 2025-11-12 12:02:16.213000+00:00

**Last seen:** 2025-11-12 12:02:22.797000+00:00

---

### 11. There is not codelist value for key B4 in codelist CB_PaymentCardSpecsName and l

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~4

**Sample Message:**
```
There is not codelist value for key B4 in codelist CB_PaymentCardSpecsName and locale cs. Will not be translated.
```

**First seen:** 2025-11-12 12:02:16.212000+00:00

**Last seen:** 2025-11-12 12:02:22.797000+00:00

---

### 12. HibernateJdbcException error handled.

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
HibernateJdbcException error handled.
```

**First seen:** 2025-11-12 12:08:09.679000+00:00

**Last seen:** 2025-11-12 12:09:20.060000+00:00

---

### 13. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#GET#SigningServiceImpl#getSigningInformations#{I

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#GET#SigningServiceImpl#getSigningInformations#500#
```

**First seen:** 2025-11-12 12:08:09.679000+00:00

**Last seen:** 2025-11-12 12:09:20.060000+00:00

---

### 14. SQL value CERTIFICATE_OF_INSURANCE could not be converted to the enumeration val

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
SQL value CERTIFICATE_OF_INSURANCE could not be converted to the enumeration value!
```

**First seen:** 2025-11-12 12:08:09.674000+00:00

**Last seen:** 2025-11-12 12:09:20.057000+00:00

---

### 15. SQL value could not be converted to the enumeration value.

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
SQL value could not be converted to the enumeration value.
```

**First seen:** 2025-11-12 12:08:09.675000+00:00

**Last seen:** 2025-11-12 12:09:20.057000+00:00

---

### 16. org.springframework.orm.hibernate5.HibernateJdbcException: JDBC exception on Hib

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
org.springframework.orm.hibernate5.HibernateJdbcException: JDBC exception on Hibernate data access: SQLException for SQL [n/a]; SQL state [null]; erro
```

**First seen:** 2025-11-12 12:08:09.678000+00:00

**Last seen:** 2025-11-12 12:09:20.059000+00:00

---

### 17. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#{ID}#Called service DoGS.c

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
ITO-006#PCB#bl-pcb#bl-pcb-v1#n/a#DoGS#casesStart#n/a#006#Called service DoGS.casesStart ends with error. null - null, null
```

**First seen:** 2025-11-12 12:07:44.593000+00:00

**Last seen:** 2025-11-12 12:08:04.349000+00:00

---

### 18. SPEED-{ID}#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/star

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
SPEED-101#PCB#bl-pcb#bl-pcb-v1#POST#dogs-test.dslab.kb.cz#/v3/BE/api/cases/start#500#
```

**First seen:** 2025-11-12 12:07:44.591000+00:00

**Last seen:** 2025-11-12 12:08:04.348000+00:00

---

### 19. Error occurred null - null, null.

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~3

**Sample Message:**
```
Error occurred null - null, null.
```

**First seen:** 2025-11-12 12:07:44.592000+00:00

**Last seen:** 2025-11-12 12:08:04.349000+00:00

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

**First seen:** 2025-11-12 12:07:44.594000+00:00

**Last seen:** 2025-11-12 12:08:04.357000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T12:00:04.084000+00:00

**Burst Size:** ~220 errors (sample: 220)

**Affected Apps (8):** bl-pcb-click2pay-v1, bl-pcb-event-processor-relay-v1, bl-pcb-v1, bl-pcb-client-rainbow-status-v1, bl-pcb-billing-v1, bl-pcb-v1-processing, bl-pcb-batch-processor-v1, bl-pcb-design-lifecycle-v1

**Namespaces:**
- `pcb-dev-01-app`: ~96
- `pcb-uat-01-app`: ~67
- `pcb-fat-01-app`: ~28


---

## 💳 Related Errors - Card IDs

### Card ID 121076

**Occurrences:** ~55

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 121076 and product instance null not found.
	at cz.kb.common.s`

### Card ID 62060

**Occurrences:** ~16

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62060 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 47028

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 47028 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62118

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62118 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62396

**Occurrences:** ~8

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62396 and product instance null not found.
	at cz.kb.common.sp`

