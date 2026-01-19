#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

import asyncio
from datetime import datetime, timedelta
from app.services.elasticsearch import es_service

async def main():
    await es_service.connect()
    
    # Nov 7, 2025 14:00-16:00 UTC = 15:00-17:00 CET (kde byl peak v 15:30 CET = 14:30 UTC)
    time_from = datetime(2025, 11, 7, 13, 0, 0)  # 13:00 UTC = 14:00 CET
    time_to = datetime(2025, 11, 7, 16, 0, 0)    # 16:00 UTC = 17:00 CET
    
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat() + "Z", "lte": time_to.isoformat() + "Z"}}},
                    {"range": {"level_value": {"gte": 40000}}}
                ]
            }
        },
        "size": 0,
        "aggs": {
            "over_time": {"date_histogram": {"field": "@timestamp", "fixed_interval": "10m"}},
            "by_app": {"terms": {"field": "kubernetes.labels.app.keyword", "size": 30}},
            "by_message": {
                "terms": {"field": "message.keyword", "size": 20},
                "aggs": {"apps": {"terms": {"field": "kubernetes.labels.app.keyword", "size": 5}}}
            },
            "by_fp": {
                "terms": {"field": "_metadata.fingerprint.keyword", "size": 50},
                "aggs": {"sample": {"top_hits": {"size": 1, "_source": ["message", "kubernetes.labels.app", "@timestamp"]}}}
            }
        }
    }
    
    print(f"🔍 Investigating PEAK on Nov 7, 2025")
    print(f"   Time window: {time_from.strftime('%Y-%m-%d %H:%M')} - {time_to.strftime('%H:%M')} UTC")
    print(f"   (CET: 14:00 - 17:00)")
    print()
    
    resp = await es_service.client.search(index=es_service.index_pattern, body=query)
    
    total = resp['hits']['total']['value']
    print(f"📊 TOTAL ERRORS: {total:,}\n")
    
    if total == 0:
        print("⚠️  No errors found in this time window!")
        print("   Checking if index pattern is correct...")
        return
    
    print("=== TIMELINE (10-minute buckets) ===")
    max_count = max(b['doc_count'] for b in resp['aggregations']['over_time']['buckets'])
    for b in resp['aggregations']['over_time']['buckets']:
        ts = datetime.fromisoformat(b['key_as_string'].replace('Z', '+00:00'))
        cnt = b['doc_count']
        bar_len = int((cnt / max_count) * 80) if max_count > 0 else 0
        bar = '█' * bar_len
        mark = ' ⚠️ PEAK!' if cnt > 5000 else ''
        # Show both UTC and CET
        cet_hour = (ts.hour + 1) % 24  # Simple CET conversion
        print(f"{ts.strftime('%H:%M')} UTC ({cet_hour:02d}:{ts.minute:02d} CET): {cnt:5d} {bar}{mark}")
    
    print("\n=== TOP 15 AFFECTED APPLICATIONS ===")
    for i, b in enumerate(resp['aggregations']['by_app']['buckets'][:15], 1):
        print(f"{i:2d}. {b['key']:45s} {b['doc_count']:6,} errors")
    
    print("\n=== TOP 10 ERROR MESSAGES ===")
    for i, b in enumerate(resp['aggregations']['by_message']['buckets'][:10], 1):
        msg = b['key'][:100]
        apps = [a['key'] for a in b['apps']['buckets'][:3]]
        print(f"\n{i}. Count: {b['doc_count']:,}")
        print(f"   Message: {msg}")
        print(f"   Apps: {', '.join(apps)}")
    
    print("\n=== TOP 10 ERROR FINGERPRINTS ===")
    for i, b in enumerate(resp['aggregations']['by_fp']['buckets'][:10], 1):
        sample = b['sample']['hits']['hits'][0]['_source']
        ts = sample.get('@timestamp', 'N/A')
        app = sample.get('kubernetes', {}).get('labels', {}).get('app', 'unknown')
        print(f"\n{i}. Fingerprint: {b['key'][:20]}... (x{b['doc_count']:,})")
        print(f"   App: {app}")
        print(f"   Time: {ts}")
        print(f"   Msg: {sample['message'][:120]}")

asyncio.run(main())
