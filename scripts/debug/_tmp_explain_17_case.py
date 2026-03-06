import os
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(); load_dotenv('config/.env')
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT','5432')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
)
cur = conn.cursor()

case_ts = datetime(2026, 3, 2, 13, 35, 58, 139000, tzinfo=timezone.utc)
ns = 'pcb-fat-01-app'

dow = 0
cur.execute('''
SELECT t.percentile_level, t.percentile_value, c.cap_value,
       LEAST(t.percentile_value, c.cap_value) AS effective_or_threshold,
       t.sample_count
FROM ailog_peak.peak_thresholds t
LEFT JOIN ailog_peak.peak_threshold_caps c ON c.namespace=t.namespace
WHERE t.namespace=%s AND t.day_of_week=%s
''', (ns, dow))
thr = cur.fetchone()
print('thresholds=', thr)

cur.execute('''
SELECT timestamp, namespace, error_type, original_value,
       ratio, baseline_mean, same_day_refs_mean,
       reference_value, replacement_value,
       threshold_used, is_spike, is_burst, score, detection_method
FROM ailog_peak.peak_investigation
WHERE timestamp = %s AND namespace=%s
''', (case_ts, ns))
row = cur.fetchone()
print('row=', row)

cur.execute('''
WITH w AS (
  SELECT date_trunc('hour', %s::timestamptz)
         + make_interval(mins => (extract(minute from %s::timestamptz)::int/15)*15) AS win_start
)
SELECT w.win_start,
       SUM(COALESCE(p.original_value,0)) AS ns_window_total,
       COUNT(*) AS rows_count,
       SUM(CASE WHEN p.is_spike THEN 1 ELSE 0 END) AS spike_rows
FROM w
JOIN ailog_peak.peak_investigation p
  ON p.namespace=%s
 AND p.timestamp >= w.win_start
 AND p.timestamp < (w.win_start + interval '15 min')
GROUP BY w.win_start
''', (case_ts, case_ts, ns))
print('ns_window=', cur.fetchone())

cur.close(); conn.close()
