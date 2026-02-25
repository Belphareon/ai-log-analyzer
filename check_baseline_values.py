#!/usr/bin/env python3
"""Check why spike detection isn't working - analyze baseline values"""

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
print("BASELINE VALUES ANALYSIS (for Spike Detection)")
print("=" * 120)
print()

# Check baseline_mean distribution
cur.execute("""
SELECT 
  COUNT(*) as total_records,
  COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) as with_baseline_mean,
  COUNT(CASE WHEN baseline_mean = 0 THEN 1 END) as zero_baseline_mean,
  COUNT(CASE WHEN baseline_mean IS NULL OR baseline_mean = 0 THEN 1 END) as no_baseline_mean,
  COUNT(CASE WHEN same_day_refs_mean IS NOT NULL THEN 1 END) as with_same_day_refs,
  AVG(baseline_mean) as avg_baseline,
  MIN(baseline_mean) as min_baseline,
  MAX(baseline_mean) as max_baseline
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
""", (from_dt, to_dt))

row = cur.fetchone()
total, with_mean, zero_mean, no_baseline, with_same_day, avg_bl, min_bl, max_bl = row

print(f"Baseline Mean Statistics:")
print(f"  Total records: {total:,}")
print(f"  Records with baseline_mean: {with_mean:,} ({100*with_mean/total:.1f}%)")
print(f"  Records with baseline_mean=0: {zero_mean:,} ({100*zero_mean/total:.1f}%)")
print(f"  Records without/zero baseline: {no_baseline:,} ({100*no_baseline/total:.1f}%)")
print(f"  Records with same_day_refs_mean: {with_same_day:,} ({100*with_same_day/total:.1f}%)")
print(f"  Average baseline_mean: {avg_bl:.2f}" if avg_bl else "  Average baseline_mean: None")
print()

# Compare original_value vs baseline_mean
cur.execute("""
SELECT 
  COUNT(*) as total,
  COUNT(CASE WHEN original_value > baseline_mean * 3.0 THEN 1 END) as spike_threshold_3x,
  COUNT(CASE WHEN original_value > baseline_mean * 2.0 THEN 1 END) as spike_threshold_2x,
  COUNT(CASE WHEN original_value > baseline_mean * 1.5 THEN 1 END) as spike_threshold_15x,
  COUNT(CASE WHEN baseline_mean IS NULL OR baseline_mean = 0 THEN 1 END) as no_baseline
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
  AND original_value IS NOT NULL
""", (from_dt, to_dt))

total, x3, x2, x15, no_bl = cur.fetchone()
print(f"Spike Detection Potential (if using baseline_mean):")
print(f"  Total records: {total:,}")
print(f"  Would be spike (3x threshold): {x3:,} ({100*x3/total:.1f}%)")
print(f"  Would be spike (2x threshold): {x2:,} ({100*x2/total:.1f}%)")
print(f"  Would be spike (1.5x threshold): {x15:,} ({100*x15/total:.1f}%)")
print(f"  (No baseline to compare): {no_bl:,} ({100*no_bl/total:.1f}%)")
print()

# Check values that ARE being marked as burst
print("-" * 120)
print("For comparison - BURST detections that are working:")
print("-" * 120)
cur.execute("""
SELECT 
  COUNT(*) as total_bursts,
  AVG(original_value) as avg_orig,
  AVG(reference_value) as avg_ref,
  AVG(ratio) as avg_ratio,
  MIN(original_value) as min_orig,
  MAX(original_value) as max_orig
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_burst = true
""", (from_dt, to_dt))

bursts, avg_orig, avg_ref, avg_ratio, min_orig, max_orig = cur.fetchone()
print(f"  Total bursts: {bursts:,}")
print(f"  Average original_value: {avg_orig:.2f}")
print(f"  Average reference_value: {avg_ref:.2f}")
print(f"  Average ratio: {avg_ratio:.2f}x")
print(f"  Min original: {min_orig:.2f} | Max original: {max_orig:.2f}")
print()

# Sample of burst detections
print("-" * 120)
print("Sample of detected bursts (top 10 by original_value):")
print("-" * 120)
cur.execute("""
SELECT 
  timestamp, namespace, error_type, original_value, reference_value, 
  baseline_mean, ratio, score
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_burst = true
ORDER BY original_value DESC
LIMIT 10
""", (from_dt, to_dt))

for ts, ns, error_type, orig, ref, baseline, ratio, score in cur.fetchall():
    baseline_str = f"{baseline:.2f}" if baseline else "NULL"
    ratio_str = f"{ratio:.2f}x" if ratio else "NULL"
    print(f"  {ts} | {ns:20s} | {error_type:25s} | Orig:{orig:8.2f} Ref:{ref:8.2f} Baseline:{baseline_str:8s} | {ratio_str:8s} | Score:{score:6.1f}")

print()
print("=" * 120)
print("LIKELY ISSUE: baseline_mean is often NULL or 0")
print("This means spike detection (which uses baseline_mean) cannot trigger")
print("Burst detection (which uses reference_value) works fine")
print("=" * 120)

conn.close()
