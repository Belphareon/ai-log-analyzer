#!/usr/bin/env python3
"""
Fill missing 15-minute windows - POUZE INIT PHASE (1-21.12.2025)
"""

import os
import psycopg2
from datetime import datetime, timedelta

env_vars = {}
with open('.env') as f:
    for line in f:
        if line.strip() and not line.startswith('#') and '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

DB_CONFIG = {
    'host': env_vars.get('DB_HOST'),
    'port': int(env_vars.get('DB_PORT')),
    'database': env_vars.get('DB_NAME'),
    'user': env_vars.get('DB_USER'),
    'password': env_vars.get('DB_PASSWORD')
}

def fill_missing_windows():
    """Fill missing windows for INIT Phase only (1-21.12.2025)"""
    
    print("=" * 80)
    print("🔧 Filling Missing Windows - INIT PHASE (21 dní: 1.12-21.12.2025)")
    print("=" * 80)
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected")
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False
    
    try:
        # STEP 1: Definuj rozsah INIT Phase
        init_start = datetime(2025, 12, 1).date()
        init_end = datetime(2025, 12, 21).date()
        print(f"\n📊 INIT Phase: {init_start} až {init_end}")
        
        # STEP 2: VŠECHNY 12 namespaces
        all_namespaces = [
            'pca-dev-01-app', 'pca-fat-01-app', 'pca-sit-01-app', 'pca-uat-01-app',
            'pcb-ch-dev-01-app', 'pcb-ch-fat-01-app', 'pcb-ch-sit-01-app', 'pcb-ch-uat-01-app',
            'pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-sit-01-app', 'pcb-uat-01-app'
        ]
        print(f"   ✅ {len(all_namespaces)} namespaces")
        
        # STEP 3: Fill only for INIT Phase days (1-21.12)
        print(f"\n🔄 Filling missing windows (21 dní × 96 oken × 12 NS = 24,192 kombinací)...")
        added = 0
        current_date = init_start
        
        while current_date <= init_end:
            day_of_week = current_date.weekday()
            
            for hour in range(24):
                for quarter in range(4):
                    minute = quarter * 15
                    ts = datetime.combine(current_date, datetime.min.time()).replace(
                        hour=hour, minute=minute, second=0
                    )
                    
                    for ns in all_namespaces:
                        cur.execute("""
                            SELECT COUNT(*) FROM ailog_peak.peak_raw_data
                            WHERE timestamp = %s AND namespace = %s
                        """, (ts, ns))
                        
                        if cur.fetchone()[0] == 0:
                            cur.execute("""
                                INSERT INTO ailog_peak.peak_raw_data
                                (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count)
                                VALUES (%s, %s, %s, %s, %s, 0.0)
                            """, (ts, day_of_week, hour, quarter, ns))
                            added += 1
            
            current_date += timedelta(days=1)
        
        conn.commit()
        print(f"   ✅ Added {added} missing windows")
        
        # STEP 4: Verify INIT Phase only
        print(f"\n✅ Verifying INIT Phase...")
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT DATE(timestamp))
            FROM ailog_peak.peak_raw_data
            WHERE DATE(timestamp) >= '2025-12-01' AND DATE(timestamp) <= '2025-12-21';
        """)
        total_init, days_init = cur.fetchone()
        
        # Check all data
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_raw_data;")
        total_all = cur.fetchone()[0]
        
        print(f"   ✅ INIT Phase (1-21.12): {total_init:,} rows ({days_init} days)")
        print(f"   ✅ Expected: {21 * 96 * 12:,} rows (21 × 96 × 12)")
        
        print(f"   ✅ Total in DB: {total_all:,} rows (včetně REGULAR Phase dat)")
        
        if total_init == 21 * 96 * 12:
            print(f"\n   ✅✅✅ PERFECT! INIT Phase je KOMPLETNÍ!")
        else:
            diff = (21 * 96 * 12) - total_init
            print(f"\n   ⚠️  Rozdíl: {diff} řádků")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    fill_missing_windows()
