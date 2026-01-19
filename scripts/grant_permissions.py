#!/usr/bin/env python3
"""
Grant permissions on ailog_peak schema to data user
"""

import os
import psycopg2
import sys

# Load .env file manually
def load_env():
    env = {}
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line and not line.startswith('#') and '=' in line:
                    key, val = line.split('=', 1)
                    env[key.strip()] = val.strip()
    except FileNotFoundError:
        pass
    return env

env = load_env()
DB_HOST = env.get('DB_HOST', os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'))
DB_PORT = int(env.get('DB_PORT', os.getenv('DB_PORT', 5432)))
DB_NAME = env.get('DB_NAME', os.getenv('DB_NAME', 'ailog_analyzer'))
DB_USER = env.get('DB_DDL_USER', os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1'))
DB_PASSWORD = env.get('DB_DDL_PASSWORD', os.getenv('DB_DDL_PASSWORD'))  # Required: Set in .env file

print("🔐 Granting permissions on ailog_peak schema...")

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
    cursor = conn.cursor()
    print("✅ Connected to PostgreSQL")
    
    # Set DDL role
    cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
    print("✅ DDL role set")
    
    # Grant schema usage
    cursor.execute("GRANT USAGE ON SCHEMA ailog_peak TO ailog_analyzer_user_d1;")
    print("✅ Granted USAGE on schema ailog_peak")
    
    # Grant table permissions
    cursor.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1;")
    print("✅ Granted SELECT, INSERT, UPDATE, DELETE on all tables")
    
    # Grant sequence permissions (if any)
    cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1;")
    print("✅ Granted USAGE, SELECT on all sequences")
    
    # Make sure future objects also get permissions
    cursor.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA ailog_peak GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ailog_analyzer_user_d1;")
    print("✅ Granted default privileges for future tables")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    print()
    print("✅ Permissions granted successfully!")
    print("   ailog_analyzer_user_d1 can now access ailog_peak schema")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
