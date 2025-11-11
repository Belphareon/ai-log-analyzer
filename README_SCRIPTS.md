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

## Performance

- **Fetch time:** ~30-60s per day (depends on error count)
- **Analysis time:** ~5-10s per day
- **Recommended sample size:**
  - Daily (< 100k errors): 30k-50k (30-50% coverage)
  - Weekly (> 500k errors): 50k (7-10% coverage)
  - 15-min incremental: 5k-10k (50%+ coverage)

---

## Best Practices

1. **Fetch data first, analyze later** - separate concerns
2. **Use appropriate sample sizes** - balance speed vs accuracy
3. **Run fetches in parallel** for different days (if ES can handle it)
4. **Store raw JSON** - enables re-analysis without re-fetching
5. **Monitor coverage** - aim for >30% for reliable statistics

