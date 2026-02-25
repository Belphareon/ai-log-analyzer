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

BASE_URL = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')  # Required: Set in .env file
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')

def fetch_unlimited(date_from, date_to, batch_size=10000, retry=3):
    """Fetch all ERROR logs using search_after pagination"""
    
    all_errors = []
    batch_num = 0
    search_after = None
    expected_total = None
    
    print("🔄 Fetcher - UNLIMITED via search_after")
    print(f"   Time range: {date_from} to {date_to}")
    print(f"   Batch size: {batch_size:,}")
    print()

    session = requests.Session()
    session.auth = HTTPBasicAuth(ES_USER, ES_PASSWORD)
    session.verify = False
    session.trust_env = False
    session.proxies = {'http': None, 'https': None}

    pit_id = None
    pit_keep_alive = '5m'

    try:
        pit_resp = session.post(f"{BASE_URL}/{INDICES}/_pit?keep_alive={pit_keep_alive}", timeout=120)
        if pit_resp.status_code != 200:
            print(f"   ❌ PIT open failed ({pit_resp.status_code}), fallback to direct index search")
        else:
            pit_id = pit_resp.json().get('id')

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
                "sort": [
                    {"@timestamp": {"order": "asc"}},
                    {"_shard_doc": {"order": "asc"}}
                ],
                "size": batch_size,
                "track_total_hits": batch_num == 1,
                "_source": [
                "message", 
                "application.name",
                "@timestamp", 
                "traceId",
                "kubernetes.labels.eamApplication",
                "kubernetes.namespace",
                "topic",
                # NEW: Additional fields for better error classification
                "exception",                    # Java exception object
                "exception.type",              # Exception class name
                "error.type",                  # Generic error type field
                "error_type",                  # App-specific error type
                "errorType",                   # camelCase variant
                "error.message",               # Structured error message
                "service.name",                # Service that produced error
                "http.status_code",            # HTTP status
                "stack_trace",                 # For better analysis
                ]
            }

            if pit_id:
                query["pit"] = {"id": pit_id, "keep_alive": pit_keep_alive}

            if search_after:
                query["search_after"] = search_after
            
            # Retry logic
            success = False
            for attempt in range(retry):
                try:
                    search_url = f"{BASE_URL}/_search" if pit_id else f"{BASE_URL}/{INDICES}/_search"
                    resp = session.post(
                        search_url,
                        json=query,
                        timeout=120,
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
            if expected_total is None:
                total_obj = data.get('hits', {}).get('total', 0)
                if isinstance(total_obj, dict):
                    expected_total = int(total_obj.get('value', 0))
                else:
                    expected_total = int(total_obj or 0)
                print(f"📊 Expected total hits: {expected_total:,}")

            if pit_id and isinstance(data.get('pit_id'), str):
                pit_id = data.get('pit_id')
            
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
                    'namespace': source.get('kubernetes', {}).get('namespace', 'unknown'),
                    'timestamp': source.get('@timestamp', ''),
                    'trace_id': source.get('traceId', ''),
                    'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
                })
            
            print(f"🔄 Batch {batch_num:3d}... ✅ {len(hits):,} | Total: {len(all_errors):,}")
            
            # Set search_after for next iteration (last document's sort values)
            if len(hits) < batch_size:
                # Got less than batch size = we're at the end
                break
            
            search_after = hits[-1]['sort']
    finally:
        if pit_id:
            try:
                session.delete(f"{BASE_URL}/_pit", json={"id": pit_id}, timeout=30)
            except Exception:
                pass
    
        session.close()

    print()
    print(f"✅ Total fetched: {len(all_errors):,} errors")
    if expected_total is not None:
        if len(all_errors) == expected_total:
            print("✅ Completeness check: fetched count matches hits.total")
        else:
            print(
                f"⚠️ Completeness check mismatch: expected {expected_total:,}, fetched {len(all_errors):,}"
            )
    return all_errors

def main():
    parser = argparse.ArgumentParser(description='Fetch ERROR logs from ES (unlimited, search_after)')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format, e.g., 2025-12-02T07:30:00Z)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format, e.g., 2025-12-02T10:30:00Z)')
    parser.add_argument('--batch-size', type=int, default=10000, help='Batch size per request (default 10K)')
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
