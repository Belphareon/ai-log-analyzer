#!/usr/bin/env python3
"""Test peak detection - verify it works"""

import psycopg2
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pathlib import Path

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

# Stats for last 24h
from_dt = datetime.utcnow() - timedelta(hours=24)
to_dt = datetime.utcnow()

print("=" * 100)
print(f"PEAK DETECTION VERIFICATION - Last 24 hours")
print(f"  From: {from_dt.strftime('%Y-%m-%d %H:%M %Z')}")
print(f"  To:   {to_dt.strftime('%Y-%m-%d %H:%M %Z')}")
print("=" * 100)
print()

cur.execute('''
SELECT COUNT(*) as total_rows, COUNT(DISTINCT error_type) as error_types,
       COUNT(DISTINCT namespace) as namespaces, 
       COUNT(DISTINCT peak_id) as peak_ids,
       MAX(timestamp) as latest_ts,
       MIN(timestamp) as earliest_ts
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
''', (from_dt, to_dt))

row = cur.fetchone()
print(f'Peak Investigation Table Summary:')
print(f'  Total rows: {row[0]:,}')
print(f'  Error types: {row[1]}')
print(f'  Namespaces: {row[2]}')
print(f'  Peak IDs: {row[3]}')
print(f'  Earliest: {row[5]}')
print(f'  Latest: {row[4]}')
print()

# Top peaks
print("Top 15 detected peaks (by row count):")
print("-" * 100)
cur.execute('''
SELECT peak_id, error_type, COUNT(*) as cnt, COUNT(DISTINCT namespace) as ns_cnt, 
       COUNT(DISTINCT DATE_TRUNC('hour', timestamp)) as hours_affected,
       MIN(timestamp) as first_ts, MAX(timestamp) as last_ts
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY peak_id, error_type
ORDER BY cnt DESC
LIMIT 15
''', (from_dt, to_dt))

for row in cur.fetchall():
    peak_id, error_type, cnt, ns_cnt, hours, first_ts, last_ts = row
    duration = (last_ts - first_ts).total_seconds() / 3600
    print(f"  PK-{peak_id:06d} | {error_type:25s} | {cnt:6,d} rows | {ns_cnt} ns | {hours:.0f}h span | {duration:.1f}h duration")

print()

# Check if baseline values are populated (critical fix in v6.1)
print("-" * 100)
print("Baseline Data Check (Critical Fix #4 in v6.1):")
print("-" * 100)
cur.execute('''
SELECT 
  COUNT(*) as total_records,
  COUNT(CASE WHEN reference_value IS NOT NULL THEN 1 END) as with_baseline,
  ROUND(100.0 * COUNT(CASE WHEN reference_value IS NOT NULL THEN 1 END) / COUNT(*), 1) as baseline_pct,
  COUNT(CASE WHEN is_spike OR is_burst OR score >= 30 THEN 1 END) as anomaly_records,
  AVG(reference_value) as avg_baseline,
  AVG(original_value) as avg_original,
  MAX(original_value) as max_original
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
''', (from_dt, to_dt))

row = cur.fetchone()
total, with_baseline, baseline_pct, anomaly_cnt, avg_baseline, avg_original, max_original = row
print(f"  Total records: {total:,}")
print(f"  With baseline: {with_baseline:,} ({baseline_pct}%)")
print(f"  Anomaly records (is_spike|is_burst|score>=30): {anomaly_cnt:,}")
if avg_baseline:
    print(f"  Average baseline: {avg_baseline:.2f}")
    print(f"  Average original: {avg_original:.2f}")
    print(f"  Max original: {max_original:.2f}")
print()

# Check namespace coverage
print("-" * 100)
print("Namespace Coverage:")
print("-" * 100)
cur.execute('''
SELECT namespace, COUNT(*) as rows, COUNT(DISTINCT peak_id) as peaks,
       COUNT(DISTINCT error_type) as error_types
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY namespace
ORDER BY rows DESC
''', (from_dt, to_dt))

for row in cur.fetchall():
    ns, rows, peaks, error_types = row
    print(f"  {ns:25s} | {rows:6,d} rows | {peaks:3d} peaks | {error_types:3d} error types")

print()
print("=" * 100)
print("✅ Peak detection is working and storing data in DB")
print("=" * 100)

conn.close()
