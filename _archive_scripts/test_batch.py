import requests
from requests.auth import HTTPBasicAuth
import os
from dotenv import load_dotenv
import urllib3
urllib3.disable_warnings()

load_dotenv('/home/jvsete/git/sas/ai-log-analyzer/.env')

ES_URL = os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD', 'ta@@swLT69EX.6164')
INDICES = os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*')

# Test with different batch sizes
for batch_size in [1000, 5000, 10000, 15000, 50000]:
    query = {
        'query': {
            'bool': {
                'must': [
                    {'range': {'@timestamp': {'gte': '2025-12-02T07:30:00Z', 'lte': '2025-12-02T10:30:00Z'}}},
                    {'term': {'level': 'ERROR'}}
                ]
            }
        },
        'from': 0,
        'size': batch_size,
    }
    
    resp = requests.post(
        f'{ES_URL}/{INDICES}/_search',
        json=query,
        auth=HTTPBasicAuth(ES_USER, ES_PASSWORD),
        verify=False,
        timeout=30
    )
    
    print(f'Size {batch_size:5d}: Status {resp.status_code}', end=' ')
    if resp.status_code == 200:
        total = resp.json().get('hits', {}).get('total', {}).get('value', 0)
        print(f'✅ Total: {total}')
    else:
        try:
            error = resp.json().get('error', {}).get('reason', resp.text[:100])
            print(f'❌ {error}')
        except:
            print(f'❌ {resp.text[:100]}')
