#!/usr/bin/env python3
import psycopg2
import os
import sys

os.chdir('/home/jvsete/git/sas/ai-log-analyzer')
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')

# Read .env file manually
env_vars = {}
with open('.env', 'r') as f:
    for line in f:
        if line.strip() and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

# Read backup file and filter problematic lines
backup_file = '_backups/ailog_peak_peak_raw_data_20260119_121213.sql'
print(f"Reading backup from: {backup_file}")

with open(backup_file, 'r') as f:
    lines = f.readlines()

# Filter out the \restrict line and other problematic psql commands
filtered_lines = []
for line in lines:
    # Skip psql-only commands
    if line.startswith('\\'):
        continue
    filtered_lines.append(line)

sql_content = ''.join(filtered_lines)
print(f"Filtered SQL ({len(sql_content):,} bytes)")

# Connect and execute
conn = psycopg2.connect(
    host=env_vars['DB_HOST'], 
    port=int(env_vars['DB_PORT']), 
    database=env_vars['DB_NAME'], 
    user=env_vars['DB_USER'], 
    password=env_vars['DB_PASSWORD']
)
cur = conn.cursor()

try:
    cur.execute(sql_content)
    conn.commit()
    print("✅ Backup restored successfully")
    
    # Verify
    cur.execute('SELECT COUNT(*) FROM ailog_peak.peak_raw_data')
    count = cur.fetchone()[0]
    print(f"✅ peak_raw_data now has {count:,} rows")
except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    conn.close()
