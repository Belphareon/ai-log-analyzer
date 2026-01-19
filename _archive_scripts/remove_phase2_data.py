#!/usr/bin/env python3
"""
Remove INIT Phase 2 data (08_09, 10_11, 12_13) from database
Return to state after INIT Phase 1
"""

import sys
import os

# Nastavit env vars přímo (bez load_dotenv)
os.environ.setdefault('DB_HOST', 'P050TD01.DEV.KB.CZ')
os.environ.setdefault('DB_PORT', '5432')
os.environ.setdefault('DB_NAME', 'ailog_analyzer')
os.environ.setdefault('DB_USER', 'ailog_analyzer_user_d1')

# Načíst heslo z .env
with open('../.env') as f:
    for line in f:
        if line.startswith('DB_PASSWORD'):
            os.environ['DB_PASSWORD'] = line.split('=', 1)[1].strip()

import psycopg2

DB_CONFIG = {
    'host': os.environ.get('DB_HOST'),
    'port': int(os.environ.get('DB_PORT')),
    'database': os.environ.get('DB_NAME'),
    'user': os.environ.get('DB_USER'),
    'password': os.environ.get('DB_PASSWORD')
}

print("=" * 80)
print("🗑️  Removing INIT Phase 2 data from database")
print("=" * 80)
print()

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
except Exception as e:
    print(f"❌ Failed to connect: {e}")
    sys.exit(1)

try:
    # Count before
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    before = cur.fetchone()[0]
    print(f"\n📊 Rows before: {before}")
    
    # Delete Phase 2 data (2481 rows = 5792 - 3311)
    print(f"\n🗑️  Deleting INIT Phase 2 data (2481 rows)...")
    cur.execute("DELETE FROM ailog_peak.peak_statistics WHERE ctid IN (SELECT ctid FROM ailog_peak.peak_statistics ORDER BY ctid DESC LIMIT 2481)")
    conn.commit()
    
    # Count after
    cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
    after = cur.fetchone()[0]
    print(f"   ✅ Rows after: {after}")
    print(f"   ✅ Deleted: {before - after} rows")
    
    if after == 3311:
        print(f"\n✅ Perfect! Back to INIT Phase 1 state (3311 rows)")
    else:
        print(f"\n⚠️  Expected 3311 rows, got {after}")
    
    cur.close()
    conn.close()
    
    print("\n" + "=" * 80)
    print("✅ Complete!")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
    cur.close()
    conn.close()
    sys.exit(1)
