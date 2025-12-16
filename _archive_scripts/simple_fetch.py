#!/usr/bin/env python3
"""Simple standalone ES fetcher - no dependencies on app modules"""
import requests
from requests.auth import HTTPBasicAuth
import json
from datetime import datetime
import argparse

# ES credentials from .env
ES_URL = "https://elasticsearch-test.kb.cz:9500"
ES_USER = "XX_PCBS_ES_READ"
ES_PASSWORD = os.getenv('ES_PASSWORD', 'your_password_here')
ES_INDEX = "cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*"

def fetch_errors(from_time, to_time, max_sample=5000):
    """Fetch errors from ES - simple version"""
    
    query = {
        "size": max_sample,
        "query": {
            "bool": {
                "must": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": from_time,
                                "lt": to_time
                            }
                        }
                    },
                    {
                        "term": {
                            "level": "ERROR"
                        }
                    }
                ]
            }
        },
        "sort": [{"@timestamp": "asc"}],
        "_source": ["message", "application.name", "kubernetes.namespace", "@timestamp", "traceId"]
    }
    
    url = f"{ES_URL}/{ES_INDEX}/_search"
    
    print(f"Fetching from {from_time} to {to_time}...")
    print(f"Query URL: {url}")
    
    response = requests.post(
        url,
        json=query,
        auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
        verify=False,
        timeout=60
    )
    
    if response.status_code != 200:
        print(f"Error: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    hits = data.get('hits', {}).get('hits', [])
    total = data.get('hits', {}).get('total', {}).get('value', 0)
    
    print(f"Total errors found: {total:,}")
    print(f"Fetched: {len(hits):,}")
    
    # Transform to our format
    errors = []
    for hit in hits:
        source = hit['_source']
        errors.append({
            'message': source.get('message', ''),
            'app': source.get('application.name', source.get('application', {}).get('name', 'unknown')),
            'namespace': source.get('kubernetes.namespace', source.get('kubernetes', {}).get('namespace', 'unknown')),
            'timestamp': source.get('@timestamp', ''),
            'trace_id': source.get('traceId', '')
        })
    
    return {
        'period_start': from_time,
        'period_end': to_time,
        'total_errors': total,
        'sample_size': len(errors),
        'coverage_percent': (len(errors) / total * 100) if total > 0 else 0,
        'errors': errors
    }

def main():
    parser = argparse.ArgumentParser(description='Simple ES fetch')
    parser.add_argument('--from', dest='from_time', required=True, help='Start time (UTC)')
    parser.add_argument('--to', dest='to_time', required=True, help='End time (UTC)')
    parser.add_argument('--max-sample', type=int, default=5000, help='Max sample size')
    parser.add_argument('--output', required=True, help='Output JSON file')
    
    args = parser.parse_args()
    
    result = fetch_errors(args.from_time, args.to_time, args.max_sample)
    
    if result:
        with open(args.output, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\n✅ Saved to {args.output}")
        print(f"   Coverage: {result['coverage_percent']:.1f}%")
    else:
        print("❌ Fetch failed")
        return 1
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
