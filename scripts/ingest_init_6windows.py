#!/usr/bin/env python3
"""
Extract statistics from collect_peak_detailed.py text output
and load them directly into PostgreSQL
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
    'password': os.getenv('DB_PASSWORD')  # Required: Set in .env file
}


def parse_peak_statistics_from_log(log_file):
    """
    Parse peak_statistics from collect_peak_detailed.py output log
    
    Format:
        Pattern N: Day HH:MM - namespace
           Raw counts:      [count]
           Smoothed counts: [float]
           Mean: X.XX, StdDev: Y.YY, Samples: N
    
    Returns: dict with statistics
    """
    
    statistics = {}
    day_map = {
        'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3,
        'Fri': 4, 'Sat': 5, 'Sun': 6
    }
    
    print(f"📖 Parsing {log_file}...")
    
    try:
        with open(log_file, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {log_file}")
        return None
    
    # Find all pattern blocks
    pattern_regex = r"Pattern \d+: (\w+) (\d+):(\d+) - (.+?)\n\s+Raw counts:\s+\[(.+?)\]\n\s+Smoothed counts:\s+\[(.+?)\]\n\s+Mean: ([\d.]+), StdDev: ([\d.]+), Samples: (\d+)"
    
    matches = re.finditer(pattern_regex, content)
    count = 0
    
    for match in matches:
        day_name = match.group(1)
        hour = int(match.group(2))
        minute = int(match.group(3))
        namespace = match.group(4).strip()
        mean_str = match.group(7)
        stddev_str = match.group(8)
        samples_str = match.group(9)
        
        # ✅ NO TIMEZONE OFFSET - .txt already has correct times
        day_of_week = day_map.get(day_name, 0)
        
        # Calculate quarter hour (0, 15, 30, 45)
        quarter_hour = (minute // 15) % 4
        
        key = (day_of_week, hour, quarter_hour, namespace)
        
        statistics[key] = {
            'mean': float(mean_str),
            'stddev': float(stddev_str),
            'samples': int(samples_str)
        }
        count += 1
    
    print(f"✅ Parsed {count} patterns from log")
    return statistics if count > 0 else None



def detect_and_skip_peaks(day_of_week, hour_of_day, quarter_hour, namespace, mean_val, all_parsed_stats, peaks_to_skip=None):
    """
    Peak Detection using PARSED DATA (not DB)
    
    Returns: (is_peak: bool, ratio: float, reference: float)
    """
    if peaks_to_skip is None:
        peaks_to_skip = set()
    
    # STEP 1: Get 3 previous 15-min windows (same day)
    refs_windows = []
    for i in range(1, 7):  # -15min, -30min, -45min, -60min, -75min, -90min
        minutes_back = i * 15
        total_minutes = hour_of_day * 60 + quarter_hour * 15 - minutes_back
        
        if total_minutes >= 0:  # Stay within same day
            prev_hour = total_minutes // 60
            prev_quarter = (total_minutes % 60) // 15
            key = (day_of_week, prev_hour, prev_quarter, namespace)
            if key in all_parsed_stats and key not in peaks_to_skip:
                refs_windows.append(all_parsed_stats[key]['mean'])
    
    # STEP 2 (INIT): No historical days - DB is empty
    refs_days = []
    
    # STEP 3: Calculate reference
    avg_windows = sum(refs_windows) / len(refs_windows) if refs_windows else None
    avg_days = sum(refs_days) / len(refs_days) if refs_days else None
    
    if avg_windows is not None and avg_days is not None:
        reference = (avg_windows + avg_days) / 2.0
    elif avg_windows is not None:
        reference = avg_windows
    elif avg_days is not None:
        reference = avg_days
    else:
        return (False, None, None)  # No references
    
    # BASELINE NORMALIZATION: If reference < 5, use 5
    if reference < 5:
        reference = 5
    
    # STEP 4: Calculate ratio
    if reference <= 0:
        return (False, None, reference)
    
    ratio = mean_val / reference
    
    # STEP 5: Peak decision (INIT: simple 35× threshold)
    is_peak = (ratio >= 35.0)
    
    return (is_peak, ratio, reference)

def insert_statistics_to_db(statistics):
    """
    Insert statistics into PostgreSQL peak_statistics table
    Using UPSERT (ON CONFLICT) pattern
    """
    
    print(f"💾 Connecting to PostgreSQL...")
    # DEBUG: Write debug file
    with open("/tmp/insert_debug.txt", "w") as f:
        f.write(f"insert_statistics_to_db called with {len(statistics)} keys\n")
    
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
    
    # SQL for UPSERT with proper aggregation for smoothing
    sql = """
    INSERT INTO ailog_peak.peak_statistics 
    (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (day_of_week, hour_of_day, quarter_hour, namespace)
    DO UPDATE SET 
        mean_errors = (
            (peak_statistics.mean_errors * peak_statistics.samples_count + EXCLUDED.mean_errors * EXCLUDED.samples_count) /
            (peak_statistics.samples_count + EXCLUDED.samples_count)
        ),
        stddev_errors = CASE 
            WHEN (peak_statistics.samples_count + EXCLUDED.samples_count) <= 1 THEN 0
            ELSE sqrt(
                ((peak_statistics.samples_count - 1) * peak_statistics.stddev_errors * peak_statistics.stddev_errors +
                 (EXCLUDED.samples_count - 1) * EXCLUDED.stddev_errors * EXCLUDED.stddev_errors +
                 peak_statistics.samples_count * EXCLUDED.samples_count * 
                 (peak_statistics.mean_errors - EXCLUDED.mean_errors) * (peak_statistics.mean_errors - EXCLUDED.mean_errors) /
                 (peak_statistics.samples_count + EXCLUDED.samples_count)) /
                (peak_statistics.samples_count + EXCLUDED.samples_count - 1)
            )
        END,
        samples_count = peak_statistics.samples_count + EXCLUDED.samples_count
    """
    
    try:
    # PASS 1: Identifikovat všechny peaks
    print(f"🔍 PASS 1: Detecting all peaks...", peaks_to_skip)
    peaks_to_skip = set(, peaks_to_skip)
    for (day_of_week, hour_of_day, quarter_hour, namespace, peaks_to_skip), stats in statistics.items(, peaks_to_skip):
        is_peak, ratio, reference = detect_and_skip_peaks(
            day_of_week, hour_of_day, quarter_hour, namespace, float(stats['mean'], peaks_to_skip), statistics
        , peaks_to_skip)
        if is_peak:
            peaks_to_skip.add((day_of_week, hour_of_day, quarter_hour, namespace, peaks_to_skip), peaks_to_skip)
    
    print(f"   Found {len(peaks_to_skip, peaks_to_skip)} peaks to skip", peaks_to_skip)
    
    # PASS 2: Vložit bez peaks v referencích
    print(f"🔄 PASS 2: Inserting with peak-aware references...", peaks_to_skip)
    
        for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
            try:
                # DEBUG pcb-ch-sit-01-app
                if namespace == "pcb-ch-sit-01-app" and 5 <= hour_of_day <= 9:
                    with open("/tmp/loop_debug.txt", "a") as f:
                        f.write(f"Loop: day={day_of_week}, hour={hour_of_day:02d}, qtr={quarter_hour}, ns={namespace}, mean={stats['mean']}\n")
                # PEAK DETECTION
                mean_val = float(stats["mean"])
                is_peak, ratio, reference = detect_and_skip_peaks(
                    day_of_week, hour_of_day, quarter_hour, namespace, mean_val, statistics
                )
                
                # Skip if peak detected
                if is_peak:
                    with open("/tmp/peaks_skipped.log", "a") as plog:
                        plog.write(f"SKIP: day={day_of_week}, hour={hour_of_day:02d}:{quarter_hour*15:02d}, ns={namespace}, val={mean_val:.1f}, ratio={ratio:.1f}x, ref={reference:.1f}\n")
                    continue  # Skip this row - do not insert
                
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
                print(f"⚠️  Failed to insert ({day_of_week},{hour_of_day},{quarter_hour},{namespace}): {e}")
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


def verify_insertion():
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
            ORDER BY namespace, day_of_week, hour_of_day, quarter_hour
            LIMIT 10
        """)
        
        print(f"\n   Sample data (first 10 rows):")
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        for day, hour, qtr, ns, mean, stddev in cur.fetchall():
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
    parser = argparse.ArgumentParser(description='Extract and ingest peak statistics from log file')
    parser.add_argument('--input', required=True, help='Input log file from collect_peak_detailed.py')
    args = parser.parse_args()
    
    print("="*80)
    print(f"📊 Extract & Ingest Peak Statistics from Log")
    print("="*80)
    print()
    
    # Parse log file
    statistics = parse_peak_statistics_from_log(args.input)
    if not statistics:
        print("❌ No statistics parsed from log")
        return 1
    
    print()
    
    # Insert to DB
    success = insert_statistics_to_db(statistics)
    if not success:
        print("❌ Failed to insert data into database")
        return 1
    
    print()
    
    # Verify
    verify_insertion()
    
    print()
    print("✅ Ingestion complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
