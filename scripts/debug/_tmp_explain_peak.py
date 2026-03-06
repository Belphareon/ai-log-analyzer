import os
import psycopg2
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

print('=== SAMPLE LOW-COUNT FLAGGED ROWS (last 2h) ===')
cur.execute('''
    SELECT timestamp, namespace, app_name, error_type, original_value, is_spike, is_burst, score
    FROM ailog_peak.peak_investigation
    WHERE timestamp >= NOW() - interval '2 hours'
      AND namespace LIKE 'pcb-%'
      AND original_value <= 20
      AND (is_spike = TRUE OR is_burst = TRUE)
    ORDER BY timestamp DESC
    LIMIT 25
''')
rows = cur.fetchall()
for r in rows:
    print(r)

print('\n=== WHY THIS HAPPENS: NAMESPACE TOTAL IN SAME 15m WINDOW ===')
cur.execute('''
    WITH flagged AS (
      SELECT
        date_trunc('hour', timestamp)
          + make_interval(mins => (extract(minute from timestamp)::int / 15) * 15) AS win_start,
        namespace,
        timestamp,
        original_value
      FROM ailog_peak.peak_investigation
      WHERE timestamp >= NOW() - interval '2 hours'
        AND namespace LIKE 'pcb-%'
        AND original_value <= 20
        AND is_spike = TRUE
    )
    SELECT
      f.timestamp,
      f.namespace,
      f.original_value AS low_row_value,
      t.win_start,
      t.win_total,
      t.row_count
    FROM flagged f
    JOIN (
      SELECT
        date_trunc('hour', timestamp)
          + make_interval(mins => (extract(minute from timestamp)::int / 15) * 15) AS win_start,
        namespace,
        SUM(original_value) AS win_total,
        COUNT(*) AS row_count
      FROM ailog_peak.peak_investigation
      WHERE timestamp >= NOW() - interval '2 hours'
        AND namespace LIKE 'pcb-%'
      GROUP BY 1,2
    ) t
      ON t.win_start = (date_trunc('hour', f.timestamp)
          + make_interval(mins => (extract(minute from f.timestamp)::int / 15) * 15))
     AND t.namespace = f.namespace
    ORDER BY f.timestamp DESC
    LIMIT 25
''')
rows = cur.fetchall()
for r in rows:
    print(r)

cur.close()
conn.close()
