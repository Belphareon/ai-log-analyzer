#!/usr/bin/env python3
"""
Fetch ALL errors from ES bez omezení - paginátor přes search_after
Stahuje po 5000 errors per request, bez omezení na index.max_result_window
"""
import requests
import json
import urllib3
from datetime import datetime

urllib3.disable_warnings()

BASE_URL = "https://elasticsearch-test.kb.cz:9500"
USER = "XX_PCBS_ES_READ"
PASS = os.getenv('ES_PASSWORD')  # Required: Set in .env file
INDICES = "cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*"

auth = (USER, PASS)
headers = {"Content-Type": "application/json"}

def get_total_count(date_from, date_to):
    """Get total count - to know cíl"""
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": date_from, "lte": date_to}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        }
    }
    
    resp = requests.post(
        f"{BASE_URL}/{INDICES}/_count",
        json=query,
        auth=auth,
        verify=False,
        timeout=30
    )
    return resp.json()['count']

def fetch_all_with_search_after(date_from, date_to, batch_size=5000, max_errors=None):
    """
    Fetchuj všechny errors pomocí search_after
    - date_from, date_to: ISO timestamps
    - batch_size: errors per request (default 5000)
    - max_errors: stop po X errors (None = všechny)
    """
    
    total = get_total_count(date_from, date_to)
    print(f"📊 Total errors in ES: {total:,}")
    
    if max_errors:
        target = min(max_errors, total)
    else:
        target = total
    print(f"   Target to fetch: {target:,}")
    
    all_errors = []
    search_after = None
    batch_num = 0
    
    # Base query - search_after potřebuje sort!
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
          # Must have sort for search_after!
        "_source": ["message", "application.name", "@timestamp", "traceId", "kubernetes.labels.eamApplication", "topic"]
    }
    
    print(f"\n📥 Fetching in batches of {batch_size}...")
    
    while len(all_errors) < target:
        batch_num += 1
        query = base_query.copy()
        
        if search_after:
            query['search_after'] = search_after
        
        try:
            resp = requests.post(
                f"{BASE_URL}/{INDICES}/_search",
                json=query,
                auth=auth,
                verify=False,
                timeout=60
            )
            
            if resp.status_code != 200:
                print(f"\n❌ Error {resp.status_code}: {resp.text[:200]}")
                break
            
            data = resp.json()
            
            if 'error' in data:
                print(f"\n❌ ES Error: {data['error']}")
                break
            
            hits = data['hits']['hits']
            
            if not hits:
                print(f"\n✅ No more hits - fetched all available")
                break
            
            # Process hits
            for hit in hits:
                source = hit.get('_source', {})
                msg = source.get('message', '')
                if isinstance(msg, dict):
                    msg = json.dumps(msg)
                if isinstance(msg, str):
                    msg = msg[:300]  # Limit message length
                
                all_errors.append({
                    'message': msg,
                    'application': source.get('application.name', 'unknown'),
                    'cluster': source.get('topic', 'unknown'),
                    'pcbs_master': source.get('kubernetes', {}).get('labels', {}).get('eamApplication', 'unknown'),
                    'timestamp': source.get('@timestamp', ''),
                    'trace_id': source.get('traceId', '')
                })
            
            # Progress
            pct = min(100, (len(all_errors) / target * 100))
            bars = '█' * int(pct / 2)
            print(f"\r   [{bars:<50}] {len(all_errors):>6,}/{target:,} ({pct:5.1f}%)", end='', flush=True)
            
            # Prepare search_after for NEXT batch
            if len(hits) > 0:
                last_hit = hits[-1]
                # Use _id for pagination - sort by _id
                search_after = [last_hit['_id']]
            
        except requests.exceptions.Timeout:
            print(f"\n⏱️  Timeout na batch {batch_num} - pausující...")
            continue
        except Exception as e:
            print(f"\n❌ Exception: {e}")
            break
    
    print()
    return all_errors, total

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch ALL errors from ES with pagination')
    parser.add_argument('--from', dest='date_from', required=True, help='ISO timestamp from')
    parser.add_argument('--to', dest='date_to', required=True, help='ISO timestamp to')
    parser.add_argument('--max', type=int, default=None, help='Max errors to fetch (None=all)')
    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size per request')
    parser.add_argument('--output', required=True, help='Output JSON file')
    
    args = parser.parse_args()
    
    errors, total = fetch_all_with_search_after(
        args.date_from,
        args.date_to,
        batch_size=args.batch_size,
        max_errors=args.max
    )
    
    print(f"\n✅ Successfully fetched {len(errors):,} errors from {total:,} total")
    print(f"   Coverage: {(len(errors)/total*100):.1f}%")
    
    result = {
        'period_start_utc': args.date_from,
        'period_end_utc': args.date_to,
        'total_errors_in_es': total,
        'fetched_errors': len(errors),
        'coverage_percent': (len(errors) / total * 100) if total > 0 else 0,
        'fetch_timestamp': datetime.utcnow().isoformat(),
        'errors': errors
    }
    
    with open(args.output, 'w') as f:
        json.dump(result, f, default=str)
    
    file_size_mb = len(json.dumps(result)) / (1024*1024)
    print(f"💾 Saved to {args.output} ({file_size_mb:.1f}MB)")
