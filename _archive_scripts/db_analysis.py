#!/usr/bin/env python3
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    print("\n" + "="*80)
    print("🔍 DATABASE ANALYSIS - Current State")
    print("="*80)
    
    # 1. Check schemas
    cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%' AND schema_name != 'information_schema'")
    schemas = [row[0] for row in cur.fetchall()]
    print(f"\n📁 SCHEMAS: {schemas if schemas else 'NONE - Need to create!'}")
    
    # 2. Check all tables
    cur.execute("""
        SELECT table_schema, table_name 
        FROM information_schema.tables 
        WHERE table_schema NOT LIKE 'pg_%' AND table_schema != 'information_schema'
        ORDER BY table_schema, table_name
    """)
    tables = cur.fetchall()
    if tables:
        print(f"\n📊 TABLES ({len(tables)}):")
        for schema, table in tables:
            print(f"   - {schema}.{table}")
    else:
        print("\n📊 TABLES: NONE - Need to create tables!")
    
    # 3. If peak_statistics exists, check data
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'ailog_peak' AND table_name = 'peak_statistics'
        )
    """)
    ps_exists = cur.fetchone()[0]
    
    if ps_exists:
        print("\n\n✅ TABLE: ailog_peak.peak_statistics EXISTS")
        
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        row_count = cur.fetchone()[0]
        print(f"   Rows: {row_count}")
        
        if row_count > 0:
            cur.execute("""
                SELECT 
                    COUNT(DISTINCT namespace) as ns_count,
                    COUNT(DISTINCT day_of_week) as days,
                    COUNT(DISTINCT (day_of_week, hour_of_day, quarter_hour)) as time_windows,
                    MIN(value) as min_val,
                    MAX(value) as max_val,
                    ROUND(AVG(value)::numeric, 2) as avg_val
                FROM ailog_peak.peak_statistics
            """)
            stats = cur.fetchone()
            print(f"   Namespaces: {stats[0]}")
            print(f"   Days: {stats[1]}")
            print(f"   Time Windows: {stats[2]}")
            print(f"   Value Range: {stats[3]} - {stats[4]}")
            print(f"   Avg Value: {stats[5]}")
            
            # Check for zeros
            cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE value = 0")
            zeros = cur.fetchone()[0]
            print(f"   Rows with value=0: {zeros}")
    else:
        print("\n\n❌ TABLE: ailog_peak.peak_statistics NOT FOUND")
        print("   Need to create schema and tables")
    
    # 4. Check peak_investigation if exists
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'ailog_peak' AND table_name = 'peak_investigation'
        )
    """)
    pi_exists = cur.fetchone()[0]
    
    if pi_exists:
        print("\n✅ TABLE: ailog_peak.peak_investigation EXISTS")
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_investigation")
        pi_count = cur.fetchone()[0]
        print(f"   Rows: {pi_count}")
    else:
        print("\n❌ TABLE: ailog_peak.peak_investigation NOT FOUND")
    
    print("\n" + "="*80 + "\n")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"\n❌ Error: {e}\n")
    import traceback
    traceback.print_exc()
