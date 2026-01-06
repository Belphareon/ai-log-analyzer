#!/usr/bin/env python3
"""
Export peaks with context: ±2 time windows around each detected peak
Shows actual values to analyze patterns
"""

import os
import sys
import psycopg2
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}

# Parse peaks from ingestion log
def parse_peaks_from_log(log_file='/tmp/ingestion.log'):
    """Extract peak info from ingestion log"""
    peaks = []
    
    with open(log_file, 'r') as f:
        for line in f:
            if 'PEAK' in line and '(' in line:
                # Extract: (day,hour,quarter,namespace): value (ref: X, ratio: Y×)
                try:
                    parts = line.split('(')
                    coords = parts[1].split(')')[0]
                    day, hour, quarter, namespace = coords.split(',')
                    
                    value_part = parts[1].split(':')[1].strip()
                    value = float(value_part.split('(')[0].strip())
                    
                    ratio_part = line.split('ratio: ')[1].split('×')[0]
                    ratio = float(ratio_part)
                    
                    category = '🔴 EXTREME' if ratio > 100 else ('🟠 SEVERE' if ratio >= 50 else '🟡 MODERATE')
                    
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

def get_context_data(conn, peak):
    """Get ±2 time windows around peak"""
    cur = conn.cursor()
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    # Query for context windows
    sql = """
    SELECT day_of_week, hour_of_day, quarter_hour, mean_errors, stddev_errors, samples_count
    FROM ailog_peak.peak_statistics
    WHERE namespace = %s
      AND day_of_week = %s
      AND (
        (hour_of_day = %s AND quarter_hour BETWEEN %s AND %s) OR
        (hour_of_day = %s AND quarter_hour >= %s) OR
        (hour_of_day = %s AND quarter_hour <= %s)
      )
    ORDER BY hour_of_day, quarter_hour
    """
    
    # Calculate time window boundaries
    hour = peak['hour']
    quarter = peak['quarter']
    
    # ±2 quarters = ±30 minutes
    start_hour = hour - 1 if quarter < 2 else hour
    end_hour = hour + 1 if quarter > 1 else hour
    start_quarter = (quarter - 2) % 4
    end_quarter = (quarter + 2) % 4
    
    try:
        cur.execute(sql, (
            peak['namespace'],
            peak['day'],
            hour, max(0, quarter-2), min(3, quarter+2),
            start_hour, start_quarter,
            end_hour, end_quarter
        ))
        
        rows = cur.fetchall()
        context = []
        
        for row in rows:
            d, h, q, mean, stddev, samples = row
            time_str = f"{day_names[d]} {h:02d}:{q*15:02d}"
            context.append({
                'time': time_str,
                'mean': mean,
                'stddev': stddev,
                'samples': samples,
                'is_peak': (d == peak['day'] and h == peak['hour'] and q == peak['quarter'])
            })
        
        cur.close()
        return context
        
    except Exception as e:
        cur.close()
        return []

def main():
    print("📊 Peak Analysis: Extracting peaks with context")
    print("=" * 80)
    
    # Parse peaks from log
    peaks = parse_peaks_from_log()
    print(f"✅ Found {len(peaks)} peaks in ingestion log\n")
    
    # Sort by ratio (highest first)
    peaks_sorted = sorted(peaks, key=lambda x: x['ratio'], reverse=True)
    
    # Connect to DB
    conn = psycopg2.connect(**DB_CONFIG)
    
    # Output file
    output_file = '/tmp/peaks_analysis.txt'
    
    with open(output_file, 'w') as f:
        f.write("PEAK ANALYSIS REPORT\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total peaks detected: {len(peaks)}\n\n")
        
        # Summary by category
        extreme = [p for p in peaks if p['ratio'] > 100]
        severe = [p for p in peaks if 50 <= p['ratio'] <= 100]
        moderate = [p for p in peaks if 15 <= p['ratio'] < 50]
        
        f.write(f"🔴 EXTREME (>100×): {len(extreme)} peaks\n")
        f.write(f"🟠 SEVERE (50-100×): {len(severe)} peaks\n")
        f.write(f"🟡 MODERATE (15-50×): {len(moderate)} peaks\n")
        f.write("\n" + "=" * 80 + "\n\n")
        
        # Timeline of all peaks
        f.write("TIMELINE OF ALL PEAKS (sorted by ratio)\n")
        f.write("-" * 80 + "\n")
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        for i, peak in enumerate(peaks_sorted, 1):
            time_str = f"{day_names[peak['day']]} {peak['hour']:02d}:{peak['quarter']*15:02d}"
            f.write(f"{i:2d}. {peak['category']} | {time_str} | {peak['namespace']:20s} | "
                   f"{peak['value']:8.1f} errors | ratio: {peak['ratio']:7.1f}×\n")
        
        f.write("\n" + "=" * 80 + "\n\n")
        
        # Detailed context for each peak
        f.write("DETAILED CONTEXT (±30 min around each peak)\n")
        f.write("=" * 80 + "\n\n")
        
        for i, peak in enumerate(peaks_sorted, 1):
            time_str = f"{day_names[peak['day']]} {peak['hour']:02d}:{peak['quarter']*15:02d}"
            
            f.write(f"\n{'=' * 80}\n")
            f.write(f"PEAK #{i}: {peak['category']}\n")
            f.write(f"Time: {time_str}\n")
            f.write(f"Namespace: {peak['namespace']}\n")
            f.write(f"Peak value: {peak['value']:.1f} errors\n")
            f.write(f"Ratio: {peak['ratio']:.1f}×\n")
            f.write(f"{'-' * 80}\n")
            
            # Get context
            context = get_context_data(conn, peak)
            
            if context:
                f.write("Time Window     | Mean Errors | StdDev | Samples | Note\n")
                f.write("-" * 80 + "\n")
                
                for row in context:
                    marker = " <-- PEAK" if row['is_peak'] else ""
                    f.write(f"{row['time']:15s} | {row['mean']:11.1f} | "
                           f"{row['stddev']:6.1f} | {row['samples']:7d} |{marker}\n")
            else:
                f.write("(Peak was skipped - not in DB)\n")
    
    conn.close()
    
    print(f"✅ Analysis complete!")
    print(f"📄 Report saved to: {output_file}")
    print(f"\n🔍 Preview (top 10 peaks):")
    print("-" * 80)
    
    day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for i, peak in enumerate(peaks_sorted[:10], 1):
        time_str = f"{day_names[peak['day']]} {peak['hour']:02d}:{peak['quarter']*15:02d}"
        print(f"{i:2d}. {peak['category']} | {time_str} | {peak['namespace']:20s} | "
              f"{peak['value']:8.1f} errors | {peak['ratio']:7.1f}×")

if __name__ == "__main__":
    main()
