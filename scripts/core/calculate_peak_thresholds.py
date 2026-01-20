#!/usr/bin/env python3
"""
Calculate Peak Thresholds from peak_raw_data
=============================================
Purpose: Calculate P93 and CAP thresholds dynamically from collected data

Algorithm:
1. Read all data from peak_raw_data (or last N weeks)
2. For each (namespace, day_of_week):
   - Calculate P93 (93rd percentile) from raw values
   - Store in peak_thresholds table
3. For each namespace:
   - Calculate CAP = (median_P93 + avg_P93) / 2 across all DOWs
   - Store in peak_threshold_caps table

Usage:
    python calculate_peak_thresholds.py                    # Calculate from all data
    python calculate_peak_thresholds.py --weeks 4          # Last 4 weeks only
    python calculate_peak_thresholds.py --percentile 0.92  # Use P92 instead of P93
    python calculate_peak_thresholds.py --dry-run          # Show what would be calculated
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import psycopg2
    from psycopg2.extras import execute_batch
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

# Day names for display
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def percentile(values: list, p: float) -> float:
    """Calculate percentile from list of values"""
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(len(s) * p)
    idx = min(idx, len(s) - 1)  # Ensure we don't go out of bounds
    return float(s[idx])


def fetch_raw_data(conn, weeks: int = None) -> dict:
    """
    Fetch raw data from peak_raw_data, grouped by (namespace, day_of_week)
    
    Args:
        conn: database connection
        weeks: if specified, only fetch last N weeks
    
    Returns:
        dict: {(namespace, day_of_week): [values]}
    """
    cur = conn.cursor()
    
    query = """
        SELECT namespace, day_of_week, original_value, timestamp
        FROM ailog_peak.peak_raw_data
        WHERE original_value IS NOT NULL
    """
    params = []
    
    if weeks:
        start_date = datetime.now() - timedelta(weeks=weeks)
        query += " AND timestamp >= %s"
        params.append(start_date)
    
    query += " ORDER BY namespace, day_of_week"
    
    print(f"📊 Fetching data from peak_raw_data...")
    cur.execute(query, params)
    rows = cur.fetchall()
    
    print(f"   Found {len(rows):,} rows")
    
    # Group by (namespace, day_of_week)
    data = defaultdict(list)
    date_range = {'min': None, 'max': None}
    
    for ns, dow, value, ts in rows:
        data[(ns, dow)].append(float(value))
        if date_range['min'] is None or ts < date_range['min']:
            date_range['min'] = ts
        if date_range['max'] is None or ts > date_range['max']:
            date_range['max'] = ts
    
    print(f"   Unique (namespace, dow) combinations: {len(data)}")
    if date_range['min'] and date_range['max']:
        print(f"   Date range: {date_range['min'].strftime('%Y-%m-%d')} to {date_range['max'].strftime('%Y-%m-%d')}")
    
    return data, date_range


def calculate_p93_thresholds(data: dict, percentile_level: float = 0.93) -> dict:
    """
    Calculate P93 (or other percentile) for each (namespace, day_of_week)
    
    Returns:
        dict: {(namespace, day_of_week): {'p93': value, 'count': n, 'median': m, 'mean': avg, 'max': max_val}}
    """
    thresholds = {}
    
    for (ns, dow), values in data.items():
        if not values:
            continue
        
        s = sorted(values)
        n = len(s)
        
        thresholds[(ns, dow)] = {
            'p93': percentile(values, percentile_level),
            'count': n,
            'median': s[n // 2],
            'mean': sum(values) / n,
            'max': max(values),
        }
    
    return thresholds


def calculate_cap_values(thresholds: dict) -> dict:
    """
    Calculate CAP for each namespace
    CAP = (median_P93 + avg_P93) / 2 across all DOWs
    
    Returns:
        dict: {namespace: {'cap': value, 'median_p93': m, 'avg_p93': avg, 'min_p93': min, 'max_p93': max, 'total_samples': n}}
    """
    # Group P93 values by namespace
    p93_by_ns = defaultdict(list)
    samples_by_ns = defaultdict(int)
    
    for (ns, dow), stats in thresholds.items():
        p93_by_ns[ns].append(stats['p93'])
        samples_by_ns[ns] += stats['count']
    
    caps = {}
    
    for ns, p93_values in p93_by_ns.items():
        if not p93_values:
            continue
        
        s = sorted(p93_values)
        median_p93 = s[len(s) // 2]
        avg_p93 = sum(p93_values) / len(p93_values)
        
        caps[ns] = {
            'cap': (median_p93 + avg_p93) / 2,
            'median_p93': median_p93,
            'avg_p93': avg_p93,
            'min_p93': min(p93_values),
            'max_p93': max(p93_values),
            'total_samples': samples_by_ns[ns],
        }
    
    return caps


def save_thresholds_to_db(conn, thresholds: dict, caps: dict, date_range: dict, 
                          percentile_level: float = 0.93, dry_run: bool = False):
    """
    Save calculated thresholds to database
    """
    cur = conn.cursor()
    
    start_date = date_range['min'].date() if date_range['min'] else None
    end_date = date_range['max'].date() if date_range['max'] else None
    
    if dry_run:
        print("\n🔍 DRY RUN - would save:")
        print(f"\n   Percentile thresholds: {len(thresholds)} rows")
        print(f"   CAP values: {len(caps)} rows")
        return
    
    # Clear existing data
    print("\n🗑️  Clearing existing thresholds...")
    cur.execute("DELETE FROM ailog_peak.peak_thresholds;")
    cur.execute("DELETE FROM ailog_peak.peak_threshold_caps;")
    conn.commit()
    
    # Insert percentile thresholds
    print(f"\n📥 Inserting {len(thresholds)} percentile thresholds...")
    
    sql_p93 = """
        INSERT INTO ailog_peak.peak_thresholds 
        (namespace, day_of_week, percentile_value, percentile_level, sample_count, 
         median_value, mean_value, max_value, calculated_at, data_start_date, data_end_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
    """
    
    p93_rows = []
    for (ns, dow), stats in thresholds.items():
        p93_rows.append((
            ns, dow, stats['p93'], percentile_level, stats['count'], 
            stats['median'], stats['mean'], stats['max'],
            start_date, end_date
        ))
    
    execute_batch(cur, sql_p93, p93_rows)
    print(f"   ✅ Inserted {len(p93_rows)} percentile threshold rows")
    
    # Insert CAP values
    print(f"\n📥 Inserting {len(caps)} CAP values...")
    
    sql_cap = """
        INSERT INTO ailog_peak.peak_threshold_caps 
        (namespace, cap_value, median_percentile, avg_percentile, min_percentile, max_percentile, 
         percentile_level, total_samples, calculated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """
    
    cap_rows = []
    for ns, stats in caps.items():
        cap_rows.append((
            ns, stats['cap'], stats['median_p93'], stats['avg_p93'],
            stats['min_p93'], stats['max_p93'], percentile_level, stats['total_samples']
        ))
    
    execute_batch(cur, sql_cap, cap_rows)
    print(f"   ✅ Inserted {len(cap_rows)} CAP value rows")
    
    conn.commit()


def print_summary(thresholds: dict, caps: dict):
    """Print summary of calculated thresholds"""
    
    # Get all namespaces
    namespaces = sorted(set(ns for (ns, dow) in thresholds.keys()))
    
    print("\n" + "=" * 120)
    print("P93 THRESHOLDS per NS per DOW")
    print("=" * 120)
    
    print(f"\n{'NS':<25} {'CAP':>7} | {'Mon':>7} {'Tue':>7} {'Wed':>7} {'Thu':>7} {'Fri':>7} {'Sat':>7} {'Sun':>7} | {'Samples':>8}")
    print("-" * 120)
    
    for ns in namespaces:
        cap = caps.get(ns, {}).get('cap', 0)
        row = f"{ns:<25} {cap:>7.0f} |"
        
        total_samples = 0
        for dow in range(7):
            stats = thresholds.get((ns, dow))
            if stats:
                row += f" {stats['p93']:>7.0f}"
                total_samples += stats['count']
            else:
                row += f" {'--':>7}"
        
        row += f" | {total_samples:>8}"
        print(row)
    
    print("\n" + "=" * 120)
    print("CAP VALUES per NS")
    print("=" * 120)
    
    print(f"\n{'NS':<25} {'CAP':>8} | {'Median_P93':>11} {'Avg_P93':>10} {'Min_P93':>9} {'Max_P93':>9} | {'Samples':>8}")
    print("-" * 100)
    
    for ns in namespaces:
        c = caps.get(ns, {})
        if c:
            print(f"{ns:<25} {c['cap']:>8.0f} | {c['median_p93']:>11.0f} {c['avg_p93']:>10.0f} {c['min_p93']:>9.0f} {c['max_p93']:>9.0f} | {c['total_samples']:>8}")


def main():
    parser = argparse.ArgumentParser(description='Calculate Peak Thresholds from peak_raw_data')
    parser.add_argument('--weeks', type=int, help='Only use last N weeks of data')
    parser.add_argument('--percentile', type=float, default=0.93, help='Percentile level (default: 0.93)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be calculated without saving')
    parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("📊 Calculate Peak Thresholds")
    print("=" * 80)
    print(f"   Percentile: P{int(args.percentile * 100)}")
    if args.weeks:
        print(f"   Data range: last {args.weeks} weeks")
    else:
        print(f"   Data range: all available data")
    if args.dry_run:
        print(f"   Mode: DRY RUN")
    
    # Connect to DB
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print(f"\n✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        return 1
    
    try:
        # Fetch data
        data, date_range = fetch_raw_data(conn, args.weeks)
        
        if not data:
            print("\n⚠️  No data found in peak_raw_data!")
            return 1
        
        # Calculate P93 thresholds
        print(f"\n📈 Calculating P{int(args.percentile * 100)} thresholds...")
        thresholds = calculate_p93_thresholds(data, args.percentile)
        
        # Calculate CAP values
        print(f"📊 Calculating CAP values...")
        caps = calculate_cap_values(thresholds)
        
        # Print summary
        print_summary(thresholds, caps)
        
        # Save to DB
        save_thresholds_to_db(conn, thresholds, caps, date_range, args.percentile, args.dry_run)
        
        print("\n" + "=" * 80)
        print("✅ Peak thresholds calculation complete!")
        print("=" * 80)
        
        conn.close()
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        return 1


if __name__ == '__main__':
    sys.exit(main())
