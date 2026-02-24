import os
import psycopg2
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

os.chdir('/home/jvsete/git/ai-log-analyzer')
load_dotenv('config/.env')

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'localhost'),
    port=int(os.getenv('DB_PORT', 5432)),
    database=os.getenv('DB_NAME', 'postgres'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD'),
)
cursor = conn.cursor()

since = datetime.now(timezone.utc) - timedelta(hours=24)

# Stats
cursor.execute('''SELECT COUNT(*), SUM(CASE WHEN is_spike THEN 1 ELSE 0 END), SUM(CASE WHEN is_burst THEN 1 ELSE 0 END), COUNT(CASE WHEN score >= 70 THEN 1 END), AVG(COALESCE(original_value,0)) FROM ailog_peak.peak_investigation WHERE timestamp >= %s''', (since,))

row = cursor.fetchone()
print(f'Last 24h: {row[0]} records')
print(f'  Spikes: {row[1]}')
print(f'  Bursts: {row[2]}')
print(f'  Score >=70: {row[3]}')
print(f'  Avg events: {row[4]:.1f}')

conn.close()
