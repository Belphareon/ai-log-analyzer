#!/usr/bin/env python3
"""
Clear all data from peak_statistics table
Quick utility for testing
"""

import psycopg2
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_HOST = os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME', 'ailog_analyzer')
DB_USER = os.getenv('DB_USER', 'ailog_analyzer_user_d1')
DB_PASSWORD = os.getenv('DB_PASSWORD')

if not DB_PASSWORD:
    print("❌ DB_PASSWORD environment variable not set")
    print("   Run: source .env")
    sys.exit(1)

print(f"🗑️  Clearing peak_statistics table...")
print(f"   Host: {DB_HOST}:{DB_PORT}/{DB_NAME}")
print(f"   User: {DB_USER}")
print()

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    
    cur = conn.cursor()
    
    # Get current count
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    before_count = cur.fetchone()[0]
    print(f"📊 Current rows: {before_count}")
    
    # Delete all
    cur.execute("DELETE FROM ailog_peak.peak_statistics")
    deleted = cur.rowcount
    conn.commit()
    
    # Verify
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    after_count = cur.fetchone()[0]
    
    print(f"✅ Deleted: {deleted} rows")
    print(f"📊 Remaining rows: {after_count}")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    sys.exit(1)
