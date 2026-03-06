import os
import psycopg2
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
cur.execute('''
SELECT timestamp, namespace, app_name, error_type, original_value, is_spike, is_burst, score
FROM ailog_peak.peak_investigation
WHERE timestamp::date = '2026-03-02'
  AND original_value = 17
ORDER BY timestamp DESC
LIMIT 200
''')
rows = cur.fetchall()
print('rows=',len(rows))
for r in rows:
    print(r)
cur.close(); conn.close()
