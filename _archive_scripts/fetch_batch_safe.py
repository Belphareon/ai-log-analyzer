#!/usr/bin/env python3
"""
ES Fetcher - Unlimited batching, no artificial limits
Uses HTTPBasicAuth which works reliably
Fetches all ERROR logs in specified time range
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
ES_PASSWORD = os.getenv('ES_PASSWORD')  # Required: Set in .env file
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

def fetch_batch(from_idx, size, date_from, date_to, retry=3):
    """Fetch single batch from ES with retry"""
    for attempt in range(retry):
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": date_from, "lte": date_to}}},
                        {"term": {"level": "ERROR"}}
                    ]
                }
            },
            "from": from_idx,
            "size": size,
            "_source": ["message", "application.name", "@timestamp", "traceId", "kubernetes.labels.eamApplication", "topic"]
        }
        
        try:
            resp = requests.post(
                f"{BASE_URL}/{INDICES}/_search",
                json=query,
                auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
                verify=False,
                timeout=120
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return data['hits']['hits']
            elif resp.status_code in [401, 403]:
                # Auth issue - wait and retry
                if attempt < retry - 1:
                    print(f"   ⏳ Auth issue (401/403), retrying in 2s...")
                    time.sleep(2)
                    continue
                else:
                    print(f"   ❌ Auth failed after {retry} retries")
                    return None
            else:
                print(f"   ❌ Error {resp.status_code}")
                return None
        except Exception as e:
            print(f"   ❌ Exception: {e}")
            if attempt < retry - 1:
                time.sleep(1)
                continue
            return None
    
    return None

def main():
    parser = argparse.ArgumentParser(description='Fetch ERROR logs from ES')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format, e.g., 2025-12-02T07:30:00Z)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format, e.g., 2025-12-02T10:30:00Z)')
    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size (default 50K)')
    parser.add_argument('--output', required=True, help='Output JSON file')
    
    args = parser.parse_args()
    
    print("🔄 Fetcher - Unlimited, NO artificial limits")
    print(f"   Time range: {args.date_from} to {args.date_to}")
    print(f"   Batch size: {args.batch_size:,}")
    print()
    
    all_errors = []
    batch_num = 0
    from_idx = 0
    batch_size = args.batch_size
    
    while True:
        batch_num += 1
        print(f"🔄 Batch {batch_num:2d} (from={from_idx:6d}, size={batch_size:,})...", end='', flush=True)
        
        hits = fetch_batch(from_idx, batch_size, args.date_from, args.date_to, retry=3)
        
        if hits is None:
            print(f" ❌ Failed")
            break
        
        if not hits:
            print(f" ✅ DONE (no more hits)")
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
        
        print(f" ✅ {len(hits):,} | Total: {len(all_errors):,}")
        
        # Move to next batch
        from_idx += batch_size
        
        # Safety check - if we're getting very few records, might be hitting limit
        if len(hits) < batch_size * 0.5:
            print(f"   ℹ️  Less than 50% of batch returned - reaching end of available data")
    
    print()
    print(f"✅ Total fetched: {len(all_errors):,} errors")
    
    # Save
    result = {
        'period_start_utc': args.date_from,
        'period_end_utc': args.date_to,
        'fetched_errors': len(all_errors),
        'batch_size': batch_size,
        'batches': batch_num - 1,
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

