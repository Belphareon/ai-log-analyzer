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

# Check all schemas
cur.execute("SELECT schema_name FROM information_schema.schemata ORDER BY schema_name")
print("📊 Schemas in ailog_analyzer:")
for schema in cur.fetchall():
    print(f"  - {schema[0]}")

print("\n📋 Tables in ailog_peak:")
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='ailog_peak'")
tables = cur.fetchall()
for table in tables:
    table_name = table[0]
    cur.execute(f"SELECT COUNT(*) FROM ailog_peak.{table_name}")
    count = cur.fetchone()[0]
    print(f"  {table_name:30s} => {count:6d} rows")

# Check if there's data in public schema
print("\n📋 Tables in public:")
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' LIMIT 20")
public_tables = cur.fetchall()
if public_tables:
    for table in public_tables:
        print(f"  - {table[0]}")
else:
    print("  (none)")

conn.close()
