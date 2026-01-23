#!/usr/bin/env python3
"""
V2 - DYNAMIC Peak Detection with Configurable Thresholds
LOADS PARAMETERS FROM values.yaml FOR EASY TUNING

Algorithm:
1. Load dynamic parameters from values.yaml
2. Parse ALL data into memory
3. For each row:
   a) Find references: 3 windows before (-15, -30, -45 min) from same day
   b) Get baseline_mean from aggregation_data (Reference 1)
   c) Calculate dynamic ratio_threshold = baseline_mean * min_ratio_multiplier
   d) If ratio >= ratio_threshold AND value >= 24h_avg * multiplier: PEAK
   e) INSERT (replaced or original) into DB
4. Log all detected peaks with configuration used
"""

import sys
import os
import argparse
import psycopg2
import re
import yaml
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

# Load configuration from values.yaml
def load_config():
    """
    Load dynamic parameters from values.yaml
    Returns: dict with peak_detection config
    """
    config_file = os.path.join(os.path.dirname(__file__), '..', 'values.yaml')
    
    if not os.path.exists(config_file):
        print(f"⚠️  Config file not found: {config_file}")
        print("   Using defaults...")
        return {
            'min_ratio_multiplier': 3.0,
            'max_ratio_multiplier': 5.0,
            'absolute_threshold_multiplier': 4.0,
            'min_absolute_value': 100,
            'same_day_window_count': 3,
            'use_aggregation_baseline': True,
            'use_24h_trend': True,
            'log_path': '/tmp/peaks_replaced_v2.log',
            'verbose': False
        }
    
    try:
        with open(config_file, 'r') as f:
            data = yaml.safe_load(f)
        
        config = data.get('peak_detection', {})
        print(f"✅ Loaded config from {config_file}")
        print(f"   min_ratio_multiplier: {config.get('min_ratio_multiplier')}")
        print(f"   max_ratio_multiplier: {config.get('max_ratio_multiplier')}")
        print(f"   dynamic_min_multiplier: {config.get('dynamic_min_multiplier')}")
        
        return config
    except Exception as e:
        print(f"⚠️  Error loading config: {e}")
        print("   Using defaults...")
        return {
            'min_ratio_multiplier': 3.0,
            'max_ratio_multiplier': 5.0,
            'absolute_threshold_multiplier': 4.0,
            'min_absolute_value': 100,
            'same_day_window_count': 3,
            'use_aggregation_baseline': True,
            'use_24h_trend': True,
            'log_path': '/tmp/peaks_replaced_v2.log',
            'verbose': False
        }

# Global config
CONFIG = load_config()


def parse_data_format(log_file):
    """
    Parse DATA| format with timestamp
    Format: DATA|TIMESTAMP|day_of_week|hour|quarter|namespace|mean|stddev|samples
    
    Example: DATA|2026-01-12T10:30:00|0|10|2|dcs-nprod-default|123.45|67.89|42
    
    Returns: dict {(day, hour, quarter, namespace): {'mean', 'stddev', 'samples', 'timestamp'}}
    """
    statistics = {}
    
    print(f"📖 Parsing DATA| format from {log_file}...")
    
    try:
        with open(log_file, 'r') as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"❌ File not found: {log_file}")
        return None
    
    count = 0
    for line in lines:
        line = line.strip()
        if not line.startswith('DATA|'):
            continue
        
        try:
            parts = line.split('|')
            if len(parts) != 9:
                print(f"⚠️  Skipping malformed line: {line}")
                continue
            
            timestamp = parts[1]
            day = int(parts[2])
            hour = int(parts[3])
            quarter = int(parts[4])
            namespace = parts[5]
            mean_val = float(parts[6])
            stddev_val = float(parts[7])
            samples = int(parts[8])
            
            key = (day, hour, quarter, namespace)
            
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
                    'samples': combined_samples,
                    'timestamp': timestamp  # Use latest timestamp
                }
            else:
                statistics[key] = {
                    'mean': mean_val,
                    'stddev': stddev_val,
                    'samples': samples,
                    'timestamp': timestamp
                }
            count += 1
            
        except Exception as e:
            print(f"⚠️  Error parsing line: {line} - {e}")
            continue
    
    print(f"✅ Parsed {count} DATA lines → {len(statistics)} unique keys (after aggregation)")
    return statistics


def parse_statistics_from_log(log_file):
    """
    Parse statistics from collect_peak_detailed.py output (OLD FORMAT)
    
    CRITICAL: Aggregate in memory!
    - Same key (day, hour, quarter, namespace) from same file may appear multiple times
    - Combine samples: mean = (old_mean * old_samples + new_mean * new_samples) / (old_samples + new_samples)
    
    NO TIMEZONE OFFSET! Use times as-is from the file.
    
    Returns: dict {(day, hour, quarter, namespace): {mean, stddev, samples}}
    """
    
    statistics = {}
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
    
    print(f"📖 Parsing OLD format from {log_file}...")
    
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
        
        # AGGREGATE IN MEMORY if key already exists
        if key in statistics:
            # Combine: new_mean = (old_mean * old_samples + new_mean * new_samples) / (old_samples + new_samples)
            old_data = statistics[key]
            old_mean = old_data['mean']
            old_samples = old_data['samples']
            
            combined_mean = (old_mean * old_samples + mean_val * samples) / (old_samples + samples)
            combined_samples = old_samples + samples
            # StdDev: keep larger one (conservative estimate)
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


def detect_peak(day, hour, quarter, namespace, value, all_stats, conn=None):
    """
    DYNAMIC Peak Detection - Ratio threshold calculated from baseline_mean
    
    Strategy:
    1. Get baseline_mean from aggregation_data (Reference 1)
    2. Calculate baseline_mean = aggregation_data.mean (7-day baseline)
    3. Get 3 previous 15-min windows from SAME day (from peak_raw_data DB)
    4. Calculate reference mean from those 3 windows
    5. Decision: EITHER condition (OR):
       - ratio >= (min_ratio_multiplier = 3.0)  [Volatility based!]
       - value >= (aggregation_data.mean * absolute_threshold_multiplier = 4.0)  [Absolute based!]
    
    Parameters:
        day, hour, quarter, namespace: current window
        value: current error count
        all_stats: dict of current batch data (for in-memory lookup)
        conn: DB connection for reading peak_raw_data
    
    Returns: dict {
        'is_peak': bool,
        'ratio': float,
        'reference': float,
        'baseline_mean': float,
        'threshold_24h': float,
        'dynamic_ratio_threshold': float,
        'refs_count': int
    }
    """
    
    # STEP 1: Get baseline_mean from aggregation_data (Reference 1)
    baseline_mean = None
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT mean 
                FROM ailog_peak.aggregation_data 
                WHERE day_of_week = %s 
                  AND hour_of_day = %s 
                  AND quarter_hour = %s 
                  AND namespace = %s;
            """, (day, hour, quarter, namespace))
            result = cur.fetchone()
            if result and result[0]:
                baseline_mean = result[0]
        except Exception:
            pass
    
    # STEP 2: Calculate DYNAMIC ratio threshold based on baseline
    if baseline_mean and baseline_mean > 0:
        dynamic_ratio_threshold = baseline_mean * CONFIG.get('min_ratio_multiplier', 3.0)
    else:
        dynamic_ratio_threshold = None  # Will fallback to absolute minimum
    
    # STEP 3: Get 3 previous time windows (same day) from peak_raw_data
    refs = []
    same_day_window_count = CONFIG.get('same_day_window_count', 3)
    
    for i in range(1, same_day_window_count + 1):  # -15, -30, -45 minutes
        minutes_back = i * 15
        total_minutes = hour * 60 + quarter * 15 - minutes_back
        
        if total_minutes >= 0:  # Stay within same day
            prev_hour = total_minutes // 60
            prev_quarter = (total_minutes % 60) // 15
            
            # First try in-memory data (current batch)
            key = (day, prev_hour, prev_quarter, namespace)
            if key in all_stats:
                refs.append(all_stats[key]['mean'])
            elif conn:
                # Fallback: read from peak_raw_data DB (latest value for this combination)
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT error_count 
                        FROM ailog_peak.peak_raw_data 
                        WHERE day_of_week = %s 
                          AND hour_of_day = %s 
                          AND quarter_hour = %s 
                          AND namespace = %s
                        ORDER BY timestamp DESC
                        LIMIT 1;
                    """, (day, prev_hour, prev_quarter, namespace))
                    result = cur.fetchone()
                    if result:
                        refs.append(result[0])
                except Exception as e:
                    pass  # Skip if DB error
    
    # STEP 4: Calculate reference from same-day windows
    if refs:
        reference = sum(refs) / len(refs)
        refs_count = len(refs)
    else:
        reference = baseline_mean if baseline_mean else 0
        refs_count = 0  # 0 = using aggregation fallback
    
    # STEP 5: Get 24h average for dynamic minimum threshold
    threshold_24h = 0
    if CONFIG.get('use_24h_trend', True) and conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT AVG(error_count) as avg_24h
                FROM ailog_peak.peak_raw_data
                WHERE namespace = %s
                  AND timestamp >= (SELECT MAX(timestamp) FROM ailog_peak.peak_raw_data) - INTERVAL '24 hours';
            """, (namespace,))
            result = cur.fetchone()
            if result and result[0]:
                threshold_24h = result[0]
        except Exception:
            pass  # Fallback to 0 if query fails
    
    # STEP 6: Peak detection - DUAL THRESHOLD (OR logic)
    absolute_threshold_multiplier = CONFIG.get('absolute_threshold_multiplier', 4.0)
    
    is_peak = False
    ratio = float('inf') if value > 0 else 0

    if reference > 0:
        ratio = value / reference

    # Decision: EITHER condition (OR logic):
    # 1. Volatility-based: ratio >= 3.0 (value is 3× higher than recent trend)
    # 2. Absolute-based: value >= aggregation_data.mean * 4.0 (value is 4× higher than 7-day baseline)
    
    ratio_threshold = CONFIG.get('ratio_multiplier', 3.0)
    absolute_threshold = baseline_mean * absolute_threshold_multiplier if baseline_mean and baseline_mean > 0 else float('inf')
    
    # Condition 1: Check ratio threshold
    condition_1 = (reference > 0 and ratio >= ratio_threshold)
    
    # Condition 2: Check absolute threshold (aggregation_data.mean * multiplier)
    condition_2 = (baseline_mean and baseline_mean > 0 and value >= absolute_threshold)
    
    is_peak = condition_1 or condition_2

    return {
        'is_peak': is_peak,
        'ratio': ratio,
        'reference': reference,
        'baseline_mean': baseline_mean,
        'refs_count': refs_count
    }



def insert_to_db(statistics, conn, init_phase=False):
    """
    Insert statistics to DB
    
    CRITICAL DIFFERENCE:
    - INIT Phase (init_phase=True):
      Insert to peak_raw_data WITHOUT aggregation
      NO ON CONFLICT UPDATE (keep all raw data separate!)
      Each day's data is separate row with timestamp
    
    - REGULAR Phase (init_phase=False):
      Insert to peak_raw_data with peak detection
      Update aggregation_data for rolling baseline
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
    log_file = CONFIG.get('log_path', '/tmp/peaks_replaced_v2.log')
    log = open(log_file, 'w')
    log.write("=" * 120 + "\n")
    log.write(f"Peak Detection & Replacement Log V2 - {datetime.now().isoformat()}\n")
    log.write(f"Phase: {'INIT (no peak detection)' if init_phase else 'REGULAR (with peak detection)'}\n")
    if not init_phase:
        log.write(f"\nCONFIGURATION USED:\n")
        log.write(f"  min_ratio_multiplier: {CONFIG.get('min_ratio_multiplier', 3.0)}\n")
        log.write(f"  max_ratio_multiplier: {CONFIG.get('max_ratio_multiplier', 5.0)}\n")
        log.write(f"  dynamic_min_multiplier: {CONFIG.get('absolute_threshold_multiplier', 4.0)}\n")
        log.write(f"  min_absolute_value: {CONFIG.get('min_absolute_value', 100)}\n")
        log.write(f"  same_day_window_count: {CONFIG.get('same_day_window_count', 3)}\n")
    log.write("=" * 120 + "\n")
    log.write("=" * 120 + "\n\n")
    
    # Counters
    inserted = 0
    replaced = 0
    failed = 0
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Check if we have timestamps in data (DATA| format) or use current time (old format)
    has_timestamps = any('timestamp' in stats for stats in statistics.values())
    batch_timestamp = datetime.now().isoformat() if not has_timestamps else None
    
    # SQL for both phases - with ON CONFLICT to handle duplicates
    sql = """
    INSERT INTO ailog_peak.peak_raw_data 
    (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
    DO UPDATE SET error_count = EXCLUDED.error_count, created_at = NOW()
    """
    
    try:
        for (day, hour, quarter, namespace), stats in sorted(statistics.items()):
            try:
                original_value = stats['mean']
                stddev = stats['stddev']
                samples = stats['samples']
                # Use timestamp from data if available, otherwise use batch timestamp
                record_timestamp = stats.get('timestamp', batch_timestamp)
                
                # Peak detection
                if init_phase:
                    # INIT Phase: NO peak detection, just load all data
                    is_peak = False
                    replacement_value = original_value
                    peak_info = None
                else:
                    # REGULAR Phase: WITH peak detection
                    peak_info = detect_peak(
                        day, hour, quarter, namespace, original_value, statistics, conn
                    )
                    is_peak = peak_info['is_peak']
                    if is_peak:
                        # Use aggregation_data.mean (baseline_mean) for replacement
                        # This is the stable 7-day baseline - always better than reference
                        replacement_value = peak_info['baseline_mean'] if peak_info['baseline_mean'] and peak_info['baseline_mean'] > 0 else original_value
                    else:
                        replacement_value = original_value
                
                # If peak detected (REGULAR phase only): RECORD and REPLACE
                if is_peak and peak_info:
                    replaced += 1
                    baseline_str = f"{peak_info['baseline_mean']:.1f}" if peak_info['baseline_mean'] else 'N/A'
                    threshold_str = 'N/A'  # dynamic_ratio_threshold removed
                    avg_24h_str = 'N/A'  # threshold_24h removed
                    log_line = (f"{day_names[day]} {hour:02d}:{quarter*15:02d} | "
                               f"{namespace:25s} | "
                               f"REPLACED: {original_value:8.1f} → {replacement_value:8.1f} ({peak_info['ratio']:6.1f}×) | "
                               f"baseline={baseline_str}, "
                               f"threshold={threshold_str} | "
                               f"24h_avg={avg_24h_str} | "
                               f"✅ INSERT to DB\n")
                    log.write(log_line)
                    
                    # *** INSERT PEAK INTO peak_investigation TABLE ***
                    # Simple INSERT - duplicates are OK for audit logging
                    try:
                        # Handle inf ratio (when reference is 0)
                        ratio_val = peak_info['ratio']
                        if ratio_val == float('inf') or ratio_val != ratio_val:  # inf or NaN
                            ratio_val = 999.0  # Store as large number instead of inf
                        
                        cur.execute("""
                            INSERT INTO ailog_peak.peak_investigation 
                            (timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
                             original_value, reference_value, replacement_value, ratio,
                             baseline_mean, same_day_refs_mean, investigation_status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (
                            record_timestamp,
                            day, hour, quarter, namespace,
                            original_value,
                            peak_info['reference'],
                            replacement_value,
                            ratio_val,
                            peak_info['baseline_mean'] if peak_info['baseline_mean'] else 0,
                            peak_info['reference'],
                            'new'  # investigation_status
                        ))
                    except Exception as inv_err:
                        print(f"⚠️  Warning - peak not logged to peak_investigation: {inv_err}")
                    
                    verbose = CONFIG.get('verbose', False)
                    if verbose or replaced <= 10:  # Log first 10 peaks
                        print(f"🔴 PEAK REPLACED: {day_names[day]} {hour:02d}:{quarter*15:02d} {namespace:20s} "
                              f"orig={original_value:8.1f} → repl={replacement_value:8.1f} ({peak_info['ratio']:5.1f}×) "
                              f"baseline={baseline_str} ✅ [logged to peak_investigation]")
                
                # Insert to peak_raw_data (with replacement_value if peak was detected)
                cur.execute(sql, (record_timestamp, day, hour, quarter, namespace, round(replacement_value, 1)))
                inserted += 1
                
                # REGULAR Phase: Update aggregation_data (rolling baseline)
                if not init_phase:
                    try:
                        cur.execute("""
                            INSERT INTO ailog_peak.aggregation_data 
                            (day_of_week, hour_of_day, quarter_hour, namespace, mean, stddev, samples, last_updated)
                            VALUES (%s, %s, %s, %s, %s, %s, 1, NOW())
                            ON CONFLICT (day_of_week, hour_of_day, quarter_hour, namespace)
                            DO UPDATE SET
                                mean = (ailog_peak.aggregation_data.mean * ailog_peak.aggregation_data.samples + EXCLUDED.mean) 
                                       / (ailog_peak.aggregation_data.samples + 1),
                                samples = ailog_peak.aggregation_data.samples + 1,
                                last_updated = NOW()
                        """, (day, hour, quarter, namespace, replacement_value, stddev))
                    except Exception as agg_err:
                        # Non-fatal - continue processing
                        pass
                
            except Exception as e:
                print(f"⚠️  Failed ({day},{hour},{quarter},{namespace}): {e}")
                failed += 1
        
        conn.commit()
        log.close()
        
        print(f"\n{'='*80}")
        print(f"📊 SUMMARY:")
        print(f"   ✅ Total inserted to peak_raw_data: {inserted}")
        if not init_phase:
            print(f"   🔴 Peaks detected & replaced: {replaced}")
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
    parser.add_argument('--init', action='store_true', help='INIT phase: no peak detection, just load raw data')
    args = parser.parse_args()
    
    print("=" * 80)
    print("📊 Peak Statistics Ingestion - DYNAMIC THRESHOLDS")
    print("=" * 80)
    print(f"Input: {args.input}")
    print(f"Mode: {'🔵 INIT PHASE (no peak detection)' if args.init else '🟢 REGULAR PHASE (with peak detection)'}")
    if not args.init:
        print(f"Peak ratio multiplier: {CONFIG.get('min_ratio_multiplier', 3.0)}×")
        print(f"Dynamic min multiplier: {CONFIG.get('absolute_threshold_multiplier', 4.0)}×")
    print("=" * 80)
    
    # Detect format (DATA| vs old format)
    print("\n🔍 Detecting file format...")
    try:
        with open(args.input, 'r') as f:
            # Skip header lines and find first data line
            for line in f:
                line = line.strip()
                if line.startswith('DATA|'):
                    is_data_format = True
                    break
                elif line.startswith('Pattern '):
                    is_data_format = False
                    break
            else:
                is_data_format = False
            print(f"   Format: {'DATA| (new format with timestamp)' if is_data_format else 'Old format (regex parsing)'}")
    except Exception as e:
        print(f"❌ Cannot read file: {e}")
        return 1
    
    # Parse data (choose parser based on format)
    if is_data_format:
        statistics = parse_data_format(args.input)
    else:
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
    
    # Insert to DB (with or without peak detection based on mode)
    success = insert_to_db(statistics, conn, init_phase=args.init)
    conn.close()
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
