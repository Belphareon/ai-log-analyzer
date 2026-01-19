import requests
import json
from dotenv import load_dotenv
import os

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
    }
}

resp = requests.post(
    f"{BASE_URL}/{INDICES}/_count",
    json=query,
    auth=(USER, PASS),
    verify=False,
    timeout=30
)

print(f"Status: {resp.status_code}")
print(f"Response: {json.dumps(resp.json(), indent=2)[:500]}")
