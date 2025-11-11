#!/usr/bin/env python3
"""
Re-fetch days with low coverage to achieve 75% target
Usage: python refetch_low_coverage.py --target-coverage 75
"""
import json
import subprocess
import argparse
from pathlib import Path

def check_coverage(day):
    """Check current coverage for a day"""
    json_file = f'/tmp/daily_{day}.json'
    try:
        with open(json_file, 'r') as f:
            data = json.load(f)
            return {
                'total': data['total_errors'],
                'sample': data['sample_size'],
                'coverage': data['coverage_percent']
            }
    except FileNotFoundError:
        return None

def refetch_day(day, sample_size):
    """Re-fetch a specific day with new sample size"""
    print(f"\n🔄 Re-fetching {day} with sample_size={sample_size:,}...")
    
    # Use curl-based fetch script (no Python dependencies)
    cmd = [
        './fetch_errors_curl.sh',
        day,
        str(sample_size),
        f'/tmp/daily_{day}.json'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, cwd='/home/jvsete/git/sas/ai-log-analyzer')
    
    if result.returncode == 0:
        print(f"✅ Successfully re-fetched {day}")
        # Show output
        for line in result.stdout.strip().split('\n')[-3:]:
            print(f"   {line}")
        return True
    else:
        print(f"❌ Failed to re-fetch {day}")
        print(result.stderr)
        return False

def main():
    parser = argparse.ArgumentParser(description='Re-fetch days with low coverage')
    parser.add_argument('--target-coverage', type=float, default=75.0, help='Target coverage percentage')
    parser.add_argument('--days', nargs='+', help='Specific days to re-fetch (YYYY-MM-DD format)')
    parser.add_argument('--auto', action='store_true', help='Automatically re-fetch all days below target')
    
    args = parser.parse_args()
    
    # Default days if not specified
    if args.days:
        days = args.days
    else:
        days = [
            '2025-11-04', '2025-11-05', '2025-11-06', '2025-11-07',
            '2025-11-08', '2025-11-09', '2025-11-10'
        ]
    
    print(f"🎯 Target coverage: {args.target_coverage}%\n")
    print("Day         | Current Coverage | Action")
    print("-" * 60)
    
    to_refetch = []
    
    for day in days:
        stats = check_coverage(day)
        
        if not stats:
            print(f"{day} | No data found    | ⚠️  Skip")
            continue
        
        if stats['coverage'] < args.target_coverage:
            target_sample = int(stats['total'] * (args.target_coverage / 100))
            to_refetch.append((day, target_sample, stats))
            print(f"{day} | {stats['coverage']:>6.1f}%         | 🔄 Re-fetch with {target_sample:,} samples")
        else:
            print(f"{day} | {stats['coverage']:>6.1f}%         | ✅ OK")
    
    if not to_refetch:
        print("\n✅ All days meet target coverage!")
        return
    
    if not args.auto:
        print(f"\n⚠️  Found {len(to_refetch)} days to re-fetch")
        response = input("Proceed with re-fetch? (y/n): ")
        if response.lower() != 'y':
            print("Aborted.")
            return
    
    # Re-fetch
    print("\n" + "=" * 60)
    print("Starting re-fetch process...")
    print("=" * 60)
    
    success_count = 0
    for day, sample_size, stats in to_refetch:
        if refetch_day(day, sample_size):
            success_count += 1
            
            # Verify new coverage
            new_stats = check_coverage(day)
            if new_stats:
                print(f"   New coverage: {new_stats['coverage']:.1f}% (was {stats['coverage']:.1f}%)")
    
    print("\n" + "=" * 60)
    print(f"✅ Re-fetched {success_count}/{len(to_refetch)} days successfully")

if __name__ == "__main__":
    main()
