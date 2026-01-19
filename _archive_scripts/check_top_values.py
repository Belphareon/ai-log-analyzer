#!/usr/bin/env python3
import os, psycopg2
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
    
    print("=" * 100)
    print("🔍 TOP 30 HIGHEST VALUES IN PEAK_STATISTICS")
    print("=" * 100)
    
    cur.execute("""
        SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors
        FROM ailog_peak.peak_statistics 
        ORDER BY mean_errors DESC
        LIMIT 30
    """)
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for i, (day, hour, quarter, ns, mean, stddev) in enumerate(cur.fetchall(), 1):
        time_str = f"{day_names[day]} {hour:02d}:{quarter*15:02d}"
        print(f"{i:2d}. {time_str:15s} {ns:30s} | mean={mean:10.1f}, stddev={stddev:8.1f}")
    
    print("\n" + "=" * 100)
    print("�� PEAKS LOGGED IN peak_investigation")
    print("=" * 100)
    
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_investigation")
    peak_count = cur.fetchone()[0]
    print(f"Total peaks logged: {peak_count}")
    
    if peak_count > 0:
        cur.execute("""
            SELECT id, day_of_week, hour_of_day, quarter_hour, namespace, 
                   original_value, reference_value, ratio
            FROM ailog_peak.peak_investigation 
            ORDER BY ratio DESC
            LIMIT 15
        """)
        
        print(f"\nTop 15 peaks by ratio:")
        for peak_id, day, hour, quarter, ns, orig, ref, ratio in cur.fetchall():
            time_str = f"{day_names[day]} {hour:02d}:{quarter*15:02d}"
            print(f"  [{peak_id:4d}] {time_str:15s} {ns:30s} | orig={orig:10.1f} → ref={ref:8.1f} ({ratio:7.1f}x)")
    
    cur.close()
    conn.close()
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
