import psycopg2
from dotenv import load_dotenv
import os

load_dotenv('.env')
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()

# Zkontroluj constraint
cur.execute("""
SELECT constraint_name, constraint_type 
FROM information_schema.table_constraints 
WHERE table_name = 'peak_statistics' AND constraint_type = 'UNIQUE';
""")
constraints = cur.fetchall()
print("🔑 UNIQUE constraints na peak_statistics:")
for row in constraints:
    print(f"  {row[0]}: {row[1]}")

# Podívej se na sloupce
cur.execute("""
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_name = 'peak_statistics' 
ORDER BY ordinal_position;
""")
cols = cur.fetchall()
print("\n📋 Sloupce v peak_statistics:")
for col in cols:
    print(f"  {col[0]}: {col[1]}")

# Zkontroluj zda máme datum sloupec
has_date = False
for col in cols:
    if 'date' in col[0].lower():
        has_date = True

print(f"\n❓ Máme DATE sloupec? {has_date}")

# Podívej se na ON CONFLICT logiku
print("\n🚨 PROBLÉM:")
print("  Primární klíč: (day_of_week, hour_of_day, quarter_hour, namespace)")
print("  CHYBA: Den v týdnu se OPAKUJE každý týden!")
print("  Příklad:")
print("    1.12.2025 = pondělí (day=0)")
print("    8.12.2025 = úterý (day=1)")
print("    15.12.2025 = pondělí (day=0) ← STEJNÉ jako 1.12!")
print("  → ON CONFLICT přepíše 1.12 data když vloží 15.12 data!")

conn.close()
