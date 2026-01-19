#!/usr/bin/env python3
"""
Calculate Aggregation Baseline from peak_raw_data

Purpose: Create aggregation_data baseline from INIT phase (21 days)
- Group by (day_of_week, hour_of_day, quarter_hour, namespace)
- Calculate mean, stddev, samples for each combination
- Result: 7 days × 96 windows × 12 namespaces = 8,064 rows
"""

import os
import sys
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import execute_batch

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


def calculate_baseline(conn):
    """
    Calculate aggregation baseline from peak_raw_data
    
    Logic:
    1. Group peak_raw_data by (day_of_week, hour_of_day, quarter_hour, namespace)
    2. Calculate AVG(error_count), STDDEV(error_count), COUNT(*) for each group
    3. Insert into aggregation_data
    4. Include zeros for missing combinations (complete grid)
    """
    
    cur = conn.cursor()
    
    print("=" * 80)
    print("📊 Calculate Aggregation Baseline")
    print("=" * 80)
    
    # Step 1: Clear aggregation_data
    print("\n🗑️  Clearing aggregation_data...")
    cur.execute("DELETE FROM ailog_peak.aggregation_data;")
    deleted = cur.rowcount
    print(f"   ✅ Deleted {deleted} rows")
    
    # Step 2: Calculate aggregation from peak_raw_data
    print("\n📊 Calculating aggregation from peak_raw_data...")
    
    sql = """
    INSERT INTO ailog_peak.aggregation_data 
    (day_of_week, hour_of_day, quarter_hour, namespace, mean, stddev, samples)
    SELECT 
        day_of_week,
        hour_of_day,
        quarter_hour,
        namespace,
        AVG(error_count) as mean,
        COALESCE(STDDEV(error_count), 0.0) as stddev,
        COUNT(*) as samples
    FROM ailog_peak.peak_raw_data
    GROUP BY day_of_week, hour_of_day, quarter_hour, namespace
    ORDER BY day_of_week, hour_of_day, quarter_hour, namespace;
    """
    
    cur.execute(sql)
    inserted = cur.rowcount
    print(f"   ✅ Inserted {inserted:,} aggregated rows")
    
    conn.commit()
    
    # Step 3: Fill missing combinations with zeros (complete grid)
    print("\n📥 Filling missing combinations with zeros...")
    
    # Get list of all namespaces from data
    cur.execute("SELECT DISTINCT namespace FROM ailog_peak.aggregation_data ORDER BY namespace;")
    namespaces = [row[0] for row in cur.fetchall()]
    print(f"   Found {len(namespaces)} namespaces")
    
    # Generate all expected combinations
    all_combinations = []
    for day in range(7):  # 0-6
        for hour in range(24):  # 0-23
            for quarter in range(4):  # 0-3
                for ns in namespaces:
                    all_combinations.append((day, hour, quarter, ns))
    
    print(f"   Expected combinations: {len(all_combinations):,}")
    
    # Find missing combinations
    cur.execute("""
        SELECT day_of_week, hour_of_day, quarter_hour, namespace 
        FROM ailog_peak.aggregation_data;
    """)
    existing = set(cur.fetchall())
    
    missing = [combo for combo in all_combinations if combo not in existing]
    
    if missing:
        print(f"   Missing: {len(missing):,} combinations - filling with zeros...")
        
        sql_insert = """
        INSERT INTO ailog_peak.aggregation_data 
        (day_of_week, hour_of_day, quarter_hour, namespace, mean, stddev, samples)
        VALUES (%s, %s, %s, %s, 0.0, 0.0, 0);
        """
        
        for day, hour, quarter, ns in missing:
            cur.execute(sql_insert, (day, hour, quarter, ns))
        
        conn.commit()
        print(f"   ✅ Inserted {len(missing):,} zero rows")
    else:
        print(f"   ✅ No missing combinations - grid complete!")
    
    conn.commit()
    
    # Step 3: Verification
    print("\n✅ Verification:")
    
    cur.execute("SELECT COUNT(*) FROM ailog_peak.aggregation_data;")
    total = cur.fetchone()[0]
    print(f"   Total rows in aggregation_data: {total:,}")
    
    cur.execute("SELECT COUNT(DISTINCT day_of_week) FROM ailog_peak.aggregation_data;")
    days = cur.fetchone()[0]
    print(f"   Distinct days: {days}")
    
    cur.execute("SELECT COUNT(DISTINCT namespace) FROM ailog_peak.aggregation_data;")
    namespaces = cur.fetchone()[0]
    print(f"   Distinct namespaces: {namespaces}")
    
    cur.execute("SELECT MIN(samples), MAX(samples), AVG(samples) FROM ailog_peak.aggregation_data;")
    min_s, max_s, avg_s = cur.fetchone()
    print(f"   Samples per key: min={min_s}, max={max_s}, avg={avg_s:.1f}")
    
    print("\n" + "=" * 80)
    print("✅ Aggregation baseline calculated successfully!")
    print("=" * 80)
    
    return True


def main():
    print("📊 Calculate Aggregation Baseline from peak_raw_data")
    print("=" * 80)
    
    # Connect to DB
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1
    
    # Calculate baseline
    try:
        success = calculate_baseline(conn)
        conn.close()
        return 0 if success else 1
    except Exception as e:
        print(f"❌ Error calculating baseline: {e}")
        conn.rollback()
        conn.close()
        return 1


if __name__ == '__main__':
    sys.exit(main())
