import os
import psycopg2
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
load_dotenv('config/.env')

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT', '5432')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
)
cur = conn.cursor()

namespaces = ['pcb-dev-01-app', 'pcb-fat-01-app', 'pcb-uat-01-app']
dow = 0  # Monday for 2026-03-02
window_start = datetime(2026, 3, 2, 13, 30, tzinfo=timezone.utc)
window_end = datetime(2026, 3, 2, 13, 45, tzinfo=timezone.utc)

print('=== THRESHOLDS (P94/CAP) FOR NAMESPACES ===')
cur.execute(
    """
    SELECT
      t.namespace,
      t.day_of_week,
      t.percentile_level,
      t.percentile_value,
      c.cap_value,
      LEAST(t.percentile_value, c.cap_value) AS effective_or_threshold,
      t.sample_count
    FROM ailog_peak.peak_thresholds t
    LEFT JOIN ailog_peak.peak_threshold_caps c ON c.namespace = t.namespace
    WHERE t.namespace = ANY(%s)
      AND t.day_of_week = %s
    ORDER BY t.namespace
    """,
    (namespaces, dow),
)
thr_rows = cur.fetchall()
for r in thr_rows:
    print(r)

print('\n=== NAMESPACE TOTALS IN 13:30-13:45 UTC WINDOW ===')
cur.execute(
    """
    SELECT
      namespace,
      SUM(COALESCE(original_value, 0)) AS namespace_total,
      COUNT(*) AS rows_count,
      SUM(CASE WHEN is_spike THEN 1 ELSE 0 END) AS spike_rows,
      SUM(CASE WHEN is_burst THEN 1 ELSE 0 END) AS burst_rows
    FROM ailog_peak.peak_investigation
    WHERE timestamp >= %s
      AND timestamp < %s
      AND namespace = ANY(%s)
    GROUP BY namespace
    ORDER BY namespace
    """,
    (window_start, window_end, namespaces),
)
win_rows = cur.fetchall()
for r in win_rows:
    print(r)

print('\n=== CHECK: EXAMPLES OF LOW ROW VALUES FLAGGED AS SPIKE IN WINDOW ===')
cur.execute(
    """
    SELECT timestamp, namespace, error_type, original_value, is_spike, is_burst, score
    FROM ailog_peak.peak_investigation
    WHERE timestamp >= %s
      AND timestamp < %s
      AND namespace = ANY(%s)
      AND original_value <= 20
      AND is_spike = TRUE
    ORDER BY timestamp DESC
    LIMIT 30
    """,
    (window_start, window_end, namespaces),
)
for r in cur.fetchall():
    print(r)

cur.close()
conn.close()
