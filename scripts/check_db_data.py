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

print("\n" + "="*80)
print("📊 KOMPLETNÍ ANALÝZA DB - Test 2025-12-04_05 (946 řádků)")
print("="*80)

# 1. Total count
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics')
total = cur.fetchone()[0]
print(f"\n✅ Total rows: {total}")

# 2. Namespaces
cur.execute('SELECT DISTINCT namespace FROM ailog_peak.peak_statistics ORDER BY namespace')
namespaces = [r[0] for r in cur.fetchall()]
print(f"\n📦 Namespaces ({len(namespaces)}):")
for ns in namespaces:
    print(f"   - {ns}")

# 3. TOP 30 highest values
print("\n" + "="*80)
print("🔥 TOP 30 HIGHEST VALUES (hledám peaks ~2890, ~673, atd.):")
print("="*80)
cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
    FROM ailog_peak.peak_statistics 
    ORDER BY mean_errors DESC LIMIT 30
''')
for r in cur.fetchall():
    time = f"{r[1]:02d}:{r[2]*15:02d}"
    if r[4] > 1000:
        flag = "🔴 PEAK! (NEMĚLO BY TU BÝT!)"
    elif r[4] > 100:
        flag = "🟡 Vysoká hodnota"
    else:
        flag = ""
    print(f"   {days[r[0]]} {time} {r[3]}: {r[4]:.1f} {flag}")

# 4. pcb-ch-sit kolem 07:00
print("\n" + "="*80)
print("🔍 pcb-ch-sit-01-app 05:00-09:00 (KRITICKÝ ČAS - peak ~2890):")
print("="*80)
cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, mean_errors 
    FROM ailog_peak.peak_statistics 
    WHERE namespace = 'pcb-ch-sit-01-app' 
      AND hour_of_day BETWEEN 5 AND 9
    ORDER BY hour_of_day, quarter_hour
''')
rows = cur.fetchall()
if rows:
    for r in rows:
        time = f"{r[1]:02d}:{r[2]*15:02d}"
        if r[3] > 1000:
            flag = "🔴 PEAK DETEKOVÁN! (měl být skipnut)"
        else:
            flag = "✅ OK"
        print(f"   {days[r[0]]} {time}: {r[3]:.1f} {flag}")
else:
    print("   ❌ ŽÁDNÁ DATA v tomto rozsahu!")

# 5. Baseline hodnoty (< 10)
print("\n" + "="*80)
print("📈 BASELINE HODNOTY (< 10) - měly by být v DB:")
print("="*80)
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors < 10')
baseline_count = cur.fetchone()[0]
print(f"   Celkem: {baseline_count} řádků")

cur.execute('''
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
    FROM ailog_peak.peak_statistics 
    WHERE mean_errors < 10 
    ORDER BY namespace, hour_of_day, quarter_hour LIMIT 30
''')
print("   Ukázka (prvních 30):")
for r in cur.fetchall():
    time = f"{r[1]:02d}:{r[2]*15:02d}"
    print(f"      {days[r[0]]} {time} {r[3]}: {r[4]:.1f}")

# 6. Střední hodnoty 10-100
print("\n" + "="*80)
print("📊 STŘEDNÍ HODNOTY (10-100):")
print("="*80)
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors BETWEEN 10 AND 100')
mid_count = cur.fetchone()[0]
print(f"   Celkem: {mid_count} řádků")

# 7. Vysoké hodnoty > 100
print("\n" + "="*80)
print("⚠️  VYSOKÉ HODNOTY (> 100) - suspected peaks:")
print("="*80)
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors > 100')
high_count = cur.fetchone()[0]
print(f"   Celkem: {high_count} řádků")

if high_count > 0:
    print("   🔴 VAROVÁNÍ: Tyto hodnoty by NEMĚLY být v DB pokud jsou peaks!")
    cur.execute('''
        SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors 
        FROM ailog_peak.peak_statistics 
        WHERE mean_errors > 100 
        ORDER BY mean_errors DESC
    ''')
    print("   Všechny hodnoty > 100:")
    for r in cur.fetchall():
        time = f"{r[1]:02d}:{r[2]*15:02d}"
        print(f"      {days[r[0]]} {time} {r[3]}: {r[4]:.1f}")

# 8. Value ranges breakdown
print("\n" + "="*80)
print("📊 STATISTIKA HODNOT:")
print("="*80)
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors < 10')
print(f"   < 10 (baseline):     {cur.fetchone()[0]:4d} řádků")
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors BETWEEN 10 AND 50')
print(f"   10-50 (normální):    {cur.fetchone()[0]:4d} řádků")
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors BETWEEN 50 AND 100')
print(f"   50-100 (zvýšené):    {cur.fetchone()[0]:4d} řádků")
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors BETWEEN 100 AND 1000')
print(f"   100-1000 (vysoké):   {cur.fetchone()[0]:4d} řádků")
cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_statistics WHERE mean_errors > 1000')
print(f"   > 1000 (PEAKS!):     {cur.fetchone()[0]:4d} řádků 🔴")

conn.close()

print("\n" + "="*80)
print("✅ Analýza dokončena")
print("="*80 + "\n")
