import requests
from requests.auth import HTTPBasicAuth
import json
import os
from dotenv import load_dotenv

load_dotenv('/home/jvsete/git/sas/ai-log-analyzer/.env')

BASE_URL = os.getenv('ES_URL')
ES_USER = os.getenv('ES_USER')
ES_PASSWORD = os.getenv('ES_PASSWORD')
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
    "from": 0,
    "size": 20000,
    "_source": ["message", "application.name", "@timestamp", "traceId"]
}

resp = requests.post(
    f"{BASE_URL}/{INDICES}/_search",
    json=query,
    auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
    verify=False,
    timeout=120
)

print(f"Status: {resp.status_code}")
print(f"Response:")
print(json.dumps(resp.json(), indent=2)[:500])
