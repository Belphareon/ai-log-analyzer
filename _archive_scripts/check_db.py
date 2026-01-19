import os, psycopg2, sys
sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')
os.chdir('/home/jvsete/git/sas/ai-log-analyzer')

from dotenv import load_dotenv
load_dotenv()

try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM peak_statistics;")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT day_of_week) FROM peak_statistics;")
    days = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT namespace) FROM peak_statistics;")
    namespaces = cursor.fetchone()[0]
    
    print(f"📊 Current DB State:")
    print(f"✅ Total rows: {total}")
    print(f"✅ Days: {days}")
    print(f"✅ Namespaces: {namespaces}")
    
    if total == 0:
        print(f"\n✨ DB is empty - ready for INIT Phase!")
    else:
        print(f"\n📈 DB has data: {days} days × {namespaces} namespaces = {total} rows")
    
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")
