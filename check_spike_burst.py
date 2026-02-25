#!/usr/bin/env python3
"""Check spike/burst detection accuracy"""

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

from_dt = datetime.utcnow() - timedelta(hours=24)
to_dt = datetime.utcnow()

print("=" * 120)
print("SPIKE/BURST DETECTION ANALYSIS (Last 24h)")
print("=" * 120)
print()

# Categories
cur.execute("""
WITH detection_categories AS (
  SELECT 
    COUNT(*) FILTER (WHERE is_spike) as spike_count,
    COUNT(*) FILTER (WHERE is_burst) as burst_count,
    COUNT(*) FILTER (WHERE is_spike OR is_burst) as anomaly_count,
    COUNT(*) as total_count,
    COUNT(DISTINCT error_type) as error_types,
    COUNT(DISTINCT namespace) as namespaces
  FROM peak_investigation
  WHERE timestamp >= %s AND timestamp <= %s
)
SELECT * FROM detection_categories
""", (from_dt, to_dt))

spike_count, burst_count, anomaly_count, total_count, error_types, namespaces = cur.fetchone()

print(f"Detection Breakdown:")
print(f"  Total detection points: {total_count:,}")
print(f"  Spike detections (is_spike=true): {spike_count:,} ({100*spike_count/total_count:.1f}%)")
print(f"  Burst detections (is_burst=true): {burst_count:,} ({100*burst_count/total_count:.1f}%)")
print(f"  Total anomalies (spike OR burst): {anomaly_count:,} ({100*anomaly_count/total_count:.1f}%)")
print(f"  Normal variance: {total_count - anomaly_count:,} ({100*(total_count-anomaly_count)/total_count:.1f}%)")
print()

# By namespace
print("-" * 120)
print("Anomaly Detection by Namespace:")
print("-" * 120)
cur.execute("""
SELECT 
  namespace,
  COUNT(*) as total_points,
  COUNT(*) FILTER (WHERE is_spike) as spikes,
  COUNT(*) FILTER (WHERE is_burst) as bursts,
  COUNT(*) FILTER (WHERE is_spike OR is_burst) as anomalies,
  ROUND(100.0 * COUNT(*) FILTER (WHERE is_spike OR is_burst) / COUNT(*), 1) as anomaly_pct,
  COUNT(DISTINCT error_type) as error_types
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY namespace
ORDER BY anomalies DESC
""", (from_dt, to_dt))

for ns, total, spikes, bursts, anomalies, anomaly_pct, error_types in cur.fetchall():
    print(f"  {ns:25s} | {total:5,d} points | {spikes:4d} spikes | {bursts:4d} bursts | {anomalies:5d} total ({anomaly_pct:5.1f}%) | {error_types:2d} types")

print()

# By error type
print("-" * 120)
print("Top Error Types with Anomalies:")
print("-" * 120)
cur.execute("""
SELECT 
  error_type,
  COUNT(*) as total_points,
  COUNT(*) FILTER (WHERE is_spike) as spikes,
  COUNT(*) FILTER (WHERE is_burst) as bursts,
  COUNT(*) FILTER (WHERE is_spike OR is_burst) as anomalies,
  ROUND(100.0 * COUNT(*) FILTER (WHERE is_spike OR is_burst) / COUNT(*), 1) as anomaly_pct,
  COUNT(DISTINCT namespace) as namespaces
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY error_type
ORDER BY anomalies DESC
LIMIT 15
""", (from_dt, to_dt))

for error_type, total, spikes, bursts, anomalies, anomaly_pct, ns_count in cur.fetchall():
    print(f"  {error_type:30s} | {total:5,d} points | {spikes:4d} spikes | {bursts:4d} bursts | {anomalies:5d} total ({anomaly_pct:5.1f}%) | {ns_count} ns")

print()

# Sample anomalies - show actual spike/burst examples
print("-" * 120)
print("Sample SPIKE Detections (original_value exceeds reference_value significantly):")
print("-" * 120)
cur.execute("""
SELECT 
  timestamp, namespace, error_type, original_value, reference_value, ratio, score
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_spike = true
ORDER BY original_value DESC
LIMIT 10
""", (from_dt, to_dt))

for ts, ns, error_type, orig, ref, ratio, score in cur.fetchall():
    print(f"  {ts} | {ns:20s} | {error_type:25s} | O:{orig:8.2f} R:{ref:8.2f} | Ratio:{ratio:6.2f}x | Score:{score:6.1f}")

print()

print("-" * 120)
print("Sample BURST Detections:")
print("-" * 120)
cur.execute("""
SELECT 
  timestamp, namespace, error_type, original_value, reference_value, ratio, score
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_burst = true
ORDER BY original_value DESC
LIMIT 10
""", (from_dt, to_dt))

for ts, ns, error_type, orig, ref, ratio, score in cur.fetchall():
    print(f"  {ts} | {ns:20s} | {error_type:25s} | O:{orig:8.2f} R:{ref:8.2f} | Ratio:{ratio:6.2f}x | Score:{score:6.1f}")

print()
print("=" * 120)
if anomaly_count > 0:
    print(f"✅ PEAK DETECTION WORKING: {anomaly_count} anomalies detected (spikes + bursts)")
else:
    print(f"⚠️  NO ANOMALIES DETECTED - Check if detection thresholds are too high")
print("=" * 120)

conn.close()
