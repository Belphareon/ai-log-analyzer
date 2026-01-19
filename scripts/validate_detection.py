#!/usr/bin/env python3
"""
Validate Peak Detection - Check if detection is working correctly

Checks:
1. All high-ratio values that SHOULD be peaks → are they in peak_investigation?
2. All values in peak_raw_data → none should have ratio >= threshold
3. Duplicates in peak_investigation
4. known_peaks vs peak_investigation consistency
"""

import os
import sys
import psycopg2

# Manual .env load
def load_env():
    env = {}
    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                env[key] = val
    return env

config = load_env()

DB_CONFIG = {
    'host': config.get('DB_HOST'),
    'port': int(config.get('DB_PORT', 5432)),
    'database': config.get('DB_NAME'),
    'user': config.get('DB_USER'),
    'password': config.get('DB_PASSWORD')
}

# Detection thresholds (from values.yaml)
RATIO_THRESHOLD = 3.0
MIN_VALUE = 50


def validate_detection():
    """Run all validation checks"""
    
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    print("=" * 80)
    print("🔍 PEAK DETECTION VALIDATION")
    print("=" * 80)
    
    issues = []
    
    # CHECK 1: Values in peak_raw_data with high ratio (potential missed peaks)
    print("\n📊 CHECK 1: High-ratio values in peak_raw_data (potential missed peaks)")
    cursor.execute("""
        SELECT 
            p.timestamp, p.namespace, p.error_count,
            a.mean as baseline_mean,
            CASE WHEN a.mean > 0 THEN p.error_count / a.mean ELSE 999 END as ratio
        FROM ailog_peak.peak_raw_data p
        LEFT JOIN ailog_peak.aggregation_data a 
            ON p.day_of_week = a.day_of_week 
            AND p.hour_of_day = a.hour_of_day 
            AND p.quarter_hour = a.quarter_hour 
            AND p.namespace = a.namespace
        WHERE p.error_count >= %s
          AND (CASE WHEN a.mean > 0 THEN p.error_count / a.mean ELSE 999 END) >= %s
        ORDER BY ratio DESC
        LIMIT 20;
    """, (MIN_VALUE, RATIO_THRESHOLD))
    
    missed = cursor.fetchall()
    if missed:
        print(f"   ⚠️  Found {len(missed)} potential missed peaks!")
        for row in missed[:5]:
            ts, ns, err, baseline, ratio = row
            baseline = baseline or 0
            print(f"      {ts} | {ns:25s} | err={err:.1f} base={baseline:.1f} ratio={ratio:.1f}×")
        issues.append(f"Potential missed peaks: {len(missed)}")
    else:
        print("   ✅ No missed peaks - all high-ratio values were replaced")
    
    # CHECK 2: Duplicates in peak_investigation
    print("\n📊 CHECK 2: Duplicates in peak_investigation")
    cursor.execute("""
        SELECT timestamp, namespace, COUNT(*) as cnt
        FROM ailog_peak.peak_investigation
        GROUP BY timestamp, namespace
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC;
    """)
    
    duplicates = cursor.fetchall()
    if duplicates:
        print(f"   ⚠️  Found {len(duplicates)} duplicate entries!")
        for ts, ns, cnt in duplicates[:5]:
            print(f"      {ts} | {ns} | {cnt} duplicates")
        issues.append(f"Duplicate peaks: {len(duplicates)}")
    else:
        print("   ✅ No duplicates in peak_investigation")
    
    # CHECK 3: peak_investigation vs known_peaks
    print("\n📊 CHECK 3: peak_investigation vs known_peaks consistency")
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_investigation;")
    inv_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.known_peaks;")
    known_count = cursor.fetchone()[0]
    
    print(f"   peak_investigation: {inv_count} rows")
    print(f"   known_peaks: {known_count} rows")
    
    if known_count == 0 and inv_count > 0:
        print(f"   ⚠️  known_peaks is empty but peak_investigation has {inv_count} peaks!")
        print("      → Peaks should be added to known_peaks for future comparison")
        issues.append("known_peaks empty")
    elif known_count < inv_count:
        print(f"   ⚠️  known_peaks ({known_count}) < peak_investigation ({inv_count})")
        issues.append("known_peaks out of sync")
    else:
        print("   ✅ Consistent")
    
    # CHECK 4: Data coverage
    print("\n📊 CHECK 4: Data coverage in peak_raw_data")
    cursor.execute("""
        SELECT MIN(timestamp), MAX(timestamp), COUNT(*), COUNT(DISTINCT DATE(timestamp))
        FROM ailog_peak.peak_raw_data;
    """)
    min_ts, max_ts, total_rows, total_days = cursor.fetchone()
    print(f"   Date range: {min_ts} → {max_ts}")
    print(f"   Total rows: {total_rows:,}")
    print(f"   Total days: {total_days}")
    
    # CHECK 5: error_patterns stats
    print("\n📊 CHECK 5: error_patterns coverage")
    cursor.execute("""
        SELECT COUNT(*), COUNT(DISTINCT namespace), 
               SUM(occurrence_count), AVG(avg_errors_per_15min)
        FROM ailog_peak.error_patterns;
    """)
    patterns, namespaces, occurrences, avg_err = cursor.fetchone()
    print(f"   Unique patterns: {patterns}")
    print(f"   Namespaces covered: {namespaces}")
    print(f"   Total occurrences: {occurrences}")
    print(f"   Avg errors/15min: {avg_err:.1f}" if avg_err else "   Avg errors/15min: N/A")
    
    # SUMMARY
    print("\n" + "=" * 80)
    print("📋 VALIDATION SUMMARY")
    print("=" * 80)
    
    if issues:
        print(f"   ⚠️  {len(issues)} issues found:")
        for issue in issues:
            print(f"      - {issue}")
    else:
        print("   ✅ All checks passed!")
    
    conn.close()
    return len(issues) == 0


if __name__ == '__main__':
    success = validate_detection()
    sys.exit(0 if success else 1)
