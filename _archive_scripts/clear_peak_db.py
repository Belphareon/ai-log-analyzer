#!/usr/bin/env python3
"""
Clear all data from peak_statistics table
Quick utility for testing and re-ingestion
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

def clear_peak_statistics():
    """Delete all rows from peak_statistics table"""
    
    print(f"🗑️  Clearing peak_statistics table...")
    print(f"📍 Database: {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Get count before delete
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        before_count = cur.fetchone()[0]
        print(f"📊 Rows before delete: {before_count}")
        
        # Delete all rows
        cur.execute("DELETE FROM ailog_peak.peak_statistics")
        conn.commit()
        
        # Verify deletion
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        after_count = cur.fetchone()[0]
        
        print(f"✅ Table cleared successfully")
        print(f"📊 Rows deleted: {before_count}")
        print(f"📊 Rows remaining: {after_count}")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    success = clear_peak_statistics()
    sys.exit(0 if success else 1)
