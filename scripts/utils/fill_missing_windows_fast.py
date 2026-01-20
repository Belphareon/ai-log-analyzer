#!/usr/bin/env python3
"""
Fill missing 15-minute windows - FAST BULK VERSION
INIT Phase: 1-31.12.2025 + 1-6.1.2026 (do 12:00)
"""

import os
import sys
import argparse
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

def fill_missing_windows(start_date='2025-12-01', end_date='2025-12-31', end_hour=24):
    """Fill missing windows - FAST BULK VERSION
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)  
        end_hour: End hour on end_date (0-24, e.g. 12 means until 12:00)
    """
    
    print("=" * 80)
    print(f"🔧 Filling Missing Windows - FAST BULK")
    print(f"   Period: {start_date} to {end_date} (hour: {end_hour})")
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
        print("\n📊 Generating complete grid for INIT Phase (1-21.12.2025)...")
        
        # Všechny namespaces
        all_namespaces = [
            'pca-dev-01-app', 'pca-fat-01-app', 'pca-sit-01-app', 'pca-uat-01-app',
            'pcb-ch-dev-01-app', 'pcb-ch-fat-01-app', 'pcb-ch-sit-01-app', 'pcb-ch-uat-01-app',
            'pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-sit-01-app', 'pcb-uat-01-app'
        ]
        
        # BULK SQL: Vytvoř všechny kombinace pro daté období
        # a INSERT ... ON CONFLICT doplní jen chybějící
        
        print("🔄 Performing bulk insert with ON CONFLICT resolution...")
        
        # Calculate end quarters for last day (e.g., end_hour=12 means quarters 0-47)
        end_quarter_max = end_hour * 4 - 1 if end_hour < 24 else 95
        
        sql = f"""
        WITH date_range AS (
            SELECT d::DATE as day
            FROM generate_series('{start_date}'::DATE, '{end_date}'::DATE, '1 day'::INTERVAL) d
        ),
        grid AS (
            SELECT 
                dr.day + (h.hour || ' hours')::INTERVAL + (q.quarter * 15 || ' minutes')::INTERVAL as timestamp,
                CASE WHEN EXTRACT(DOW FROM dr.day) = 0 THEN 6 ELSE EXTRACT(DOW FROM dr.day)::INT - 1 END as day_of_week,
                h.hour as hour_of_day,
                q.quarter as quarter_hour,
                ns.namespace,
                0.0 as error_count
            FROM date_range dr
            CROSS JOIN (SELECT generate_series(0, 23) AS hour) h
            CROSS JOIN (SELECT generate_series(0, 3) AS quarter) q
            CROSS JOIN (VALUES %s) ns(namespace)
            WHERE 
                -- For all days except end_date, include all windows
                (dr.day < '{end_date}'::DATE)
                OR
                -- For end_date, only include up to end_hour
                (dr.day = '{end_date}'::DATE AND (h.hour * 4 + q.quarter) <= {end_quarter_max})
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
        cur.execute(f"""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT DATE(timestamp)) as days,
                COUNT(DISTINCT namespace) as namespaces,
                MIN(timestamp) as min_ts,
                MAX(timestamp) as max_ts
            FROM ailog_peak.peak_raw_data
            WHERE timestamp >= '{start_date}'::TIMESTAMP 
              AND timestamp <= '{end_date}'::DATE + '{end_hour} hours'::INTERVAL;
        """)
        total, days, namespaces, min_ts, max_ts = cur.fetchone()
        
        print(f"   ✅ Total rows: {total:,}")
        print(f"   ✅ Calendar days: {days}")
        print(f"   ✅ Namespaces: {namespaces}")
        print(f"   ✅ Time range: {min_ts} to {max_ts}")
        
        # Check overall count
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_raw_data")
        overall = cur.fetchone()[0]
        print(f"   ✅ Overall peak_raw_data: {overall:,} rows")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description='Fill missing 15-minute windows')
    parser.add_argument('--start', default='2025-12-01', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', default='2025-12-31', help='End date (YYYY-MM-DD)')
    parser.add_argument('--end-hour', type=int, default=24, help='End hour on end date (0-24)')
    args = parser.parse_args()
    
    fill_missing_windows(args.start, args.end, args.end_hour)


if __name__ == '__main__':
    main()
