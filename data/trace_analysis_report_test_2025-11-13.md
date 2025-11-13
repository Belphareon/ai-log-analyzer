# Detailed Trace-Based Root Cause Analysis Report

**Period:** 2025-11-12T08:30:00 → 2025-11-12T09:00:00

> 📌 This report focuses on **concrete, actionable root causes** extracted from trace analysis.
> Generic messages like 'Error handler threw exception' are replaced with specific issues.

## 📊 Overview

- **Total Errors:** 1,374
- **Unique Trace IDs:** 315
- **Unique Root Causes:** 91
- **Avg errors per trace:** 4.4
- **Analysis method:** Trace-ID based (first error in chain = root cause)

## 🎯 App Impact Distribution

- **bl-pcb-v1**:   835 errors ( 60.8%) ██████████████████████████████ 🔴 PRIMARY
- **bl-pcb-event-processor-relay-v1**:   177 errors ( 12.9%) ██████░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-card-client-segment-v1**:   116 errors (  8.4%) ████░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-document-signing-v1**:    80 errors (  5.8%) ██░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-dispute-v1**:    76 errors (  5.5%) ██░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-billing-v1**:    35 errors (  2.5%) █░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-batch-processor-v1**:    25 errors (  1.8%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-v1-processing**:    17 errors (  1.2%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-atm-locator-v1**:     8 errors (  0.6%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-click2pay-v1**:     4 errors (  0.3%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-design-lifecycle-v1**:     1 errors (  0.1%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY

## 🔗 Namespace Distribution

- **pcb-sit-01-app**:   640 errors ( 46.6%) ███████████░░░░░░░░░░░░░░ ⚠️  Imbalanced
- **pcb-dev-01-app**:   512 errors ( 37.3%) █████████░░░░░░░░░░░░░░░░ ✅ Balanced
- **pcb-uat-01-app**:   130 errors (  9.5%) ██░░░░░░░░░░░░░░░░░░░░░░░ ⚠️  Imbalanced
- **pcb-fat-01-app**:    92 errors (  6.7%) █░░░░░░░░░░░░░░░░░░░░░░░░ ⚠️  Imbalanced

## 🔍 Concrete Root Causes (Top 15)

### Sorted by Impact (Errors × Prevalence)

### ✅ Concrete Issues (Actionable)

#### 1. 🔴 CRITICAL SPEED-101: bc-accountservicing-v1.stage.nca.kbcloud to /api/accounts/account-servicing/v2/customers/970393538/current-accounts failed

**Context:** External service call failed - /api/accounts/account-servicing/v2/customers/970393538/current-accounts returned error

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 177 (12.9%)
- **Unique Traces:** 27
- **Time Range:** 2025-11-12 08:32:49.385000 → 2025-11-12 08:41:45.727000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-dev-01-app, pcb-sit-01-app
- **Sample trace IDs:** `f8816702a1bd879f92841beda8f8642d`, `cc7ba2edf2a82943d12bb151f0ef7630`

#### 2. 🟠 HIGH HTTP 404 Not Found

**Context:** HTTP 404 response from upstream service

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 132 (9.6%)
- **Unique Traces:** 44
- **Time Range:** 2025-11-12 08:31:12.457000 → 2025-11-12 08:59:41.418000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `e516d3f78c7511d1c61daf034b179450`, `9160e7e6fa24084a9a45028f0952f161`

#### 3. 🟡 MEDIUM Resource not found. Card with id 13000 and product instance null not found.

**Context:** Exception type: ServiceBusinessException

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 39 (2.8%)
- **Unique Traces:** 9
- **Time Range:** 2025-11-12 08:42:09.978000 → 2025-11-12 08:49:16.854000
- **Propagated to:** bl-pcb-event-processor-relay-v1, bl-pcb-v1
- **Environments:** pcb-dev-01-app, pcb-sit-01-app, pcb-uat-01-app
- **Sample trace IDs:** `69144a0c4097876023e30496fa88a924`, `69144a0c2f7e37b7ec3d303c5cd58f29`

#### 4. 🟡 MEDIUM SPEED-101: bl-pcb-v1.pcb-fat-01-app:9080 to /api/v1/card/13000 failed

**Context:** External service call failed - /api/v1/card/13000 returned error

- **Source App:** `bl-pcb-event-processor-relay-v1`
- **Total Errors:** 39 (2.8%)
- **Unique Traces:** 23
- **Time Range:** 2025-11-12 08:30:28.070000 → 2025-11-12 08:49:16.800000
- **Propagated to:** bl-pcb-billing-v1, bl-pcb-event-processor-relay-v1, bl-pcb-v1-processing
- **Environments:** pcb-fat-01-app
- **Sample trace IDs:** `69144a0c3f8947cfcef7e5e95bb9744e`, `691448bcf3b47b76e4245d642a870650`

#### 5. 🟡 MEDIUM SPEED-101: dogs-test.dslab.kb.cz to /v3/BE/api/cases/start failed

**Context:** External service call failed - /v3/BE/api/cases/start returned error

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 30 (2.2%)
- **Unique Traces:** 5
- **Time Range:** 2025-11-12 08:37:31.952000 → 2025-11-12 08:38:03.282000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `af3e9f2a19551397fa94a69bd7ff4cbd`, `0a7ef19f1eac0c82bda8541b337ca33d`

### ⚠️  Semi-Specific Issues (Needs investigation)

#### 1. 🔴 CRITICAL Application startup context failed

**Context:** Failed to start application context during boot - check configuration and dependencies

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 195 (14.2%)
- **Unique Traces:** 1
- **Time Range:** 2025-11-12 08:33:08.890000 → 2025-11-12 08:58:15.398000
- **Propagated to:** bl-pcb-atm-locator-v1, bl-pcb-billing-v1, bl-pcb-dispute-v1
- **Environments:** pcb-fat-01-app

#### 2. 🟡 MEDIUM Resource not found (404)

**Context:** Resource lookup failed - endpoint or entity not found

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 60 (4.4%)
- **Unique Traces:** 20
- **Time Range:** 2025-11-12 08:31:20.378000 → 2025-11-12 08:59:47.760000
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `cd71911d0f5885187bb9539c01b2c8f3`, `e435bcef67714b58030a1e280dd6a9ae`

#### 3. 🟡 MEDIUM SPEED-100#PCBS#bl-pcb-dispute#bl-pcb-dispute-v1#DocflowRequestServicePortType#completeValidation#500

**Context:** Generic error - insufficient logging context

- **Source App:** `bl-pcb-dispute-v1`
- **Total Errors:** 38 (2.8%)
- **Unique Traces:** 19
- **Time Range:** 2025-11-12 08:55:49.800000 → 2025-11-12 08:56:35.845000
- **Propagated to:** bl-pcb-dispute-v1
- **Environments:** pcb-dev-01-app, pcb-sit-01-app
- **Sample trace IDs:** `3f6b5f94eab83c787896650436ddf164`, `b1418ff8851596ceed59039e9775b26b`

#### 4. 🟡 MEDIUM Cannot access card case document for msc signing case id 3b3c38a1-66ac-4a87-8f28-68be52df6ae8 and us

**Context:** Unknown cause - see full message

- **Source App:** `bl-pcb-document-signing-v1`
- **Total Errors:** 36 (2.6%)
- **Unique Traces:** 6
- **Time Range:** 2025-11-12 08:44:24.633000 → 2025-11-12 08:49:47.491000
- **Propagated to:** bl-pcb-document-signing-v1
- **Environments:** pcb-dev-01-app, pcb-sit-01-app
- **Sample trace IDs:** `a563536e33519a82f7e2d9ab218d5617`, `d167de74979d8d7aad88589948107b6f`

#### 5. 🟡 MEDIUM ServiceBusinessException error handled.

**Context:** Generic error - insufficient logging context

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 23 (1.7%)
- **Unique Traces:** 4
- **Time Range:** 2025-11-12 08:30:38.247000 → 2025-11-12 08:54:51.790000
- **Propagated to:** bl-pcb-billing-v1, bl-pcb-event-processor-relay-v1, bl-pcb-v1
- **Environments:** pcb-dev-01-app, pcb-sit-01-app, pcb-uat-01-app
- **Sample trace IDs:** `c82912b42d461b16ba571bf685aa87de`, `6914473f7a0043755f4166bd05449cdc`


## 📋 Executive Summary

🎯 **PRIMARY ISSUE:** SPEED-101: bc-accountservicing-v1.stage.nca.kbcloud to /api/accounts/account-servicing/v2/customers/970393538/current-accounts failed

- **Impact:** 177 errors (12.9%)
- **Source:** bl-pcb-v1
- **Affected apps:** bl-pcb-v1
- **Time window:** 2025-11-12 08:32:49.385000 → 2025-11-12 08:41:45.727000
- **Prevalence:** 27 unique traces

**Action items:**
1. Investigate root cause on bl-pcb-v1
2. Monitor for propagation to 
3. Check if this is a known issue or new

**Additional concrete issues:** 29 more actionable problems detected

**Requires deeper investigation:** 61 issues with generic error messages
*Recommendation: Examine individual trace chains for these.*

## 📈 Root Cause Specificity Breakdown

- 🎯 **Concrete (Actionable):** 30 causes (33%)
- ⚠️  **Semi-specific:** 61 causes (67%)
- ❓ **Generic (Needs investigation):** 0 causes (0%)

