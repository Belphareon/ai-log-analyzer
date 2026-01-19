#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

import asyncio
from datetime import datetime
from app.services.elasticsearch import es_service

async def main():
    await es_service.connect()
    
    # Peak window: 14:30-14:40 UTC (15:30-15:40 CET)
    time_from = datetime(2025, 11, 7, 14, 30, 0)
    time_to = datetime(2025, 11, 7, 14, 40, 0)
    
    # Simple query - just get top apps
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat() + "Z", "lte": time_to.isoformat() + "Z"}}},
                    {"range": {"level_value": {"gte": 40000}}}
                ]
            }
        },
        "size": 10,
        "aggs": {
            "by_app": {"terms": {"field": "kubernetes.labels.app.keyword", "size": 20}},
            "by_logger": {"terms": {"field": "logger_name.keyword", "size": 20}}
        },
        "_source": ["message", "kubernetes.labels.app", "logger_name", "@timestamp"]
    }
    
    print(f"🔍 PEAK DETAIL: Nov 7, 14:30-14:40 UTC (15:30-15:40 CET)")
    print()
    
    resp = await es_service.client.search(index=es_service.index_pattern, body=query)
    
    total = resp['hits']['total']['value']
    print(f"📊 Total errors in 10-min peak: {total:,}\n")
    
    print("=== TOP APPLICATIONS ===")
    for i, b in enumerate(resp['aggregations']['by_app']['buckets'], 1):
        pct = (b['doc_count'] / total * 100) if total > 0 else 0
        print(f"{i:2d}. {b['key']:40s} {b['doc_count']:6,} ({pct:5.1f}%)")
    
    print("\n=== TOP LOGGERS ===")
    for i, b in enumerate(resp['aggregations']['by_logger']['buckets'][:10], 1):
        pct = (b['doc_count'] / total * 100) if total > 0 else 0
        print(f"{i:2d}. {b['key']:50s} {b['doc_count']:6,} ({pct:5.1f}%)")
    
    print("\n=== SAMPLE ERRORS ===")
    for i, hit in enumerate(resp['hits']['hits'], 1):
        src = hit['_source']
        app = src.get('kubernetes', {}).get('labels', {}).get('app', 'unknown')
        msg = src.get('message', 'N/A')[:150]
        ts = src.get('@timestamp', 'N/A')
        print(f"\n{i}. [{ts}] {app}")
        print(f"   {msg}")

asyncio.run(main())
