#!/usr/bin/env python3
"""
SIMPLE INIT INGEST - Load data into empty DB
No peak detection, no UPSERT, just simple INSERT
"""
import sys, os, argparse, psycopg2, re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
DB = {'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'), 'port': int(os.getenv('DB_PORT', 5432)), 
      'database': os.getenv('DB_NAME', 'ailog_analyzer'), 'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
      'password': os.getenv('DB_PASSWORD')}

def parse_log(log_file):
    stats = {}
    day_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
    print(f"📖 Parsing {log_file}...")
    try:
        with open(log_file, 'r') as f: content = f.read()
    except: print(f"❌ File not found"); return None
    pattern_regex = r"Pattern \d+: (\w+) (\d+):(\d+) - (.+?)\n\s+Raw counts:\s+\[(.+?)\]\n\s+Smoothed counts:\s+\[(.+?)\]\n\s+Mean: ([\d.]+), StdDev: ([\d.]+), Samples: (\d+)"
    matches = re.finditer(pattern_regex, content)
    count = 0
    for match in matches:
        day_name, hour, minute, namespace, mean_str, stddev_str, samples_str = match.group(1), int(match.group(2)), int(match.group(3)), match.group(4).strip(), match.group(7), match.group(8), match.group(9)
        day_of_week, quarter_hour = day_map.get(day_name, 0), (minute // 15) % 4
        key = (day_of_week, hour, quarter_hour, namespace)
        stats[key] = {'mean': float(mean_str), 'stddev': float(stddev_str), 'samples': int(samples_str)}
        count += 1
    print(f"✅ Parsed {count} patterns"); return stats if count > 0 else None

def insert_to_db(statistics, conn):
    try: cur = conn.cursor()
    except: print(f"❌ Failed to connect"); return False
    print(f"📤 Inserting {len(statistics)} rows...")
    sql = "INSERT INTO ailog_peak.peak_statistics (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count) VALUES (%s, %s, %s, %s, %s, %s, %s)"
    inserted = 0
    for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
        try:
            cur.execute(sql, (int(day_of_week), int(hour_of_day), int(quarter_hour), namespace, round(float(stats['mean']), 1), round(float(stats['stddev']), 1), int(stats['samples'])))
            inserted += 1
        except Exception as e: print(f"⚠️  Failed to insert: {e}")
    conn.commit(); cur.close(); conn.close()
    print(f"✅ Inserted: {inserted} rows"); return True

def main():
    parser = argparse.ArgumentParser(description='Simple INIT: Load into empty DB')
    parser.add_argument('--input', required=True, help='Input log file')
    args = parser.parse_args()
    print("="*80); print(f"📊 SIMPLE INIT: Load peak statistics"); print("="*80); print()
    stats = parse_log(args.input)
    if not stats: print("❌ No statistics parsed"); return 1
    print()
    try: conn = psycopg2.connect(**DB)
    except Exception as e: print(f"❌ Failed to connect: {e}"); return 1
    success = insert_to_db(stats, conn)
    if not success: print("❌ Failed to insert"); return 1
    print(); print("✅ INIT Ingestion complete!"); return 0

if __name__ == '__main__': sys.exit(main())
