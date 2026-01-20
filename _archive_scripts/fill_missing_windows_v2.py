#!/usr/bin/env python3
"""
Fill missing 15-minute windows in DB for ALL data (dynamic based on actual date range).

Oprava: Script zjistí MIN/MAX timestamp z DB a doplní VŠECHNY chybějící kombinace
pro každý kalendářní den v tom rozsahu, nikoliv jen jeden týden!
"""

import os
import psycopg2
from datetime import datetime, timedelta

# Load from .env
env_vars = {}
with open('.env') as f:
    for line in f:
        if line.strip() and not line.startswith('#') and '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

DB_CONFIG = {
    'host': env_vars.get('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(env_vars.get('DB_PORT', 5432)),
    'database': env_vars.get('DB_NAME', 'ailog_analyzer'),
    'user': env_vars.get('DB_USER', 'ailog_analyzer_user_d1'),
    'password': env_vars.get('DB_PASSWORD')
}

def fill_missing_windows():
    """Fill missing windows for ALL date range"""
    
    print("=" * 80)
    print("🔧 Filling Missing Windows - DYNAMIC (všechny dny v rozsahu)")
    print("=" * 80)
    print()
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False
    
    try:
        # STEP 1: Zjisti rozsah dat z DB
        print("\n📊 Analyzing data range...")
        cur.execute("""
            SELECT 
                MIN(timestamp)::DATE as min_date,
                MAX(timestamp)::DATE as max_date,
                COUNT(DISTINCT DATE(timestamp)) as unique_days
            FROM ailog_peak.peak_raw_data;
        """)
        min_date, max_date, unique_days = cur.fetchone()
        
        if not min_date or not max_date:
            print("❌ Žádná data v DB!")
            return False
        
        print(f"   ✅ Date range: {min_date} až {max_date}")
        print(f"   ✅ Unique calendar days: {unique_days}")
        
        # STEP 2: Definuj VŠECH 12 namespaces
        all_namespaces = [
            'pca-dev-01-app',
            'pca-fat-01-app',
            'pca-sit-01-app',
            'pca-uat-01-app',
            'pcb-ch-dev-01-app',
            'pcb-ch-fat-01-app',
            'pcb-ch-sit-01-app',
            'pcb-ch-uat-01-app',
            'pcb-dev-01-app',
            'pcb-fat-01-app',
            'pcb-sit-01-app',
            'pcb-uat-01-app'
        ]
        print(f"\n   ✅ Using all {len(all_namespaces)} namespaces:")
        for ns in all_namespaces:
            print(f"      - {ns}")
        
        # STEP 3: Pro KAŽDÝ kalendářní den v rozsahu
        print("\n🔄 Filling missing windows for each calendar day...")
        
        added = 0
        current_date = min_date
        
        while current_date <= max_date:
            # Pro každý den: 96 oken (24h × 4 quarters)
            for hour in range(24):
                for quarter in range(4):
                    # Zjisti day_of_week pro tento kalendářní den
                    day_of_week = current_date.weekday()  # Mon=0, Sun=6
                    
                    for ns in all_namespaces:
                        # Zkontroluj jestli kombinace existuje
                        cur.execute("""
                            SELECT COUNT(*) FROM ailog_peak.peak_raw_data
                            WHERE DATE(timestamp) = %s 
                              AND hour_of_day = %s 
                              AND quarter_hour = %s 
                              AND namespace = %s
                        """, (current_date, hour, quarter, ns))
                        
                        if cur.fetchone()[0] == 0:
                            # Missing - insert s mean=0
                            cur.execute("""
                                INSERT INTO ailog_peak.peak_raw_data
                                (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, error_count)
                                VALUES (NOW(), %s, %s, %s, %s, %s)
                            """, (day_of_week, hour, quarter, ns, 0.0))
                            added += 1
            
            current_date += timedelta(days=1)
        
        conn.commit()
        print(f"   ✅ Added {added} missing windows")
        
        # STEP 4: Ověř výsledek
        print("\n✅ Verifying result...")
        
        cur.execute("""
            SELECT 
                COUNT(*) as total_rows,
                COUNT(DISTINCT DATE(timestamp)) as unique_days,
                COUNT(DISTINCT namespace) as unique_namespaces
            FROM ailog_peak.peak_raw_data;
        """)
        total, days, namespaces = cur.fetchone()
        
        print(f"   ✅ Total rows: {total:,}")
        print(f"   ✅ Unique calendar days: {days}")
        print(f"   ✅ Unique namespaces: {namespaces}")
        
        expected = days * 96 * 12  # days × 96 windows/day × 12 NS
        print(f"   Expected: {expected:,} rows ({days} days × 96 × 12)")
        
        if total == expected:
            print(f"   ✅ PERFECT! Všechna data jsou kompletní!")
        else:
            print(f"   ⚠️  Mismatch: máme {total:,}, očekáváno {expected:,}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    fill_missing_windows()
