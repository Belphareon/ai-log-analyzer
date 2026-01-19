import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT',5432)), database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
cur.execute("SELECT day_of_week, hour_of_day, quarter_hour, mean_errors FROM ailog_peak.peak_statistics WHERE namespace='pcb-ch-sit-01-app' AND day_of_week IN (3,4) AND hour_of_day=7 ORDER BY day_of_week, quarter_hour")
print('✅ Thu/Fri 07:xx pcb-ch-sit-01-app values in DB:')
rows = cur.fetchall()
if not rows:
    print('  ❌ NO DATA FOUND')
else:
    for row in rows:
        day = ['Mon','Tue','Wed','Thu','Fri'][row[0]]
        print(f'  {day} 07:{row[2]*15:02d} = {row[3]:.1f}')
cur.execute("SELECT MAX(mean_errors) FROM ailog_peak.peak_statistics WHERE namespace='pcb-ch-sit-01-app'")
max_val = cur.fetchone()[0]
print(f'\n✅ Max value for pcb-ch-sit-01-app: {max_val:.1f}')
conn.close()
