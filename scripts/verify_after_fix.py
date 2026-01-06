#!/usr/bin/env python3
"""
VERIFICATION SCRIPT - Check if peaks are correctly skipped after DB fix
Run AFTER fixing DB: python verify_after_fix.py
"""
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

PEAKS = [
    (4, 7, "pcb-ch-sit-01-app", "4.12 Fri 07:00", 2884),
    (4, 20, "pcb-ch-sit-01-app", "4.12 Fri 20:30", 673),
    (5, 14, "pcb-dev-01-app", "5.12 Sat 14:30", 43000),
    (5, 20, "pcb-dev-01-app", "5.12 Sat 20:00", 1573),
    (4, 9, "pcb-ch-sit-01-app", "4.12 Fri 09:45", "normal"),
    (4, 13, "pcb-ch-sit-01-app", "4.12 Fri 13:15", "normal"),
    (4, 22, "pcb-ch-sit-01-app", "4.12 Fri 22:30", 687),
    (4, 23, "pcb-ch-sit-01-app", "4.12 Fri 23:15", "normal"),
    (5, 7, "pcb-ch-sit-01-app", "5.12 Sat 07:00", 2885),
]

print("=" * 100)
print("PEAK VERIFICATION - USER REPORTED vs DB ACTUAL (After Fix)")
print("=" * 100)
print()

day_names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

for dow, hour, ns, label, expected in PEAKS:
    cur.execute("""
        SELECT mean_errors, samples_count
        FROM ailog_peak.peak_statistics
        WHERE day_of_week = %s AND hour_of_day = %s AND namespace = %s
    """, (dow, hour, ns))
    
    rows = cur.fetchall()
    
    print(f"📅 {label} {ns}")
    print(f"   Expected: {expected}")
    
    if rows:
        values_str = ", ".join([f"{r[0]:.1f}" for r in rows])
        print(f"   DB Values: [{values_str}]")
        
        # Check if peak is correctly skipped
        if expected == "normal":
            print(f"   ✅ Should be normal traffic - OK" if all(r[0] < 100 for r in rows) else f"   ❌ ERROR: Should be <100 but got high values")
        else:
            max_val = max(r[0] for r in rows)
            if max_val < expected * 0.5:  # Significantly lower = skipped
                print(f"   ✅ SKIPPED - reduced from ~{expected} to {max_val:.1f}")
            elif max_val > expected * 0.8:  # Still high = NOT skipped
                print(f"   ❌ NOT SKIPPED - still {max_val:.1f} (expected to skip ~{expected})")
            else:
                print(f"   ⚠️  PARTIAL - {max_val:.1f} (unclear if properly skipped)")
    else:
        print(f"   ❌ NOT FOUND in DB")
    
    print()

conn.close()
print("=" * 100)
