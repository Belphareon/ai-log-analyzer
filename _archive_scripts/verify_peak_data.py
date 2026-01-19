#!/usr/bin/env python3
"""
Verify collected peak data in database
"""

import psycopg2
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')  # Required: Set in .env file
}

print("🔍 Verifying peak data in database...")
print()

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 1. Total row count
    cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    total_rows = cursor.fetchone()[0]
    print(f"📊 Total rows: {total_rows}")
    print()
    
    # 2. Distinct namespaces
    cursor.execute("SELECT DISTINCT namespace FROM ailog_peak.peak_statistics ORDER BY namespace")
    namespaces = [row[0] for row in cursor.fetchall()]
    print(f"📦 Distinct namespaces ({len(namespaces)}):")
    for ns in namespaces:
        print(f"   - {ns}")
    print()
    
    # 3. Sample statistics for each namespace
    print("📈 Sample statistics (first 5 rows per namespace):")
    print()
    for ns in namespaces[:3]:  # Show first 3 namespaces
        cursor.execute("""
            SELECT day_of_week, hour_of_day, quarter_hour, 
                   mean_errors, stddev_errors, samples_count, last_updated
            FROM ailog_peak.peak_statistics
            WHERE namespace = %s
            ORDER BY day_of_week, hour_of_day, quarter_hour
            LIMIT 5
        """, (ns,))
        
        rows = cursor.fetchall()
        print(f"   Namespace: {ns}")
        print(f"   {'Day':<4} {'Hour':<5} {'Qtr':<4} {'Mean':<8} {'StdDev':<8} {'Samples':<8} {'Updated'}")
        print(f"   {'-'*70}")
        
        for row in rows:
            day, hour, qtr, mean_err, std_err, samples, updated = row
            day_name = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][day]
            print(f"   {day_name:<4} {hour:02d}:00 Q{qtr}  {mean_err:>7.2f}  {std_err:>7.2f}  {samples:>7}   {updated.strftime('%Y-%m-%d %H:%M')}")
        print()
    
    # 4. Statistics by day of week
    cursor.execute("""
        SELECT day_of_week, COUNT(*) as cnt, 
               AVG(mean_errors) as avg_mean, AVG(stddev_errors) as avg_std
        FROM ailog_peak.peak_statistics
        GROUP BY day_of_week
        ORDER BY day_of_week
    """)
    
    print("📅 Statistics by day of week:")
    print(f"   {'Day':<10} {'Count':<8} {'Avg Mean':<12} {'Avg StdDev'}")
    print(f"   {'-'*50}")
    
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    for row in cursor.fetchall():
        day_idx, cnt, avg_mean, avg_std = row
        print(f"   {days[day_idx]:<10} {cnt:<8} {avg_mean:>11.2f}  {avg_std:>11.2f}")
    print()
    
    # 5. Recent updates
    cursor.execute("""
        SELECT namespace, COUNT(*) as cnt, MAX(last_updated) as latest
        FROM ailog_peak.peak_statistics
        GROUP BY namespace
        ORDER BY latest DESC
    """)
    
    print("🕐 Most recent updates:")
    print(f"   {'Namespace':<30} {'Count':<8} {'Last Updated'}")
    print(f"   {'-'*60}")
    
    for row in cursor.fetchall():
        ns, cnt, latest = row
        print(f"   {ns:<30} {cnt:<8} {latest.strftime('%Y-%m-%d %H:%M:%S')}")
    
    cursor.close()
    conn.close()
    
    print()
    print("✅ Verification complete!")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
