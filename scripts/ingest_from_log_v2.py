#!/usr/bin/env python3
"""
V2 - SIMPLIFIED Peak Detection and DB Ingestion
NO TIMEZONE OFFSET, CLEAN SIMPLE LOGIC

Algorithm:
1. Parse ALL data into memory
2. For each row:
   a) Find references: 3 windows before (-15, -30, -45 min) + 3 days before (day-1, day-2, day-3)
   b) Calculate average reference
   c) If current >= 15× reference AND current >= 100: SKIP (it's a peak)
   d) Else: INSERT into DB
3. Log all skipped peaks
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

# Peak detection settings
PEAK_RATIO_THRESHOLD = 15.0   # Value must be 15× higher than reference
MIN_PEAK_VALUE = 100.0         # Values below this are NEVER considered peaks


def parse_statistics_from_log(log_file):
    """
    Parse statistics from collect_peak_detailed.py output
    
    NO TIMEZONE OFFSET! Use times as-is from the file.
    
    Returns: dict {(day, hour, quarter, namespace): {mean, stddev, samples}}
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
        
        # ✅ NO TIMEZONE OFFSET - use times as-is
        day_of_week = day_map.get(day_name, 0)
        hour_of_day = hour
        quarter_hour = (minute // 15) % 4
        
        key = (day_of_week, hour_of_day, quarter_hour, namespace)
        statistics[key] = {
            'mean': mean_val,
            'stddev': stddev_val,
            'samples': samples
        }
        count += 1
    
    print(f"✅ Parsed {count} patterns")
    return statistics


def detect_peak(day, hour, quarter, namespace, value, all_stats):
    """
    SIMPLIFIED Peak Detection
    
    1. Get 3 previous 15-min windows (same day): -15, -30, -45 min
    2. Get 3 previous days (same time): day-1, day-2, day-3
    3. Average all references
    4. If value >= 15× average AND value >= 100: IT'S A PEAK
    
    Returns: (is_peak: bool, ratio: float, reference: float, refs_count: int)
    """
    
    # Values < 100 are NEVER peaks (baseline traffic)
    if value < MIN_PEAK_VALUE:
        return (False, None, None, 0)
    
    # STEP 1: Get 3 previous time windows (same day)
    refs = []
    
    for i in range(1, 4):  # -15, -30, -45 minutes
        minutes_back = i * 15
        total_minutes = hour * 60 + quarter * 15 - minutes_back
        
        if total_minutes >= 0:  # Stay within same day
            prev_hour = total_minutes // 60
            prev_quarter = (total_minutes % 60) // 15
            key = (day, prev_hour, prev_quarter, namespace)
            if key in all_stats:
                refs.append(all_stats[key]['mean'])
    
    # STEP 2: Get 3 previous days (same time)
    for i in range(1, 4):  # day-1, day-2, day-3
        prev_day = (day - i + 7) % 7
        key = (prev_day, hour, quarter, namespace)
        if key in all_stats:
            refs.append(all_stats[key]['mean'])
    
    # STEP 3: Calculate reference
    if not refs:
        # No references - cannot determine if peak
        return (False, None, None, 0)
    
    reference = sum(refs) / len(refs)
    
    # Avoid division by zero
    if reference <= 0:
        return (False, None, reference, len(refs))
    
    # STEP 4: Calculate ratio
    ratio = value / reference
    
    # STEP 5: Peak decision
    is_peak = (ratio >= PEAK_RATIO_THRESHOLD)
    
    return (is_peak, ratio, reference, len(refs))


def insert_to_db(statistics, conn):
    """
    Insert statistics to DB with peak detection
    
    - Peaks (ratio >= 15×): SKIP and log
    - Normal values: INSERT to DB
    """
    
    print(f"\n💾 Connecting to database...")
    
    try:
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False
    
    print(f"📤 Processing {len(statistics)} rows...")
    
    # Open log file
    log_file = "/tmp/peaks_skipped_v2.log"
    log = open(log_file, 'w')
    log.write("=" * 100 + "\n")
    log.write(f"Peak Detection Log V2 - {datetime.now().isoformat()}\n")
    log.write("=" * 100 + "\n")
    log.write("Format: DAY HH:MM | NAMESPACE | VALUE | REFERENCE | RATIO | REFS_COUNT\n")
    log.write("=" * 100 + "\n\n")
    
    # Counters
    inserted = 0
    skipped = 0
    failed = 0
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # SQL for UPSERT
    sql = """
    INSERT INTO ailog_peak.peak_statistics 
    (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (day_of_week, hour_of_day, quarter_hour, namespace)
    DO UPDATE SET 
        mean_errors = EXCLUDED.mean_errors,
        stddev_errors = EXCLUDED.stddev_errors,
        samples_count = peak_statistics.samples_count + EXCLUDED.samples_count
    """
    
    try:
        for (day, hour, quarter, namespace), stats in sorted(statistics.items()):
            try:
                value = stats['mean']
                stddev = stats['stddev']
                samples = stats['samples']
                
                # Peak detection
                is_peak, ratio, reference, refs_count = detect_peak(
                    day, hour, quarter, namespace, value, statistics
                )
                
                # If peak: SKIP and log
                if is_peak:
                    skipped += 1
                    log_line = (f"{day_names[day]} {hour:02d}:{quarter*15:02d} | "
                               f"{namespace:25s} | "
                               f"VALUE={value:8.1f} | "
                               f"REF={reference:8.1f} | "
                               f"RATIO={ratio:6.1f}× | "
                               f"REFS={refs_count}\n")
                    log.write(log_line)
                    
                    print(f"🔴 SKIP: {day_names[day]} {hour:02d}:{quarter*15:02d} {namespace:20s} "
                          f"value={value:8.1f} (ref={reference:6.1f}, ratio={ratio:5.1f}×)")
                    continue
                
                # Normal value: INSERT
                cur.execute(sql, (day, hour, quarter, namespace, 
                                 round(value, 1), round(stddev, 1), samples))
                inserted += 1
                
            except Exception as e:
                print(f"⚠️  Failed ({day},{hour},{quarter},{namespace}): {e}")
                failed += 1
        
        conn.commit()
        log.close()
        
        print(f"\n{'='*80}")
        print(f"📊 SUMMARY:")
        print(f"   ✅ Inserted to DB: {inserted}")
        print(f"   🔴 Skipped (peaks): {skipped}")
        print(f"   ❌ Failed: {failed}")
        print(f"   📄 Peak log: {log_file}")
        print(f"{'='*80}\n")
        
        return True
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        conn.rollback()
        return False


def main():
    parser = argparse.ArgumentParser(description='V2 - Simplified peak detection and ingestion')
    parser.add_argument('--input', required=True, help='Input log file from collect_peak_detailed.py')
    args = parser.parse_args()
    
    print("=" * 80)
    print("📊 Peak Statistics Ingestion V2 - SIMPLIFIED")
    print("=" * 80)
    print(f"Input: {args.input}")
    print(f"Peak threshold: {PEAK_RATIO_THRESHOLD}×")
    print(f"Min peak value: {MIN_PEAK_VALUE}")
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
