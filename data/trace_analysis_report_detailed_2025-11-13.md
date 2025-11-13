# Detailed Trace-Based Root Cause Analysis Report

**Period:** 2025-11-12T14:15:00 → 2025-11-12T15:15:00

> 📌 This report focuses on **concrete, actionable root causes** extracted from trace analysis.
> Generic messages like 'Error handler threw exception' are replaced with specific issues.

## 📊 Overview

- **Total Errors:** 163
- **Unique Trace IDs:** 57
- **Unique Root Causes:** 13
- **Avg errors per trace:** 2.9
- **Analysis method:** Trace-ID based (first error in chain = root cause)

## 🎯 App Impact Distribution

- **bl-pcb-v1**:   140 errors ( 85.9%) ██████████████████████████████████████████ 🔴 PRIMARY
- **bl-pcb-v1-processing**:     8 errors (  4.9%) ██░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-atm-locator-v1**:     4 errors (  2.5%) █░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-notification-v1**:     4 errors (  2.5%) █░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-batch-processor-v1**:     3 errors (  1.8%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-card-georisk-v1**:     2 errors (  1.2%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY
- **bl-pcb-document-signing-v1**:     2 errors (  1.2%) ░░░░░░░░░░░░░░░░░░░░░░░░░ 🟢 TERTIARY

## 🔗 Namespace Distribution

- **pcb-sit-01-app**:   143 errors ( 87.7%) █████████████████████░░░░ ⚠️  Imbalanced
- **pcb-dev-01-app**:    14 errors (  8.6%) ██░░░░░░░░░░░░░░░░░░░░░░░ ⚠️  Imbalanced
- **pcb-uat-01-app**:     4 errors (  2.5%) ░░░░░░░░░░░░░░░░░░░░░░░░░ ⚠️  Imbalanced
- **pcb-fat-01-app**:     2 errors (  1.2%) ░░░░░░░░░░░░░░░░░░░░░░░░░ ⚠️  Imbalanced

## 🔍 Concrete Root Causes (Top 13)

### Sorted by Impact (Errors × Prevalence)

### ✅ Concrete Issues (Actionable)

#### 1. 🔴 CRITICAL HTTP 404 Not Found

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 90 (55.2%)
- **Unique Traces:** 30
- **Time Range:** 2025-11-12 14:15:16.637000+00:00 → 2025-11-12 14:25:56.459000+00:00
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `7b84bd49fea1cccccfee314519999e82`, `55f7bb384b6c829ef82b72916673292d`

### ⚠️  Semi-Specific Issues (Needs investigation)

#### 1. 🔴 CRITICAL Resource not found (404)

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 30 (18.4%)
- **Unique Traces:** 10
- **Time Range:** 2025-11-12 14:15:27.590000+00:00 → 2025-11-12 14:25:35.980000+00:00
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `a35b6fb632f4909e28f350dd4daef3d4`, `614a6a04cff4d6968ad7d56f4c56b0f3`

#### 2. 🟠 HIGH The header 'X-KB-Orig-System-Identity' is empty!!!

- **Source App:** `bl-pcb-atm-locator-v1`
- **Total Errors:** 10 (6.1%)
- **Unique Traces:** 1
- **Time Range:** 2025-11-12 14:16:21.265000+00:00 → 2025-11-12 14:25:22.218000+00:00
- **Propagated to:** bl-pcb-atm-locator-v1, bl-pcb-card-georisk-v1, bl-pcb-v1
- **Environments:** pcb-dev-01-app

#### 3. 🟡 MEDIUM ITO-154: bl-pcb-v1

- **Source App:** `bl-pcb-v1-processing`
- **Total Errors:** 6 (3.7%)
- **Unique Traces:** 3
- **Time Range:** 2025-11-12 14:25:01.280000+00:00 → 2025-11-12 14:25:03.857000+00:00
- **Propagated to:** bl-pcb-v1-processing
- **Environments:** pcb-dev-01-app, pcb-sit-01-app, pcb-uat-01-app
- **Sample trace IDs:** `691498bda3ef43d62c3b8158cfcc4e6a`, `691498bd2089f795a3f7773d075a9856`

#### 4. 🟡 MEDIUM ITO-156: bl-pcb-notification-v1

- **Source App:** `bl-pcb-notification-v1`
- **Total Errors:** 4 (2.5%)
- **Unique Traces:** 4
- **Time Range:** 2025-11-12 14:15:01.634000+00:00 → 2025-11-12 14:15:02.859000+00:00
- **Propagated to:** bl-pcb-notification-v1
- **Environments:** pcb-dev-01-app, pcb-fat-01-app, pcb-sit-01-app, pcb-uat-01-app
- **Sample trace IDs:** `691496652c242177167740f1bb107d79`, `691496652e58b816119b148c274d0d2e`

#### 5. 🟡 MEDIUM The required entity was not f

- **Source App:** `bl-pcb-v1`
- **Total Errors:** 3 (1.8%)
- **Unique Traces:** 1
- **Time Range:** 2025-11-12 14:26:09.160000+00:00 → 2025-11-12 14:26:09.160000+00:00
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-sit-01-app
- **Sample trace IDs:** `c29c357ddd0e65064a26c71a656162c8`, `...`


## 📋 Executive Summary

🎯 **PRIMARY ISSUE:** HTTP 404 Not Found

- **Impact:** 90 errors (55.2%)
- **Source:** bl-pcb-v1
- **Affected apps:** bl-pcb-v1
- **Time window:** 2025-11-12 14:15:16.637000+00:00 → 2025-11-12 14:25:56.459000+00:00
- **Prevalence:** 30 unique traces

**Action items:**
1. Investigate root cause on bl-pcb-v1
2. Monitor for propagation to 
3. Check if this is a known issue or new

**Requires deeper investigation:** 12 issues with generic error messages
*Recommendation: Examine individual trace chains for these.*

## 📈 Root Cause Specificity Breakdown

- 🎯 **Concrete (Actionable):** 1 causes (8%)
- ⚠️  **Semi-specific:** 12 causes (92%)
- ❓ **Generic (Needs investigation):** 0 causes (0%)

