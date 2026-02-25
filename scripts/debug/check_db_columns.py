#!/usr/bin/env python3
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(
    host=os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    port=int(os.getenv('DB_PORT', 5432)),
    database=os.getenv('DB_NAME', 'ailog_analyzer'),
    user=os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute('SET search_path = ailog_peak;')

# Check what baseline columns exist
cur.execute('''
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'ailog_peak' AND table_name = 'peak_investigation'
  AND column_name LIKE '%baseline%'
ORDER BY ordinal_position
''')

print('Existing baseline columns:')
for col_name, in cur.fetchall():
    print(f'  - {col_name}')

conn.close()
