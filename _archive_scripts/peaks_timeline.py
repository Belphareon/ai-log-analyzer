#!/usr/bin/env python3
"""
Export peaks as timeline - grouped by time
Shows all namespaces that have peaks at the same time together
"""

import os
import sys
from collections import defaultdict
from dotenv import load_dotenv

load_dotenv()

def get_actual_dates():
    """Map day_of_week to actual dates from data range 2025-12-01 to 2025-12-16"""
    from datetime import datetime, timedelta
    
    # Reference: 2025-12-01 is Sunday (day_of_week=6)
    reference_date = datetime(2025, 12, 1)  # Sunday
    reference_day = 6
    
    # Find first occurrence of each day_of_week
    day_to_date = {}
    for offset in range(16):  # 16 days of data
        current_date = reference_date + timedelta(days=offset)
        current_day = current_date.weekday()  # 0=Mon, 6=Sun
        if current_day not in day_to_date:
            day_to_date[current_day] = current_date
    
    return day_to_date

def parse_peaks_from_log(log_file='/tmp/ingestion.log'):
    """Extract peak info from ingestion log"""
    peaks = []
    
    with open(log_file, 'r') as f:
        for line in f:
            if 'PEAK' in line and '(' in line:
                try:
                    parts = line.split('(')
                    coords = parts[1].split(')')[0]
                    day, hour, quarter, namespace = coords.split(',')
                    
                    value_part = parts[1].split(':')[1].strip()
                    value = float(value_part.split('(')[0].strip())
                    
                    ratio_part = line.split('ratio: ')[1].split('×')[0]
                    ratio = float(ratio_part)
                    
                    category = '🔴' if ratio > 100 else ('🟠' if ratio >= 50 else '🟡')
                    
                    peaks.append({
                        'day': int(day),
                        'hour': int(hour),
                        'quarter': int(quarter),
                        'namespace': namespace.strip(),
                        'value': value,
                        'ratio': ratio,
                        'category': category
                    })
                except:
                    continue
    
    return peaks

def main():
    peaks = parse_peaks_from_log()
    day_to_date = get_actual_dates()
    
    # Group by time (day, hour, quarter)
    timeline = defaultdict(list)
    for peak in peaks:
        key = (peak['day'], peak['hour'], peak['quarter'])
        timeline[key].append(peak)
    
    # Sort timeline by day, hour, quarter
    sorted_timeline = sorted(timeline.items(), key=lambda x: (x[0][0], x[0][1], x[0][2]))
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    print("\n" + "="*100)
    print("PEAK TIMELINE - Grouped by Time Slot")
    print("="*100)
    print(f"Total: {len(peaks)} peaks across {len(sorted_timeline)} different time slots\n")
    
    output_file = '/tmp/peaks_timeline.txt'
    
    with open(output_file, 'w') as f:
        f.write("PEAK TIMELINE - Grouped by Time Slot\n")
        f.write("="*100 + "\n")
        f.write(f"Total: {len(peaks)} peaks across {len(sorted_timeline)} different time slots\n\n")
        
        for (day, hour, quarter), peaks_at_time in sorted_timeline:
            actual_date = day_to_date.get(day)
            date_str = actual_date.strftime('%Y-%m-%d') if actual_date else '????-??-??'
            time_str = f"{date_str} {day_names[day]} {hour:02d}:{quarter*15:02d}"
            
            # Print to console
            print(f"📅 {time_str}")
            print("-" * 100)
            
            # Write to file
            f.write(f"\n📅 {time_str}\n")
            f.write("-" * 100 + "\n")
            
            # Sort by ratio within same time
            peaks_sorted = sorted(peaks_at_time, key=lambda x: x['ratio'], reverse=True)
            
            for peak in peaks_sorted:
                line = f"   {peak['category']} {peak['namespace']:25s}  {peak['value']:10,.0f} errors  (ratio: {peak['ratio']:7.1f}×)"
                print(line)
                f.write(line + "\n")
            
            print()
    
    print("="*100)
    print(f"✅ Timeline saved to: {output_file}\n")
    
    # Summary statistics
    extreme = sum(1 for p in peaks if p['ratio'] > 100)
    severe = sum(1 for p in peaks if 50 <= p['ratio'] <= 100)
    moderate = sum(1 for p in peaks if 15 <= p['ratio'] < 50)
    
    print("📊 Summary:")
    print(f"   🔴 EXTREME (>100×):   {extreme:2d} peaks")
    print(f"   🟠 SEVERE (50-100×):  {severe:2d} peaks")
    print(f"   🟡 MODERATE (15-50×): {moderate:2d} peaks")
    print(f"   {'─'*40}")
    print(f"   TOTAL:                {len(peaks):2d} peaks")

if __name__ == "__main__":
    main()
