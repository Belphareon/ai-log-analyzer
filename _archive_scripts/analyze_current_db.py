#!/usr/bin/env python3
from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

print("\n" + "="*70)
print("📊 ANALÝZA DB - Test 2025-12-04_05")
print("="*70)

# 1. Total
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics')
print(f"\n✅ Total rows: {cur.fetchone()[0]}")

# 2. TOP 30
cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
    FROM ailog_peak.peak_statistics 
    ORDER BY mean_errors DESC LIMIT 30
''')
print("\n🔥 TOP 30 HIGHEST VALUES:")
print("   (Hledám peaks ~2890, ~43000, ~673, atd.)")
for r in cur.fetchall():
    time = f"{r[1]:02d}:{r[2]*15:02d}"
    flag = "🔴 PEAK!" if r[4] > 1000 else ("��" if r[4] > 100 else "")
    print(f"   {days[r[0]]} {time} {r[3]}: {r[4]:.1f} {flag}")

# 3. pcb-ch-sit 05-09
cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, mean_errors 
    FROM ailog_peak.peak_statistics 
    WHERE namespace = 'pcb-ch-sit-01-app' 
      AND hour_of_day BETWEEN 5 AND 9
    ORDER BY hour_of_day, quarter_hour
''')
print("\n🔍 pcb-ch-sit-01-app 05:00-09:00:")
print("   (Měl by CHYBĚT peak ~2890 v 07:00)")
rows = cur.fetchall()
if rows:
    for r in rows:
        time = f"{r[1]:02d}:{r[2]*15:02d}"
        flag = "🔴 PEAK!" if r[3] > 1000 else ""
        print(f"   {days[r[0]]} {time}: {r[3]:.1f} {flag}")
else:
    print("   ❌ ŽÁDNÁ DATA!")

# 4. Baseline < 10
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors < 10')
baseline_count = cur.fetchone()[0]
print(f"\n📈 Baseline hodnoty (< 10): {baseline_count} řádků")

cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
    FROM ailog_peak.peak_statistics 
    WHERE mean_errors < 10 
    ORDER BY namespace, hour_of_day, quarter_hour LIMIT 20
''')
print("   Ukázka (prvních 20):")
for r in cur.fetchall():
    time = f"{r[1]:02d}:{r[2]*15:02d}"
    print(f"      {days[r[0]]} {time} {r[3]}: {r[4]:.1f}")

# 5. Mid 50-100
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors BETWEEN 50 AND 100')
print(f"\n🟡 Střední hodnoty (50-100): {cur.fetchone()[0]} řádků")

# 6. High > 100
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors > 100')
high_count = cur.fetchone()[0]
print(f"\n🔴 Vysoké hodnoty (> 100): {high_count} řádků")
if high_count > 0:
    print("   ⚠️  VAROVÁNÍ: Peaks by NEMĚLY být v DB!")

conn.close()
print("\n" + "="*70)
print("✅ Analýza dokončena")
print("="*70 + "\n")
