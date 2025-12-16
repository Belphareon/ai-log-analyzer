#!/usr/bin/env python3
"""
Ingest peak statistics into PostgreSQL database
This script extracts statistics from collect_peak_detailed.py output
and loads them into ailog_peak.peak_statistics table
"""

import sys
import os
import json
import argparse
import psycopg2
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from statistics import mean, stdev

# Import fetch_unlimited module
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_unlimited import fetch_unlimited


# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD', 'y01d40Mmdys/lbDE')
}


def fetch_errors_search_after(date_from, date_to, batch_size=5000):
    """
    Fetch ALL errors using fetch_unlimited.py
    Returns: list of {timestamp, namespace} dicts
    """
    
    # Convert datetime to ISO string with Z suffix
    date_from_str = date_from.isoformat().replace('+00:00', 'Z')
    date_to_str = date_to.isoformat().replace('+00:00', 'Z')
    
    print(f"🔄 Fetching errors from {date_from_str} to {date_to_str}")
    print(f"   Using fetch_unlimited.py (batch size: {batch_size:,})")
    
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
    
    print(f"✅ Total errors fetched: {len(all_errors):,}")
    print(f"   Namespaces: {sorted(ns_set)}")
    return all_errors


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
    
    print(f"📊 Generated {len(windows)} 15-minute windows")
    return windows


def group_into_windows(errors, windows):
    """Group errors into 15-min windows by namespace"""
    
    print(f"📊 Grouping {len(errors):,} errors into windows...")
    
    window_counts = defaultdict(int)
    
    for err in errors:
        ts_str = err['timestamp']
        ns = err['namespace']
        
        # Parse timestamp
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        
        # Find which window this belongs to
        for idx, (win_start, win_end) in enumerate(windows):
            if win_start <= ts < win_end:
                key = (idx, ns)
                window_counts[key] += 1
                break
    
    print(f"✅ Grouped into {len(window_counts)} (window, namespace) combinations")
    return window_counts


def calculate_statistics_by_time_pattern(window_counts, windows):
    """
    Calculate statistics grouped by (day_of_week, hour, quarter, namespace)
    with 3-window smoothing
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


def insert_statistics_to_db(statistics):
    """
    Insert statistics into PostgreSQL peak_statistics table
    Using UPSERT (ON CONFLICT) pattern
    """
    
    print(f"💾 Connecting to PostgreSQL...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return False
    
    print(f"📤 Inserting {len(statistics)} statistics rows...")
    
    inserted = 0
    failed = 0
    
    # SQL for UPSERT
    sql = """
    INSERT INTO ailog_peak.peak_statistics 
    (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count, created_at, updated_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
    ON CONFLICT (day_of_week, hour_of_day, quarter_hour, namespace)
    DO UPDATE SET 
        mean_errors = EXCLUDED.mean_errors,
        stddev_errors = EXCLUDED.stddev_errors,
        samples_count = EXCLUDED.samples_count,
        updated_at = NOW()
    """
    
    try:
        for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
            try:
                cur.execute(sql, (
                    int(day_of_week),
                    int(hour_of_day),
                    int(quarter_hour),
                    namespace,
                    float(stats['mean']),
                    float(stats['stddev']),
                    int(stats['samples'])
                ))
                inserted += 1
            except Exception as e:
                print(f"⚠️  Failed to insert row ({day_of_week},{hour_of_day},{quarter_hour},{namespace}): {e}")
                failed += 1
        
        conn.commit()
        print(f"✅ Inserted: {inserted}, Failed: {failed}")
        
    except Exception as e:
        print(f"❌ Error during insert: {e}")
        conn.rollback()
        cur.close()
        conn.close()
        return False
    
    cur.close()
    conn.close()
    return True


def verify_insertion(date_from=None):
    """Verify data was inserted into DB"""
    
    print(f"🔍 Verifying data in database...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return False
    
    try:
        # Get total row count
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        total_count = cur.fetchone()[0]
        print(f"✅ Total rows in peak_statistics: {total_count}")
        
        # Get count by namespace
        cur.execute("""
            SELECT namespace, COUNT(*) as count 
            FROM ailog_peak.peak_statistics 
            GROUP BY namespace 
            ORDER BY namespace
        """)
        
        print(f"   Breakdown by namespace:")
        for ns, count in cur.fetchall():
            print(f"   - {ns}: {count} patterns")
        
        # Sample some data
        cur.execute("""
            SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors 
            FROM ailog_peak.peak_statistics 
            LIMIT 5
        """)
        
        print(f"\n   Sample data:")
        for day, hour, qtr, ns, mean, stddev in cur.fetchall():
            day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            print(f"   - {day_names[day]} {hour:02d}:{qtr*15:02d} {ns}: mean={mean:.2f}, stddev={stddev:.2f}")
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        cur.close()
        conn.close()
        return False
    
    cur.close()
    conn.close()
    return True


def main():
    parser = argparse.ArgumentParser(description='Ingest peak statistics into database')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format, e.g., 2025-12-01T00:00:00Z)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format, e.g., 2025-12-02T00:00:00Z)')
    parser.add_argument('--skip-fetch', action='store_true', help='Skip fetching from ES (use if data already on disk)')
    args = parser.parse_args()
    
    print("="*80)
    print(f"📊 Ingest Peak Statistics to PostgreSQL")
    print("="*80)
    print()
    
    # Parse dates
    try:
        date_from = datetime.fromisoformat(args.date_from.replace('Z', '+00:00'))
        date_to = datetime.fromisoformat(args.date_to.replace('Z', '+00:00'))
    except ValueError as e:
        print(f"❌ Invalid date format: {e}")
        return 1
    
    print(f"📅 Date range:")
    print(f"   From: {args.date_from}")
    print(f"   To:   {args.date_to}")
    print()
    
    # Fetch errors
    errors = fetch_errors_search_after(date_from, date_to, batch_size=5000)
    if not errors:
        print("❌ No errors fetched")
        return 1
    
    print()
    
    # Generate windows
    windows = generate_15min_windows_for_range(date_from, date_to)
    
    # Group into windows
    window_counts = group_into_windows(errors, windows)
    
    # Calculate statistics
    statistics = calculate_statistics_by_time_pattern(window_counts, windows)
    
    print()
    
    # Insert to DB
    success = insert_statistics_to_db(statistics)
    if not success:
        print("❌ Failed to insert data into database")
        return 1
    
    print()
    
    # Verify
    verify_insertion(date_from)
    
    print()
    print("✅ Ingestion complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
