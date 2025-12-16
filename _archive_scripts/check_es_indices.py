#!/usr/bin/env python3
"""
Check what indices actually exist in ES
"""

import requests
from requests.auth import HTTPBasicAuth
import os
import urllib3

urllib3.disable_warnings()

ES_CONFIG = {
    'url': os.getenv('ES_URL', 'https://elasticsearch-test.kb.cz:9500'),
    'user': os.getenv('ES_USER', 'XX_PCBS_ES_READ'),
    'password': os.getenv('ES_PASSWORD')  # Required: Set in .env file
}

print("🔍 Checking available indices in Elasticsearch")
print(f"   URL: {ES_CONFIG['url']}")
print()

patterns = [
    'cluster-app_pcb-*',
    'cluster-app_pca-*',
    'cluster-app_pcb-ch-*',
    'logstash-kb-k8s-apps-nprod-*',
    'logstash-kb-k8s-apps-prod-*',
    '*pcb*',
    '*pca*'
]

for pattern in patterns:
    print(f"📋 Pattern: {pattern}")
    try:
        resp = requests.get(
            f"{ES_CONFIG['url']}/_cat/indices/{pattern}?v&h=index,docs.count,store.size&s=index",
            auth=HTTPBasicAuth(ES_CONFIG['user'], ES_CONFIG['password']),
            verify=False,
            timeout=10
        )
        
        if resp.status_code == 200:
            lines = resp.text.strip().split('\n')
            if len(lines) > 1:  # Has results
                print(f"   Found {len(lines)-1} indices:")
                for line in lines[:10]:  # Show first 10
                    print(f"   {line}")
                if len(lines) > 10:
                    print(f"   ... and {len(lines)-10} more")
            else:
                print("   ❌ No indices found")
        else:
            print(f"   ❌ HTTP {resp.status_code}")
    except Exception as e:
        print(f"   ❌ Error: {e}")
    
    print()

print("✅ Check complete")
