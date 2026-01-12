#!/usr/bin/env python3
"""
Fill missing 15-minute windows in DB for INIT Phase 1 data.

Problem:
- INIT Phase 1 (1.12-7.12) has incomplete data for some namespaces
- Missing windows break Regular phase peak detection (can't calculate references)

Solution:
- Identify all unique (day, hour, quarter) combinations in DB
- Identify all unique namespaces in DB
- For missing combinations: INSERT with mean=0, stddev=0, samples=1
- Result: Complete grid of namespaces × time windows

Use after INIT Phase 1 ingestion, before INIT Phase 2 (which will be Regular phase).
"""

import sys
import os
import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}


def fill_missing_windows():
    """Fill missing windows in database"""
    
    print("=" * 80)
    print("🔧 Filling Missing Windows - INIT Phase 1 Completion")
    print("=" * 80)
    print()
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False
    
    try:
        # Step 1: Get all unique (day, hour, quarter) and namespaces currently in DB
        print("\n📊 Analyzing current data...")
        
        cur.execute("""
            SELECT DISTINCT day_of_week, hour_of_day, quarter_hour 
            FROM ailog_peak.peak_statistics 
            ORDER BY day_of_week, hour_of_day, quarter_hour
        """)
        all_times = cur.fetchall()
        print(f"   ✅ Found {len(all_times)} unique time windows")
        
        # Definovat všechny 12 namespaces (včetně těch, co nejsou v Phase 1)
        all_namespaces = [
            'pca-dev-01-app',
            'pca-sit-01-app',
            'pca-fat-01-app',        # Nový - přidat nuly
            'pca-uat-01-app',        # Nový - přidat nuly
            'pcb-ch-dev-01-app',
            'pcb-ch-sit-01-app',
            'pcb-ch-fat-01-app',
            'pcb-ch-uat-01-app',
            'pcb-dev-01-app',
            'pcb-fat-01-app',
            'pcb-sit-01-app',
            'pcb-uat-01-app'
        ]
        print(f"   ✅ Using all 12 namespaces:")
        for ns in all_namespaces:
            print(f"      - {ns}")
        
        # Step 2: Find missing combinations and INSERT them
        print("\n🔄 Finding and inserting missing windows...")
        
        added = 0
        for day, hour, quarter in all_times:
            for ns in all_namespaces:
                # Check if this combination exists
                cur.execute("""
                    SELECT COUNT(*) FROM ailog_peak.peak_statistics 
                    WHERE day_of_week = %s AND hour_of_day = %s AND quarter_hour = %s AND namespace = %s
                """, (day, hour, quarter, ns))
                
                if cur.fetchone()[0] == 0:
                    # Missing - insert with mean=0 (no errors = OK system)
                    cur.execute("""
                        INSERT INTO ailog_peak.peak_statistics 
                        (day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (day, hour, quarter, ns, 0, 0, 1))
                    added += 1
        
        conn.commit()
        print(f"   ✅ Added {added} missing windows (mean=0)")
        
        # Step 3: Verify result
        print("\n✅ Verifying result...")
        
        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        total_rows = cur.fetchone()[0]
        print(f"   Total rows now: {total_rows}")
        
        # Expected: len(all_times) * len(all_namespaces)
        expected = len(all_times) * len(all_namespaces)
        print(f"   Expected: {expected} (all_times × all_namespaces)")
        
        if total_rows == expected:
            print(f"   ✅ PERFECT! Complete grid achieved!")
        else:
            print(f"   ⚠️  Mismatch: have {total_rows}, expected {expected}")
        
        # Step 4: Show breakdown by namespace
        print(f"\n   Breakdown by namespace:")
        cur.execute("""
            SELECT namespace, COUNT(*) as count 
            FROM ailog_peak.peak_statistics 
            GROUP BY namespace 
            ORDER BY namespace
        """)
        
        for ns, count in cur.fetchall():
            status = "✅" if count == len(all_times) else "⚠️"
            print(f"   {status} {ns}: {count} windows")
        
        cur.close()
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
        cur.close()
        conn.close()
        return False


def main():
    success = fill_missing_windows()
    
    if success:
        print("\n" + "=" * 80)
        print("✅ Filling complete!")
        print("=" * 80)
        print("\n📌 Next steps:")
        print("   1. INIT Phase 2 (8.12-14.12) can now be run as REGULAR phase")
        print("   2. Use: python3 ingest_from_log.py --input /tmp/peak_fixed_2025_12_08_09.txt")
        print("   3. Repeat for all 4 files (08_09, 10_11, 12_13, 14_15)")
        return 0
    else:
        print("\n❌ Failed to fill missing windows")
        return 1


if __name__ == '__main__':
    sys.exit(main())
