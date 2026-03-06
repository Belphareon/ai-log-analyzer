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

cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'ailog_peak' AND table_name = 'peak_investigation'
        ORDER BY ordinal_position
        """
)
columns = [r[0] for r in cur.fetchall()]
print('columns=', columns)

count_col = 'original_value'
app_col = 'app_name' if 'app_name' in columns else ('app' if 'app' in columns else 'NULL')

query = f"""
SELECT timestamp, namespace, {count_col} AS cnt,
             is_spike, is_burst, score, error_type, {app_col} AS app, detection_method, threshold_used
FROM ailog_peak.peak_investigation
WHERE timestamp >= NOW() - interval '24 hours'
    AND ({count_col})::int <= 30
    AND (is_spike = TRUE OR is_burst = TRUE)
ORDER BY timestamp DESC
LIMIT 200
"""

cur.execute(query)
rows = cur.fetchall()
print(f"rows={len(rows)}")
for row in rows:
        print(row)

cur.close()
conn.close()
