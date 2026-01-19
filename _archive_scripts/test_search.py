import requests
import json
import time
import os
from dotenv import load_dotenv

load_dotenv('/home/jvsete/git/sas/ai-log-analyzer/.env')

BASE_URL = os.getenv('ES_URL')
USER = os.getenv('ES_USER')
PASS = os.getenv('ES_PASSWORD')
INDICES = os.getenv('ES_INDEX')

query = {
    "query": {
        "bool": {
            "must": [
                {"range": {"@timestamp": {"gte": "2025-12-02T07:30:00Z", "lte": "2025-12-02T10:30:00Z"}}},
                {"term": {"level": "ERROR"}}
            ]
        }
    },
    "size": 100,
    "sort": ["_id"],
    "_source": ["message", "application.name", "@timestamp", "traceId"]
}

for attempt in range(3):
    print(f"Attempt {attempt+1}...", end=" ", flush=True)
    resp = requests.post(
        f"{BASE_URL}/{INDICES}/_search",
        json=query,
        auth=(USER, PASS),
        verify=False,
        timeout=30
    )
    
    print(f"Status {resp.status_code}")
    
    if resp.status_code == 200:
        data = resp.json()
        count = len(data['hits']['hits'])
        total = data['hits']['total']['value']
        print(f"✅ Got {count} records, total available: {total}")
        break
    elif resp.status_code in [401, 403]:
        if attempt < 2:
            print(f"⏳ Auth issue, retrying in 2s...")
            time.sleep(2)
        else:
            print(f"❌ Auth failed after retries")
    else:
        print(f"❌ Error")
        print(json.dumps(resp.json(), indent=2)[:300])
