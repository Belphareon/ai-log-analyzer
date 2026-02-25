#!/usr/bin/env python3
"""Verify detection results against database - detailed check"""

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
print("VERIFICATION: Peak Detection Results vs Database")
print("=" * 100)
print()

# Check last 24h
from_dt = datetime.now(timezone.utc) - timedelta(hours=24)
to_dt = datetime.now(timezone.utc)

print(f"Time window: {from_dt.strftime('%Y-%m-%d %H:%M %Z')} → {to_dt.strftime('%Y-%m-%d %H:%M %Z')}")
print()

# 1. Check baseline_mean is populated
print("-" * 100)
print("1. BASELINE_MEAN VALUES CHECK")
print("-" * 100)
cur.execute("""
SELECT 
  COUNT(*) as total,
  COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) as with_baseline,
  COUNT(CASE WHEN baseline_mean > 0 THEN 1 END) as with_nonzero_baseline,
  AVG(baseline_mean) as avg_baseline,
  MIN(baseline_mean) as min_baseline,
  MAX(baseline_mean) as max_baseline
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
""", (from_dt, to_dt))

total, with_bl, with_nonzero, avg_bl, min_bl, max_bl = cur.fetchone()
print(f"Total detection records: {total:,}")
print(f"With baseline_mean values: {with_bl:,} ({100*with_bl/total:.1f}%)")
print(f"With baseline_mean > 0: {with_nonzero:,} ({100*with_nonzero/total:.1f}%)")
if avg_bl:
    print(f"Average baseline: {avg_bl}")
    print(f"Min baseline: {min_bl} | Max baseline: {max_bl}")
print()

# 2. Spike detection
print("-" * 100)
print("2. SPIKE DETECTION VERIFICATION")
print("-" * 100)
cur.execute("""
SELECT 
  COUNT(*) as total_spikes,
  COUNT(DISTINCT error_type) as error_types,
  COUNT(DISTINCT namespace) as namespaces,
  COUNT(DISTINCT DATE(timestamp)) as days_with_spikes,
  AVG(original_value) as avg_spike_value,
  MAX(original_value) as max_spike_value
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_spike = true
""", (from_dt, to_dt))

total_spikes, spike_types, spike_ns, spike_days, avg_spike, max_spike = cur.fetchone()
print(f"Total spikes detected: {total_spikes}")
print(f"Error types with spikes: {spike_types}")
print(f"Namespaces with spikes: {spike_ns}")
print(f"Days with spike detections: {spike_days}")
if total_spikes > 0:
    print(f"Average spike value: {avg_spike:.2f}")
    print(f"Max spike value: {max_spike:.2f}")
print()

# 3. Burst detection
print("-" * 100)
print("3. BURST DETECTION VERIFICATION")
print("-" * 100)
cur.execute("""
SELECT 
  COUNT(*) as total_bursts,
  COUNT(DISTINCT error_type) as error_types,
  COUNT(DISTINCT namespace) as namespaces,
  COUNT(DISTINCT DATE(timestamp)) as days_with_bursts,
  AVG(original_value) as avg_burst_value,
  MAX(original_value) as max_burst_value
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_burst = true
""", (from_dt, to_dt))

total_bursts, burst_types, burst_ns, burst_days, avg_burst, max_burst = cur.fetchone()
print(f"Total bursts detected: {total_bursts}")
print(f"Error types with bursts: {burst_types}")
print(f"Namespaces with bursts: {burst_ns}")
print(f"Days with burst detections: {burst_days}")
if total_bursts > 0:
    print(f"Average burst value: {avg_burst:.2f}")
    print(f"Max burst value: {max_burst:.2f}")
print()

# 4. Sample spikes and bursts
print("-" * 100)
print("4. SAMPLE DETECTIONS")
print("-" * 100)

print("\nTop 5 SPIKES (by original_value):")
cur.execute("""
SELECT timestamp, namespace, error_type, original_value, baseline_mean, is_spike, is_burst
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_spike = true
ORDER BY original_value DESC
LIMIT 5
""", (from_dt, to_dt))

spikes = cur.fetchall()
if spikes:
    for ts, ns, et, orig, baseline, spike, burst in spikes:
        print(f"  {ts} | {ns:25s} | {et:30s} | Orig:{orig:8.2f} | Base:{baseline:8.2f if baseline else 'NULL':>8s}")
else:
    print("  (none found)")

print("\nTop 5 BURSTS (by original_value):")
cur.execute("""
SELECT timestamp, namespace, error_type, original_value, baseline_mean, is_spike, is_burst
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_burst = true
ORDER BY original_value DESC
LIMIT 5
""", (from_dt, to_dt))

bursts = cur.fetchall()
if bursts:
    for ts, ns, et, orig, baseline, spike, burst in bursts:
        print(f"  {ts} | {ns:25s} | {et:30s} | Orig:{orig:8.2f} | Base:{baseline:8.2f if baseline else 'NULL':>8s}")
else:
    print("  (none found)")

print()
print("=" * 100)
if total_spikes > 0 or total_bursts > 0:
    print("✅ SPIKE/BURST DETECTION WORKING")
    print(f"   {total_spikes} spikes + {total_bursts} bursts = {total_spikes + total_bursts} anomalies detected")
else:
    print("❌ NO SPIKE/BURST DETECTIONS FOUND - Something is wrong")
print("=" * 100)

conn.close()
