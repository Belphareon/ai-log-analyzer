#!/usr/bin/env python3
"""
Check Peak Detection Results

Verifies that peak detection is working correctly by checking:
1. Top 30 highest values in DB
2. Confirming that critical peaks (>500) are properly skipped
3. Calculating the effectiveness of peak detection
"""

import psycopg2
import os
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

    print("=" * 80)
    print("📊 TOP 30 HIGHEST VALUES IN DB (po peak detection)")
    print("=" * 80)

    cur.execute("""
        SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
        FROM ailog_peak.peak_statistics 
        ORDER BY mean_errors DESC
        LIMIT 30
    """)

    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for idx, (day, hour, qtr, ns, mean) in enumerate(cur.fetchall(), 1):
        print(f"{idx:2d}. {day_names[day]} {hour:02d}:{qtr*15:02d} {ns:25s} = {mean:10.1f}")

    print("\n" + "=" * 80)
    print("Kontrola: Jsou tu kritické peaks (>500)?")
    print("=" * 80)

    cur.execute("""
        SELECT namespace, hour_of_day, quarter_hour, COUNT(*) as cnt, MAX(mean_errors) as max_val
        FROM ailog_peak.peak_statistics
        WHERE mean_errors > 500
        GROUP BY namespace, hour_of_day, quarter_hour
        ORDER BY max_val DESC
    """)

    print("\nHodnoty > 500:")
    rows = cur.fetchall()
    if rows:
        for ns, hour, qtr, cnt, max_val in rows:
            print(f"  ❌ {ns:25s} {hour:02d}:{qtr*15:02d}: {max_val:10.1f} (patterns: {cnt})")
        print("\n⚠️  VAROVÁNÍ: Peak detection NEFUNGUJE - kritické peaks jsou v DB!")
    else:
        print("  ✅ ŽÁDNÉ! Peak detection funguje správně!")

    print("\n" + "=" * 80)
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    total = cur.fetchone()[0]
    print(f"Celkem řádků v DB: {total}")

    conn.close()
    
except Exception as e:
    print(f"❌ Chyba: {e}")
    exit(1)
