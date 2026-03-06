import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
load_dotenv('config/.env')

print('DB_USER=', os.getenv('DB_USER'))
print('DB_DDL_USER=', os.getenv('DB_DDL_USER'))

try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', '5432')),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
    )
    cur = conn.cursor()
    cur.execute('SELECT 1')
    print('APP CONNECT OK', cur.fetchone())
    cur.close()
    conn.close()
except Exception as e:
    print('APP CONNECT FAIL', e)
