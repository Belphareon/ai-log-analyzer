import requests
import json
import os
from dotenv import load_dotenv

load_dotenv('/home/jvsete/git/sas/ai-log-analyzer/.env')

BASE_URL = os.getenv('ES_URL')
ES_USER = os.getenv('ES_USER')
ES_PASSWORD = os.getenv('ES_PASSWORD')
INDICES = os.getenv('ES_INDEX')

# Create session
session = requests.Session()
session.verify = False
session.headers.update({'Connection': 'keep-alive'})

query = {
    "query": {
        "bool": {
            "must": [
                {"range": {"@timestamp": {"gte": "2025-12-02T07:30:00Z", "lte": "2025-12-02T10:30:00Z"}}},
                {"term": {"level": "ERROR"}}
            ]
        }
    },
    "from": 0,
    "size": 5000
}

print("Fetching first batch...")
resp = session.post(
    f"{BASE_URL}/{INDICES}/_search",
    json=query,
    auth=(ES_USER, ES_PASSWORD),
    timeout=60
)

print(f"Status: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    hits = data['hits']['hits']
    total = data['hits']['total']['value']
    print(f"✅ Got {len(hits)} records, total available: {total}")
else:
    print(f"❌ Error: {resp.text[:200]}")

