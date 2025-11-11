#!/bin/bash
# Standalone ES error fetcher using curl only
# Usage: ./fetch_errors_curl.sh 2025-11-09 50000 /tmp/daily_2025-11-09.json

DATE=$1
SAMPLE_SIZE=${2:-30000}
OUTPUT=${3:-/tmp/daily_${DATE}.json}

if [ -z "$DATE" ]; then
    echo "Usage: $0 <DATE> [SAMPLE_SIZE] [OUTPUT]"
    echo "Example: $0 2025-11-09 50000 /tmp/daily_2025-11-09.json"
    exit 1
fi

FROM="${DATE}T00:00:00"
TO="${DATE}T23:59:59"

echo "📊 Fetching errors for $DATE"
echo "   Time range: $FROM to $TO"
echo "   Sample size: $SAMPLE_SIZE"
echo "   Output: $OUTPUT"
echo

# ES credentials from env or defaults
ES_HOST=${ES_HOST:-"https://logs.domena.cz"}
ES_USER=${ES_USER:-"elasticsearch_user"}
ES_PASS=${ES_PASS:-"elasticsearch_heslo"}

# First get total count
echo "⏳ Getting total error count..."
TOTAL_QUERY='{
  "query": {
    "bool": {
      "filter": [
        {"range": {"@timestamp": {"gte": "'$FROM'", "lte": "'$TO'"}}},
        {"term": {"loglevel": "ERROR"}}
      ]
    }
  },
  "size": 0,
  "track_total_hits": true
}'

TOTAL_RESULT=$(curl -s -u "$ES_USER:$ES_PASS" \
  -H "Content-Type: application/json" \
  "$ES_HOST/logs-*/_search" \
  -d "$TOTAL_QUERY")

TOTAL=$(echo "$TOTAL_RESULT" | jq -r '.hits.total.value // 0')
echo "   Total errors: $TOTAL"

if [ "$TOTAL" -eq 0 ]; then
    echo "❌ No errors found for $DATE"
    exit 1
fi

# Fetch sample
echo "⏳ Fetching $SAMPLE_SIZE sample errors..."
FETCH_QUERY='{
  "query": {
    "bool": {
      "filter": [
        {"range": {"@timestamp": {"gte": "'$FROM'", "lte": "'$TO'"}}},
        {"term": {"loglevel": "ERROR"}}
      ]
    }
  },
  "size": '$SAMPLE_SIZE',
  "sort": [{"@timestamp": "asc"}],
  "_source": ["@timestamp", "message", "kubernetes.namespace_name", "kubernetes.labels.app"]
}'

FETCH_RESULT=$(curl -s -u "$ES_USER:$ES_PASS" \
  -H "Content-Type: application/json" \
  "$ES_HOST/logs-*/_search" \
  -d "$FETCH_QUERY")

# Transform to expected format
echo "⏳ Transforming data..."
jq -n \
  --argjson total "$TOTAL" \
  --argjson sample "$SAMPLE_SIZE" \
  --arg from "$FROM" \
  --arg to "$TO" \
  --argjson hits "$(echo "$FETCH_RESULT" | jq '[.hits.hits[] | {
    timestamp: ._source["@timestamp"],
    message: ._source.message,
    namespace: ._source.kubernetes.namespace_name,
    app: ._source.kubernetes.labels.app
  }]')" \
  '{
    period_start: $from,
    period_end: $to,
    total_errors: $total,
    sample_size: ($hits | length),
    coverage_percent: (($hits | length) / $total * 100),
    errors: $hits
  }' > "$OUTPUT"

ACTUAL_SAMPLE=$(jq -r '.sample_size' "$OUTPUT")
COVERAGE=$(jq -r '.coverage_percent' "$OUTPUT")

echo
echo "✅ Success!"
echo "   Fetched: $ACTUAL_SAMPLE / $TOTAL errors"
echo "   Coverage: ${COVERAGE}%"
echo "   Saved to: $OUTPUT"
