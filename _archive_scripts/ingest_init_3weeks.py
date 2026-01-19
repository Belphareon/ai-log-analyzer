#!/usr/bin/env python3
"""
INIT Phase 3 Weeks - Data Ingestion WITHOUT Peak Replacement
Purpose: Load baseline data for 3 weeks (1.12-21.12)
No peak detection, no replacement - just aggregate and insert

Algorithm:
1. Parse all data from input file
2. Aggregate by (day_of_week, hour, quarter, namespace)
3. ON CONFLICT: combine samples using weighted average
4. INSERT into DB
"""

import sys
import os
import argparse
import psycopg2
import re
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}


def parse_statistics_from_log(log_file):
    """
    Parse statistics from collect_peak_detailed.py output
    Aggregate in memory: same key (day, hour, quarter, namespace) = weighted average
    """
    
    statistics = {}
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
    
    print(f"📖 Parsing {log_file}...")
    
    try:
        with open(log_file, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {log_file}")
        return None
    
    # Regex to match pattern blocks
    pattern_regex = r"Pattern \d+: (\w+) (\d+):(\d+) - (.+?)\n\s+Raw counts:\s+\[(.+?)\]\n\s+Smoothed counts:\s+\[(.+?)\]\n\s+Mean: ([\d.]+), StdDev: ([\d.]+), Samples: (\d+)"
    
    matches = re.finditer(pattern_regex, content)
    count = 0
    
    for match in matches:
        day_name = match.group(1)
        hour = int(match.group(2))
        minute = int(match.group(3))
        namespace = match.group(4).strip()
        mean_val = float(match.group(7))
        stddev_val = float(match.group(8))
        samples = int(match.group(9))
        
        day_of_week = day_map.get(day_name, 0)
        hour_of_day = hour
        quarter_hour = (minute // 15) % 4
        
        key = (day_of_week, hour_of_day, quarter_hour, namespace)
        
        # AGGREGATE IN MEMORY if key already exists
        if key in statistics:
            old_data = statistics[key]
            old_mean = old_data['mean']
            old_samples = old_data['samples']
            
            combined_mean = (old_mean * old_samples + mean_val * samples) / (old_samples + samples)
            combined_samples = old_samples + samples
            combined_stddev = max(old_data['stddev'], stddev_val)
            
            statistics[key] = {
                'mean': combined_mean,
                'stddev': combined_stddev,
                'samples': combined_samples
            }
        else:
            statistics[key] = {
                'mean': mean_val,
                'stddev': stddev_val,
                'samples': samples
            }
        count += 1
    
    print(f"✅ Parsed {count} patterns → {len(statistics)} unique keys (after aggregation)")
    return statistics


def insert_to_db(statistics, conn):
    """
    Insert statistics to DB with ON CONFLICT UPDATE
    NO peak detection - just insert all data
    """
    
    print(f"\n💾 Connecting to database...")
    
    try:
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False
    
    print(f"📤 Processing {len(statistics)} rows...")
    
    # SQL for INSERT with ON CONFLICT UPDATE
    sql = """
    INSERT INTO ailog_peak.peak_statistics 
    (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (day_of_week, hour_of_day, quarter_hour, namespace)
    DO UPDATE SET 
        mean_errors = (
            peak_statistics.mean_errors * peak_statistics.samples_count + 
            EXCLUDED.mean_errors * EXCLUDED.samples_count
        ) / (peak_statistics.samples_count + EXCLUDED.samples_count),
        stddev_errors = GREATEST(peak_statistics.stddev_errors, EXCLUDED.stddev_errors),
        samples_count = peak_statistics.samples_count + EXCLUDED.samples_count,
        last_updated = NOW()
    """
    
    # Counters
    inserted = 0
    failed = 0
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    try:
        for (day, hour, quarter, namespace), stats in sorted(statistics.items()):
            try:
                original_value = stats['mean']
                stddev = stats['stddev']
                samples = stats['samples']
                
                # Just insert - no peak detection
                cur.execute(sql, (day, hour, quarter, namespace, 
                                 round(original_value, 1), round(stddev, 1), samples))
                inserted += 1
                
            except Exception as e:
                print(f"⚠️  Failed ({day},{hour},{quarter},{namespace}): {e}")
                failed += 1
        
        conn.commit()
        
        print(f"\n{'='*80}")
        print(f"📊 SUMMARY:")
        print(f"   ✅ Total inserted to DB: {inserted}")
        print(f"   ❌ Failed: {failed}")
        print(f"{'='*80}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        conn.rollback()
        return False


def main():
    parser = argparse.ArgumentParser(description='INIT Phase 3 Weeks - Data ingestion (1.12-21.12)')
    parser.add_argument('--input', required=True, help='Input log file from collect_peak_detailed.py')
    args = parser.parse_args()
    
    print("=" * 80)
    print("📊 INIT Phase 3 Weeks - Data Ingestion (NO Peak Replacement)")
    print("=" * 80)
    print(f"Input: {args.input}")
    print("=" * 80)
    
    # Parse data
    statistics = parse_statistics_from_log(args.input)
    if not statistics:
        print("❌ Failed to parse data")
        return 1
    
    # Connect to DB
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1
    
    # Insert to DB
    success = insert_to_db(statistics, conn)
    conn.close()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
