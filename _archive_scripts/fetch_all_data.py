#!/usr/bin/env python3
"""
Efficient ES data fetcher - uses search_after (no 10K limit)
Grabs ALL errors in one efficient pass with proper session management
"""

import requests
import json
import os
import sys
import urllib3
from datetime import datetime
from dotenv import load_dotenv

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

BASE_URL = os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER')
ES_PASSWORD = os.getenv('ES_PASSWORD')
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

if not ES_PASSWORD:
    print("❌ ES_PASSWORD not set in .env")
    sys.exit(1)

# Session with proper connection pooling
session = requests.Session()
session.verify = False
session.auth = (ES_USER, ES_PASSWORD)
session.headers.update({
    'Content-Type': 'application/json',
    'Connection': 'keep-alive'
})

def fetch_all_errors(date_from, date_to, batch_size=10000):
    """
    Fetch ALL errors using search_after cursor pagination
    - No 10K limit (that's only for from/size)
    - Efficient cursor-based pagination
    - Single logical request (stateless from ES perspective)
    """
    
    all_errors = []
    search_after = None
    batch_count = 0
    
    print(f"🔍 Fetching all ERROR logs from {date_from} to {date_to}")
    print(f"📊 Using batch_size={batch_size:,}")
    print()
    
    while True:
        batch_count += 1
        
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": date_from, "lte": date_to}}},
                        {"term": {"level": "ERROR"}}
                    ]
                }
            },
            "size": batch_size,
            "sort": ["_id"],
            "_source": ["message", "application.name", "@timestamp", "traceId", 
                       "kubernetes.labels.eamApplication", "topic", "level"]
        }
        
        if search_after:
            query['search_after'] = search_after
        
        print(f"📥 Batch {batch_count}...", end="", flush=True)
        
        try:
            resp = session.post(
                f"{BASE_URL}/{INDICES}/_search",
                json=query,
                timeout=60
            )
            
            if resp.status_code != 200:
                print(f" ❌ Status {resp.status_code}")
                error = resp.json()
                print(f"   Error: {error.get('error', {}).get('reason', 'Unknown')}")
                return None
            
            data = resp.json()
            hits = data['hits']['hits']
            
            if not hits:
                print(f" ✅ Complete!")
                break
            
            # Extract errors
            for hit in hits:
                source = hit['_source']
                error = {
                    'message': source.get('message', ''),
                    'application': source.get('application.name', 'unknown'),
                    'cluster': source.get('topic', 'unknown'),
                    'timestamp': source.get('@timestamp', ''),
                    'trace_id': source.get('traceId', ''),
                    'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
                    'level': source.get('level', 'ERROR')
                }
                all_errors.append(error)
            
            print(f" ✅ Got {len(hits)} records (total: {len(all_errors):,})")
            
            # Set cursor for next batch
            last_hit = hits[-1]
            search_after = last_hit['sort']
            
        except Exception as e:
            print(f" ❌ Exception: {str(e)}")
            return None
    
    return all_errors

def main():
    date_from = "2025-12-02T07:30:00Z"
    date_to = "2025-12-02T10:30:00Z"
    output_file = "data/batch_ALL_ERRORS_FRESH.json"
    
    print("=" * 70)
    print("🚀 EFFICIENT ES DATA FETCHER")
    print("=" * 70)
    print(f"📍 Indices: {INDICES}")
    print(f"⏰ Period: {date_from} to {date_to}")
    print(f"💾 Output: {output_file}")
    print()
    
    errors = fetch_all_errors(date_from, date_to, batch_size=10000)
    
    if errors is None:
        print("\n❌ Failed to fetch data")
        return 1
    
    print()
    print("=" * 70)
    print(f"✅ SUCCESS: Fetched {len(errors):,} error records")
    print("=" * 70)
    
    # Calculate stats
    total_with_trace = sum(1 for e in errors if e['trace_id'])
    trace_coverage = (total_with_trace / len(errors) * 100) if errors else 0
    
    print(f"📊 Statistics:")
    print(f"   Total errors: {len(errors):,}")
    print(f"   With traceId: {total_with_trace:,} ({trace_coverage:.1f}%)")
    print(f"   Applications: {len(set(e['application'] for e in errors))}")
    print(f"   Clusters: {set(e['cluster'] for e in errors)}")
    print()
    
    # Save to JSON
    result = {
        'period_start_utc': date_from,
        'period_end_utc': date_to,
        'fetched_errors': len(errors),
        'trace_id_coverage_percent': trace_coverage,
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'errors': errors
    }
    
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(result, f, default=str, indent=2)
    
    file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
    print(f"💾 Saved to: {output_file}")
    print(f"📦 File size: {file_size_mb:.1f} MB")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
