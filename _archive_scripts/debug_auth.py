import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv

load_dotenv('/home/jvsete/git/sas/ai-log-analyzer/.env')

BASE_URL = os.getenv('ES_URL')
USER = os.getenv('ES_USER')
PASS = os.getenv('ES_PASSWORD')

print(f"Base URL: {BASE_URL}")
print(f"User: {USER}")
print(f"Pass: {PASS}")

# Prepare request
req = requests.Request(
    'GET',
    f'{BASE_URL}/_cluster/health',
    auth=HTTPBasicAuth(USER, PASS)
)

prepared = req.prepare()
print(f"\nPrepared Authorization header: {prepared.headers.get('Authorization', 'NOT SET')}")

# Try the request
resp = requests.post(
    f"{BASE_URL}/cluster-app_pcb-*/_search",
    json={"query": {"match_all": {}}, "size": 1},
    auth=(USER, PASS),
    verify=False,
    timeout=10,
    headers={'Connection': 'keep-alive'}
)

print(f"\nStatus: {resp.status_code}")
if resp.status_code != 200:
    print(f"Error: {resp.text[:300]}")
else:
    print(f"Success! Got response")

