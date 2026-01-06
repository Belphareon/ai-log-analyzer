#!/usr/bin/env python3
"""
Analyze problematic peaks that were NOT skipped
"""
import psycopg2
import os
import sys

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv
load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

problems = [
    ('Fri', 4, 7, 0, 'pcb-ch-sit-01-app', 2892.0, 2884),
    ('Sat', 5, 7, 0, 'pcb-ch-sit-01-app', 2892.5, 2885),
]

days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']

for day_str, day_of_week, hour, minute, ns, db_value, expected in problems:
    quarter = minute // 15
    
    print('\n' + '='*90)
    print(f'{day_str} {hour:02d}:{minute:02d} {ns}')
    print(f'  DB value: {db_value:.1f}  |  Expected peak: {expected}')
    print('='*90)
    
    prev_days = [(day_of_week - 1 + 7) % 7, (day_of_week - 2 + 7) % 7, (day_of_week - 3 + 7) % 7]
    prev_names = [days[d] for d in prev_days]
    print(f'\nReference days (3 previous): {", ".join(prev_names)}')
    
    cur.execute('''
        SELECT day_of_week, mean_errors FROM ailog_peak.peak_statistics
        WHERE namespace = %s AND day_of_week IN (%s, %s, %s) AND hour_of_day = %s AND quarter_hour = %s
        ORDER BY day_of_week
    ''', (ns, prev_days[0], prev_days[1], prev_days[2], hour, quarter))
    
    refs = cur.fetchall()
    if refs:
        print(f'\n✅ Reference values found: {len(refs)}')
        for ref_day, ref_val in refs:
            day_name = days[ref_day]
            print(f'  - {day_name}: {ref_val:.1f}')
        
        ref_values = [r[1] for r in refs]
        ref_sorted = sorted(ref_values)
        median = ref_sorted[len(ref_sorted)//2] if len(ref_sorted) % 2 == 1 else (ref_sorted[len(ref_sorted)//2-1] + ref_sorted[len(ref_sorted)//2])/2
        
        if median > 0:
            ratio = db_value / median
            print(f'\n📊 Analysis:')
            print(f'  Median reference: {median:.1f}')
            print(f'  Ratio: {db_value:.1f} / {median:.1f} = {ratio:.2f}×')
            print(f'  Threshold: 15.0×')
            if ratio >= 15.0:
                print(f'  ❌ Status: SHOULD HAVE BEEN SKIPPED!')
                print(f'     → Peak ratio {ratio:.1f}× exceeds threshold 15×')
            else:
                print(f'  ✅ Status: Below threshold (not a peak by definition)')
    else:
        print('\n❌ NO REFERENCES FOUND')
        print('   → Peak detection could NOT run (no historical data)')
        print('   → This is WHY it was NOT skipped during ingest')
        print(f'\n💡 SOLUTION: Need to do 2-pass ingest:')
        print(f'   1. First pass: ingest all data (including peaks)')
        print(f'   2. Second pass: detect and delete peaks based on full dataset')

cur.close()
conn.close()
