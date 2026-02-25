#!/usr/bin/env python3
"""Debug baseline_mean issue - why is it only in 12.7% of records?"""

import psycopg2
import os
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    port=int(os.getenv('DB_PORT', 5432)),
    database=os.getenv('DB_NAME', 'ailog_analyzer'),
    user=os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute('SET search_path = ailog_peak;')

print("=" * 100)
print("DEBUG: baseline_mean Distribution")
print("=" * 100)
print()

from_dt = datetime.now(timezone.utc) - timedelta(hours=24)
to_dt = datetime.now(timezone.utc)

# Check by detection_method
print("Breakdown by detection_method:")
cur.execute("""
SELECT 
  detection_method,
  COUNT(*) as total,
  COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) as with_baseline,
  COUNT(CASE WHEN baseline_mean > 0 THEN 1 END) as nonzero
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY detection_method
ORDER BY total DESC
""", (from_dt, to_dt))

for method, total, with_bl, nonzero in cur.fetchall():
    pct = 100 * with_bl / total if total > 0 else 0
    print(f"  {method:20s} | {total:5,d} | baseline: {with_bl:5,d} ({pct:5.1f}%) | nonzero: {nonzero:5,d}")

print()
print("Sample records with baseline_mean=NULL:")
cur.execute("""
SELECT timestamp, detection_method, original_value, reference_value, baseline_mean, is_spike, is_burst
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND baseline_mean IS NULL
LIMIT 5
""", (from_dt, to_dt))

for ts, method, orig, ref, baseline, spike, burst in cur.fetchall():
    print(f"  {ts} | {method:20s} | Orig:{orig:8.2f} Ref:{ref:8.2f} Base:{baseline}")

print()
print("Sample records WITH baseline_mean:")
cur.execute("""
SELECT timestamp, detection_method, original_value, reference_value, baseline_mean, is_spike, is_burst
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND baseline_mean IS NOT NULL
LIMIT 5
""", (from_dt, to_dt))

for ts, method, orig, ref, baseline, spike, burst in cur.fetchall():
    print(f"  {ts} | {method:20s} | Orig:{orig:8.2f} Ref:{ref:8.2f} Base:{baseline:8.2f}")

print()
conn.close()
