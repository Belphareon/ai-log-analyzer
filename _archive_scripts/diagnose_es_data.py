#!/usr/bin/env python3
"""
Diagnostic: Check what ES returns for last 24h
"""

import requests
from requests.auth import HTTPBasicAuth
import json
from datetime import datetime, timedelta, timezone
import os
import urllib3

urllib3.disable_warnings()

ES_CONFIG = {
    'url': os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500'),
    'user': os.getenv('ES_USER', 'XX_PCBS_ES_READ'),
    'password': os.getenv('ES_PASSWORD', 'ta@@swLT69EX.6164'),
    'indices': os.getenv('ES_INDICES', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')
}

now = datetime.now(timezone.utc)
start = now - timedelta(hours=24)

print("🔍 ES Diagnostic Query")
print(f"   URL: {ES_CONFIG['url']}")
print(f"   Indices: {ES_CONFIG['indices']}")
print(f"   Time range: {start.isoformat()} to {now.isoformat()}")
print()

# Simple aggregation to see ALL namespaces
query = {
    "track_total_hits": True,  # Get real total count
    "query": {
        "bool": {
            "must": [
                {"range": {"@timestamp": {"gte": start.isoformat(), "lte": now.isoformat()}}},
                {"term": {"level": "ERROR"}}
            ]
        }
    },
    "aggs": {
        "namespaces": {
            "terms": {
                "field": "kubernetes.namespace",
                "size": 100,
                "order": {"_count": "desc"}
            }
        }
    },
    "size": 0
}

try:
    print("🔄 Sending query to ES...")
    resp = requests.post(
        f"{ES_CONFIG['url']}/{ES_CONFIG['indices']}/_search",
        json=query,
        auth=HTTPBasicAuth(ES_CONFIG['user'], ES_CONFIG['password']),
        verify=False,
        timeout=30
    )
    
    if resp.status_code != 200:
        print(f"❌ ES query failed: {resp.status_code}")
        print(resp.text[:1000])
        exit(1)
    
    data = resp.json()
    
    # Total hits
    total_errors = data['hits']['total']['value']
    print(f"📊 Total ERROR logs in last 24h: {total_errors:,}")
    print()
    
    # Namespaces
    ns_buckets = data['aggregations']['namespaces']['buckets']
    print(f"📦 Namespaces found: {len(ns_buckets)}")
    print()
    print(f"   {'Namespace':<30} {'Error Count':<12} {'%'}")
    print(f"   {'-'*60}")
    
    for bucket in ns_buckets:
        ns = bucket['key']
        count = bucket['doc_count']
        pct = (count / total_errors * 100) if total_errors > 0 else 0
        print(f"   {ns:<30} {count:>11,}  {pct:>6.2f}%")
    
    print()
    
    # Check if we're missing namespaces
    expected = [
        'pca-dev-01-app', 'pca-fat-01-app', 'pca-sit-01-app', 'pca-uat-01-app',
        'pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-sit-01-app', 'pcb-uat-01-app',
        'pcb-ch-dev-01-app', 'pcb-ch-fat-01-app', 'pcb-ch-sit-01-app', 'pcb-ch-uat-01-app'
    ]
    
    found = [b['key'] for b in ns_buckets]
    missing = [ns for ns in expected if ns not in found]
    
    if missing:
        print(f"⚠️  Missing namespaces ({len(missing)}):")
        for ns in missing:
            print(f"   - {ns}")
    else:
        print("✅ All expected namespaces found!")
    
    print()
    print("✅ Diagnostic complete")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
