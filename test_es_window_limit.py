#!/usr/bin/env python3
"""
Verify ES limit - check what actually happens with different from+size combinations
"""

import requests
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv('ES_HOST', 'https://elasticsearch-test.kb.cz:9500')
ES_USER = os.getenv('ES_USER', 'XX_PCBS_ES_READ')
ES_PASSWORD = os.getenv('ES_PASSWORD')
INDICES = "cluster-app_pcb-*"  # Single index for faster response

def test_window(from_val, size_val, description):
    """Test a specific from/size combination"""
    
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
        "size": size_val
    }
    
    window_end = from_val + size_val
    print(f"\n{description}")
    print(f"  Query: from={from_val}, size={size_val} (window_end={window_end})")
    
    try:
        start = time.time()
        resp = requests.post(
            f"{BASE_URL}/{INDICES}/_search",
            json=query,
            auth=(ES_USER, ES_PASSWORD),
            verify=False,
            timeout=15
        )
        elapsed = time.time() - start
        
        print(f"  Status: {resp.status_code} (took {elapsed:.1f}s)")
        
        if resp.status_code == 200:
            data = resp.json()
            hits = data['hits']['hits']
            total = data['hits']['total']['value']
            print(f"  ✅ Got {len(hits)} records, total available: {total}")
            return True, len(hits)
        else:
            try:
                err = resp.json()
                error_type = err.get('error', {}).get('type', 'Unknown')
                reason = err.get('error', {}).get('reason', '')
                print(f"  ❌ Error: {error_type}")
                if 'result window' in reason.lower():
                    print(f"  💡 ES LIMIT FOUND: {reason}")
                else:
                    print(f"  Reason: {reason[:100]}")
            except:
                print(f"  ❌ HTTP {resp.status_code}")
            return False, 0
    except requests.exceptions.Timeout:
        print(f"  ⏱️  TIMEOUT (15s)")
        return False, 0
    except Exception as e:
        print(f"  ❌ Exception: {str(e)[:50]}")
        return False, 0

print("=" * 70)
print("🔬 ES WINDOW LIMIT VERIFICATION")
print("=" * 70)
print(f"Index: {INDICES}")
print(f"Query: ERROR logs from 2025-12-02 07:30-10:30 UTC")
print()

# Test progression
results = []

print("Testing small windows:")
results.append(("5K (0-5000)", test_window(0, 5000, "Test 1: size=5000 from=0")))

print("\nTesting 10K boundary:")
results.append(("10K (0-10000)", test_window(0, 10000, "Test 2: size=10000 from=0")))

print("\nTesting slightly over 10K:")
results.append(("10.1K (0-10100)", test_window(0, 10100, "Test 3: size=10100 from=0")))

print("\nTesting with offset at 10K boundary:")
results.append(("offset 5K (5000-10000)", test_window(5000, 5000, "Test 4: from=5000 size=5000")))
results.append(("offset 5K (5000-15000)", test_window(5000, 10000, "Test 5: from=5000 size=10000")))

print("\nTesting 20K window:")
results.append(("20K (0-20000)", test_window(0, 20000, "Test 6: size=20000 from=0")))

print("\n" + "=" * 70)
print("📊 SUMMARY")
print("=" * 70)

for desc, (success, count) in results:
    status = "✅" if success else "❌"
    print(f"{status} {desc}")

print("\n💡 CONCLUSION:")
successful = [r for r in results if r[1][0]]
if len(successful) >= 3 and results[-1][1][0]:
    print("No hard 10K limit found - ES accepted large windows!")
elif not results[1][1][0]:
    print("10K limit confirmed - queries with from+size >= 10001 fail")
else:
    print("Mixed results - need more investigation")
