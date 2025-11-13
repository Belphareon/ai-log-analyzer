# Daily Error Report

**Period:** 2025-11-12T14:15:00 → 2025-11-12T15:15:00

**Total Errors:** 163

**Sample Size:** 163 (100.0% coverage)

**Unique Patterns Found:** 6

---

## Top 20 Error Patterns

### 1. jakarta.ws.rs.NotFoundException: HTTP {ID} Not Found
	at org.glassfish.jersey.se

**Estimated Total:** ~46 occurrences

**Sample Count:** 46

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~46

**Sample Message:**
```
jakarta.ws.rs.NotFoundException: HTTP 404 Not Found
	at org.glassfish.jersey.server.ServerRuntime$1.run(ServerRuntime.java:271)
	at org.glassfish.jers
```

**First seen:** 2025-11-12 14:15:16.637000+00:00

**Last seen:** 2025-11-12 14:26:09.160000+00:00

---

### 2. NotFoundException error handled.

**Estimated Total:** ~46 occurrences

**Sample Count:** 46

**Affected Apps:** bl-pcb-v1

**Namespaces:**
- `pcb-sit-01-app`: ~46

**Sample Message:**
```
NotFoundException error handled.
```

**First seen:** 2025-11-12 14:15:16.638000+00:00

**Last seen:** 2025-11-12 14:26:09.160000+00:00

---

### 3. 

***************************
APPLICATION FAILED TO START
**********************

**Estimated Total:** ~4 occurrences

**Sample Count:** 4

**Affected Apps:** bl-pcb-v1-processing, bl-pcb-v1

**Namespaces:**
- `pcb-dev-01-app`: ~4

**Sample Message:**
```


***************************
APPLICATION FAILED TO START
***************************

Description:

Failed to bind properties under 'kb.speed.feature
```

**First seen:** 2025-11-12 14:19:38.485000+00:00

**Last seen:** 2025-11-12 14:25:22.218000+00:00

---

### 4. The header 'X-KB-Orig-System-Identity' is empty!!!

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

**First seen:** 2025-11-12 14:16:21.265000+00:00

**Last seen:** 2025-11-12 14:21:20.512000+00:00

---

### 5. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Events are too long in status

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1-processing

**Namespaces:**
- `pcb-uat-01-app`: ~1
- `pcb-dev-01-app`: ~1
- `pcb-sit-01-app`: ~1

**Sample Message:**
```
ITO-154#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#154#Events are too long in status REGISTERED.
```

**First seen:** 2025-11-12 14:25:01.280000+00:00

**Last seen:** 2025-11-12 14:25:03.623000+00:00

---

### 6. ITO-{ID}#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#{ID}#Events are too long in status

**Estimated Total:** ~3 occurrences

**Sample Count:** 3

**Affected Apps:** bl-pcb-v1-processing

**Namespaces:**
- `pcb-uat-01-app`: ~1
- `pcb-dev-01-app`: ~1
- `pcb-sit-01-app`: ~1

**Sample Message:**
```
ITO-154#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#154#Events are too long in status PROCESSING.
```

**First seen:** 2025-11-12 14:25:01.338000+00:00

**Last seen:** 2025-11-12 14:25:03.857000+00:00

---


---

## ⏰ Temporal Clusters - Error Bursts

Error bursts within 15-minute windows show potential cascading failures:

### Cluster 1: 2025-11-12T14:15:01.634000+00:00

**Burst Size:** ~163 errors (sample: 163)

**Affected Apps (7):** bl-pcb-v1, bl-pcb-notification-v1, bl-pcb-card-georisk-v1, bl-pcb-atm-locator-v1, bl-pcb-document-signing-v1, bl-pcb-v1-processing, bl-pcb-batch-processor-v1

**Namespaces:**
- `pcb-sit-01-app`: ~143
- `pcb-dev-01-app`: ~14
- `pcb-uat-01-app`: ~4

