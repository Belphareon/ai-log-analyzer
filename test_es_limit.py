#!/usr/bin/env python3
"""
Test script to verify ES 10K window limit
Try different from/size combinations to find actual limit
"""

import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')
INDICES = "cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*"

def test_limit(from_idx, size, label):
    """Test specific from/size combination"""
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": "2025-12-02T07:30:00Z", "lte": "2025-12-02T10:30:00Z"}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "from": from_idx,
        "size": size
    }
    
    try:
        print(f"\n📊 Test: {label}")
        print(f"   from={from_idx}, size={size} (window: {from_idx + size})")
        
        resp = requests.post(
            f"{BASE_URL}/{INDICES}/_search",
            json=query,
            auth=(ES_USER, ES_PASSWORD),
            verify=False,
            timeout=30
        )
        
        print(f"   Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            total_hits = data['hits']['total']['value']
            returned = len(data['hits']['hits'])
            print(f"   ✅ SUCCESS: Got {returned} records (total available: {total_hits})")
            return True
        else:
            error = resp.json()
            print(f"   ❌ FAILED: {error.get('error', {}).get('type', 'Unknown error')}")
            if 'error' in error:
                print(f"   Reason: {error['error'].get('reason', 'No reason given')}")
            return False
            
    except Exception as e:
        print(f"   ❌ EXCEPTION: {str(e)}")
        return False

print("=" * 70)
print("🔍 ES LIMIT TEST - Checking 10K window limit claim")
print("=" * 70)

# Test 1: Small window (should work)
print("\n1️⃣  BASELINE TESTS (should all work)")
test_limit(0, 100, "Small batch: 0-100")
test_limit(0, 1000, "Medium batch: 0-1000")
test_limit(0, 5000, "Large batch: 0-5000")

# Test 2: Edge of 10K
print("\n2️⃣  TESTING 10K BOUNDARY")
test_limit(0, 10000, "Exactly 10K: 0-10000")
test_limit(0, 10001, "Just over 10K: 0-10001")
test_limit(0, 15000, "15K window: 0-15000")

# Test 3: Using offset (from > 0)
print("\n3️⃣  TESTING WITH OFFSET (from > 0)")
test_limit(5000, 5000, "Mid-window: 5000-10000 (total 10K)")
test_limit(5000, 5001, "Just over: 5000-10001 (total 10001)")
test_limit(10000, 5000, "After 10K: 10000-15000 (total 15K)")

# Test 4: Very large offset
print("\n4️⃣  TESTING LARGE OFFSET")
test_limit(50000, 100, "Large offset: 50000 + 100")
test_limit(60000, 5000, "Very large: 60000 + 5000 (total 65K)")

print("\n" + "=" * 70)
print("✨ TEST COMPLETE")
print("=" * 70)
