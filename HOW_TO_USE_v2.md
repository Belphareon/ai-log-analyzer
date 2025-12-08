# How to Use AI Log Analyzer (v2.0)

Complete guide for using the AI Log Analyzer orchestration pipeline.

---

## 🎯 Typical Workflow

### 1. Basic Analysis (Most Common)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate

# Analyze last hour of errors
python3 analyze_period.py \
  --from "2025-12-08T11:00:00Z" \
  --to "2025-12-08T12:00:00Z" \
  --output analysis_result.json
```

**Output:** `analysis_result.json` containing all 5 STEPS of analysis

### 2. View Results

```bash
# View intelligent analysis (human-readable)
python3 -c "
import json
with open('analysis_result.json') as f:
    data = json.load(f)
    print(data['intelligent_analysis_output'])
"

# View statistics (JSON)
python3 -c "
import json
with open('analysis_result.json') as f:
    data = json.load(f)
    print(json.dumps(data['statistics'], indent=2))
"

# View root causes
python3 -c "
import json
with open('analysis_result.json') as f:
    data = json.load(f)
    for cause in data['root_causes_analysis']['root_causes'][:10]:
        print(f\"{cause['errors_count']} errors: {cause['message'][:80]}\")
"
```

### 3. Longer Periods

```bash
# Analyze entire day
python3 analyze_period.py \
  --from "2025-12-08T00:00:00Z" \
  --to "2025-12-09T00:00:00Z" \
  --output daily_analysis.json

# Analyze week
python3 analyze_period.py \
  --from "2025-12-01T00:00:00Z" \
  --to "2025-12-08T00:00:00Z" \
  --output weekly_analysis.json
```

### 4. Custom Batch Size

```bash
# For high-volume periods, increase batch size
python3 analyze_period.py \
  --from "2025-12-08T11:00:00Z" \
  --to "2025-12-08T12:00:00Z" \
  --output analysis.json \
  --batch-size 10000
```

---

## 📊 Understanding Output

### Output JSON Structure

```json
{
  "metadata": {
    "analysis_type": "Complete Trace-Based Root Cause Analysis",
    "period_start": "2025-12-08T11:00:00Z",
    "period_end": "2025-12-08T12:00:00Z",
    "generated_at": "2025-12-08T15:30:45.123456",
    "version": "1.0"
  },
  "statistics": {
    "total_errors_fetched": 1518,
    "errors_with_trace_id": 1486,
    "trace_id_coverage_percent": 97.9,
    "unique_traces": 281,
    "root_causes_identified": 68,
    "new_unique_patterns": 12,
    "avg_errors_per_trace": 5.4,
    "execution_time_seconds": 4,
    "app_distribution": {
      "bl-pcb-v1": 910,
      "bl-pcb-event-processor-relay-v1": 189,
      "bl-pcb-billing-v1": 164
    },
    "cluster_distribution": {
      "cluster-k8s_nprod_3100-in": 827,
      "cluster-k8s_nprod_3095-in": 691
    }
  },
  "batch_data": { ... },
  "root_causes_analysis": { ... },
  "markdown_report": "# Error Analysis Report\n...",
  "intelligent_analysis_output": "📊 Loading batches...\n... (text output)"
}
```

### Key Sections

#### 1. Statistics
Quick overview of analysis scope and results:
- Total errors analyzed
- Unique traces identified
- Root causes extracted
- Execution time
- Application and cluster distribution

#### 2. Batch Data
Raw error data from Elasticsearch, preprocessed:
- Error counts
- Error list with full details
- Timestamp range

#### 3. Root Causes Analysis
Structured root cause groupings:
- Message patterns
- Error counts per pattern
- First/last seen timestamps
- Affected namespaces

#### 4. Markdown Report
Human-readable formatted report:
- Summary statistics
- Top error patterns
- Severity classifications
- Markdown formatted for easy sharing

#### 5. Intelligent Analysis Output
Detailed analysis with advanced insights:
- **Trace-based root cause analysis** - 281 unique traces, 67 root causes
- **Timeline analysis** - 5-minute buckets showing error distribution over time
- **API call analysis** - Failed API endpoints and patterns (210 API failures)
- **Cross-app correlation** - Service-to-service failure chains
- **Executive summary** - Key findings and prioritized recommendations

---

## 🔍 Example: Detailed Analysis

### Reading Intelligent Analysis Output

```
📊 Loading batches from /tmp/batch_for_intelligent_analysis...
  ✓ batch_001.json: 1518 errors
✅ Total: 1,518 errors loaded

================================================================================
🔍 TRACE-BASED ROOT CAUSE ANALYSIS
================================================================================

📊 Trace Statistics:
  Total unique traces: 281                    <- 281 independent request chains
  Total errors: 1518                          <- Total errors across all traces
  Avg errors per trace: 5.4                   <- Each trace averages 5.4 errors
  Unique root causes: 67                      <- 67 distinct root cause types

🎯 Root Causes by App:
  bl-pcb-v1: 910 errors (59.9%)              <- Dominant failing app
  bl-pcb-event-processor-relay-v1: 189 errors (12.5%)

🔴 Top Root Causes:
  1. 🔴 CRITICAL
     App: bl-pcb-v1
     Message: ServiceBusinessException error handled....
     Errors: 337 (22.2%)
     Traces: 58
     Namespaces: pcb-dev-01-app, pcb-fat-01-app, pcb-uat-01-app
```

**Reading Guide:**
- 🔴 = CRITICAL (>10% of errors)
- 🟠 = HIGH (5-10% of errors)
- 🟡 = MEDIUM (1-5% of errors)
- 🟢 = LOW (<1% of errors)

### Timeline Analysis

```
================================================================================
⏰ TIMELINE (5-minute buckets, CET timezone)
================================================================================
12:00 CET:   17 █
12:05 CET:  183 █████████████████████
12:10 CET:   58 ██████
12:25 CET:  280 ████████████████████████████████
12:50 CET:  341 ████████████████████████████████████████
              ↑ PEAK

🔥 Peak: 12:50 CET with 341 errors in 5 minutes
```

**What This Means:**
- Errors are not evenly distributed
- Major spike at 12:50 CET (341 errors)
- This 5-minute window had 22% of all errors
- Indicates cascading failure or specific incident

### API Call Analysis

```
================================================================================
🌐 API CALL ANALYSIS (210 API-related errors)
================================================================================

1. POST /api/v1/card/121566 → 404
   Count: 60
   Host: bl-pcb-v1.pcb-dev-01-app:9080
   Calling apps: bl-pcb-event-processor-relay-v1
   Namespaces: pcb-dev-01-app, pcb-fat-01-app, pcb-uat-01-app

2. POST /api/v1/card/124458 → 404
   Count: 33
   Host: bl-pcb-v1.pcb-uat-01-app:9080
   Calling apps: bl-pcb-event-processor-relay-v1
```

**What This Shows:**
- Event relay is calling bl-pcb-v1 card API
- 60+ calls to card ID 121566 are failing with 404
- Happening across multiple environments (DEV, FAT, UAT)
- This is a clear root cause: missing or inaccessible card data

### Cross-App Correlation

```
================================================================================
🔗 CROSS-APP CORRELATION & CALL CHAINS
================================================================================

📡 Internal Service Calls (bl-pcb → bl-pcb):

  bl-pcb-event-processor-relay-v1 → bl-pcb-v1
    Total failures: 210
      pcb-fat-01-app: 66
      pcb-uat-01-app: 64
      pcb-dev-01-app: 57
```

**What This Shows:**
- Event processor relies on bl-pcb-v1
- 210 failures in this specific call chain
- Failures distributed across environments
- Suggests issue with bl-pcb-v1 card API

### Executive Summary

```
================================================================================
🎯 BIG PICTURE - EXECUTIVE SUMMARY
================================================================================

💡 Recommendations Priority:
  🔴 HIGH: Fix event relay → bl-pcb-v1 communication (339 failures)
  🟡 MEDIUM: Investigate DoGS integration (32 failures)
  🟡 MEDIUM: Review SIT test data quality (card not found)
  🟢 LOW: Monitor event queue processing
```

**Action Items:**
- 🔴 HIGH: Investigate why bl-pcb-v1 card endpoint is failing
- 🟡 MEDIUM: Check DoGS external service health
- 🟡 MEDIUM: Verify test data in SIT environment
- 🟢 LOW: Monitor queue processing (lower priority)

---

## 🛠️ Troubleshooting

### Issue: "Elasticsearch connection refused"

```
❌ Elasticsearch connection error: Connection refused
```

**Solution:**
1. Check if Elasticsearch is running
2. Verify ES_HOST and ES_PORT environment variables
3. Test connectivity: `curl https://elasticsearch-test.kb.cz:9500`

### Issue: "No errors found for period"

```
✅ Fetched 0 ERROR logs
```

**Possible Causes:**
1. Date range has no errors (try different period)
2. Wrong date format (must use ISO 8601 with Z: `2025-12-08T11:00:00Z`)
3. Elasticsearch connection not reaching production data

**Solution:**
```bash
# Try a wider time range
python3 analyze_period.py \
  --from "2025-12-07T00:00:00Z" \
  --to "2025-12-08T23:59:59Z" \
  --output analysis.json
```

### Issue: Execution takes too long

**Solution:** Process in smaller chunks:
```bash
# Instead of 24 hours, do 1 hour at a time
for hour in {00..23}; do
  python3 analyze_period.py \
    --from "2025-12-08T${hour}:00:00Z" \
    --to "2025-12-08T${hour+1}:00:00Z" \
    --output "analysis_hour_${hour}.json"
done
```

---

## 📈 Batch Processing

### Process Multiple Periods

```bash
#!/bin/bash
# analyze_multiple.sh

for day in {01..08}; do
  echo "Analyzing 2025-12-${day}..."
  python3 analyze_period.py \
    --from "2025-12-${day}T00:00:00Z" \
    --to "2025-12-${day+1}T00:00:00Z" \
    --output "analysis_2025-12-${day}.json" \
    --batch-size 10000
done
```

Run with:
```bash
chmod +x analyze_multiple.sh
./analyze_multiple.sh
```

---

## 📊 Integration Examples

### Parse Results in Python

```python
import json

with open('analysis_result.json') as f:
    data = json.load(f)

# Get statistics
stats = data['statistics']
print(f"Total errors: {stats['total_errors_fetched']:,}")
print(f"Root causes: {stats['root_causes_identified']}")
print(f"Execution time: {stats['execution_time_seconds']}s")

# Get top root causes
for cause in data['root_causes_analysis']['root_causes'][:5]:
    print(f"{cause['errors_count']} - {cause['message'][:60]}")

# Get intelligent analysis text
print(data['intelligent_analysis_output'])

# Get markdown report
print(data['markdown_report'])
```

### Send to External System

```python
import json
import requests

with open('analysis_result.json') as f:
    data = json.load(f)

# Send to Teams webhook
webhook_url = "https://outlook.webhook.office.com/webhookb2/..."
message = {
    "summary": f"Error Analysis: {data['statistics']['total_errors_fetched']} errors",
    "sections": [{
        "activityTitle": "AI Log Analysis Report",
        "facts": [
            {"name": "Errors", "value": str(data['statistics']['total_errors_fetched'])},
            {"name": "Root Causes", "value": str(data['statistics']['root_causes_identified'])},
            {"name": "Top App", "value": list(data['statistics']['app_distribution'].keys())[0]}
        ]
    }]
}

requests.post(webhook_url, json=message)
```

---

## ✅ Quality Checks

### Validate Output

```bash
# Check JSON validity
python3 -m json.tool analysis_result.json > /dev/null && echo "✅ Valid JSON"

# Verify all sections present
python3 -c "
import json
with open('analysis_result.json') as f:
    data = json.load(f)
    required = ['metadata', 'statistics', 'batch_data', 'root_causes_analysis', 
                'markdown_report', 'intelligent_analysis_output']
    missing = [k for k in required if k not in data]
    if missing:
        print(f'❌ Missing: {missing}')
    else:
        print('✅ All sections present')
"

# Check error counts match
python3 -c "
import json
with open('analysis_result.json') as f:
    data = json.load(f)
    fetched = data['statistics']['total_errors_fetched']
    batch_errors = len(data['batch_data'].get('errors', []))
    print(f'Fetched: {fetched}, In batch: {batch_errors}')
    if fetched == batch_errors:
        print('✅ Counts match')
    else:
        print('⚠️  Count mismatch!')
"
```

---

## 📝 Notes

- All datetime parameters must use ISO 8601 format with `Z` suffix
- Batch size of 5000 is default and handles most scenarios
- Larger batch sizes (10000+) for high-volume periods
- Smaller batch sizes (1000) if memory is constrained
- Results are self-contained in single JSON file for easy sharing

---

**Version:** 2.0  
**Last Updated:** 2025-12-08  
**Status:** Production Ready
