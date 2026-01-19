#!/usr/bin/env python3
"""
Fill missing 15-minute windows in DB for INIT Phase (21 dní).

Problem:
- INIT Phase (1-21.12) má incomplete data pro některé namespaces
- Missing windows break Regular phase peak detection (nemůže se spočítat references)

Solution:
- Identifikuj všechny unique (day, hour, quarter) kombinace v DB
- Identifikuj všechny unique namespaces v DB
- Pro chybějící kombinace: INSERT s mean=0, stddev=0, samples=1
- Result: Complete grid namespaces × time windows

Use after INIT Phase ingestion, před REGULAR phase (peak detection).
"""

import sys
import os
import psycopg2

# Load environment variables manually
env_vars = {}
with open('.env') as f:
    for line in f:
        if line.strip() and not line.startswith('#') and '=' in line:
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

# Database configuration
DB_CONFIG = {
    'host': env_vars.get('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(env_vars.get('DB_PORT', 5432)),
    'database': env_vars.get('DB_NAME', 'ailog_analyzer'),
    'user': env_vars.get('DB_USER', 'ailog_analyzer_user_d1'),
    'password': env_vars.get('DB_PASSWORD')
}


def fill_missing_windows():
    """Fill missing windows in database"""

    print("=" * 80)
    print("🔧 Filling Missing Windows - INIT Phase (21 dní) Completion")
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
            FROM ailog_peak.peak_raw_data
            ORDER BY day_of_week, hour_of_day, quarter_hour
        """)
        all_times = cur.fetchall()
        print(f"   ✅ Found {len(all_times)} unique time windows")

        # Get all namespaces from existing data
        cur.execute("""
            SELECT DISTINCT namespace FROM ailog_peak.peak_raw_data
            ORDER BY namespace
        """)
        all_namespaces = [row[0] for row in cur.fetchall()]
        print(f"   ✅ Found {len(all_namespaces)} namespaces in data:")
        for ns in all_namespaces:
            print(f"      - {ns}")

        # Step 2: Find missing combinations and INSERT them
        print("\n🔄 Finding and inserting missing windows...")

        added = 0
        for day, hour, quarter in all_times:
            for ns in all_namespaces:
                # Check if this combination exists
                cur.execute("""
                    SELECT COUNT(*) FROM ailog_peak.peak_raw_data
                    WHERE day_of_week = %s AND hour_of_day = %s AND quarter_hour = %s AND namespace = %s
                """, (day, hour, quarter, ns))

                if cur.fetchone()[0] == 0:
                    # Missing - insert with mean=0 (no errors = healthy system)
                    cur.execute("""
                        INSERT INTO ailog_peak.peak_raw_data
                        (day_of_week, hour_of_day, quarter_hour, namespace, error_count, timestamp)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                    """, (day, hour, quarter, ns, 0.0))
                    added += 1

        conn.commit()
        print(f"   ✅ Added {added} missing windows (mean=0)")

        # Step 3: Verify result
        print("\n✅ Verifying result...")

        cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_raw_data")
        total_rows = cur.fetchone()[0]
        print(f"   Total rows now: {total_rows:,}")

        # Expected: len(all_times) * len(all_namespaces)
        expected = len(all_times) * len(all_namespaces)
        print(f"   Expected: {expected:,} (time_windows × namespaces)")

        if total_rows == expected:
            print(f"   ✅ PERFECT! Complete grid achieved!")
        else:
            print(f"   ⚠️  Mismatch: have {total_rows:,}, expected {expected:,}")

        # Step 4: Show breakdown by day_of_week
        print(f"\n   Breakdown by day_of_week:")
        cur.execute("""
            SELECT day_of_week, COUNT(*) as count
            FROM ailog_peak.peak_raw_data
            GROUP BY day_of_week
            ORDER BY day_of_week
        """)

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        expected_per_day = (len(all_times) // 7) * len(all_namespaces)
        
        for day, count in cur.fetchall():
            status = "✅" if count == expected_per_day else "⚠️"
            print(f"   {status} {day_names[day]} (day {day}): {count:,} rows")

        # Step 5: Show breakdown by namespace
        print(f"\n   Breakdown by namespace ({len(all_namespaces)}):")
        cur.execute("""
            SELECT namespace, COUNT(*) as count
            FROM ailog_peak.peak_raw_data
            GROUP BY namespace
            ORDER BY namespace
        """)

        expected_per_ns = len(all_times)
        for ns, count in cur.fetchall():
            status = "✅" if count == expected_per_ns else "⚠️"
            print(f"   {status} {ns}: {count:,} windows")

        # Step 6: Check for 21-day INIT Phase
        cur.execute("""
            SELECT MIN(day_of_week) as min_day, MAX(day_of_week) as max_day, 
                   COUNT(DISTINCT day_of_week) as unique_days
            FROM ailog_peak.peak_raw_data
        """)
        min_day, max_day, unique_days = cur.fetchone()
        print(f"\n   Days coverage: {unique_days} unique days (expected 7)")
        print(f"   Time windows per day: {len(all_times) // 7} (expected 96 = 24h × 4 quarters)")

        cur.close()
        conn.close()
        return True

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
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
        print("   1. Verify INIT Phase is complete: peak_raw_data should have 24,192 rows")
        print("   2. REGULAR Phase (DAILY with peak detection) can start")
        print("   3. Use: python3 ingest_from_log_v2.py /tmp/peak_fixed_2025_12_22.txt")
        return 0
    else:
        print("\n❌ Failed to fill missing windows")
        return 1


if __name__ == '__main__':
    sys.exit(main())
