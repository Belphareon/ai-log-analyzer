#!/usr/bin/env python3
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
DB_CONFIG = {'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'), 'port': int(os.getenv('DB_PORT', 5432)), 'database': os.getenv('DB_NAME', 'ailog_analyzer'), 'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'), 'password': os.getenv('DB_PASSWORD')}
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
print("🔍 OVĚŘENÍ\n")
tests = [
    (4, 7, "pcb-ch-sit-01-app", "4.12 Fri 07:00"),
    (4, 20, "pcb-ch-sit-01-app", "4.12 Fri 20:30"),
    (5, 14, "pcb-dev-01-app", "5.12 Sat 14:30"),
    (5, 20, "pcb-dev-01-app", "5.12 Sat 20:00"),
]
for dow, hour, ns, label in tests:
    cur.execute("SELECT mean_errors FROM ailog_peak.peak_statistics WHERE day_of_week=%s AND hour_of_day=%s AND namespace=%s", (dow, hour, ns))
    rows = cur.fetchall()
    if rows:
        vals = [f"{r[0]:.1f}" for r in rows]
        print(f"{label} {ns}: {', '.join(vals)}")
    else:
        print(f"{label} {ns}: ❌ NOT FOUND")
conn.close()
