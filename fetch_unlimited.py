#!/usr/bin/env python3
"""
ES Fetcher - Truly unlimited data fetching via search_after
Uses HTTPBasicAuth + search_after for cursor-based pagination
No artificial limits - fetches ALL records in date range
"""

import requests
from requests.auth import HTTPBasicAuth
import json
import os
import time
import urllib3
import argparse
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings()
load_dotenv()

BASE_URL = os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD', 'ta@@swLT69EX.6164')
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

def fetch_unlimited(date_from, date_to, batch_size=5000, retry=3):
    """Fetch all ERROR logs using search_after pagination"""
    
    all_errors = []
    batch_num = 0
    search_after = None
    
    print("🔄 Fetcher - UNLIMITED via search_after")
    print(f"   Time range: {date_from} to {date_to}")
    print(f"   Batch size: {batch_size:,}")
    print()

    while True:
        batch_num += 1
        
        # Build query with search_after
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": date_from, "lte": date_to}}},
                        {"term": {"level": "ERROR"}}
                    ]
                }
            },
            "sort": [{"@timestamp": "asc"}],  # Required for search_after
            "size": batch_size,
            "_source": ["message", "application.name", "@timestamp", "traceId", "kubernetes.labels.eamApplication", "topic"]
        }
        
        if search_after:
            query["search_after"] = search_after
        
        # Retry logic
        success = False
        for attempt in range(retry):
            try:
                resp = requests.post(
                    f"{BASE_URL}/{INDICES}/_search",
                    json=query,
                    auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
                    verify=False,
                    timeout=120
                )
                
                if resp.status_code == 200:
                    success = True
                    break
                elif resp.status_code in [401, 403]:
                    if attempt < retry - 1:
                        time.sleep(2)
                        continue
                    else:
                        print(f"   ❌ Auth failed after {retry} retries")
                        return None
                else:
                    error_msg = resp.json().get('error', {}).get('reason', 'Unknown error')
                    print(f"   ❌ Error {resp.status_code}: {error_msg[:100]}")
                    return None
            except Exception as e:
                if attempt < retry - 1:
                    time.sleep(1)
                    continue
                else:
                    print(f"   ❌ Exception: {e}")
                    return None
        
        if not success:
            break
        
        data = resp.json()
        hits = data['hits']['hits']
        
        if not hits:
            print(f"🔄 Batch {batch_num:3d}... ✅ DONE (no more hits)")
            break
        
        # Process hits
        for hit in hits:
            source = hit.get('_source', {})
            msg = source.get('message', '')
            if isinstance(msg, dict):
                msg = json.dumps(msg)
            if isinstance(msg, str):
                msg = msg[:500]
            
            all_errors.append({
                'message': msg,
                'application': source.get('application.name', 'unknown'),
                'cluster': source.get('topic', 'unknown'),
                'timestamp': source.get('@timestamp', ''),
                'trace_id': source.get('traceId', ''),
                'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
            })
        
        print(f"🔄 Batch {batch_num:3d}... ✅ {len(hits):,} | Total: {len(all_errors):,}")
        
        # Set search_after for next iteration (last document's sort values)
        if len(hits) < batch_size:
            # Got less than batch size = we're at the end
            break
        
        search_after = hit['sort']
    
    print()
    print(f"✅ Total fetched: {len(all_errors):,} errors")
    return all_errors

def main():
    parser = argparse.ArgumentParser(description='Fetch ERROR logs from ES (unlimited, search_after)')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format, e.g., 2025-12-02T07:30:00Z)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format, e.g., 2025-12-02T10:30:00Z)')
    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size per request (default 5K)')
    parser.add_argument('--output', required=True, help='Output JSON file')

    args = parser.parse_args()

    all_errors = fetch_unlimited(args.date_from, args.date_to, batch_size=args.batch_size)
    
    if all_errors is None:
        print("❌ Fetch failed!")
        return 1

    # Save result
    result = {
        'period_start_utc': args.date_from,
        'period_end_utc': args.date_to,
        'fetched_errors': len(all_errors),
        'batch_size': args.batch_size,
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'errors': all_errors
    }

    with open(args.output, 'w') as f:
        json.dump(result, f, default=str)

    file_size_mb = len(json.dumps(result)) / (1024*1024)
    print(f"💾 Saved to {args.output} ({file_size_mb:.1f}MB)")

    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
