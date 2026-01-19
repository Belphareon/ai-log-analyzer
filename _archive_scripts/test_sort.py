import requests
from requests.auth import HTTPBasicAuth
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')
from dotenv import load_dotenv
import os

load_dotenv('/home/jvsete/git/sas/ai-log-analyzer/.env')
ES_URL = os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD', 'ta@@swLT69EX.6164')
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

# Test different sort options
sort_options = [
    (None, 'No sort'),
    ([{"@timestamp": "asc"}], 'Sort by @timestamp'),
    ([{"@timestamp": "asc"}, {"_id": "asc"}], 'Sort by @timestamp + _id'),
]

for sort, desc in sort_options:
    query = {
        'query': {
            'bool': {
                'must': [
                    {'range': {'@timestamp': {'gte': '2025-12-02T07:30:00Z', 'lte': '2025-12-02T10:30:00Z'}}},
                    {'term': {'level': 'ERROR'}}
                ]
            }
        },
        'size': 5
    }
    
    if sort:
        query['sort'] = sort
    
    resp = requests.post(
        f'{ES_URL}/{INDICES}/_search',
        json=query,
        auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
        verify=False,
        timeout=30
    )
    
    hits = len(resp.json()['hits']['hits']) if resp.status_code == 200 else 0
    print(f'{desc:40s} → {hits} hits')
