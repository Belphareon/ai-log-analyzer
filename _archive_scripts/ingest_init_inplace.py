#!/usr/bin/env python3
"""
IN-PLACE Peak Detection & Replacement Algorithm
WITHOUT 2-PASS - Modifies values during iteration

OPERACE:
1. Detekuj peak (porovnání s průměrem z 5 předchozích oken)
2. Nahraď jeho hodnotu tímto průměrem
3. Vlož nahrazenou hodnotu do DB
4. Automaticky se stane referenční pro další okno!

Key: Není 2-PASS - hodnota se mění hned v paměti během iterace.
"""

import sys
import os
import argparse
import psycopg2
import re
from datetime import datetime
from dotenv import load_dotenv
from collections import OrderedDict

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
    
    Returns: OrderedDict (维持pořadí) with statistics
    """
    
    statistics = OrderedDict()
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
        
        day_of_week = day_map.get(day_name, 0)
        quarter_hour = (minute // 15) % 4
        
        key = (day_of_week, hour, quarter_hour, namespace)
        
        statistics[key] = {
            'mean': float(mean_str),
            'stddev': float(stddev_str),
            'samples': int(samples_str),
            'original_mean': float(mean_str),  # Uložit originálu pro logování
            'is_peak': False,
            'reference': None,
            'ratio': None
        }
        count += 1
    
    print(f"✅ Parsed {count} patterns from log")
    return statistics if count > 0 else None


def create_missing_patterns(statistics):
    """
    Fill in missing 15-minute windows for all namespaces.
    
    Problem: Some namespaces have no errors in certain periods (quiet systems).
    These missing windows break the peak detection algorithm in Regular phase,
    because we can't calculate references without them.
    
    Solution (2026-01-08):
    - Identify all unique (day, hour, quarter) combinations
    - Identify all unique namespaces
    - For each combination that's missing: create with mean=0
    - During reference calculation: 0 → 1 (minimum baseline)
    
    Result: Complete grid of all namespaces × all time windows
    """
    
    # Get all unique time windows and namespaces
    all_times = set()
    all_namespaces = set()
    
    for (day, hour, quarter, ns) in statistics.keys():
        all_times.add((day, hour, quarter))
        all_namespaces.add(ns)
    
    print(f"📊 Filling missing patterns...")
    print(f"   Unique times: {len(all_times)}")
    print(f"   Unique namespaces: {len(all_namespaces)}")
    
    # Create missing entries
    added = 0
    for (day, hour, quarter) in all_times:
        for ns in all_namespaces:
            key = (day, hour, quarter, ns)
            if key not in statistics:
                # Create missing pattern with mean=0 (no errors = OK system)
                statistics[key] = {
                    'mean': 0,
                    'stddev': 0,
                    'samples': 1,
                    'original_mean': 0,
                    'is_peak': False,
                    'reference': None,
                    'ratio': None
                }
                added += 1
    
    print(f"   ✅ Added {added} missing patterns")
    print(f"   ✅ Total patterns now: {len(statistics)}")
    
    return statistics


def get_reference_from_previous_windows(day_of_week, hour_of_day, quarter_hour, namespace, statistics, window_count=5):
    """
    Get average from N previous 15-min windows BEFORE current value.
    
    Returns: (reference_value, found_count)
    
    ⚠️ BASELINE NORMALIZATION (2026-01-08):
    - Empty windows (mean=0) represent "no errors" (system is quiet/OK)
    - For reference calculation: 0 → 1 (minimum baseline for algorithm)
    - This ensures peak detection doesn't trigger on quiet periods
    """
    refs = []
    
    # Get N previous 15-min windows (lookback = window_count * 15 minutes)
    for i in range(1, window_count + 1):
        minutes_back = i * 15
        total_minutes = hour_of_day * 60 + quarter_hour * 15 - minutes_back
        
        if total_minutes >= 0:  # Stay within same day
            prev_hour = total_minutes // 60
            prev_quarter = (total_minutes % 60) // 15
            key = (day_of_week, prev_hour, prev_quarter, namespace)
            
            if key in statistics:
                # ⚠️ BASELINE NORMALIZATION (2026-01-08):
                # If value is 0 (no errors) or very small, normalize to 1
                # This ensures: 0 = OK system, but still usable for reference calc
                val = statistics[key]['mean']
                if val <= 0:
                    val = 1
                refs.append(val)
    
    if not refs:
        return None, 0
    
    # Průměr z dostupných předchozích oken
    reference = sum(refs) / len(refs)
    
    return reference, len(refs)


def detect_and_replace_peak(day_of_week, hour_of_day, quarter_hour, namespace, current_mean, 
                           statistics, window_count=5, peak_threshold=None):
    """
    INIT PHASE Peak detection with simple rule:
    - If value > 300: treat as peak, replace with reference
    - Otherwise: normal value, keep as is
    
    Returns: (replacement_value, is_peak, ratio, reference) or (None, False, None, None)
    """
    
    # INIT PRAVIDLO: Jednoduché - hodnota > 300 = peak
    is_peak = current_mean > 300
    
    if not is_peak:
        # Normální hodnota - neměnit
        return None, False, None, None
    
    # Je peak - potřebujeme referenci pro nahrazení
    reference, found_count = get_reference_from_previous_windows(
        day_of_week, hour_of_day, quarter_hour, namespace, statistics, window_count
    )
    
    if reference is None:
        # Nemáme reference - nemůžeme nahradit, necháme jako je
        return None, False, None, None
    
    # Vrátit replacement (reference)
    ratio = current_mean / reference if reference > 0 else 1.0
    return reference, True, ratio, reference


def insert_statistics_to_db_inplace(statistics):
    """
    Insert statistics into PostgreSQL with IN-PLACE peak replacement
    
    Algoritmus:
    - Iteruj přes OrderedDict (chronologický pořadí)
    - Pro každé okno: detekuj peak, eventuálně nahraď hodnotu
    - Vložit (případně nahrazenou) hodnotu do DB
    - Nahrazená hodnota se automaticky stane referenční pro DALŠÍ okno
    """
    
    print(f"💾 Connecting to PostgreSQL...")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return False
    
    print(f"🔄 PROCESSING {len(statistics)} statistics with IN-PLACE replacement...")
    
    inserted = 0
    failed = 0
    peaks_detected = 0
    peaks_replaced = 0
    
    # SQL for UPSERT
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
    
    peaks_log = open("/tmp/peaks_replaced.log", "w")
    
    try:
        for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
            try:
                current_mean = stats['mean']
                original_mean = stats['original_mean']
                
                # DETEKCE & NAHRAZENÍ IN-PLACE
                # INIT fáze: pravidlo "value > 300" = peak
                replacement_value, is_peak, ratio, reference = detect_and_replace_peak(
                    day_of_week, hour_of_day, quarter_hour, namespace, 
                    current_mean, statistics, window_count=5
                )
                
                # Aktualizuj hodnotu v paměti pro příští iterace
                if replacement_value is not None:
                    stats['mean'] = replacement_value  # ⚠️ IN-PLACE ZMĚNA!
                    peaks_detected += 1
                    peaks_replaced += 1
                    
                    # Log replacement
                    peaks_log.write(
                        f"REPLACED: day={day_of_week}, {hour_of_day:02d}:{quarter_hour*15:02d}, "
                        f"ns={namespace}, original={original_mean:.1f} → replacement={replacement_value:.1f}, "
                        f"ratio={ratio:.1f}x, ref={reference:.1f}\n"
                    )
                    print(f"  ⚙️  REPLACE {namespace} {hour_of_day:02d}:{quarter_hour*15:02d}: "
                          f"{original_mean:.1f} → {replacement_value:.1f} ({ratio:.1f}x)")
                
                # VLOŽIT do DB (původní nebo nahrazenou hodnotu)
                value_to_insert = stats['mean']
                
                cur.execute(sql, (
                    int(day_of_week),
                    int(hour_of_day),
                    int(quarter_hour),
                    namespace,
                    value_to_insert,
                    float(stats['stddev']),
                    int(stats['samples'])
                ))
                inserted += 1
                
            except Exception as e:
                print(f"⚠️  Failed to insert ({day_of_week},{hour_of_day},{quarter_hour},{namespace}): {e}")
                failed += 1
        
        conn.commit()
        peaks_log.close()
        
        print(f"\n📊 REZULTÁTY:")
        print(f"  ✅ Inserted: {inserted}")
        print(f"  ⚠️  Failed: {failed}")
        print(f"  🔴 Peaks detected & replaced: {peaks_replaced}/{peaks_detected}")
        print(f"  📝 Peaks log: /tmp/peaks_replaced.log")
        
    except Exception as e:
        print(f"❌ Error during insert: {e}")
        conn.rollback()
        peaks_log.close()
        cur.close()
        conn.close()
        return False
    
    cur.close()
    conn.close()
    return True


def verify_insertion():
    """Verify data was inserted into DB"""
    
    print(f"\n🔍 Verifying data in database...")
    
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
        
        print(f"\n   Breakdown by namespace:")
        for ns, count in cur.fetchall():
            print(f"   - {ns}: {count} patterns")
        
        # Check for outliers (to verify peaks were handled)
        cur.execute("""
            SELECT namespace, day_of_week, hour_of_day, quarter_hour, mean_errors
            FROM ailog_peak.peak_statistics
            WHERE mean_errors > 1000
            ORDER BY mean_errors DESC
            LIMIT 20
        """)
        
        print(f"\n   Values > 1000 (verify peaks are handled):")
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        results = cur.fetchall()
        if results:
            for ns, day, hour, qtr, mean in results:
                print(f"   - {day_names[day]} {hour:02d}:{qtr*15:02d} {ns}: {mean:.1f}")
        else:
            print(f"   - (none - all values < 1000 ✅)")
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        cur.close()
        conn.close()
        return False
    
    cur.close()
    conn.close()
    return True


def main():
    parser = argparse.ArgumentParser(description='IN-PLACE peak detection & replacement')
    parser.add_argument('--input', required=True, help='Input log file from collect_peak_detailed.py')
    parser.add_argument('--clear-db', action='store_true', help='Clear DB before insert')
    args = parser.parse_args()
    
    print("="*80)
    print(f"⚙️  IN-PLACE Peak Detection & Replacement Algorithm")
    print("="*80)
    print()
    
    if args.clear_db:
        print("🗑️  Clearing database...")
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("TRUNCATE TABLE ailog_peak.peak_statistics")
            conn.commit()
            cur.close()
            conn.close()
            print("✅ Database cleared")
        except Exception as e:
            print(f"❌ Failed to clear DB: {e}")
            return 1
        print()
    
    # Parse log file
    statistics = parse_peak_statistics_from_log(args.input)
    if not statistics:
        print("❌ No statistics parsed from log")
        return 1
    
    print()
    
    # Fill missing patterns for complete namespace × time grid
    statistics = create_missing_patterns(statistics)
    
    print()
    
    # Insert to DB with IN-PLACE replacement
    success = insert_statistics_to_db_inplace(statistics)
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
