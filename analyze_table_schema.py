#!/usr/bin/env python3
"""Analyze peak_investigation table schema and structure"""

import psycopg2
import os
from datetime import datetime, timedelta
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
print("TABLE STRUCTURE: peak_investigation")
print("=" * 100)

# Get columns
cur.execute("""
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'ailog_peak' AND table_name = 'peak_investigation'
ORDER BY ordinal_position
""")

print("\nColumns:")
for col_name, col_type, nullable in cur.fetchall():
    null_str = "NULL" if nullable == "YES" else "NOT NULL"
    print(f"  {col_name:25s} | {col_type:20s} | {null_str}")

print()
print("=" * 100)
print("PEAK DETECTION SAMPLE (showing actual data to understand structure)")
print("=" * 100)

from_dt = datetime.utcnow() - timedelta(hours=24)
to_dt = datetime.utcnow()

cur.execute("""
SELECT peak_id, error_type, namespace, timestamp, 
       original_value, reference_value, score,
       is_spike, is_burst, ratio,
       timestamp - LAG(timestamp) OVER (PARTITION BY namespace ORDER BY timestamp) as time_delta
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
ORDER BY timestamp DESC
LIMIT 20
""", (from_dt, to_dt))

print("\nRecent peaks (showing chronological pattern):")
print("-" * 100)
for row in cur.fetchall():
    peak_id, error_type, namespace, timestamp, \
    orig_val, ref_val, score, is_spike, is_burst, ratio, time_delta = row
    
    spike_burst = ""
    if is_spike:
        spike_burst = "SPIKE"
    if is_burst:
        spike_burst = "BURST"
    if not spike_burst:
        spike_burst = "-"
    
    time_delta_str = f"{time_delta.total_seconds()/60:.0f}min" if time_delta else "FIRST"
    
    print(f"  ID:{peak_id:10d} | {error_type:25s} | {namespace:20s} | {orig_val:8.2f}/{ref_val:8.2f} | {spike_burst:6s} | {time_delta_str:6s} → {timestamp}")

print()
print("=" * 100)
print("CHECKING: Is each error detection instance getting its own peak_id?")
print("=" * 100)

cur.execute("""
SELECT error_type, namespace, COUNT(*) as total_rows, 
       COUNT(DISTINCT peak_id) as unique_peak_ids,
       COUNT(DISTINCT DATE_TRUNC('minute', timestamp)) as minute_buckets,
       MAX(timestamp) - MIN(timestamp) as time_span
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY error_type, namespace
ORDER BY total_rows DESC
LIMIT 5
""", (from_dt, to_dt))

print("\nTop 5 error_type+namespace combinations:")
for error_type, namespace, total_rows, unique_peak_ids, minute_buckets, time_span in cur.fetchall():
    print(f"  {error_type:30s} | {namespace:20s} | {total_rows:5d} rows | {unique_peak_ids:5d} peak_ids | {minute_buckets:4d} min buckets | span: {time_span}")

print()
print("=" * 100)

conn.close()
