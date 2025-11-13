# Daily Error Report

**Period:** 2025-11-13T08:41:00Z → 2025-11-13T09:41:00Z

**Total Errors:** 9,397

**Sample Size:** 5,000 (53.2% coverage)

**Unique Patterns Found:** 104

---

## Top 20 Error Patterns

### 1. 🟠 AccessDeniedException error handled.

**Severity:** HIGH

**Impact:** 894 errors across 5 app(s) in 2 environment(s)

**Trace Context:** 476 unique request(s) tracked

**Estimated Total:** ~894 occurrences

**Sample Count:** 476

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bl-pcb-document-signing-v1, bff-pcb-ch-card-servicing-admin-v1, bl-pcb-v1, bff-pcb-ch-card-validation-v1

**Namespaces:**
- `pcb-ch-sit-01-app`: ~864
- `pcb-sit-01-app`: ~30

**Sample Message:**
```
AccessDeniedException error handled.
```

**First seen:** 2025-11-13T09:12:23.899Z

**Last seen:** 2025-11-13T09:13:45.222Z

---

### 2. 🟠 SPEED-{ID}#PCB#bl-pcb-token#bl-pcb-token-v1#{UUID}#null##INCOMING MESSAGE ERROR#

**Severity:** HIGH

**Impact:** 796 errors across 1 app(s) in 3 environment(s)

**Trace Context:** 6 unique request(s) tracked

**Estimated Total:** ~796 occurrences

**Sample Count:** 424

**Affected Apps:** bl-pcb-token-v1

**Namespaces:**
- `pcb-uat-01-app`: ~266
- `pcb-dev-01-app`: ~264
- `pcb-fat-01-app`: ~264

**Sample Message:**
```
SPEED-304#PCB#bl-pcb-token#bl-pcb-token-v1#35d240d3-bc3d-4e1e-9c72-cd49e2662d3e#null##INCOMING MESSAGE ERROR#text
```

**First seen:** 2025-11-13T09:08:23.322Z

**Last seen:** 2025-11-13T09:20:10.850Z

---

### 3. 🟠 Error occurred during message processing. Created exception for message with id 

**Severity:** HIGH

**Impact:** 796 errors across 1 app(s) in 3 environment(s)

**Trace Context:** 6 unique request(s) tracked

**Estimated Total:** ~796 occurrences

**Sample Count:** 424

**Affected Apps:** bl-pcb-token-v1

**Namespaces:**
- `pcb-uat-01-app`: ~266
- `pcb-dev-01-app`: ~264
- `pcb-fat-01-app`: ~264

**Sample Message:**
```
Error occurred during message processing. Created exception for message with id '35d240d3-bc3d-4e1e-9c72-cd49e2662d3e' with error: text
```

**First seen:** 2025-11-13T09:08:23.331Z

**Last seen:** 2025-11-13T09:20:10.851Z

---

### 4. 🟠 Error handler threw an exception

**Severity:** HIGH

**Impact:** 791 errors across 1 app(s) in 3 environment(s)

**Estimated Total:** ~791 occurrences

**Sample Count:** 421

**Affected Apps:** bl-pcb-token-v1

**Namespaces:**
- `pcb-uat-01-app`: ~264
- `pcb-dev-01-app`: ~263
- `pcb-fat-01-app`: ~263

**Sample Message:**
```
Error handler threw an exception
```

**First seen:** 2025-11-13T09:08:28.360Z

**Last seen:** 2025-11-13T09:20:10.846Z

---

### 5. 🟠 org.springframework.security.access.AccessDeniedException: Access is denied
	at 

**Severity:** HIGH

**Impact:** 522 errors across 5 app(s) in 1 environment(s)

**Trace Context:** 278 unique request(s) tracked

**Estimated Total:** ~522 occurrences

**Sample Count:** 278

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bff-pcb-ch-card-validation-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~522

**Sample Message:**
```
org.springframework.security.access.AccessDeniedException: Access is denied
	at org.springframework.security.access.vote.AffirmativeBased.decide(Affir
```

**First seen:** 2025-11-13T09:12:24.824Z

**Last seen:** 2025-11-13T09:13:44.124Z

---

### 6. 🟠 ServiceBusinessException error handled.

**Severity:** HIGH

**Impact:** 409 errors across 5 app(s) in 6 environment(s)

**Trace Context:** 214 unique request(s) tracked

**Estimated Total:** ~409 occurrences

**Sample Count:** 218

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bl-pcb-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~264
- `pcb-fat-01-app`: ~33
- `pcb-uat-01-app`: ~33
- `pcb-sit-01-app`: ~31
- `pcb-dev-01-app`: ~26
- `pca-dev-01-app`: ~18

**Sample Message:**
```
ServiceBusinessException error handled.
```

**First seen:** 2025-11-13T08:51:08.086Z

**Last seen:** 2025-11-13T09:13:45.355Z

---

### 7. 🟡 jakarta.ws.rs.NotFoundException: HTTP {STATUS} Not Found
	at org.glassfish.jerse

**Severity:** MEDIUM

**Impact:** 281 errors across 1 app(s) in 1 environment(s)

**Trace Context:** 150 unique request(s) tracked

**Estimated Total:** ~281 occurrences

**Sample Count:** 150

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~281

**Sample Message:**
```
jakarta.ws.rs.NotFoundException: HTTP 404 Not Found
	at org.glassfish.jersey.server.ServerRuntime$1.run(ServerRuntime.java:271)
	at org.glassfish.jers
```

**First seen:** 2025-11-13T08:41:35.902Z

**Last seen:** 2025-11-13T09:20:10.101Z

---

### 8. 🟡 NotFoundException error handled.

**Severity:** MEDIUM

**Impact:** 281 errors across 1 app(s) in 1 environment(s)

**Trace Context:** 150 unique request(s) tracked

**Estimated Total:** ~281 occurrences

**Sample Count:** 150

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~281

**Sample Message:**
```
NotFoundException error handled.
```

**First seen:** 2025-11-13T08:41:35.903Z

**Last seen:** 2025-11-13T09:20:10.101Z

---

### 9. 🟡 An error occurred in the handler 'cz.kb.speed.messaging.core.handlerholder.Refle

**Severity:** MEDIUM

**Impact:** 266 errors across 1 app(s) in 1 environment(s)

**Trace Context:** 2 unique request(s) tracked

**Estimated Total:** ~266 occurrences

**Sample Count:** 142

**Affected Apps:** bl-pcb-token-v1

**Namespaces:**
- `pcb-uat-01-app`: ~266

**Sample Message:**
```
An error occurred in the handler 'cz.kb.speed.messaging.core.handlerholder.ReflectionInvocationHandler@68403d09[bean=cz.kb.pcb.token.event.tokenized.C
```

**First seen:** 2025-11-13T09:08:23.477Z

**Last seen:** 2025-11-13T09:20:10.850Z

---

### 10. 🟡 An error occurred in the handler 'cz.kb.speed.messaging.core.handlerholder.Refle

**Severity:** MEDIUM

**Impact:** 264 errors across 1 app(s) in 1 environment(s)

**Trace Context:** 2 unique request(s) tracked

**Estimated Total:** ~264 occurrences

**Sample Count:** 141

**Affected Apps:** bl-pcb-token-v1

**Namespaces:**
- `pcb-dev-01-app`: ~264

**Sample Message:**
```
An error occurred in the handler 'cz.kb.speed.messaging.core.handlerholder.ReflectionInvocationHandler@6297b104[bean=cz.kb.pcb.token.event.tokenized.C
```

**First seen:** 2025-11-13T09:08:23.310Z

**Last seen:** 2025-11-13T09:20:06.205Z

---

### 11. 🟡 An error occurred in the handler 'cz.kb.speed.messaging.core.handlerholder.Refle

**Severity:** MEDIUM

**Impact:** 264 errors across 1 app(s) in 1 environment(s)

**Trace Context:** 2 unique request(s) tracked

**Estimated Total:** ~264 occurrences

**Sample Count:** 141

**Affected Apps:** bl-pcb-token-v1

**Namespaces:**
- `pcb-fat-01-app`: ~264

**Sample Message:**
```
An error occurred in the handler 'cz.kb.speed.messaging.core.handlerholder.ReflectionInvocationHandler@6373a753[bean=cz.kb.pcb.token.event.tokenized.C
```

**First seen:** 2025-11-13T09:08:23.462Z

**Last seen:** 2025-11-13T09:20:06.716Z

---

### 12. 🟡 Mismatch between token scopes [directbanking.common] and required scopes [author

**Severity:** MEDIUM

**Impact:** 176 errors across 5 app(s) in 1 environment(s)

**Trace Context:** 94 unique request(s) tracked

**Estimated Total:** ~176 occurrences

**Sample Count:** 94

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-init-v1, bff-pcb-ch-click2pay-v1

**Namespaces:**
- `pcb-ch-sit-01-app`: ~176

**Sample Message:**
```
Mismatch between token scopes [directbanking.common] and required scopes [authorize], operation not allowed.
```

**First seen:** 2025-11-13T09:12:24.823Z

**Last seen:** 2025-11-13T09:13:39.512Z

---

### 13. 🟡 cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Missing

**Severity:** MEDIUM

**Impact:** 157 errors across 5 app(s) in 1 environment(s)

**Trace Context:** 84 unique request(s) tracked

**Estimated Total:** ~157 occurrences

**Sample Count:** 84

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-init-v1, bff-pcb-ch-card-opening-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~157

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Missing required attribute user id.
	at cz.kb.common.speed.exception.ServiceB
```

**First seen:** 2025-11-13T09:12:24.535Z

**Last seen:** 2025-11-13T09:13:40.291Z

---

### 14. 🟡 The Decision server return status code: {ID}

**Severity:** MEDIUM

**Impact:** 131 errors across 5 app(s) in 2 environment(s)

**Trace Context:** 58 unique request(s) tracked

**Estimated Total:** ~131 occurrences

**Sample Count:** 70

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bl-pcb-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~125
- `pcb-sit-01-app`: ~5

**Sample Message:**
```
The Decision server return status code: 401
```

**First seen:** 2025-11-13T09:12:28.759Z

**Last seen:** 2025-11-13T09:13:44.430Z

---

### 15. 🟡 org.springframework.security.access.AccessDeniedException: Unable to perform cal

**Severity:** MEDIUM

**Impact:** 107 errors across 5 app(s) in 2 environment(s)

**Trace Context:** 57 unique request(s) tracked

**Estimated Total:** ~107 occurrences

**Sample Count:** 57

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bl-pcb-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~103
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
org.springframework.security.access.AccessDeniedException: Unable to perform call to PDP. Error: Unable to resolve authorization status. The Decision 
```

**First seen:** 2025-11-13T09:12:28.762Z

**Last seen:** 2025-11-13T09:13:44.432Z

---

### 16. 🟢 cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Missing

**Severity:** LOW

**Impact:** 99 errors across 5 app(s) in 1 environment(s)

**Trace Context:** 53 unique request(s) tracked

**Estimated Total:** ~99 occurrences

**Sample Count:** 53

**Affected Apps:** bff-pcb-ch-click2pay-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v2, bff-pcb-ch-card-servicing-init-v1, bff-pcb-ch-card-servicing-notice-v1

**Namespaces:**
- `pcb-ch-sit-01-app`: ~99

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Validation error. Missing required attribute card id.
	at cz.kb.common.speed.exception.ServiceB
```

**First seen:** 2025-11-13T09:12:51.831Z

**Last seen:** 2025-11-13T09:13:45.355Z

---

### 17. 🟠 cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card 

**Severity:** HIGH

**Impact:** 90 errors across 1 app(s) in 4 environment(s)

**Trace Context:** 48 unique request(s) tracked

**Estimated Total:** ~90 occurrences

**Sample Count:** 48

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-fat-01-app`: ~33
- `pcb-uat-01-app`: ~33
- `pcb-dev-01-app`: ~18
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 87684 and product instance null not found.
	at cz.kb.common.sp
```

**First seen:** 2025-11-13T08:51:08.079Z

**Last seen:** 2025-11-13T09:08:30.268Z

---

### 18. 🟢 Mismatch between token scopes [invalid.scope] and required scopes [directbanking

**Severity:** LOW

**Impact:** 90 errors across 5 app(s) in 1 environment(s)

**Trace Context:** 48 unique request(s) tracked

**Estimated Total:** ~90 occurrences

**Sample Count:** 48

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-init-v1, bff-pcb-ch-card-opening-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~90

**Sample Message:**
```
Mismatch between token scopes [invalid.scope] and required scopes [directbanking.common], operation not allowed.
```

**First seen:** 2025-11-13T09:12:26.785Z

**Last seen:** 2025-11-13T09:13:35.789Z

---

### 19. 🟢 Mismatch between token scopes [invalid.scope] and required scopes [directbanking

**Severity:** LOW

**Impact:** 82 errors across 5 app(s) in 1 environment(s)

**Trace Context:** 44 unique request(s) tracked

**Estimated Total:** ~82 occurrences

**Sample Count:** 44

**Affected Apps:** bff-pcb-ch-card-validation-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-v2, bff-pcb-ch-card-opening-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~82

**Sample Message:**
```
Mismatch between token scopes [invalid.scope] and required scopes [directbanking.common, mujklient_web], operation not allowed.
```

**First seen:** 2025-11-13T09:12:26.619Z

**Last seen:** 2025-11-13T09:13:44.123Z

---

### 20. 🟢 org.springframework.security.access.AccessDeniedException: [{"name":"CutOff - Lo

**Severity:** LOW

**Impact:** 75 errors across 5 app(s) in 2 environment(s)

**Trace Context:** 40 unique request(s) tracked

**Estimated Total:** ~75 occurrences

**Sample Count:** 40

**Affected Apps:** bff-pcb-ch-card-servicing-notice-v1, bl-pcb-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-servicing-v1, bff-pcb-ch-card-servicing-v2

**Namespaces:**
- `pcb-ch-sit-01-app`: ~71
- `pcb-sit-01-app`: ~3

**Sample Message:**
```
org.springframework.security.access.AccessDeniedException: [{"name":"CutOff - Low security level","code":"LOW_AUTH_LEVEL","payload":"Security level of
```

**First seen:** 2025-11-13T09:12:32.651Z

**Last seen:** 2025-11-13T09:13:45.221Z

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-13T09:12:31.322000+00:00

**Burst Size:** ~6,284 errors (sample: 3344)

**Affected Apps (17):** bff-pcb-ch-card-servicing-notice-v1, bl-pcb-batch-processor-v1, bl-pcb-v1, bl-pcb-document-signing-v1, bff-pcb-ch-card-servicing-admin-v1, bff-pcb-ch-card-validation-v1, bl-pcb-notification-v1, bff-pcb-ch-card-servicing-v1, bl-pcb-atm-locator-v1, bl-pcb-token-v1

**Namespaces:**
- `pcb-ch-sit-01-app`: ~3,802
- `pcb-dev-01-app`: ~699
- `pcb-uat-01-app`: ~695

### Cluster 2: 2025-11-13T08:57:31.284000+00:00

**Burst Size:** ~2,770 errors (sample: 1474)

**Affected Apps (11):** bl-pcb-batch-processor-v1, bl-pcb-design-lifecycle-v1, bl-pcb-v1, bl-pcb-pilot-context-v1, bff-pcb-ch-card-servicing-v1, bl-pcb-event-processor-relay-v1, bl-pcb-client-rainbow-status-v1, bl-pcb-token-v1, feapi-pca-v1, bl-pcb-click2pay-v1

**Namespaces:**
- `pcb-dev-01-app`: ~612
- `pcb-fat-01-app`: ~516
- `pcb-uat-01-app`: ~514

### Cluster 3: 2025-11-13T08:41:35.902000+00:00

**Burst Size:** ~342 errors (sample: 182)

**Affected Apps (5):** bl-pcb-batch-processor-v1, bl-pcb-design-lifecycle-v1, bl-pcb-v1, bl-pcb-event-processor-relay-v1, bl-pcb-click2pay-v1

**Namespaces:**
- `pcb-sit-01-app`: ~302
- `pcb-dev-01-app`: ~22
- `pcb-fat-01-app`: ~9


---

## �🔗 Related Errors - Case IDs

Errors grouped by Case ID show error chains and processing failures:

### Case ID 2245

**Occurrences:** ~46 (sample: 25)

**Affected Namespaces:**
- `pcb-sit-01-app`: ~37
- `pcb-ch-sit-01-app`: ~9

**Error Chain (7 unique patterns):**
1. (~9x) `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Case 2245 was not found.
	at cz.kb.common.spe...`
2. (~9x) `Cannot finish card case 2245 by user 970564704....`
3. (~5x) `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@32983602[category=15,code=err.103,originalCode=<null>,...`


---

## 💳 Related Errors - Card IDs

### Card ID 121076

**Occurrences:** ~157

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 121076 and product instance null not found.
	at cz.kb.common.s`

### Card ID 3

**Occurrences:** ~67

**Sample:** `Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6ae8 and user 970976514.`

### Card ID 62060

**Occurrences:** ~45

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 62060 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 47028

**Occurrences:** ~30

**Sample:** `cz.kb.common.speed.exception.ServiceBusinessException: Resource not found. Card with id 47028 and product instance null not found.
	at cz.kb.common.sp`

### Card ID 62118

**Occurrences:** ~30

**Sample:** `Handle fault. Error: cz.kb.speed.exception.error.model.ErrorModel@5e7766d0[category=15,code=err.103,originalCode=<null>,message=Resource not found. Ca`

