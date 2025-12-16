#!/usr/bin/env python3
"""
Simple ES fetcher - fetch ERROR logs for specific time range
Just change TIME_FROM and TIME_TO variables
"""

import requests
from requests.auth import HTTPBasicAuth
import json
import os
import urllib3
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings()
load_dotenv()

# ===== CHANGE THESE ONLY =====
TIME_FROM = "2025-12-02T07:30:00Z"
TIME_TO = "2025-12-02T10:30:00Z"
OUTPUT_FILE = "data/batch_current.json"
# =============================

BASE_URL = os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')  # Required: Set in .env file
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

def fetch_all():
    """Fetch ALL errors for time range using search_after"""
    
    all_errors = []
    batch_num = 0
    search_after = None
    
    print(f"📥 Fetching ERROR logs")
    print(f"   Time: {TIME_FROM} to {TIME_TO}")
    print(f"   Using search_after (no 10K limit)")
    print()
    
    while True:
        batch_num += 1
        
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": TIME_FROM, "lte": TIME_TO}}},
                        {"term": {"level": "ERROR"}}
                    ]
                }
            },
            "size": 10000,
            "sort": [{"@timestamp": "asc"}, {"_id": "asc"}],
            "_source": ["message", "application.name", "@timestamp", "traceId", "kubernetes.labels.eamApplication", "topic"]
        }
        
        if search_after:
            query['search_after'] = search_after
        
        print(f"🔄 Batch {batch_num:2d}...", end=" ", flush=True)
        
        try:
            resp = requests.post(
                f"{BASE_URL}/{INDICES}/_search",
                json=query,
                auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
                verify=False,
                timeout=120
            )
            
            if resp.status_code != 200:
                print(f"❌ Error {resp.status_code}")
                error = resp.json().get('error', {}).get('reason', 'Unknown')
                print(f"   {error[:100]}")
                break
            
            data = resp.json()
            hits = data['hits']['hits']
            
            if not hits:
                print(f"✅ DONE")
                break
            
            # Process hits
            for hit in hits:
                source = hit.get('_source', {})
                all_errors.append({
                    'message': str(source.get('message', ''))[:500],
                    'application': source.get('application.name', 'unknown'),
                    'cluster': source.get('topic', 'unknown'),
                    'timestamp': source.get('@timestamp', ''),
                    'trace_id': source.get('traceId', ''),
                    'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
                })
            
            print(f"✅ {len(hits):5d} | Total: {len(all_errors):,}")
            
            # Set cursor for next batch
            search_after = hits[-1].get('sort', [])
            
        except Exception as e:
            print(f"❌ Exception: {str(e)[:50]}")
            break
    
    return all_errors

def main():
    errors = fetch_all()
    
    print()
    print(f"✅ Total fetched: {len(errors):,} errors")
    
    if len(errors) == 0:
        print(f"⚠️  WARNING: No errors found for this time range!")
        print(f"   Check if data exists and time format is correct (UTC)")
    
    # Save
    result = {
        'period_start_utc': TIME_FROM,
        'period_end_utc': TIME_TO,
        'fetched_errors': len(errors),
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'errors': errors
    }
    
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(result, f, default=str)
    
    file_size_mb = len(json.dumps(result)) / (1024*1024)
    print(f"💾 Saved to {OUTPUT_FILE} ({file_size_mb:.1f}MB)")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
