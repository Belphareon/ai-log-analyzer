#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

import asyncio
import re
from datetime import datetime
from collections import Counter
from app.services.elasticsearch import es_service

async def main():
    await es_service.connect()
    
    # Peak: 14:30-14:40 UTC
    time_from = datetime(2025, 11, 7, 14, 30, 0)
    time_to = datetime(2025, 11, 7, 14, 40, 0)
    
    # Get 1000 samples (max we can get at once)
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat() + "Z", "lte": time_to.isoformat() + "Z"}}},
                    {"range": {"level_value": {"gte": 40000}}}
                ]
            }
        },
        "size": 1000,
        "_source": ["message", "kubernetes.labels.app", "logger_name", "@timestamp", "level"]
    }
    
    print(f"🔍 ANALYZING PEAK: Nov 7, 14:30 UTC (15:30 CET)")
    print(f"   Fetching 1,000 sample errors...")
    print()
    
    resp = await es_service.client.search(index=es_service.index_pattern, body=query)
    
    hits = resp['hits']['hits']
    total = resp['hits']['total']['value']
    
    print(f"�� Analyzing {len(hits)} samples from {total:,} total errors\n")
    
    # Extract data
    apps = []
    messages = []
    card_ids = []
    error_codes = []
    
    for hit in hits:
        src = hit['_source']
        app = src.get('kubernetes', {}).get('labels', {}).get('app', 'unknown')
        msg = src.get('message', '')
        
        apps.append(app)
        messages.append(msg[:200])
        
        # Extract card IDs
        card_match = re.search(r'[Cc]ard.*?id\s+(\d+)', msg)
        if card_match:
            card_ids.append(card_match.group(1))
        
        # Extract error codes
        err_match = re.search(r'err\.(\d+)', msg)
        if err_match:
            error_codes.append(f"err.{err_match.group(1)}")
    
    # Analysis
    app_counts = Counter(apps)
    card_counts = Counter(card_ids)
    error_counts = Counter(error_codes)
    
    print("=== TOP 10 AFFECTED APPLICATIONS ===")
    for i, (app, count) in enumerate(app_counts.most_common(10), 1):
        pct = (count / len(hits)) * 100
        extrapolated = int((count / len(hits)) * total)
        print(f"{i:2d}. {app:45s} {count:4d} samples ({pct:5.1f}%) → ~{extrapolated:,} total")
    
    print("\n=== TOP CARD IDs (Resource Not Found) ===")
    for i, (card_id, count) in enumerate(card_counts.most_common(15), 1):
        pct = (count / len(card_ids)) * 100 if card_ids else 0
        print(f"{i:2d}. Card ID {card_id:10s} {count:4d} times ({pct:5.1f}%)")
    
    print("\n=== ERROR CODES ===")
    for code, count in error_counts.most_common():
        pct = (count / len(error_codes)) * 100 if error_codes else 0
        print(f"    {code:10s} {count:4d} times ({pct:5.1f}%)")
    
    # Message patterns
    print("\n=== MESSAGE PATTERNS (Top 10) ===")
    msg_patterns = Counter()
    for msg in messages:
        # Normalize: remove IDs, timestamps, etc
        normalized = re.sub(r'\d{5,}', '{ID}', msg)
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}T[\d:\.]+Z', '{TS}', normalized)
        normalized = normalized[:100]
        msg_patterns[normalized] += 1
    
    for i, (pattern, count) in enumerate(msg_patterns.most_common(10), 1):
        pct = (count / len(messages)) * 100
        print(f"\n{i}. ({count} times, {pct:.1f}%)")
        print(f"   {pattern}")
    
    await es_service.close()

asyncio.run(main())
