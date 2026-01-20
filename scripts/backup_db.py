#!/usr/bin/env python3
"""
Backup ailog_peak schema tables
"""

import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv('DB_HOST')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

BACKUP_DIR = '/tmp'
TIMESTAMP = datetime.now().strftime('%Y%m%d_%H%M%S')

print("="*70)
print("💾 Backup ailog_peak schema")
print("="*70)

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    cur = conn.cursor()
    
    # Backup each table
    tables = {
        'peak_raw_data': f'{BACKUP_DIR}/backup_peak_raw_data_{TIMESTAMP}.sql',
        'aggregation_data': f'{BACKUP_DIR}/backup_aggregation_data_{TIMESTAMP}.sql',
        'peak_investigation': f'{BACKUP_DIR}/backup_peak_investigation_{TIMESTAMP}.sql'
    }
    
    print(f"\nHost: {DB_HOST}")
    print(f"Database: {DB_NAME}")
    print(f"Schema: ailog_peak")
    print(f"Timestamp: {TIMESTAMP}\n")
    
    # Get row counts
    print("📊 Table info:")
    for table in tables.keys():
        cur.execute(f"SELECT COUNT(*) FROM ailog_peak.{table}")
        count = cur.fetchone()[0]
        print(f"   {table}: {count:,} rows")
    
    # Backup using pg_dump
    for table, filepath in tables.items():
        print(f"\n💾 Backing up {table}...")
        cmd = f"pg_dump -h {DB_HOST} -U {DB_USER} -d {DB_NAME} -t ailog_peak.{table} --no-privileges --no-owner > {filepath} 2>/dev/null"
        result = os.system(f"PGPASSWORD='{DB_PASSWORD}' {cmd}")
        
        if result == 0:
            size = os.path.getsize(filepath) / 1024
            print(f"   ✅ Saved ({size:.1f} KB)")
        else:
            print(f"   ❌ Failed to backup {table}")
    
    print("\n" + "="*70)
    print("✅ Backup complete!")
    print(f"   Files: /tmp/backup_*_{TIMESTAMP}.sql")
    print("="*70)
    
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
