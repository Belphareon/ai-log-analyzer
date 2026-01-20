#!/usr/bin/env python3
"""
Quick verification of Phase 2 ingestion results
Check:
1. Data completeness in peak_statistics
2. Peak investigation logging
3. Missing windows after fill
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    print("="*100)
    print("📊 PHASE 2 INGESTION VERIFICATION")
    print("="*100)
    print()
    
    # 1. Statistics table summary
    print("1️⃣  PEAK_STATISTICS TABLE")
    print("-" * 100)
    
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    total_rows = cur.fetchone()[0]
    print(f"   Total rows: {total_rows}")
    
    # Get stats by namespace
    cur.execute("""
        SELECT namespace, COUNT(*) as count, 
               MIN(mean_errors) as min_mean, 
               MAX(mean_errors) as max_mean, 
               AVG(mean_errors) as avg_mean
        FROM ailog_peak.peak_statistics 
        GROUP BY namespace 
        ORDER BY namespace
    """)
    
    print(f"\n   Per-namespace breakdown:")
    for ns, count, min_m, max_m, avg_m in cur.fetchall():
        print(f"      {ns:30s}: {count:4d} rows | mean: {avg_m:7.2f} (min={min_m:7.2f}, max={max_m:7.2f})")
    
    # 2. Check unique time windows
    cur.execute("""
        SELECT COUNT(DISTINCT day_of_week), 
               COUNT(DISTINCT hour_of_day), 
               COUNT(DISTINCT quarter_hour),
               COUNT(DISTINCT (day_of_week, hour_of_day, quarter_hour)) as unique_times
        FROM ailog_peak.peak_statistics
    """)
    
    days, hours, quarters, unique_times = cur.fetchone()
    print(f"\n   Time grid completeness:")
    print(f"      Days: {days}, Hours: {hours}, Quarters: {quarters} → {unique_times} unique time windows")
    print(f"      Expected: 7 days × 24 hours × 4 quarters = 672 time windows")
    
    # Check if complete
    cur.execute("""
        SELECT COUNT(DISTINCT namespace) FROM ailog_peak.peak_statistics
    """)
    ns_count = cur.fetchone()[0]
    expected_rows = 672 * ns_count
    print(f"      Expected total rows: {expected_rows} (672 × {ns_count} namespaces)")
    print(f"      Actual rows: {total_rows}")
    
    if total_rows == expected_rows:
        print(f"      ✅ PERFECT! Complete grid!")
    else:
        print(f"      ⚠️  Gap: {expected_rows - total_rows} rows missing")
    
    # 3. Peak investigation logging
    print()
    print("2️⃣  PEAK_INVESTIGATION TABLE (Peak Logging)")
    print("-" * 100)
    
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_investigation")
    peak_count = cur.fetchone()[0]
    print(f"   Total peak investigations logged: {peak_count}")
    
    if peak_count > 0:
        print(f"\n   Top 10 peaks (recent):")
        cur.execute("""
            SELECT peak_investigation_id, namespace, app_version, original_value, reference_value, 
                   ratio, status, timestamp
            FROM ailog_peak.peak_investigation 
            ORDER BY timestamp DESC
            LIMIT 10
        """)
        
        for peak_id, ns, app, orig, ref, ratio, status, ts in cur.fetchall():
            print(f"      [{peak_id:6d}] {ns:30s} | orig={orig:8.1f} → ref={ref:8.1f} ({ratio:6.1f}x) | {status}")
        
        # Stats by app_version
        cur.execute("""
            SELECT app_version, COUNT(*) as peaks, 
                   AVG(ratio) as avg_ratio, MAX(ratio) as max_ratio
            FROM ailog_peak.peak_investigation 
            GROUP BY app_version 
            ORDER BY peaks DESC
        """)
        
        print(f"\n   Peaks by app_version:")
        for app, count, avg_r, max_r in cur.fetchall():
            print(f"      {app:20s}: {count:4d} peaks | avg_ratio={avg_r:7.2f}x, max={max_r:7.2f}x")
    else:
        print("   ⚠️  No peaks logged!")
    
    # 4. Peak patterns table
    print()
    print("3️⃣  PEAK_PATTERNS TABLE")
    print("-" * 100)
    
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_patterns")
    pattern_count = cur.fetchone()[0]
    print(f"   Total patterns recorded: {pattern_count}")
    
    if pattern_count > 0:
        cur.execute("""
            SELECT COUNT(*) as pattern_id, occurrence_count, is_known
            FROM ailog_peak.peak_patterns 
            GROUP BY occurrence_count, is_known
            ORDER BY occurrence_count DESC
        """)
        
        print(f"\n   Pattern distribution:")
        for pid, occ, is_known in cur.fetchall():
            known_str = "✅ Known" if is_known else "❓ Unknown"
            print(f"      {known_str}: {pid} patterns with {occ} occurrences")
    
    # 5. Sample recent data
    print()
    print("4️⃣  SAMPLE DATA (Top 20 recent rows)")
    print("-" * 100)
    
    cur.execute("""
        SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count
        FROM ailog_peak.peak_statistics 
        ORDER BY namespace, day_of_week DESC, hour_of_day DESC, quarter_hour DESC
        LIMIT 20
    """)
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for day, hour, quarter, ns, mean, stddev, samples in cur.fetchall():
        time_str = f"{day_names[day]} {hour:02d}:{quarter*15:02d}"
        print(f"   {time_str} {ns:30s} | mean={mean:8.2f}, stddev={stddev:8.2f}, samples={samples}")
    
    print()
    print("="*100)
    print("✅ VERIFICATION COMPLETE")
    print("="*100)
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
