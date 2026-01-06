#!/usr/bin/env python3
"""
TRUNCATE and clean re-ingest - starts completely fresh
"""
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Use DDL user for TRUNCATE operation (requires elevated permissions)
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

print("⚠️  TRUNCATE PEAK STATISTICS - VŠECHNA DATA BUDOU SMAZÁNA!")
print()

response = input("Opravdu chceš vymazat VŠECHNY řádky? (yes/no): ")
if response.lower() != 'yes':
    print("Zrušeno.")
    exit(0)

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

try:
    print("🗑️  TRUNCATING peak_statistics...")
    cur.execute("TRUNCATE TABLE ailog_peak.peak_statistics")
    conn.commit()
    
    # Verify
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    count = cur.fetchone()[0]
    print(f"✅ TRUNCATED - Rows remaining: {count}")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    conn.rollback()
finally:
    cur.close()
    conn.close()

print()
print("NEXT: Run batch ingest fresh:")
print("  python clear_peak_db.py")
print("  for file in /tmp/peak_fixed_*.txt; do python ingest_from_log.py --input \"$file\"; done")
