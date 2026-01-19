import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')
import asyncio
from datetime import datetime, timedelta
import re
from collections import Counter
from app.services.elasticsearch import es_service

async def main():
    await es_service.connect()
    
    # Today from 7:00 AM
    now = datetime.utcnow()
    time_from = datetime(now.year, now.month, now.day, 6, 0, 0)  # 6 UTC = 7 CET
    
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat() + "Z", "lte": now.isoformat() + "Z"}}},
                    {"range": {"level_value": {"gte": 40000}}}
                ]
            }
        },
        "size": 1000,
        "_source": ["message", "kubernetes.labels.app", "@timestamp"]
    }
    
    print(f"🔍 Analyzing errors from {time_from.strftime('%Y-%m-%d %H:%M')} to {now.strftime('%H:%M')} UTC")
    resp = await es_service.client.search(index=es_service.index_pattern, body=query)
    
    hits = resp['hits']['hits']
    total = resp['hits']['total']['value']
    print(f"📊 {total:,} total errors, analyzing {len(hits)} samples\n")
    
    apps = []
    card_ids = []
    error_codes = []
    
    for hit in hits:
        src = hit['_source']
        app = src.get('kubernetes', {}).get('labels', {}).get('app', 'unknown')
        msg = src.get('message', '')
        
        apps.append(app)
        
        card_match = re.search(r'[Cc]ard.*?id\s+(\d+)', msg)
        if card_match:
            card_ids.append(card_match.group(1))
        
        err_match = re.search(r'err\.(\d+)', msg)
        if err_match:
            error_codes.append(f"err.{err_match.group(1)}")
    
    print("=== TOP APPS ===")
    for app, cnt in Counter(apps).most_common(10):
        print(f"{app:40s} {cnt:4d} ({cnt/len(hits)*100:5.1f}%)")
    
    print("\n=== TOP CARD IDs ===")
    for card, cnt in Counter(card_ids).most_common(10):
        print(f"Card {card:10s} {cnt:4d} times")
    
    print("\n=== ERROR CODES ===")
    for code, cnt in Counter(error_codes).most_common():
        print(f"{code:10s} {cnt:4d} times")

asyncio.run(main())
