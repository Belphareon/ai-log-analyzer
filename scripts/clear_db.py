#!/usr/bin/env python3
"""
Clear all peak tables (INIT phase redo)
"""

import os
import sys
from dotenv import load_dotenv
import psycopg2

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


def main():
    print("=" * 80)
    print("🗑️  Clear Peak Tables (INIT Phase Redo)")
    print("=" * 80)
    
    # Connect to DB
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1
    
    # Check before delete
    print("\n📊 BEFORE clearing:")
    try:
        for t in ['peak_raw_data', 'aggregation_data', 'peak_investigation']:
            cur.execute(f'SELECT COUNT(*) FROM ailog_peak.{t}')
            count = cur.fetchone()[0]
            print(f"   {t:30s}: {count:8,} rows")
    except Exception as e:
        print(f"⚠️  Error reading counts: {e}")
    
    # Clear
    print("\n🗑️  Clearing tables...")
    try:
        tables = [
            'peak_raw_data',
            'aggregation_data', 
            'peak_investigation'
        ]
        
        for t in tables:
            cur.execute(f'DELETE FROM ailog_peak.{t};')
            count = cur.rowcount
            print(f"   ✅ Deleted {count:8,} rows from {t}")
        
        conn.commit()
    except Exception as e:
        print(f"❌ Error clearing tables: {e}")
        conn.rollback()
        conn.close()
        return 1
    
    # Check after delete
    print("\n📊 AFTER clearing:")
    try:
        for t in ['peak_raw_data', 'aggregation_data', 'peak_investigation']:
            cur.execute(f'SELECT COUNT(*) FROM ailog_peak.{t}')
            count = cur.fetchone()[0]
            print(f"   {t:30s}: {count:8,} rows")
    except Exception as e:
        print(f"⚠️  Error reading counts: {e}")
    
    conn.close()
    print("\n" + "=" * 80)
    print("✅ All tables cleared - ready for INIT phase redo")
    print("=" * 80)
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
