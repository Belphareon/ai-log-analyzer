#!/usr/bin/env python3
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
    
    # Check table structure
    cur.execute("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'ailog_peak' AND table_name = 'peak_investigation'
        ORDER BY ordinal_position
    """)
    
    print("📋 PEAK_INVESTIGATION TABLE STRUCTURE:")
    print("-" * 80)
    for col_name, data_type, nullable, default in cur.fetchall():
        null_str = "✅ NULL" if nullable == 'YES' else "❌ NOT NULL"
        print(f"  {col_name:25s} {data_type:20s} {null_str:15s} {default or ''}")
    
    # Try to insert a test peak
    print("\n🧪 TESTING INSERT...")
    try:
        cur.execute("""
            INSERT INTO ailog_peak.peak_investigation 
            (timestamp, namespace, app_version, original_value, reference_value, ratio, status, analysis_result)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING peak_investigation_id
        """, (
            '2026-01-09T12:00:00',
            'test-app',
            'test',
            100.0,
            10.0,
            10.0,
            'test',
            'Test peak'
        ))
        
        result = cur.fetchone()
        print(f"✅ Test INSERT successful! ID: {result[0]}")
        conn.rollback()  # Don't commit test
    except Exception as e:
        print(f"❌ Test INSERT failed: {e}")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
