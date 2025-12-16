#!/usr/bin/env python3
"""Smart fetcher - automatically adjusts sample for 75%+ coverage"""
import sys
import argparse
from datetime import datetime, timezone
import asyncio
import json

sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')
from app.services.elasticsearch import es_service

async def get_total_count(time_from, time_to):
    """Get total error count first"""
    await es_service.connect()
    
    query = {
        "query": {
            "bool": {
                "must": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat() + "Z", "lte": time_to.isoformat() + "Z"}}},
                    {"term": {"level": "ERROR"}}
                ]
            }
        },
        "size": 0
    }
    
    response = await es_service.client.search(index=es_service.index_pattern, body=query)
    return response['hits']['total']['value']

async def fetch_with_target_coverage(date_from, date_to, target_coverage=75, max_sample=100000):
    """Fetch errors with target coverage percentage"""
    # Parse input as naive datetime and assume it's local time (CET/CEST)
    time_from_local = datetime.fromisoformat(date_from)
    time_to_local = datetime.fromisoformat(date_to)
    
    # Convert to UTC by subtracting 1 hour (CET = UTC+1)
    # Note: This is simplified - proper handling would use pytz or zoneinfo
    from datetime import timedelta
    time_from = time_from_local - timedelta(hours=1)
    time_to = time_to_local - timedelta(hours=1)
    
    print(f"📊 Getting total count for {date_from} (local) = {time_from.isoformat()}Z (UTC)...")
    total = await get_total_count(time_from, time_to)
    
    # Calculate needed sample for target coverage
    needed_sample = int((target_coverage / 100) * total)
    sample_size = min(needed_sample, max_sample)
    
    print(f"   Total errors: {total:,}")
    print(f"   Target coverage: {target_coverage}%")
    print(f"   Calculated sample: {needed_sample:,}")
    print(f"   Actual sample (capped): {sample_size:,}")
    print()
    
    # Import here to avoid circular dependency
    from app.services.trend_analyzer import trend_analyzer
    
    print("⏳ Fetching errors with progress tracking...")
    print(f"   Progress: [", end="", flush=True)
    
    errors = []
    batch_count = 0
    total_batches = (sample_size // 10000) + 1
    
    # Fetch in batches with progress
    for i in range(0, sample_size, 10000):
        batch_size_current = min(10000, sample_size - i)
        batch_errors, _ = await trend_analyzer.fetch_errors_batch(
            time_from=time_from,
            time_to=time_to,
            batch_size=batch_size_current,
            max_total=batch_size_current
        )
        errors.extend(batch_errors)
        batch_count += 1
        
        # Progress bar
        progress = int((batch_count / total_batches) * 50)
        print(f"\r   Progress: [{'=' * progress}{' ' * (50 - progress)}] {batch_count}/{total_batches} batches ({len(errors):,} errors)", end="", flush=True)
        
        if len(errors) >= sample_size:
            break
    
    print()  # New line after progress
    
    coverage = (len(errors) / total * 100) if total > 0 else 0
    
    print(f"✅ Fetched {len(errors):,} errors ({coverage:.1f}% coverage)")
    
    return {
        'period_start': time_from_local.isoformat(),
        'period_end': time_to_local.isoformat(),
        'period_start_utc': time_from.isoformat() + 'Z',
        'period_end_utc': time_to.isoformat() + 'Z',
        'total_errors': total,
        'sample_size': len(errors),
        'coverage_percent': coverage,
        'target_coverage': target_coverage,
        'errors': errors
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Smart error fetcher')
    parser.add_argument('--from', dest='date_from', required=True)
    parser.add_argument('--to', dest='date_to', required=True)
    parser.add_argument('--coverage', type=int, default=75, help='Target coverage %')
    parser.add_argument('--max-sample', type=int, default=100000)
    parser.add_argument('--output', required=True)
    
    args = parser.parse_args()
    
    result = asyncio.run(fetch_with_target_coverage(
        args.date_from, args.date_to, args.coverage, args.max_sample
    ))
    
    with open(args.output, 'w') as f:
        json.dump(result, f, default=str, indent=2)
    
    print(f"\n💾 Saved to {args.output}")
