#!/usr/bin/env python3
import psycopg2
import os

with open('../.env') as f:
    for line in f:
        if line.startswith('DB_PASSWORD='):
            os.environ['DB_PASSWORD'] = line.split('=', 1)[1].strip()

DB_CONFIG = {
    'host': 'P050TD01.DEV.KB.CZ',
    'port': 5432,
    'database': 'ailog_analyzer',
    'user': 'ailog_analyzer_user_d1',
    'password': os.environ.get('DB_PASSWORD')
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

print("📊 DB DISTRIBUTION - INIT Phase 1")
print("=" * 80)

# Unique time windows
cur.execute("SELECT COUNT(*) FROM (SELECT DISTINCT day_of_week, hour_of_day, quarter_hour FROM ailog_peak.peak_statistics) t")
unique_times = cur.fetchone()[0]
print(f"Unique time windows: {unique_times} (expected: 7 days × 96 windows/day = 672)")

# Unique namespaces
cur.execute("SELECT COUNT(DISTINCT namespace) FROM ailog_peak.peak_statistics")
unique_ns = cur.fetchone()[0]
print(f"Unique namespaces: {unique_ns}")

# Expected total
expected = unique_times * unique_ns
print(f"\nExpected total: {expected} (unique_times × NS)")
print(f"Actual total: 5460")

if expected == 5460:
    print("✅ PERFECT! Complete grid!")
else:
    print(f"⚠️ Mismatch: {expected} vs 5460")

# Breakdown by NS
print("\n📈 Breakdown by namespace:")
cur.execute("""
    SELECT namespace, COUNT(*) as count 
    FROM ailog_peak.peak_statistics 
    GROUP BY namespace 
    ORDER BY namespace
""")

for ns, count in cur.fetchall():
    status = "✅" if count == unique_times else "⚠️"
    print(f"{status} {ns:30s}: {count:4d} windows")

cur.close()
conn.close()
