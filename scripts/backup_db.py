#!/usr/bin/env python3
"""
Backup peak_statistics table to CSV
"""

import sys
import os
import psycopg2
import csv
from datetime import datetime
from dotenv import load_dotenv

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


def backup_db():
    """Backup peak_statistics to CSV"""
    
    print("=" * 80)
    print("💾 Backing up peak_statistics table...")
    print("=" * 80)
    print()
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return None
    
    try:
        # Get all data
        cur.execute("""
            SELECT day_of_week, hour_of_day, quarter_hour, namespace, 
                   mean_errors, stddev_errors, samples_count, last_updated
            FROM ailog_peak.peak_statistics 
            ORDER BY day_of_week, hour_of_day, quarter_hour, namespace
        """)
        
        rows = cur.fetchall()
        total = len(rows)
        print(f"📊 Fetched {total} rows from database")
        
        # Create backup file
        backup_file = f"/tmp/backup_peak_statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(backup_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['day_of_week', 'hour_of_day', 'quarter_hour', 'namespace', 
                           'mean_errors', 'stddev_errors', 'samples_count', 'last_updated'])
            writer.writerows(rows)
        
        print(f"✅ Backup saved to: {backup_file}")
        
        cur.close()
        conn.close()
        return backup_file
        
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        cur.close()
        conn.close()
        return None


def main():
    backup_file = backup_db()
    
    if backup_file:
        print()
        print("=" * 80)
        print(f"✅ Backup complete: {backup_file}")
        print("=" * 80)
        return 0
    else:
        print()
        print("❌ Backup failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
