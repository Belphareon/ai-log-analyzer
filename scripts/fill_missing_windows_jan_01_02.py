#!/usr/bin/env python3
"""
Fill missing 15-minute windows - FAST BULK VERSION
Jen pro leden 1-2 (2026-01-01 až 2026-01-02)
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
    """Fill missing windows - FAST BULK VERSION"""
    
    print("=" * 80)
    print("🔧 Filling Missing Windows - FAST BULK (REGULAR Phase: 1-2.1.2026)")
    print("=" * 80)
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected")
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False
    
    try:
        # STEP 1: Vytvořit všechny povinné řádky pomocí SQL
        print("\n📊 Generating complete grid for January 1-2, 2026...")
        
        # Všechny namespaces
        all_namespaces = [
            'pca-dev-01-app', 'pca-fat-01-app', 'pca-sit-01-app', 'pca-uat-01-app',
            'pcb-ch-dev-01-app', 'pcb-ch-fat-01-app', 'pcb-ch-sit-01-app', 'pcb-ch-uat-01-app',
            'pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-sit-01-app', 'pcb-uat-01-app'
        ]
        
        # BULK SQL: Vytvoř všechny kombinace (2 dní × 96 oken × 12 NS = 2,304 řádků)
        # a INSERT ... ON CONFLICT doplní jen chybějící
        
        print("🔄 Performing bulk insert with ON CONFLICT resolution...")
        
        sql = """
        WITH date_range AS (
            SELECT d::DATE as day
            FROM generate_series('2026-01-01'::DATE, '2026-01-02'::DATE, '1 day'::INTERVAL) d
        ),
        time_windows AS (
            SELECT 
                dr.day,
                h.hour,
                q.quarter,
                (h.hour * 4 + q.quarter) as minute_offset,
                EXTRACT(ISODOW FROM dr.day)::INT - 1 as day_of_week
            FROM date_range dr
            CROSS JOIN (SELECT 0 AS hour UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 
                       UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 
                       UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 
                       UNION ALL SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 
                       UNION ALL SELECT 16 UNION ALL SELECT 17 UNION ALL SELECT 18 UNION ALL SELECT 19 
                       UNION ALL SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23) h
            CROSS JOIN (SELECT 0 AS quarter UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3) q
        ),
        grid AS (
            SELECT 
                day + (h.hour || ' hours')::INTERVAL + (q.quarter * 15 || ' minutes')::INTERVAL as timestamp,
                EXTRACT(ISODOW FROM day)::INT - 1 as day_of_week,
                h.hour as hour_of_day,
                q.quarter as quarter_hour,
                ns.namespace,
                0.0 as error_count
            FROM date_range dr
            CROSS JOIN (SELECT 0 AS hour UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3 
                       UNION ALL SELECT 4 UNION ALL SELECT 5 UNION ALL SELECT 6 UNION ALL SELECT 7 
                       UNION ALL SELECT 8 UNION ALL SELECT 9 UNION ALL SELECT 10 UNION ALL SELECT 11 
                       UNION ALL SELECT 12 UNION ALL SELECT 13 UNION ALL SELECT 14 UNION ALL SELECT 15 
                       UNION ALL SELECT 16 UNION ALL SELECT 17 UNION ALL SELECT 18 UNION ALL SELECT 19 
                       UNION ALL SELECT 20 UNION ALL SELECT 21 UNION ALL SELECT 22 UNION ALL SELECT 23) h
            CROSS JOIN (SELECT 0 AS quarter UNION ALL SELECT 1 UNION ALL SELECT 2 UNION ALL SELECT 3) q
            CROSS JOIN (VALUES %s) ns(namespace)
        )
        INSERT INTO ailog_peak.peak_raw_data 
        (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count)
        SELECT timestamp, day_of_week, hour_of_day, quarter_hour, namespace, 0.0 FROM grid
        ON CONFLICT (timestamp, day_of_week, hour_of_day, quarter_hour, namespace) DO NOTHING;
        """
        
        # Převeď namespaces na tuple pro VALUES clause
        ns_values = ','.join([f"('{ns}')" for ns in all_namespaces])
        
        cur.execute(sql % ns_values)
        added = cur.rowcount
        conn.commit()
        
        print(f"   ✅ Inserted {added} missing windows")
        
        # STEP 2: Verify
        print("\n✅ Verifying result...")
        cur.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT DATE(timestamp)) as days,
                COUNT(DISTINCT namespace) as namespaces,
                COUNT(DISTINCT day_of_week) as dow_count
            FROM ailog_peak.peak_raw_data
            WHERE DATE(timestamp) >= '2026-01-01' AND DATE(timestamp) <= '2026-01-02';
        """)
        total, days, namespaces, dow_count = cur.fetchone()
        
        expected = days * 96 * 12
        print(f"   ✅ Total rows (1-2.1.2026): {total:,}")
        print(f"   ✅ Calendar days: {days}")
        print(f"   ✅ Namespaces: {namespaces}")
        print(f"   ✅ Day_of_week values: {dow_count}")
        print(f"   Expected: {expected:,} ({days} × 96 × 12)")
        
        if total == expected and namespaces == 12:
            print(f"\n   ✅✅✅ PERFECT! January 1-2 grid je kompletní!")
        else:
            print(f"\n   ⚠️  Rozdíl: {total - expected} řádků")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    fill_missing_windows()
