#!/usr/bin/env python3
"""
Universal ES error fetcher with progress bar
Usage: python fetch_errors.py --from "2025-10-27T00:00:00" --to "2025-10-28T00:00:00" --output report.json
"""
import sys
import argparse
from datetime import datetime
import asyncio
import json

sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

from app.services.trend_analyzer import trend_analyzer

async def fetch_errors(date_from: str, date_to: str, max_sample: int = 50000):
    """Fetch errors with progress indication"""
    print(f"📊 Fetching errors from {date_from} to {date_to}")
    print(f"   Max sample: {max_sample:,}")
    print()
    
    time_from = datetime.fromisoformat(date_from)
    time_to = datetime.fromisoformat(date_to)
    
    print("⏳ Connecting to ES and fetching data...")
    errors, total = await trend_analyzer.fetch_errors_batch(
        time_from=time_from,
        time_to=time_to,
        batch_size=10000,
        max_total=max_sample
    )
    
    coverage = (len(errors) / total * 100) if total > 0 else 0
    
    print(f"✅ Fetched {len(errors):,} errors from {total:,} total ({coverage:.1f}% coverage)")
    
    return {
        'period_start': time_from.isoformat(),
        'period_end': time_to.isoformat(),
        'total_errors': total,
        'sample_size': len(errors),
        'coverage_percent': coverage,
        'errors': errors
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Fetch errors from ES')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format)')
    parser.add_argument('--max-sample', type=int, default=50000, help='Max sample size')
    parser.add_argument('--output', required=True, help='Output JSON file')
    
    args = parser.parse_args()
    
    result = asyncio.run(fetch_errors(args.date_from, args.date_to, args.max_sample))
    
    with open(args.output, 'w') as f:
        json.dump(result, f, default=str, indent=2)
    
    print(f"\n💾 Saved to {args.output}")
