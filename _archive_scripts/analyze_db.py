from dotenv import load_dotenv
import psycopg2, os

load_dotenv()

conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    port=int(os.getenv('DB_PORT', 5432)),
    database=os.getenv('DB_NAME', 'ailog_analyzer'),
    user=os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()

print("\n📊 ANALÝZA DB - 946 řádků")
print("="*60)

# 1. TOP 20 peaks
cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
    FROM ailog_peak.peak_statistics 
    ORDER BY mean_errors DESC LIMIT 20
''')
print("\n🔥 TOP 20 HIGHEST VALUES (jsou to peaks nebo normální?):")
for r in cur.fetchall():
    day = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][r[0]]
    time = f"{r[1]:02d}:{r[2]*15:02d}"
    print(f"   {day} {time} {r[3]}: {r[4]:.1f}")

# 2. pcb-ch-sit kolem 07:00
cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, mean_errors 
    FROM ailog_peak.peak_statistics 
    WHERE namespace = 'pcb-ch-sit-01-app' 
      AND hour_of_day BETWEEN 5 AND 9
    ORDER BY hour_of_day, quarter_hour
''')
print("\n🔍 pcb-ch-sit-01-app 05:00-09:00 (HLEDÁM PEAK ~2890):")
rows = cur.fetchall()
if rows:
    for r in rows:
        day = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][r[0]]
        time = f"{r[1]:02d}:{r[2]*15:02d}"
        flag = "🔴 PEAK!" if r[3] > 1000 else ""
        print(f"   {day} {time}: {r[3]:.1f} {flag}")
else:
    print("   ❌ ŽÁDNÁ DATA!")

# 3. Baseline hodnoty (< 10)
cur.execute('''
    SELECT COUNT(*) FROM ailog_peak.peak_statistics 
    WHERE mean_errors < 10
''')
baseline_count = cur.fetchone()[0]
print(f"\n📈 Baseline hodnoty (< 10): {baseline_count} řádků")

cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
    FROM ailog_peak.peak_statistics 
    WHERE mean_errors < 10 
    ORDER BY mean_errors LIMIT 10
''')
print("   Ukázka nejnižších hodnot:")
for r in cur.fetchall():
    day = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][r[0]]
    time = f"{r[1]:02d}:{r[2]*15:02d}"
    print(f"      {day} {time} {r[3]}: {r[4]:.1f}")

conn.close()
