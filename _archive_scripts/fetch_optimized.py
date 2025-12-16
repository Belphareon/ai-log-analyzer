#!/usr/bin/env python3
"""
Optimized ES fetcher - NO unnecessary batching
Uses search_after for unlimited pagination without 10K window limit
Fetches 50K per request for efficiency
"""

import requests
from requests.auth import HTTPBasicAuth
import json
import os
import time
import urllib3
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings()
load_dotenv()

BASE_URL = os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')  # Required: Set in .env file
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

def fetch_all_with_search_after(date_from, date_to, batch_size=50000):
    """
    Fetch ALL errors using search_after (no 10K window limit)
    - Fetches 50K per request (efficient)
    - Uses cursor-based pagination
    - No arbitrary batching needed
    """
    
    all_errors = []
    search_after = None
    batch_num = 0
    
    base_query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": date_from, "lte": date_to}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "size": batch_size,
        "sort": ["_id"],  # Required for search_after
        "_source": ["message", "application.name", "@timestamp", "traceId", "kubernetes.labels.eamApplication", "topic"]
    }
    
    print(f"📥 Fetching ALL errors with search_after pagination")
    print(f"   Batch size: {batch_size:,}")
    print(f"   Time range: {date_from} to {date_to}")
    print()
    
    while True:
        batch_num += 1
        query = base_query.copy()
        
        if search_after:
            query['search_after'] = search_after
        
        try:
            print(f"🔄 Batch {batch_num:2d}...", end=" ", flush=True)
            
            resp = requests.post(
                f"{BASE_URL}/{INDICES}/_search",
                json=query,
                auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
                verify=False,
                timeout=120
            )
            
            if resp.status_code != 200:
                print(f"❌ Error {resp.status_code}")
                break
            
            data = resp.json()
            hits = data['hits']['hits']
            
            if not hits:
                print(f"✅ DONE (no more hits)")
                break
            
            # Process hits
            for hit in hits:
                source = hit.get('_source', {})
                msg = source.get('message', '')
                
                all_errors.append({
                    'message': str(msg)[:500],  # Limit message length
                    'application': source.get('application.name', 'unknown'),
                    'timestamp': source.get('@timestamp', ''),
                    'traceId': source.get('traceId', ''),
                    'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
                    'cluster': source.get('topic', 'unknown'),
                })
            
            print(f"✅ Got {len(hits):,} records | Total: {len(all_errors):,}")
            
            # Set cursor for next batch
            search_after = hits[-1].get('sort', [])
            
        except Exception as e:
            print(f"❌ Exception: {str(e)[:50]}")
            break
    
    return all_errors

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Optimized ES fetcher with search_after')
    parser.add_argument('--from', dest='date_from', required=True, help='ISO timestamp from')
    parser.add_argument('--to', dest='date_to', required=True, help='ISO timestamp to')
    parser.add_argument('--batch-size', type=int, default=50000, help='Batch size (default 50K)')
    parser.add_argument('--output', required=True, help='Output JSON file')
    
    args = parser.parse_args()
    
    start_time = time.time()
    
    errors = fetch_all_with_search_after(
        args.date_from,
        args.date_to,
        batch_size=args.batch_size
    )
    
    elapsed = time.time() - start_time
    
    print()
    print(f"✅ Fetched {len(errors):,} total errors in {elapsed:.1f}s")
    
    result = {
        'period_start_utc': args.date_from,
        'period_end_utc': args.date_to,
        'fetched_errors': len(errors),
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'elapsed_seconds': elapsed,
        'errors': errors
    }
    
    with open(args.output, 'w') as f:
        json.dump(result, f, default=str)
    
    file_size_mb = len(json.dumps(result)) / (1024*1024)
    print(f"💾 Saved to {args.output} ({file_size_mb:.1f}MB)")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
