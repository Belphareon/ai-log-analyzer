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

# Peak detection thresholds
PEAK_RATIO_THRESHOLD = 15.0  # Value must be 15× higher than reference
MIN_VALUE_THRESHOLD = 100.0   # Values below this are NEVER skipped (baseline)


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
        
        # ✅ NO TIMEZONE OFFSET - collect_peak_detailed.py already applies CET conversion
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


def detect_and_skip_peaks(day_of_week, hour_of_day, quarter_hour, namespace, mean_val, all_parsed_stats):
    """
    FIXED IMPLEMENTATION - Peak Detection using PARSED DATA (not DB)
    
    Algorithm:
    1. Get 3 previous 15-min windows (same day): -15min, -30min, -45min
    2. Get 3 previous days (same time): day-1, day-2, day-3
    3. Combine: reference = (avg_windows + avg_days) / 2
    4. Calculate ratio = current / reference
    5. If ratio >= 15× AND current >= 10 → SKIP (it's a peak)
    
    Special handling:
    - If reference < 10: Use higher threshold (50×) - avoid false peaks
    - If current < 10: NEVER skip - it's baseline
    
    Args:
        day_of_week: 0-6 (Mon-Sun)
        hour_of_day: 0-23
        quarter_hour: 0-3
        namespace: string
        mean_val: float - value to test
        all_parsed_stats: dict - ALL parsed data from file: {(day, hour, qtr, ns): {mean, stddev, samples}}
    
    Returns: (is_peak: bool, ratio: float, reference: float, debug_info: dict)
    """
    
    # STEP 1: Calculate 3 previous time windows (same day)
    prev_windows = []
    for i in range(1, 4):  # -15min, -30min, -45min
        minutes_back = i * 15
        total_minutes = hour_of_day * 60 + quarter_hour * 15 - minutes_back
        
        if total_minutes >= 0:  # Stay within same day
            prev_hour = total_minutes // 60
            prev_quarter = (total_minutes % 60) // 15
            prev_windows.append((prev_hour, prev_quarter))
    
    # STEP 2: Get values from previous windows (same day) from PARSED DATA
    refs_windows = []
    if prev_windows:
        for prev_hour, prev_quarter in prev_windows:
            key = (day_of_week, prev_hour, prev_quarter, namespace)
            if key in all_parsed_stats:
                refs_windows.append(all_parsed_stats[key]['mean'])
    
    # STEP 3: Get values from previous days (same time) from PARSED DATA
    refs_days = []
    day_minus_1 = (day_of_week - 1 + 7) % 7
    day_minus_2 = (day_of_week - 2 + 7) % 7
    day_minus_3 = (day_of_week - 3 + 7) % 7
    
    for prev_day_of_week in [day_minus_1, day_minus_2, day_minus_3]:
        key = (prev_day_of_week, hour_of_day, quarter_hour, namespace)
        if key in all_parsed_stats:
            refs_days.append(all_parsed_stats[key]['mean'])
    
    # STEP 4: Calculate reference value
    avg_windows = sum(refs_windows) / len(refs_windows) if refs_windows else None
    avg_days = sum(refs_days) / len(refs_days) if refs_days else None
    
    if avg_windows is not None and avg_days is not None:
        reference = (avg_windows + avg_days) / 2.0
    elif avg_windows is not None:
        reference = avg_windows
    elif avg_days is not None:
        reference = avg_days
    else:
        # No references - cannot detect peak
        return (False, None, None, {'refs_windows': refs_windows, 'refs_days': refs_days, 'reason': 'no_references'})
    
    # ✅ BASELINE NORMALIZATION (2026-01-08):
    # Empty windows (0 errors) = OK system (quiet period)
    # For reference: 0 → 1 (minimum baseline for algorithm)
    # Reason: 0 shouldn't trigger peak detection on quiet systems
    # Logic: If most references are 0-1, threshold becomes stricter (natural)
    if reference <= 0:
        reference = 1
    
    # STEP 5: Calculate ratio and decide if it's a peak
    if reference <= 0:
        return (False, None, reference, {'refs_windows': refs_windows, 'refs_days': refs_days, 'reason': 'zero_reference'})
    
    ratio = mean_val / reference
    
    # STEP 6: Peak decision logic with quality checks
    # Rule 1: Values < 10 are ALWAYS baseline (never skip)
    if mean_val < 10:
        is_peak = False
        reason = 'baseline_value'
    # Rule 2: If reference < 10 (after normalization), use higher threshold (50×)
    # to avoid false positives with limited reference data
    elif reference < 10:
        is_peak = (ratio >= 50.0)
        reason = 'low_reference_threshold' if is_peak else 'below_threshold'
    # Rule 3: Normal threshold (15×)
    else:
        is_peak = (ratio >= PEAK_RATIO_THRESHOLD)
        reason = 'peak_detected' if is_peak else 'below_threshold'
    
    # DEBUG: Log peaks for critical namespace/times
    if namespace == 'pcb-ch-sit-01-app' and hour_of_day == 7 and mean_val > 100:
        print(f"DEBUG {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][day_of_week]} 07:{quarter_hour*15:02d} {namespace}: val={mean_val:.1f}, ref={reference:.1f}, ratio={ratio:.1f}×, is_peak={is_peak}")
    
    debug_info = {
        'refs_windows': refs_windows,
        'refs_days': refs_days,
        'avg_windows': avg_windows,
        'avg_days': avg_days,
        'reference': reference,
        'ratio': ratio,
        'reason': reason
    }
    
    return (is_peak, ratio, reference, debug_info)


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
                    'samples': 1
                }
                added += 1
    
    print(f"   ✅ Added {added} missing patterns")
    print(f"   ✅ Total patterns now: {len(statistics)}")
    
    return statistics


def fill_missing_windows(conn):
    """
    Fill missing 15-minute windows in database after ingestion.
    
    Problem:
    - After each ingestion cycle, some namespaces may have incomplete time windows
    - Missing windows break peak detection (can't calculate references)
    
    Solution:
    - Identify all unique (day, hour, quarter) combinations in DB
    - Identify all unique namespaces in DB
    - For missing combinations: INSERT with mean=0, stddev=0, samples=1
    - Result: Complete grid of namespaces × time windows
    
    This is called automatically after each ingest cycle.
    """
    
    cur = conn.cursor()
    
    print("   📊 Analyzing current data...")
    
    try:
        # Step 1: Get all unique (day, hour, quarter) and namespaces currently in DB
        cur.execute("""
            SELECT DISTINCT day_of_week, hour_of_day, quarter_hour 
            FROM ailog_peak.peak_statistics 
            ORDER BY day_of_week, hour_of_day, quarter_hour
        """)
        all_times = cur.fetchall()
        print(f"      ✅ Found {len(all_times)} unique time windows")
        
        # Get all unique namespaces from DB
        cur.execute("""
            SELECT DISTINCT namespace 
            FROM ailog_peak.peak_statistics 
            ORDER BY namespace
        """)
        all_namespaces = [row[0] for row in cur.fetchall()]
        print(f"      ✅ Found {len(all_namespaces)} unique namespaces")
        
        # Step 2: Find missing combinations and INSERT them
        print(f"   🔄 Finding and inserting missing windows...")
        
        added = 0
        for day, hour, quarter in all_times:
            for ns in all_namespaces:
                # Check if this combination exists
                cur.execute("""
                    SELECT COUNT(*) FROM ailog_peak.peak_statistics 
                    WHERE day_of_week = %s AND hour_of_day = %s AND quarter_hour = %s AND namespace = %s
                """, (day, hour, quarter, ns))
                
                if cur.fetchone()[0] == 0:
                    # Missing - insert with mean=0 (no errors = OK system)
                    cur.execute("""
                        INSERT INTO ailog_peak.peak_statistics 
                        (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (day, hour, quarter, ns, 0, 0, 1))
                    added += 1
        
        conn.commit()
        print(f"      ✅ Added {added} missing windows (mean=0)")
        
        # Step 3: Verify result
        print(f"   ✅ Verifying result...")
        
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        total_rows = cur.fetchone()[0]
        print(f"      Total rows now: {total_rows}")
        
        # Expected: len(all_times) * len(all_namespaces)
        expected = len(all_times) * len(all_namespaces)
        print(f"      Expected: {expected} (all_times × all_namespaces)")
        
        if total_rows == expected:
            print(f"      ✅ PERFECT! Complete grid achieved!")
        else:
            print(f"      ⚠️  Mismatch: have {total_rows}, expected {expected}")
        
        cur.close()
        return True
        
    except Exception as e:
        print(f"   ❌ Error filling missing windows: {e}")
        conn.rollback()
        cur.close()
        return False


def insert_peak_investigation(cur, day_of_week, hour_of_day, quarter_hour, namespace, 
                               original_value, reference_value, ratio, debug_info):
    """
    Log peak detection event to peak_investigation table
    
    Args:
        cur: psycopg2 cursor
        day_of_week: 0-6
        hour_of_day: 0-23
        quarter_hour: 0-3
        namespace: string
        original_value: float - detected peak value
        reference_value: float - smoothed replacement value
        ratio: float - peak/reference ratio
        debug_info: dict - detection debug info
    """
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Determine app_version from namespace (e.g., "pcb-ch-sit-01-app" → "pcb-ch")
    parts = namespace.split('-')
    if len(parts) >= 2:
        app_version = f"{parts[0]}-{parts[1]}"
    else:
        app_version = parts[0]
    
    # Create analysis summary
    reason = debug_info.get('reason', 'unknown')
    refs_windows = debug_info.get('refs_windows', [])
    refs_days = debug_info.get('refs_days', [])
    
    # Convert lists to PostgreSQL arrays for storage
    refs_windows_array = refs_windows[:3] if refs_windows else []
    refs_days_array = refs_days[:3] if refs_days else []
    
    sql_investigation = """
    INSERT INTO ailog_peak.peak_investigation 
    (day_of_week, hour_of_day, quarter_hour, namespace, app_version, original_value, 
     reference_value, ratio, refs_windows_values, refs_days_values, detection_method, 
     investigation_status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
    """
    
    try:
        cur.execute(sql_investigation, (
            int(day_of_week),
            int(hour_of_day),
            int(quarter_hour),
            namespace,
            app_version,
            float(original_value),
            float(reference_value),
            float(ratio),
            refs_windows_array,  # PostgreSQL array
            refs_days_array,     # PostgreSQL array
            reason,              # detection_method
            'pending'            # investigation_status
        ))
        
        # Get the investigation ID
        result = cur.fetchone()
        if result:
            investigation_id = result[0]
            return investigation_id
    except Exception as e:
        print(f"⚠️  Failed to log peak investigation: {e}")
        return None
    
    return None


def insert_statistics_to_db_with_peak_replacement(statistics, conn):
    """
    Insert statistics with PEAK REPLACEMENT (not skip!)
    
    CRITICAL FIX (2026-01-08):
    - Regular phase MUST replace peaks, not skip them
    - If peak is skipped → gap in DB → missing reference for next window
    - If peak is replaced → continuous data → proper references
    
    Algorithm:
    1. Detect peak (using historical data as reference)
    2. Replace peak with reference value
    3. Log peak to peak_investigation table
    4. Insert replaced value to DB
    5. Next window uses replaced value as reference
    
    Result: No gaps, proper chain of references, full peak audit trail
    """
    
    print(f"💾 Connecting to PostgreSQL...")
    
    try:
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect to database: {e}")
        return False
    
    print(f"📤 Inserting {len(statistics)} statistics rows...")
    
    inserted = 0
    failed = 0
    peaks_detected = 0
    peaks_extreme = 0
    peaks_severe = 0
    peaks_moderate = 0
    
    # Open log file for peak recording
    peaks_log_path = "/tmp/peaks_skipped.log"
    peaks_log = open(peaks_log_path, 'w')
    peaks_log.write("=" * 100 + "\n")
    peaks_log.write(f"Peak Detection Log - {datetime.now().isoformat()}\n")
    peaks_log.write("=" * 100 + "\n")
    peaks_log.write("Format: TIMESTAMP | CATEGORY | RATIO | DAY HOUR:QUARTER | NAMESPACE | ORIGINAL | REFERENCES\n")
    peaks_log.write("=" * 100 + "\n\n")
    
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
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    try:
        # DEBUG: Print first few keys to understand data structure
        debug_count = 0
        debug_file = open('/tmp/debug_keys.txt', 'w')
        debug_file.write("=== DEBUG KEYS ===\n")
        for key in list(statistics.keys())[:10]:
            debug_file.write(f"DEBUG KEY {debug_count}: {key}\n")
            print(f"DEBUG KEY {debug_count}: {key}")
            debug_count += 1
        debug_file.write(f"\n=== TOTAL KEYS: {len(statistics)} ===\n")
        debug_file.write(f"SAMPLE pcb-ch-sit-01-app KEYS:\n")
        
        # Find all keys for pcb-ch-sit-01-app
        pcb_keys = [k for k in statistics.keys() if k[3] == 'pcb-ch-sit-01-app']
        for k in pcb_keys[:5]:
            debug_file.write(f"  {k}\n")
        debug_file.close()
        
        for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
            try:
                current_mean = stats['mean']
                
                # DETECT PEAK using historical data
                is_peak, ratio, reference, debug_info = detect_and_skip_peaks(
                    day_of_week, hour_of_day, quarter_hour, namespace, 
                    current_mean, statistics
                )
                
                # FIX (2026-01-08): Replace peak instead of skipping!
                # This ensures: 1) no gaps in DB, 2) proper references for next window
                if is_peak and reference is not None:
                    # REPLACE peak with reference value
                    value_to_insert = reference
                    peaks_detected += 1
                    
                    # Log replacement to peak_investigation table
                    investigation_id = insert_peak_investigation(
                        cur, day_of_week, hour_of_day, quarter_hour, namespace,
                        current_mean, reference, ratio, debug_info
                    )
                    
                    # Log replacement to file
                    peaks_log.write(
                        f"{datetime.now().isoformat()} | REPLACED | "
                        f"ratio={ratio:.1f}x | {day_names[day_of_week]} {hour_of_day:02d}:{quarter_hour*15:02d} | "
                        f"{namespace:30s} | original={current_mean:.1f} → {reference:.1f} | "
                        f"investigation_id={investigation_id}\n"
                    )
                    print(f"  🔴 REPLACE {namespace} {day_names[day_of_week]} {hour_of_day:02d}:{quarter_hour*15:02d}: "
                          f"{current_mean:.1f} → {reference:.1f} ({ratio:.1f}x) [id={investigation_id}]")
                else:
                    # Normal value - insert as is
                    value_to_insert = current_mean
                
                # INSERT to DB (either original or replaced value)
                cur.execute(sql, (
                    int(day_of_week),
                    int(hour_of_day),
                    int(quarter_hour),
                    namespace,
                    value_to_insert,
                    float(stats.get('stddev', 0)),
                    int(stats.get('samples', 1))
                ))
                inserted += 1
                
                # CRITICAL FIX: Update statistics in-place for next iteration
                # This ensures: next window's reference = replaced value (if peak)
                # Result: continuous reference chain, no gaps
                if is_peak and reference is not None:
                    statistics[(day_of_week, hour_of_day, quarter_hour, namespace)]['mean'] = reference
                
            except Exception as e:
                print(f"⚠️  Failed to insert ({day_of_week},{hour_of_day},{quarter_hour},{namespace}): {e}")
                failed += 1
                    print(f"LOOP: {day_names[day_of_week]} 07:{quarter_hour*15:02d} {namespace}")
                
                original_mean = float(stats['mean'])
                stddev_val = float(stats['stddev'])
                
                # ✅ FIXED: PEAK DETECTION using PARSED DATA (not DB!)
                is_peak, ratio, reference, debug_info = detect_and_skip_peaks(
                    day_of_week, hour_of_day, quarter_hour, namespace, original_mean,
                    statistics  # ✅ Pass ALL parsed statistics, not cursor
                )
                
                # DEBUG: Log peaks for critical namespace/times
                if namespace == 'pcb-ch-sit-01-app' and hour_of_day == 7:
                    print(f"DEBUG: {day_names[day_of_week]} 07:{quarter_hour*15:02d} {namespace}: val={original_mean:.1f}, is_peak={is_peak}, ratio={ratio}, ref={reference}")
                
                # DEBUG: Log ALL pcb-ch-sit-01-app values around 05:00-09:00
                if namespace == 'pcb-ch-sit-01-app' and 5 <= hour_of_day <= 9:
                    ratio_str = f"{ratio:.1f}×" if ratio else "N/A"
                    ref_str = f"{reference:.1f}" if reference else "N/A"
                    print(f"DEBUG: {day_names[day_of_week]} {hour_of_day:02d}:{quarter_hour*15:02d} {namespace}")
                    print(f"  Value: {original_mean:.1f}, Ratio: {ratio_str}, Ref: {ref_str}")
                    print(f"  Is Peak: {is_peak}, Refs: windows={len(debug_info.get('refs_windows', []))}, days={len(debug_info.get('refs_days', []))}")
                
                # SKIP if it's a peak
                if is_peak:
                    peaks_detected += 1
                    
                    # Categorize by ratio
                    if ratio and ratio > 100.0:
                        peak_category = "🔴 EXTREME (>100×) SKIPPED"
                        peaks_extreme += 1
                    elif ratio and ratio >= 50.0:
                        peak_category = "🟠 SEVERE (50-100×) SKIPPED"
                        peaks_severe += 1
                    else:
                        peak_category = "🟡 MODERATE (15-50×) SKIPPED"
                        peaks_moderate += 1
                    
                    # Log peak details
                    log_line = (f"{datetime.now().isoformat()} | "
                               f"{peak_category} | "
                               f"ratio={ratio:.2f if ratio else 0}× | "
                               f"date={day_names[day_of_week]} | "
                               f"time={hour_of_day:02d}:{quarter_hour*15:02d} | "
                               f"ns={namespace:20s} | "
                               f"original={original_mean:12.1f} | "
                               f"reference={reference:.1f if reference else 0} | "
                               f"refs_windows={len(debug_info.get('refs_windows', []))} | "
                               f"refs_days={len(debug_info.get('refs_days', []))}\n")
                    peaks_log.write(log_line)
                    print(f"{peak_category} {day_names[day_of_week]} {hour_of_day:02d}:{quarter_hour*15:02d} {namespace}: {original_mean:.1f} → skip (ref={reference:.1f if reference else 0}, ratio: {ratio:.1f if ratio else 0}×)")
                    continue  # SKIP THIS ROW - DON'T INSERT
                
                # Insert non-peak value - round to 1 decimal place
                mean_to_insert = round(original_mean, 1)
                stddev_val = round(stddev_val, 1)
                
                cur.execute(sql, (
                    int(day_of_week),
                    int(hour_of_day),
                    int(quarter_hour),
                    namespace,
                    mean_to_insert,
                    stddev_val,
                    int(stats['samples'])
                ))
                inserted += 1
            except Exception as e:
                print(f"⚠️  Failed to insert ({day_of_week},{hour_of_day},{quarter_hour},{namespace}): {e}")
                failed += 1
        
        conn.commit()
        peaks_log.close()
        
        print(f"\n📊 INSERTION SUMMARY:")
        print(f"   ✅ Inserted: {inserted}")
        print(f"   ❌ Failed: {failed}")
        print(f"   🔴 Peaks detected: {peaks_detected} total")
        print(f"      - EXTREME (>100×): {peaks_extreme}")
        print(f"      - SEVERE (50-100×): {peaks_severe}")
        print(f"      - MODERATE (15-50×): {peaks_moderate}")
        print(f"   📄 Log file: {peaks_log_path}")
        
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
    
    # Fill missing patterns for complete namespace × time grid
    statistics = create_missing_patterns(statistics)
    
    print()
    
    # Connect to DB
    try:
        conn = psycopg2.connect(**DB_CONFIG)
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return 1
    
    # Insert to DB (with peak replacement, not skip!)
    success = insert_statistics_to_db_with_peak_replacement(statistics, conn)
    if not success:
        print("❌ Failed to insert data into database")
        conn.close()
        return 1

    print()
    
    # Fill missing windows (integrate seamlessly, no separate manual step)
    print("=" * 80)
    print("🔧 Filling Missing Windows")
    print("=" * 80)
    fill_missing_windows(conn)
    
    print()
    
    # Verify
    verify_insertion()
    
    conn.close()
    print()
    print("✅ Ingestion complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
