"""Test kolik errorů můžeme fetchnout z ES"""
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

import asyncio
from datetime import datetime, timedelta
from app.services.elasticsearch import es_service

async def test_fetch_limits():
    await es_service.connect()
    
    time_to = datetime.utcnow()
    time_from = time_to - timedelta(hours=1)  # Jen 1 hodina
    
    # Test různé velikosti
    for size in [1000, 5000, 10000]:
        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": time_from.isoformat() + "Z", "lte": time_to.isoformat() + "Z"}}},
                        {"range": {"level_value": {"gte": 40000}}}
                    ]
                }
            },
            "size": size,
            "_source": ["message", "kubernetes.labels.app", "@timestamp"]
        }
        
        print(f"Testing size={size}...")
        start = datetime.now()
        
        try:
            response = await es_service.client.search(
                index=es_service.index_pattern, 
                body=query,
                request_timeout=60
            )
            
            duration = (datetime.now() - start).total_seconds()
            hits = len(response['hits']['hits'])
            total = response['hits']['total']['value']
            
            print(f"  ✅ Got {hits} hits from {total} total in {duration:.1f}s")
        except Exception as e:
            print(f"  ❌ Failed: {e}")

asyncio.run(test_fetch_limits())
