#!/usr/bin/env python3
"""
Collect peak data using search_after pagination (like fetch_unlimited.py)
This ensures we get ALL errors, not just aggregated counts
"""

import sys
import os

# Import fetch_unlimited module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_unlimited import fetch_unlimited

import json
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from statistics import mean, stdev
import argparse


def generate_15min_windows(num_days=1):
    """Generate synchronized 15-minute window boundaries"""
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=num_days)
    
    # Align to 15-min boundary
    minute = start_time.minute
    aligned_minute = (minute // 15) * 15
    start_time = start_time.replace(minute=aligned_minute, second=0, microsecond=0)
    
    windows = []
    current_start = start_time
    
    while current_start < now:
        current_end = current_start + timedelta(minutes=15)
        if current_end <= now:
            windows.append((current_start, current_end))
        current_start = current_end
    
    print(f"📊 Generated {len(windows)} 15-minute windows for last {num_days} day(s)")
    return windows


def generate_15min_windows_for_range(date_from, date_to):
    """Generate synchronized 15-minute window boundaries for explicit date range"""
    
    # Align start to 15-min boundary
    minute = date_from.minute
    aligned_minute = (minute // 15) * 15
    start_time = date_from.replace(minute=aligned_minute, second=0, microsecond=0)
    
    windows = []
    current_start = start_time
    
    while current_start < date_to:
        current_end = current_start + timedelta(minutes=15)
        if current_end <= date_to:
            windows.append((current_start, current_end))
        current_start = current_end
    
    print(f"📊 Generated {len(windows)} 15-minute windows for date range")
    return windows


def fetch_errors_search_after(date_from, date_to, batch_size=5000):
    """
    Fetch ALL errors using fetch_unlimited.py (proven working)
    Returns: list of {timestamp, namespace} dicts
    """
    
    # Convert datetime to ISO string with Z suffix
    date_from_str = date_from.isoformat().replace('+00:00', 'Z')
    date_to_str = date_to.isoformat().replace('+00:00', 'Z')
    
    print(f"🔄 Fetching errors from {date_from_str} to {date_to_str}")
    print(f"   Using fetch_unlimited.py (batch size: {batch_size:,})")
    print()
    
    # Use fetch_unlimited to get all errors
    all_errors_raw = fetch_unlimited(date_from_str, date_to_str, batch_size=batch_size)
    
    if all_errors_raw is None:
        print("❌ Failed to fetch errors from fetch_unlimited")
        return None
    
    # Extract just timestamp + namespace from raw data
    all_errors = []
    ns_set = set()
    for error in all_errors_raw:
        ns = error.get('namespace', 'unknown')
        ns_set.add(ns)
        all_errors.append({
            'timestamp': error.get('timestamp', ''),
            'namespace': ns
        })
    
    print()
    print(f"✅ Total errors fetched: {len(all_errors):,}")
    print(f"   Namespaces in fetch: {sorted(ns_set)}")
    return all_errors


def group_into_windows(errors, windows):
    """
    Group errors into 15-min windows by namespace
    
    Returns: dict with key=(window_idx, namespace), value=error_count
    """
    
    print(f"📊 Grouping {len(errors):,} errors into {len(windows)} windows...")
    
    window_counts = defaultdict(int)
    ns_set_2 = set()
    
    for err in errors:
        ts_str = err['timestamp']
        ns = err['namespace']
        ns_set_2.add(ns)
        
        # Parse timestamp
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        
        # Find which window this belongs to
        for idx, (win_start, win_end) in enumerate(windows):
            if win_start <= ts < win_end:
                key = (idx, ns)
                window_counts[key] += 1
                break
    
    print(f"✅ Grouped into {len(window_counts)} (window, namespace) combinations")
    print(f"   Namespaces after grouping: {sorted(ns_set_2)}")
    return window_counts


def calculate_statistics_by_time_pattern(window_counts, windows):
    """
    Calculate statistics grouped by (day_of_week, hour, quarter, namespace)
    with 3-window smoothing
    
    Returns: dict with stats
    """
    
    print(f"📊 Calculating statistics with 3-window smoothing...")
    
    # Group by time pattern
    pattern_data = defaultdict(list)
    
    for (win_idx, ns), count in window_counts.items():
        win_start, win_end = windows[win_idx]
        
        day_of_week = win_end.weekday()
        hour_of_day = win_end.hour
        quarter_hour = (win_end.minute // 15) % 4
        
        key = (day_of_week, hour_of_day, quarter_hour, ns)
        pattern_data[key].append(count)
    
    # Calculate mean/stddev with 3-window smoothing
    statistics = {}
    
    for key, counts in pattern_data.items():
        # Apply 3-window smoothing
        if len(counts) >= 3:
            smoothed = []
            for i in range(len(counts)):
                neighbors = counts[max(0, i-1):min(len(counts), i+2)]
                smoothed.append(mean(neighbors))
        else:
            smoothed = counts
        
        mean_errors = mean(smoothed) if smoothed else 0
        stddev_errors = stdev(smoothed) if len(smoothed) > 1 else 0
        
        statistics[key] = {
            'mean': mean_errors,
            'stddev': stddev_errors,
            'samples': len(counts),
            'raw_counts': counts,
            'smoothed_counts': smoothed
        }
    
    print(f"✅ Calculated statistics for {len(statistics)} patterns")
    return statistics


def print_detailed_report(statistics, windows):
    """Print detailed analysis report"""
    
    print()
    print("="*80)
    print("📊 DETAILED PEAK DETECTION ANALYSIS REPORT")
    print("="*80)
    print()
    
    # Get all namespaces
    namespaces = sorted(set(key[3] for key in statistics.keys()))
    
    print(f"📦 Namespaces found: {len(namespaces)}")
    for ns in namespaces:
        print(f"   - {ns}")
    print()
    
    # Statistics by namespace
    print("📈 Error Statistics by Namespace:")
    print(f"   {'Namespace':<30} {'Patterns':<10} {'Avg Mean':<12} {'Avg StdDev':<12} {'Total Samples'}")
    print(f"   {'-'*85}")
    
    for ns in namespaces:
        ns_stats = [v for k, v in statistics.items() if k[3] == ns]
        
        avg_mean = mean([s['mean'] for s in ns_stats])
        avg_std = mean([s['stddev'] for s in ns_stats])
        total_samples = sum([s['samples'] for s in ns_stats])
        
        print(f"   {ns:<30} {len(ns_stats):<10} {avg_mean:>11.2f}  {avg_std:>11.2f}  {total_samples:>12}")
    
    print()
    
    # Smoothing effectiveness check - PRINT ALL PATTERNS (not just sample!)
    print("🔬 All Patterns (for Database Ingestion):")
    print()
    
    # Show ALL patterns (not just first 5)
    for i, (key, stats) in enumerate(sorted(statistics.items()), 1):
        day, hour, qtr, ns = key
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        print(f"   Pattern {i}: {day_names[day]} {hour:02d}:{qtr*15:02d} - {ns}")
        print(f"      Raw counts:      {stats['raw_counts']}")
        print(f"      Smoothed counts: {[f'{x:.1f}' for x in stats['smoothed_counts']]}")
        print(f"      Mean: {stats['mean']:.2f}, StdDev: {stats['stddev']:.2f}, Samples: {stats['samples']}")
        print()
    
    print("="*80)


def main():
    parser = argparse.ArgumentParser(description='Collect peak data with search_after pagination')
    parser.add_argument('--days', type=int, default=1, help='Number of days to collect (default: 1) - RELATIVE to now')
    parser.add_argument('--from', dest='date_from', help='Start date (ISO format, e.g., 2025-12-15T00:00:00Z) - OVERRIDES --days')
    parser.add_argument('--to', dest='date_to', help='End date (ISO format, e.g., 2025-12-16T00:00:00Z) - OVERRIDES --days')
    args = parser.parse_args()
    
    print("="*80)
    print(f"🚀 Peak Data Collection - Detailed Analysis")
    print("="*80)
    print()
    
    # Determine date range
    if args.date_from and args.date_to:
        # Use explicit dates
        print(f"📅 Using EXPLICIT date range:")
        print(f"   From: {args.date_from}")
        print(f"   To:   {args.date_to}")
        
        # Parse explicit dates
        date_from = datetime.fromisoformat(args.date_from.replace('Z', '+00:00'))
        date_to = datetime.fromisoformat(args.date_to.replace('Z', '+00:00'))
    else:
        # Use relative days
        print(f"📅 Using RELATIVE date range (last {args.days} day(s)):")
        now = datetime.now(timezone.utc)
        date_from = now - timedelta(days=args.days)
        date_to = now
        print(f"   From: {date_from.isoformat().replace('+00:00', 'Z')}")
        print(f"   To:   {date_to.isoformat().replace('+00:00', 'Z')}")
    
    print()
    
    # Generate windows from the determined date range
    windows = generate_15min_windows_for_range(date_from, date_to)
    
    if not windows:
        print("❌ No windows generated")
        return 1
    
    # Fetch errors for this range
    errors = fetch_errors_search_after(date_from, date_to, batch_size=5000)
    
    if not errors:
        print("❌ No errors fetched")
        return 1
    
    # Group into windows
    window_counts = group_into_windows(errors, windows)
    
    # Calculate statistics
    statistics = calculate_statistics_by_time_pattern(window_counts, windows)
    
    # Print detailed report
    print_detailed_report(statistics, windows)
    
    print()
    print("✅ Analysis complete!")
    
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
