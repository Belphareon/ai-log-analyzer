import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT',5432)), database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
cur.execute("SELECT namespace, day_of_week, hour_of_day, quarter_hour, mean_errors FROM ailog_peak.peak_statistics ORDER BY mean_errors DESC LIMIT 10")
days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
print("=== TOP 10 HIGHEST VALUES IN DB ===")
for ns, day, hr, qtr, val in cur.fetchall():
    print(f"  {days[day]} {hr:02d}:{qtr*15:02d} {ns:25s} = {val:8.1f}")
conn.close()
