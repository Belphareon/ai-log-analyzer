#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

import asyncio
from datetime import datetime, timedelta
from app.services.elasticsearch import es_service

async def main():
    await es_service.connect()
    
    time_to = datetime.utcnow()
    time_from = time_to - timedelta(hours=4)
    
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat(), "lte": time_to.isoformat()}}},
                    {"range": {"level_value": {"gte": 40000}}}
                ]
            }
        },
        "size": 0,
        "aggs": {
            "over_time": {"date_histogram": {"field": "@timestamp", "fixed_interval": "10m"}},
            "by_app": {"terms": {"field": "kubernetes.labels.app.keyword", "size": 20}},
            "by_fp": {
                "terms": {"field": "_metadata.fingerprint.keyword", "size": 50},
                "aggs": {"sample": {"top_hits": {"size": 1, "_source": ["message", "kubernetes.labels.app"]}}}
            }
        }
    }
    
    print("Querying ES...")
    resp = await es_service.client.search(index=es_service.index_pattern, body=query)
    
    total = resp['hits']['total']['value']
    print(f"\nTOTAL: {total:,} errors\n")
    
    print("=== TIMELINE ===")
    for b in resp['aggregations']['over_time']['buckets']:
        ts = datetime.fromisoformat(b['key_as_string'].replace('Z', '+00:00'))
        cnt = b['doc_count']
        bar = '█' * (cnt // 100)
        mark = ' ← PEAK!' if cnt > 5000 else ''
        print(f"{ts.strftime('%H:%M')}: {cnt:5d} {bar}{mark}")
    
    print("\n=== TOP APPS ===")
    for b in resp['aggregations']['by_app']['buckets'][:15]:
        print(f"{b['key']:40s} {b['doc_count']:6d}")
    
    print("\n=== TOP ERRORS ===")
    for i, b in enumerate(resp['aggregations']['by_fp']['buckets'][:10], 1):
        sample = b['sample']['hits']['hits'][0]['_source']
        print(f"{i}. {b['key'][:16]}... x{b['doc_count']:,}")
        print(f"   {sample['message'][:100]}")
    
    await es_service.close()

asyncio.run(main())
