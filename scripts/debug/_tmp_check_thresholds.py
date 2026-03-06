import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
load_dotenv('config/.env')

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT', '5432')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_DDL_USER') or os.getenv('DB_USER'),
    password=os.getenv('DB_DDL_PASSWORD') or os.getenv('DB_PASSWORD'),
)

cur = conn.cursor()
role = os.getenv('DB_DDL_ROLE', 'role_ailog_analyzer_ddl')
cur.execute(f'SET ROLE {role}')

cur.execute(
    """
    SELECT t.namespace, t.day_of_week, t.percentile_value, c.cap_value, t.sample_count
    FROM ailog_peak.peak_thresholds t
    LEFT JOIN ailog_peak.peak_threshold_caps c ON c.namespace=t.namespace
    WHERE t.namespace IN ('pcb-dev-01-app','pcb-fat-01-app','pcb-uat-01-app')
    ORDER BY t.namespace, t.day_of_week
    """
)

for row in cur.fetchall():
    print(row)

cur.close()
conn.close()
