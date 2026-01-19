#!/usr/bin/env python3
"""
Fill missing windows in peak_raw_data with zeros
After INIT phase ingestion, some (day, hour, quarter, namespace) combinations may be missing
This script fills them with error_count=0 and timestamp=now()

CRITICAL: Include ALL 12 namespaces (even if some have no data in INIT, they need zeros for REGULAR phase)

Expected result: All 21 × 96 × 12 = 24,192 combinations present
"""

import os
import psycopg2
from datetime import datetime

def load_env():
    env = {}
    with open('.env', 'r') as f:
        for line in f:
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                env[key.strip()] = val.strip()
    return env

env = load_env()
DB_CONFIG = {
    'host': env['DB_HOST'],
    'port': int(env['DB_PORT']),
    'database': env['DB_NAME'],
    'user': env['DB_USER'],
    'password': env['DB_PASSWORD']
}

# ALL 12 namespaces - fixed list
ALL_NAMESPACES = [
    'pca-dev-01-app',
    'pca-fat-01-app',      # <-- Missing in INIT, needs zeros!
    'pca-sit-01-app',
    'pca-uat-01-app',
    'pcb-ch-dev-01-app',
    'pcb-ch-fat-01-app',
    'pcb-ch-sit-01-app',
    'pcb-ch-uat-01-app',
    'pcb-dev-01-app',
    'pcb-fat-01-app',
    'pcb-sit-01-app',
    'pcb-uat-01-app',
]

print("=" * 80)
print("FILL MISSING WINDOWS IN peak_raw_data")
print("=" * 80)

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # Get all existing (day, hour, quarter) combinations from DB
    cursor.execute("""
        SELECT DISTINCT day_of_week, hour_of_day, quarter_hour
        FROM ailog_peak.peak_raw_data
        ORDER BY day_of_week, hour_of_day, quarter_hour;
    """)
    time_combos_db = cursor.fetchall()
    
    print(f"\n📊 Found {len(time_combos_db)} existing (day, hour, quarter) combinations in DB")
    
    # BUT generate ALL EXPECTED combinations (we should have 7 days × 24 hours × 4 quarters = 672)
    time_combos_expected = []
    for day in range(7):  # 0-6 (all weekdays)
        for hour in range(24):  # 0-23
            for quarter in range(4):  # 0-3
                time_combos_expected.append((day, hour, quarter))
    
    print(f"   Expected (day, hour, quarter) combinations: {len(time_combos_expected)}")
    
    # Find missing time combinations
    existing_time = set(time_combos_db)
    missing_time = []
    for combo in time_combos_expected:
        if combo not in existing_time:
            missing_time.append(combo)
    
    if missing_time:
        print(f"   ⚠️  Missing {len(missing_time)} time combinations - will fill with all namespaces")
    
    # Now use ALL time combos (both existing and missing)
    all_time_combos = time_combos_expected
    
    # Count before
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_raw_data;")
    count_before = cursor.fetchone()[0]
    
    print(f"\n🔍 Before: {count_before} rows")
    
    # Get all existing combinations
    cursor.execute("""
        SELECT day_of_week, hour_of_day, quarter_hour, namespace
        FROM ailog_peak.peak_raw_data;
    """)
    existing = set(cursor.fetchall())
    
    # Generate all expected combinations with ALL 12 namespaces using all_time_combos
    all_combinations = []
    for day, hour, quarter in all_time_combos:
        for ns in ALL_NAMESPACES:
            all_combinations.append((day, hour, quarter, ns))
    
    # Find missing combinations
    missing = []
    for combo in all_combinations:
        if combo not in existing:
            missing.append(combo)
    
    print(f"   Missing: {len(missing)} combinations")
    
    if missing:
        print(f"\n📥 Inserting {len(missing)} missing windows with error_count=0...")
        
        timestamp = datetime.now().isoformat()
        sql = """
        INSERT INTO ailog_peak.peak_raw_data 
        (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count)
        VALUES (%s, %s, %s, %s, %s, 0.0)
        """
        
        for day, hour, quarter, ns in missing:
            cursor.execute(sql, (timestamp, day, hour, quarter, ns))
        
        conn.commit()
        print(f"   ✅ Inserted {len(missing)} rows")
    else:
        print(f"   ✅ No missing combinations found!")
    
    # Count after
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_raw_data;")
    count_after = cursor.fetchone()[0]
    
    # Verify - fixed SQL
    cursor.execute("SELECT COUNT(DISTINCT namespace) FROM ailog_peak.peak_raw_data;")
    ns_cnt = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT day_of_week) FROM ailog_peak.peak_raw_data;")
    day_cnt = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT hour_of_day) FROM ailog_peak.peak_raw_data;")
    hour_cnt = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT quarter_hour) FROM ailog_peak.peak_raw_data;")
    q_cnt = cursor.fetchone()[0]
    
    print(f"\n✅ VERIFICATION:")
    print(f"   Rows before: {count_before}")
    print(f"   Rows added: {len(missing)}")
    print(f"   Rows after: {count_after}")
    print(f"   Expected: {7 * 24 * 4 * 12} (7 days × 24 hours × 4 quarters × 12 namespaces)")
    print(f"   Distinct namespaces: {ns_cnt} (expected 12)")
    print(f"   Distinct days: {day_cnt} (expected 7)")
    print(f"   Distinct hours: {hour_cnt} (expected 24)")
    print(f"   Distinct quarters: {q_cnt} (expected 4)")
    
    if count_after == 7 * 24 * 4 * 12:
        print(f"\n🎉 PERFECT! All {count_after} combinations present!")
    else:
        print(f"\n⚠️  Note: have {count_after} rows")
    
    cursor.close()
    conn.close()

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
