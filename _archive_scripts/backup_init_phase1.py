import psycopg2
import csv
from datetime import datetime

DB_CONFIG = {
    'host': 'P050TD01.DEV.KB.CZ',
    'port': 5432,
    'database': 'ailog_analyzer',
    'user': 'ailog_analyzer_user_d1',
    'password': 'y01d40Mmdys/lbDE'
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_file = f'/tmp/backup_peak_statistics_INIT_PHASE1_{timestamp}.csv'

cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
cur.execute("""
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count
    FROM ailog_peak.peak_statistics
    ORDER BY day_of_week, hour_of_day, quarter_hour, namespace
""")

with open(backup_file, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['day_of_week', 'hour_of_day', 'quarter_hour', 'namespace', 'mean_errors', 'stddev_errors', 'samples_count'])
    for row in cur.fetchall():
        writer.writerow(row)

print(f"✅ Backup: {backup_file}")
print(f"📁 Size: {len(open(backup_file).readlines())} lines")

conn.close()
