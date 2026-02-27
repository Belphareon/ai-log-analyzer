#!/usr/bin/env python3
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

# Check last 24h
from_dt = datetime.utcnow() - timedelta(hours=24)
to_dt = datetime.utcnow()

print('=' * 120)
print('BASELINE_MEAN VERIFICATION (Last 24h)')
print('=' * 120)
print(f'Period: {from_dt} → {to_dt}')
print()

cur.execute('''
SELECT 
  detection_method,
  COUNT(*) as total,
  COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) as with_baseline,
  ROUND(100.0 * COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) / COUNT(*), 1) as baseline_pct,
  AVG(baseline_mean) as avg_baseline,
  MIN(baseline_mean) as min_baseline,
  MAX(baseline_mean) as max_baseline,
  ROUND(100.0 * COUNT(CASE WHEN is_spike THEN 1 END) / COUNT(*), 1) as spike_pct,
  ROUND(100.0 * COUNT(CASE WHEN is_burst THEN 1 END) / COUNT(*), 1) as burst_pct
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
GROUP BY detection_method
ORDER BY total DESC
''', (from_dt, to_dt))

print('Detection Method | Total Rows | With BL | BL % | Avg BL | Min BL | Max BL | Spike % | Burst %')
print('-' * 120)
for method, total, with_bl, pct, avg_bl, min_bl, max_bl, spike_pct, burst_pct in cur.fetchall():
    avg_str = f'{avg_bl:.1f}' if avg_bl else 'NULL'
    min_str = f'{min_bl:.1f}' if min_bl else 'NULL'
    max_str = f'{max_bl:.1f}' if max_bl else 'NULL'
    print(f'{method:15s} | {total:10,d} | {with_bl:7,d} | {pct:4.1f}% | {avg_str:6s} | {min_str:6s} | {max_str:6s} | {spike_pct:6.1f}% | {burst_pct:6.1f}%')

print()

# Check spike detection potential
print('=' * 120)
print('SPIKE DETECTION CAPABILITY')
print('=' * 120)
cur.execute('''
SELECT 
  COUNT(*) as total,
  COUNT(CASE WHEN baseline_mean IS NOT NULL AND baseline_mean > 0 THEN 1 END) as can_spike_detect,
  COUNT(CASE WHEN is_spike THEN 1 END) as detected_spikes,
  ROUND(100.0 * COUNT(CASE WHEN is_spike THEN 1 END) / NULLIF(COUNT(*), 0), 1) as spike_rate
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s
  AND detection_method != 'baseline_test'
''', (from_dt, to_dt))

total, can_spike, detected, spike_rate = cur.fetchone()
print(f'Total detection points: {total:,}')
print(f'Can support spike detection (baseline > 0): {can_spike:,} ({100*can_spike/total:.1f}%)')
print(f'Actual spikes detected: {detected:,} ({spike_rate}%)')
print()

# Sample spikes and bursts
print('=' * 120)
print('SAMPLE SPIKES (with original_value comparison)')
print('=' * 120)
cur.execute('''
SELECT 
  timestamp, namespace, error_type, original_value, baseline_mean, ratio
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_spike = true
ORDER BY original_value DESC
LIMIT 5
''', (from_dt, to_dt))

spike_rows = cur.fetchall()
if spike_rows:
    for ts, ns, error_type, orig, baseline, ratio in spike_rows:
        bl_str = f'{baseline:.1f}' if baseline else 'NULL'
        ratio_str = f'{ratio:.2f}x' if ratio else 'NULL'
        print(f'  {ts} | {ns:20s} | {error_type:25s} | Orig:{orig:8.1f} BL:{bl_str:8s} | {ratio_str:6s}')
else:
    print('  (No spikes detected)')

print()

# Sample bursts
print('=' * 120)
print('SAMPLE BURSTS')
print('=' * 120)
cur.execute('''
SELECT 
  timestamp, namespace, error_type, original_value, baseline_mean, ratio
FROM peak_investigation
WHERE timestamp >= %s AND timestamp <= %s AND is_burst = true
ORDER BY original_value DESC
LIMIT 5
''', (from_dt, to_dt))

for ts, ns, error_type, orig, baseline, ratio in cur.fetchall():
    bl_str = f'{baseline:.1f}' if baseline else 'NULL'
    ratio_str = f'{ratio:.2f}x' if ratio else 'NULL'
    print(f'  {ts} | {ns:20s} | {error_type:25s} | Orig:{orig:8.1f} BL:{bl_str:8s} | {ratio_str:6s}')

print()
print('=' * 120)

conn.close()
