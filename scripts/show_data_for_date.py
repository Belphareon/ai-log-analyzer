#!/usr/bin/env python3
"""
Analyze actual data from DB - show all patterns including peaks that were skipped
Compare with reference values to identify anomalies
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
from datetime import datetime
from collections import defaultdict

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

def get_db_data_for_date_range(conn, start_date, end_date):
    """Get all data from DB for date range"""
    cur = conn.cursor()
    
    # Map dates to day_of_week
    from datetime import datetime, timedelta
    
    reference_date = datetime(2025, 12, 1)  # Sunday
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    days_of_week = set()
    current = start
    while current <= end:
        days_of_week.add(current.weekday())
        current += timedelta(days=1)
    
    sql = """
    SELECT day_of_week, hour_of_day, quarter_hour, namespace, mean_errors, stddev_errors, samples_count
    FROM ailog_peak.peak_statistics
    WHERE day_of_week = ANY(%s)
    ORDER BY day_of_week, hour_of_day, quarter_hour, namespace
    """
    
    cur.execute(sql, (list(days_of_week),))
    rows = cur.fetchall()
    cur.close()
    
    return rows

def main():
    if len(sys.argv) < 3:
        print("Usage: python show_data_for_date.py START_DATE END_DATE")
        print("Example: python show_data_for_date.py 2025-12-04 2025-12-05")
        sys.exit(1)
    
    start_date = sys.argv[1]
    end_date = sys.argv[2]
    
    print(f"\n{'='*100}")
    print(f"DATA ANALYSIS: {start_date} to {end_date}")
    print(f"{'='*100}\n")
    
    conn = psycopg2.connect(**DB_CONFIG)
    rows = get_db_data_for_date_range(conn, start_date, end_date)
    conn.close()
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Map day_of_week to actual date
    from datetime import datetime, timedelta
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    day_to_dates = defaultdict(list)
    current = start
    while current <= end:
        day_to_dates[current.weekday()].append(current)
        current += timedelta(days=1)
    
    # Group by time slot
    timeline = defaultdict(lambda: defaultdict(list))
    for row in rows:
        day, hour, quarter, namespace, mean, stddev, samples = row
        key = (day, hour, quarter)
        timeline[key][namespace].append({
            'mean': mean,
            'stddev': stddev,
            'samples': samples
        })
    
    # Sort and display
    sorted_timeline = sorted(timeline.items(), key=lambda x: (x[0][0], x[0][1], x[0][2]))
    
    print(f"Found {len(rows)} data points in {len(sorted_timeline)} time slots\n")
    
    for (day, hour, quarter), namespaces in sorted_timeline:
        dates = day_to_dates.get(day, [])
        date_strs = ', '.join([d.strftime('%Y-%m-%d') for d in dates])
        time_str = f"{date_strs} {day_names[day]} {hour:02d}:{quarter*15:02d}"
        
        # Check if any value is high (>100 errors)
        max_val = max([ns[0]['mean'] for ns in namespaces.values()])
        marker = " ⚠️ HIGH" if max_val > 100 else ""
        
        print(f"\n📅 {time_str}{marker}")
        print("-" * 100)
        
        for namespace in sorted(namespaces.keys()):
            data = namespaces[namespace][0]
            print(f"   {namespace:25s}  {data['mean']:8.1f} errors  (stddev: {data['stddev']:6.1f}, samples: {data['samples']})")

if __name__ == "__main__":
    main()
