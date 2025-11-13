# AI Log Analyzer - Scripts Documentation

## Universal Data Fetching & Analysis Scripts

### 1. `fetch_errors.py` - Universal ES Error Fetcher

Fetches errors from Elasticsearch for any date range.

**Usage:**
```bash
python3 fetch_errors.py \
  --from "2025-11-04T00:00:00" \
  --to "2025-11-05T00:00:00" \
  --max-sample 30000 \
  --output /tmp/daily_2025-11-04.json
```

**Parameters:**
- `--from`: Start date (ISO format)
- `--to`: End date (ISO format)
- `--max-sample`: Maximum sample size (default: 50000)
- `--output`: Output JSON file path

**Output Format:**
```json
{
  "period_start": "2025-11-04T00:00:00",
  "period_end": "2025-11-05T00:00:00",
  "total_errors": 63249,
  "sample_size": 30000,
  "coverage_percent": 47.4,
  "errors": [...]
}
```

---

### 2. `analyze_daily.py` - Daily Report Generator

Analyzes fetched errors and generates markdown report.

**Usage:**
```bash
python3 analyze_daily.py \
  --input /tmp/daily_2025-11-04.json \
  --output /tmp/report_2025-11-04.md
```

**Parameters:**
- `--input`: Input JSON file (from fetch_errors.py)
- `--output`: Output markdown report

**Report Includes:**
- Total errors & coverage statistics
- Top 20 error patterns
- Namespace breakdown (which environments affected)
- Error codes
- Affected applications
- Sample messages
- First/last seen timestamps

---

### 3. Batch Processing

**Fetch all days in a week:**
```bash
#!/bin/bash
for DAY in 2025-11-{04..10}; do
  NEXT=$(date -d "$DAY + 1 day" +%Y-%m-%d)
  python3 fetch_errors.py \
    --from "${DAY}T00:00:00" \
    --to "${NEXT}T00:00:00" \
    --max-sample 30000 \
    --output "/tmp/daily_${DAY}.json"
done
```

**Generate all reports:**
```bash
for JSON in /tmp/daily_*.json; do
  DAY=$(basename $JSON .json | cut -d_ -f2)
  python3 analyze_daily.py \
    --input "$JSON" \
    --output "/tmp/report_${DAY}.md"
done
```

---

## API Endpoints

### Weekly Trends
```bash
curl "http://localhost:8000/api/v1/trends/weekly?days=7&max_sample=50000"
```

**Response includes:**
- Recurring vs new issues
- Known issues (top 30)
- Namespace breakdown
- Coverage statistics
- Recommendations

---

## Trace-Based Root Cause Analysis

### 4. `trace_extractor.py` - Extract Root Causes from Traces

Groups errors by trace_id to identify root causes. The first error in a trace chain is the root cause.

**Usage:**
```bash
python3 trace_extractor.py \
  --input /tmp/daily_2025-11-12.json \
  --output /tmp/root_causes.json
```

**Parameters:**
- `--input`: Input JSON file (from fetch_errors.py)
- `--output`: Output JSON with extracted root causes

**Output Format:**
```json
{
  "period_start": "2025-11-12T00:00:00",
  "period_end": "2025-11-12T00:00:00",
  "stats": {
    "total_errors": 1374,
    "total_traces": 315,
    "app_distribution": {"bl-pcb-v1": 835, ...},
    "namespace_distribution": {"pcb-sit-01-app": 640, ...}
  },
  "root_causes": [
    {
      "rank": 1,
      "message": "SPEED-101#PCB#...",
      "app": "bl-pcb-v1",
      "errors_count": 177,
      "errors_percent": 12.9,
      "trace_ids_count": 27,
      "first_seen": "2025-11-12T08:32:49.385000",
      "last_seen": "2025-11-12T08:41:45.727000",
      ...
    }
  ]
}
```

**Key Features:**
- Groups errors by trace_id
- Extracts root cause (first error in each trace)
- Calculates impact (error count, affected apps/namespaces)
- Generates statistics for analysis

---

### 5. `trace_report_detailed.py` - Generate Root Cause Report

Creates detailed markdown report with concrete, actionable root causes extracted from error messages.

**Usage:**
```bash
python3 trace_report_detailed.py \
  --input /tmp/root_causes.json \
  --output /tmp/root_cause_report.md
```

**Parameters:**
- `--input`: Input JSON (from trace_extractor.py)
- `--output`: Output markdown report

**Report Structure:**
- **Overview**: Total errors, traces, root causes, analysis method
- **App Impact Distribution**: PRIMARY/SECONDARY/TERTIARY apps with severity
- **Namespace Distribution**: Balanced vs Imbalanced breakdown
- **Concrete Root Causes**: Top actionable issues with context
- **Semi-Specific Issues**: Issues needing investigation
- **Generic Issues**: Insufficient information (marked for manual review)
- **Executive Summary**: Primary issue + action items
- **Specificity Breakdown**: Percentage of concrete/semi-specific/generic causes

**Root Cause Extraction (15+ patterns):**
- SPEED-XXX service errors: "SPEED-101: bc-accountservicing-v1 to /api/accounts/.../current-accounts failed"
- HTTP errors: "HTTP 404 Not Found", "HTTP 403 Forbidden"
- Business exceptions: "Resource not found. Card with id 13000"
- Validation errors: "ConstraintViolationException: validate.toValid.context..."
- Service errors: "DoGS case management service error"
- Startup errors: "Failed Jersey auto-config during startup"

**Each root cause includes:**
- Severity indicator (🔴🟠🟡🟢)
- Concrete description (not generic)
- Context: Why this error occurred
- Impact: Error count, affected apps, namespaces
- Time range: When it happened
- Sample trace IDs: For manual investigation

**Example Output:**
```markdown
#### 1. 🔴 CRITICAL SPEED-101: bc-accountservicing-v1 to /api/accounts/.../current-accounts failed

**Context:** Authorization failure - missing/invalid credentials for downstream service

- **Source App:** bl-pcb-v1
- **Total Errors:** 177 (12.9%)
- **Unique Traces:** 27
- **Time Range:** 2025-11-12 08:32:49 → 2025-11-12 08:41:45
- **Propagated to:** bl-pcb-v1
- **Environments:** pcb-dev-01-app, pcb-sit-01-app
- **Sample trace IDs:** f8816702a1bd879f92841beda8f8642d, cc7ba2edf2a82943d12bb151f0ef7630
```

---

### 6. `test_integration_pipeline.py` - End-to-End Testing

Validates the complete trace analysis pipeline.

**Usage:**
```bash
python3 test_integration_pipeline.py
```

**Tests Included:**
1. Data loading (test on 3,500 errors from 8 batches)
2. Trace extraction (917 unique traces → 126 root causes)
3. Report generation (markdown output with concrete causes)

**Performance Baseline:**
- Data loading: ~1 second
- Trace extraction: ~0.15 seconds
- Report generation: ~0.08 seconds
- **Total: ~1.2 seconds for 3,500 errors**

**Sample Test Output:**
```
TEST 1: Data Loading
✅ Loaded 3500 errors from 8 batches

TEST 2: Trace Extraction
✅ Extracted 917 unique traces
✅ Identified 126 unique root causes

TEST 3: Report Generation
✅ Generated markdown report
✅ All 5 concrete issues identified
✅ Report written to /tmp/test_report.md
```

---

## Complete Workflow Example

**Daily Root Cause Analysis Pipeline:**

```bash
#!/bin/bash
DATE="2025-11-12"
NEXT=$(date -d "$DATE + 1 day" +%Y-%m-%d)

# Step 1: Fetch errors
python3 fetch_errors.py \
  --from "${DATE}T00:00:00" \
  --to "${NEXT}T00:00:00" \
  --max-sample 50000 \
  --output "data/${DATE}_errors.json"

# Step 2: Extract root causes using traces
python3 trace_extractor.py \
  --input "data/${DATE}_errors.json" \
  --output "data/${DATE}_root_causes.json"

# Step 3: Generate detailed report
python3 trace_report_detailed.py \
  --input "data/${DATE}_root_causes.json" \
  --output "data/${DATE}_root_cause_report.md"

# Step 4: Validate pipeline (optional)
python3 test_integration_pipeline.py

echo "✅ Daily analysis complete: data/${DATE}_root_cause_report.md"
```

---

## Performance

- **Fetch time:** ~30-60s per day (depends on error count)
- **Trace extraction:** ~2s per 1,500 errors
- **Report generation:** ~0.1s per 1,500 errors
- **Total analysis time:** ~35-65s per day
- **Recommended sample size:**
  - Daily (< 100k errors): 30k-50k (30-50% coverage)
  - Weekly (> 500k errors): 50k (7-10% coverage)
  - 15-min incremental: 5k-10k (50%+ coverage)

---

## Best Practices

1. **Fetch data first, analyze later** - separate concerns
2. **Use trace_id grouping** - more accurate root cause identification
3. **Check specificity breakdown** - identifies if more logging is needed
4. **Run integration tests** - validates pipeline before production use
5. **Store raw JSON** - enables re-analysis without re-fetching
6. **Monitor coverage** - aim for >30% for reliable statistics
7. **Use concrete root causes** - focus on actionable issues first



