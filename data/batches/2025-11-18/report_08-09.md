# Detailed Trace-Based Root Cause Analysis Report

**Period:** 2025-11-18T08:00:00 → 2025-11-18T09:00:00

> 📌 This report focuses on **concrete, actionable root causes** extracted from trace analysis.
> Generic messages like 'Error handler threw exception' are replaced with specific issues.

## 📊 Overview

- **Total Errors:** 285
- **Unique Trace IDs:** 69
- **Unique Root Causes:** 27
- **Avg errors per trace:** 4.1
- **Analysis method:** Trace-ID based (first error in chain = root cause)

## 🎯 App Impact Distribution

- **bl-pcb-v1**:   211 errors ( 74.0%) █████████████████████████████████████ 🔴 PRIMARY
- **bl-pcb-event-processor-relay-v1**:    23 errors (  8.1%) ████░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-batch-processor-v1**:    22 errors (  7.7%) ███░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-v1-processing**:     7 errors (  2.5%) █░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-click2pay-v1**:     6 errors (  2.1%) █░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-billing-v1**:     4 errors (  1.4%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-atm-locator-v1**:     4 errors (  1.4%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-card-georisk-v1**:     3 errors (  1.1%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-client-rainbow-status-v1**:     2 errors (  0.7%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-document-signing-v1**:     2 errors (  0.7%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-design-lifecycle-v1**:     1 errors (  0.4%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY

## 🔗 Namespace Distribution

- **pcb-sit-01-app**:   113 errors ( 39.6%) █████████░░░░░░░░░░░░░░░░ ✅ Balanced
- **pcb-dev-01-app**:    63 errors ( 22.1%) █████░░░░░░░░░░░░░░░░░░░░ ✅ Balanced
- **pcb-fat-01-app**:    59 errors ( 20.7%) █████░░░░░░░░░░░░░░░░░░░░ ✅ Balanced
- **pcb-uat-01-app**:    50 errors ( 17.5%) ████░░░░░░░░░░░░░░░░░░░░░ ⚠️  Imbalanced

## 🔍 Concrete Root Causes (Top 15)

### Sorted by Impact (Errors × Prevalence)

### ✅ Concrete Issues (Actionable)

#### 1. 🟠 HIGH Resource not found. Card with id 199999000199999000 and product instance null not found.

**Context:** Exception type: ServiceBusinessException

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 28 (9.8%)
- **Unique Traces:** 7
- **Time Range:** 2025-11-18 07:00:00.622000 → 2025-11-18 07:00:41.804000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `b7612ebe930740f388195215567d9820`, `fbfbb0e6723e4454a75f5a52ebd3ebc9`

#### 2. 🟠 HIGH SPEED-101: dogs-test.dslab.kb.cz to /v3/BE/api/cases/start failed

**Context:** External service call failed - /v3/BE/api/cases/start returned error

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 21 (7.4%)
- **Unique Traces:** 3
- **Time Range:** 2025-11-18 07:07:41.695000 → 2025-11-18 07:07:58.900000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-dev-01-app
- **Sample trace IDs:** `9a324306e401b92eec05f3458b0a2b78`, `fe64f3a741cca0eef6486a554cf317cf`

#### 3. 🟠 HIGH Resource not found. Card with id 62060 and product instance null not found.

**Context:** Exception type: ServiceBusinessException

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 20 (7.0%)
- **Unique Traces:** 4
- **Time Range:** 2025-11-18 07:06:46.679000 → 2025-11-18 07:06:56.691000
- **Propagated to:** bl-pcb-event-processor-relay-v1, bl-pcb-v1
- **Environments:** pcb-fat-01-app, pcb-sit-01-app, pcb-uat-01-app
- **Sample trace IDs:** `691c1b06f13945784b526912f9895923`, `691c1b068ae6d2c8724ac1f1d78c994f`

#### 4. 🟠 HIGH SQL value CERTIFICATE_OF_INSURANCE could not be converted to the enumeration value!

**Context:** Unknown cause - see full message

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 18 (6.3%)
- **Unique Traces:** 3
- **Time Range:** 2025-11-18 07:08:03.931000 → 2025-11-18 07:09:13.200000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-dev-01-app
- **Sample trace IDs:** `fb5c72f85c04cc5d50ad33ff10a3b4a0`, `1ef1782108095ac604d971147c96d2aa`

#### 5. 🟠 HIGH Resource not found. Card with id 121076 and product instance null not found.

**Context:** Exception type: ServiceBusinessException

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 18 (6.3%)
- **Unique Traces:** 3
- **Time Range:** 2025-11-18 07:08:46.968000 → 2025-11-18 07:08:47.158000
- **Propagated to:** bl-pcb-billing-v1, bl-pcb-event-processor-relay-v1, bl-pcb-v1
- **Environments:** pcb-dev-01-app, pcb-fat-01-app, pcb-uat-01-app
- **Sample trace IDs:** `691c1b7e37538e8abd841f6b5bdf6d65`, `691c1b7e49b1730fac50be6c2fa1d76b`

### ⚠️  Semi-Specific Issues (Needs investigation)

#### 1. 🔴 CRITICAL ServiceBusinessException error handled.

**Context:** Generic error - insufficient logging context

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 33 (11.6%)
- **Unique Traces:** 7
- **Time Range:** 2025-11-18 07:00:46.403000 → 2025-11-18 07:06:56.692000
- **Propagated to:** bl-pcb-event-processor-relay-v1, bl-pcb-v1
- **Environments:** pcb-fat-01-app, pcb-sit-01-app, pcb-uat-01-app
- **Sample trace IDs:** `fb7bc51c84454dabad0e26678115e1a2`, `569f05a5098c4871ae69de5e9d874a86`

#### 2. 🟡 MEDIUM An error occurred during job processing, job BatchJobIdentification(jobName=accountBalancesCzExport,

**Context:** Generic error - insufficient logging context

- **Source App:** `bl-pcb-batch-processor-v1`
- **Total Errors:** 14 (4.9%)
- **Unique Traces:** 7
- **Time Range:** 2025-11-18 07:00:02.113000 → 2025-11-18 07:35:02.073000
- **Propagated to:** bl-pcb-batch-processor-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `691c1972aabaa6d71eb112d150639d35`, `691c1a9debf7169cb543241718abc23c`

#### 3. 🟡 MEDIUM ITO-154: bl-pcb-client-rainbow-status-v1

**Context:** Service operation error - ITO-154 in bl-pcb-client-rainbow-status

- **Source App:** `bl-pcb-client-rainbow-status-v1`
- **Total Errors:** 10 (3.5%)
- **Unique Traces:** 1
- **Time Range:** 2025-11-18 07:00:03.656000 → 2025-11-18 07:30:04.463000
- **Propagated to:** bl-pcb-atm-locator-v1, bl-pcb-billing-v1, bl-pcb-card-georisk-v1
- **Environments:** pcb-dev-01-app

#### 4. 🟡 MEDIUM ITO-004: bl-pcb-v1

**Context:** Service operation error - ITO-004 in bl-pcb

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 8 (2.8%)
- **Unique Traces:** 1
- **Time Range:** 2025-11-18 07:03:13.574000 → 2025-11-18 07:03:13.701000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `800932b32e004f306132a90bf4076ed5`, `...`

#### 5. 🟡 MEDIUM There is not codelist value for key B4 in codelist CB_PaymentCardSpecsName and locale cs. Will not b

**Context:** Unknown cause - see full message

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 8 (2.8%)
- **Unique Traces:** 1
- **Time Range:** 2025-11-18 07:03:19.129000 → 2025-11-18 07:03:19.216000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `ad3ef05fc2d46005a3246feb02ee7906`, `...`


## 📋 Executive Summary

🎯 **PRIMARY ISSUE:** Resource not found. Card with id 199999000199999000 and product instance null not found.

- **Impact:** 28 errors (9.8%)
- **Source:** bl-pcb-v1
- **Affected apps:** bl-pcb-v1
- **Time window:** 2025-11-18 07:00:00.622000 → 2025-11-18 07:00:41.804000
- **Prevalence:** 7 unique traces

**Action items:**
1. Investigate root cause on bl-pcb-v1
2. Monitor for propagation to 
3. Check if this is a known issue or new

**Additional concrete issues:** 11 more actionable problems detected

**Requires deeper investigation:** 15 issues with generic error messages
*Recommendation: Examine individual trace chains for these.*

## 📈 Root Cause Specificity Breakdown

- 🎯 **Concrete (Actionable):** 12 causes (44%)
- ⚠️  **Semi-specific:** 15 causes (56%)
- ❓ **Generic (Needs investigation):** 0 causes (0%)

