#!/usr/bin/env python3
"""
Fill missing 15-minute windows - OPRAVA: správný timestamp pro každé okno
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
    """Fill missing windows"""
    
    print("=" * 80)
    print("🔧 Filling Missing Windows - V3 (správný timestamp)")
    print("=" * 80)
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected")
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False
    
    try:
        # STEP 1: Zjisti rozsah
        print("\n📊 Analyzing data range...")
        cur.execute("""
            SELECT MIN(timestamp)::DATE, MAX(timestamp)::DATE
            FROM ailog_peak.peak_raw_data;
        """)
        min_date, max_date = cur.fetchone()
        print(f"   ✅ Date range: {min_date} až {max_date}")
        
        # STEP 2: VŠECHNY namespaces
        all_namespaces = [
            'pca-dev-01-app', 'pca-fat-01-app', 'pca-sit-01-app', 'pca-uat-01-app',
            'pcb-ch-dev-01-app', 'pcb-ch-fat-01-app', 'pcb-ch-sit-01-app', 'pcb-ch-uat-01-app',
            'pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-sit-01-app', 'pcb-uat-01-app'
        ]
        
        # STEP 3: Fill for each day
        print("\n🔄 Filling missing windows...")
        added = 0
        current_date = min_date
        
        while current_date <= max_date:
            day_of_week = current_date.weekday()
            
            for hour in range(24):
                for quarter in range(4):
                    minute = quarter * 15
                    # Vytvoř timestamp: YYYY-MM-DD HH:MM:00
                    ts = datetime.combine(current_date, datetime.min.time()).replace(
                        hour=hour, minute=minute, second=0
                    )
                    
                    for ns in all_namespaces:
                        # Zkontroluj existenci
                        cur.execute("""
                            SELECT COUNT(*) FROM ailog_peak.peak_raw_data
                            WHERE timestamp = %s AND namespace = %s
                        """, (ts, ns))
                        
                        if cur.fetchone()[0] == 0:
                            # Insert
                            cur.execute("""
                                INSERT INTO ailog_peak.peak_raw_data
                                (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count)
                                VALUES (%s, %s, %s, %s, %s, 0.0)
                            """, (ts, day_of_week, hour, quarter, ns))
                            added += 1
            
            current_date += timedelta(days=1)
        
        conn.commit()
        print(f"   ✅ Added {added} missing windows")
        
        # STEP 4: Verify
        print("\n✅ Verifying...")
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT DATE(timestamp)), COUNT(DISTINCT namespace)
            FROM ailog_peak.peak_raw_data;
        """)
        total, days, namespaces = cur.fetchone()
        expected = days * 96 * 12
        
        print(f"   ✅ Total: {total:,} rows")
        print(f"   ✅ Days: {days}, Namespaces: {namespaces}")
        print(f"   Expected: {expected:,} ({days} × 96 × 12)")
        
        if total == expected:
            print(f"   ✅✅✅ PERFECT! Data je kompletní!")
        else:
            print(f"   ⚠️  Rozdíl: {total - expected}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    fill_missing_windows()
