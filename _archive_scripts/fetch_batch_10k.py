#!/usr/bin/env python3
"""
Safe batch fetcher - 10K batches (exactly at ES limit)
7 batches * 10K = 70K capacity for 65K errors
"""

import requests
import json
import os
import time
from datetime import datetime

BASE_URL = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')
INDICES = "cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*"

def fetch_batch(from_idx, size=10000, retry=2):
    """Fetch single 10K batch from ES"""
    for attempt in range(retry):
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": "2025-12-02T07:30:00Z", "lte": "2025-12-02T10:30:00Z"}}},
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
                auth=(ES_USER, ES_PASSWORD),
                verify=False,
                timeout=90
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return data['hits']['hits']
            elif resp.status_code in [401, 403]:
                if attempt < retry - 1:
                    time.sleep(2)
                    continue
                else:
                    return None
            else:
                return None
        except Exception as e:
            if attempt < retry - 1:
                time.sleep(1)
                continue
            return None
    
    return None

def main():
    print("🔄 Batch Fetcher - 10K batches (exactly at ES limit)")
    print(f"   Time range: 2025-12-02 07:30-10:30 UTC")
    print(f"   Batch size: 10,000 | Total batches: 7")
    print()
    
    all_errors = []
    batch_num = 0
    max_batches = 7  # 7 * 10K = 70K capacity
    failed_batches = []
    
    for from_idx in range(0, max_batches * 10000, 10000):
        batch_num += 1
        print(f"🔄 Batch {batch_num}/7 (from={from_idx:5d}, size=10000)...", end='', flush=True)
        
        hits = fetch_batch(from_idx, 10000, retry=2)
        
        if hits is None:
            print(f" ❌ FAILED")
            failed_batches.append(batch_num)
            continue
        
        if not hits:
            print(f" ✅ NO MORE DATA")
            break
        
        # Process hits
        for hit in hits:
            source = hit['_source']
            all_errors.append({
                'message': str(source.get('message', ''))[:300],
                'application': source.get('application.name', 'unknown'),
                'cluster': source.get('topic', 'unknown'),
                'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
                'timestamp': source.get('@timestamp', ''),
                'trace_id': source.get('traceId', '')
            })
        
        pct = min(100, len(all_errors) / 65000 * 100)
        print(f" ✅ {len(hits):5d} | Total: {len(all_errors):6d} ({pct:5.1f}%)")
    
    # Verify data
    print(f"\n📊 DATA QUALITY CHECK:")
    print(f"   Total records: {len(all_errors):,}")
    
    trace_ids = sum(1 for e in all_errors if e['trace_id'])
    print(f"   traceId coverage: {trace_ids:,}/{len(all_errors):,} ({100*trace_ids/len(all_errors) if all_errors else 0:.1f}%)")
    
    # Application distribution
    apps = {}
    for e in all_errors:
        app = e['application']
        apps[app] = apps.get(app, 0) + 1
    
    print(f"\n   📱 Top 5 applications:")
    for app, count in sorted(apps.items(), key=lambda x: -x[1])[:5]:
        pct = 100*count/len(all_errors)
        print(f"      {app}: {count:,} ({pct:.1f}%)")
    
    # PCBS Master
    masters = {}
    for e in all_errors:
        master = e['pcbs_master']
        masters[master] = masters.get(master, 0) + 1
    
    print(f"\n   🏢 PCBS Masters:")
    for master, count in sorted(masters.items(), key=lambda x: -x[1]):
        pct = 100*count/len(all_errors)
        print(f"      {master}: {count:,} ({pct:.1f}%)")
    
    if failed_batches:
        print(f"\n⚠️  Failed batches: {failed_batches}")
    
    # Save
    output_file = 'data/batch_COMPLETE_65K.json'
    with open(output_file, 'w') as f:
        json.dump({
            'errors': all_errors,
            'stats': {
                'total': len(all_errors),
                'with_trace_id': trace_ids,
                'fetch_timestamp': datetime.utcnow().isoformat(),
                'time_range': '2025-12-02 07:30-10:30 UTC',
                'coverage_pct': 100 * len(all_errors) / 65000
            }
        }, f)
    
    print(f"\n💾 Saved to {output_file}")
    print(f"✅ COMPLETE - READY FOR ANALYSIS!")
    return len(all_errors)

if __name__ == '__main__':
    main()
