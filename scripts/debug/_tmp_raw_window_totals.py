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

window_start = datetime(2026,3,2,13,30,tzinfo=timezone.utc)
window_end = datetime(2026,3,2,13,45,tzinfo=timezone.utc)
namespaces = ['pcb-dev-01-app','pcb-fat-01-app','pcb-uat-01-app']

cur.execute('''
SELECT timestamp, namespace, error_count, original_value
FROM ailog_peak.peak_raw_data
WHERE timestamp >= %s
  AND timestamp < %s
  AND namespace = ANY(%s)
ORDER BY timestamp, namespace
''', (window_start, window_end, namespaces))
print('peak_raw_data rows:')
for r in cur.fetchall():
    print(r)

cur.close(); conn.close()
