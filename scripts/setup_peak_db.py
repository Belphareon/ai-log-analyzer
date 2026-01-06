#!/usr/bin/env python3
"""
Quick Setup: Create ailog_peak schema and peak_statistics table
Uses SET ROLE to handle DDL operations
"""

import psycopg2
import os
import sys

DB_HOST = os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME', 'ailog_analyzer')
DB_USER = os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1')
DB_PASSWORD = os.getenv('DB_DDL_PASSWORD')  # Required: Set in .env file

print("🔐 Database Setup: Creating ailog_peak schema and tables")
print(f"   Host: {DB_HOST}:{DB_PORT}/{DB_NAME}")
print(f"   User: {DB_USER}")
print()

try:
    # Connect
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
    cursor = conn.cursor()
    print("✅ Connected to PostgreSQL")
    
    # Set role for DDL
    print("🔑 Setting DDL role...")
    try:
        cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
        print("✅ DDL role set")
        ddl_role_available = True
    except psycopg2.Error as e:
        print(f"⚠️  DDL role not available: {e}")
        print("   Will create in public schema instead")
        ddl_role_available = False
    
    schema_name = "public" if not ddl_role_available else "ailog_peak"
    
    # Create schema if DDL role available
    if ddl_role_available:
        print("📁 Creating schema ailog_peak...")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS ailog_peak;")
        conn.commit()
        print("✅ Schema created")
    
    # Create peak_statistics table
    print(f"📊 Creating table {schema_name}.peak_statistics...")
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {schema_name}.peak_statistics (
            day_of_week INT NOT NULL,
            hour_of_day INT NOT NULL,
            quarter_hour INT NOT NULL,
            namespace VARCHAR(255) NOT NULL,
            
            mean_errors FLOAT,
            stddev_errors FLOAT,
            samples_count INT DEFAULT 0,
            last_updated TIMESTAMP DEFAULT NOW(),
            
            PRIMARY KEY (day_of_week, hour_of_day, quarter_hour, namespace)
        );
    """)
    conn.commit()
    print("✅ Table created")
    
    # Verify
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    count = cursor.fetchone()[0]
    print(f"✅ Verification: peak_statistics table has {count} rows")
    
    cursor.close()
    conn.close()
    
    print()
    print("✅ Setup complete! Ready for data collection")
    print("   Next: python3 collect_historical_peak_data.py")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
