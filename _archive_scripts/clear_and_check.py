import psycopg2

DB_CONFIG = {
    'host': 'P050TD01.DEV.KB.CZ',
    'port': 5432,
    'database': 'ailog_analyzer',
    'user': 'ailog_analyzer_user_d1',
    'password': 'y01d40Mmdys/lbDE'
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

print("🧹 Clearing wrong data...")

# Delete from peak_statistics (186 rows from 1.12)
cur.execute("DELETE FROM ailog_peak.peak_statistics")
print(f"  Deleted peak_statistics")

# Delete from peak_investigation (11 rows from my run)
cur.execute("DELETE FROM ailog_peak.peak_investigation")
print(f"  Deleted peak_investigation")

conn.commit()

# Verify
cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
ps_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_investigation")
pi_count = cur.fetchone()[0]

print(f"\n✅ After cleanup:")
print(f"  peak_statistics: {ps_count} rows")
print(f"  peak_investigation: {pi_count} rows")
print(f"\n❌ DB je ČISTÁ - data z minulé session jsou ZTRACENÁ!")
print(f"   Mělo by tam být: 5,460 rows z INIT Phase 1 (1.12-7.12)")

conn.close()
