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

def test_batch(size_val, from_val=0, label=""):
    """Test specific size"""
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": "2025-12-02T07:30:00Z", "lte": "2025-12-02T10:30:00Z"}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "from": from_val,
        "size": size_val,
        "sort": ["_id"]
    }
    
    resp = requests.post(
        f"{BASE_URL}/{INDICES}/_search",
        json=query,
        auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
        verify=False,
        timeout=60
    )
    
    window = from_val + size_val
    status = "✅" if resp.status_code == 200 else "❌"
    
    if resp.status_code == 200:
        hits = len(resp.json()['hits']['hits'])
        print(f"{status} {label:25s} | from={from_val:5d}, size={size_val:6d} (window={window:6d}) → Got {hits:6d} records")
    else:
        error = resp.json().get('error', {}).get('reason', 'Unknown')
        print(f"{status} {label:25s} | from={from_val:5d}, size={size_val:6d} (window={window:6d}) → ERROR: {error[:50]}")
    
    return resp.status_code == 200

print("Testing different batch sizes with from/size pagination:")
print("=" * 100)

# Test different sizes
test_batch(1000, 0, "Small: 1K")
test_batch(5000, 0, "Medium: 5K")
test_batch(10000, 0, "10K (claimed limit)")
test_batch(15000, 0, "15K (over limit?)")
test_batch(20000, 0, "20K (over limit?)")
test_batch(30000, 0, "30K (over limit?)")
test_batch(50000, 0, "50K (over limit?)")

print("\nNow testing search_after (should bypass limit):")
print("=" * 100)

# Test search_after with large batch
query_sa = {
    "query": {
        "bool": {
            "must": [
                {"range": {"@timestamp": {"gte": "2025-12-02T07:30:00Z", "lte": "2025-12-02T10:30:00Z"}}},
                {"term": {"level": "ERROR"}}
            ]
        }
    },
    "size": 50000,
    "sort": ["_id"]
}

resp = requests.post(
    f"{BASE_URL}/{INDICES}/_search",
    json=query_sa,
    auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
    verify=False,
    timeout=60
)

if resp.status_code == 200:
    hits = len(resp.json()['hits']['hits'])
    print(f"✅ search_after with size=50000 → Got {hits:6d} records")
else:
    error = resp.json().get('error', {}).get('reason', 'Unknown')
    print(f"❌ search_after with size=50000 → ERROR: {error}")

