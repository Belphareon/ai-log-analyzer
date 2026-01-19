#!/usr/bin/env python3
"""Quick query to show top values in DB"""
import psycopg2, os
from dotenv import load_dotenv

load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

print("="*70)
print("TOP 20 HIGHEST VALUES IN DB")
print("="*70)
cur.execute("""
    SELECT namespace, day_of_week, hour_of_day, quarter_hour, mean_errors 
    FROM ailog_peak.peak_statistics 
    ORDER BY mean_errors DESC 
    LIMIT 20
""")
days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
for ns, day, hr, qtr, val in cur.fetchall():
    print(f"  {days[day]} {hr:02d}:{qtr*15:02d} {ns:25s} = {val:8.1f}")

print("\n" + "="*70)
print("DB STATISTICS")
print("="*70)
cur.execute("SELECT COUNT(*), MAX(mean_errors), AVG(mean_errors) FROM ailog_peak.peak_statistics")
count, max_val, avg_val = cur.fetchone()
print(f"  Total rows: {count}")
print(f"  Max value:  {max_val:.1f}")
print(f"  Avg value:  {avg_val:.1f}")

conn.close()
