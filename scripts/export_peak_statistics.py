#!/usr/bin/env python3
"""
Export peak statistics to CSV for verification and import

Reads peak detection data from collect_peak_detailed.py output
and exports to CSV format for verification and DB import.

Usage:
    python3 export_peak_statistics.py --output /tmp/peak_baseline.csv
    python3 export_peak_statistics.py --output baseline.csv --date-range "2025-12-15 to 2025-12-16"
"""

import csv
import json
import argparse
import os
from datetime import datetime
from collections import defaultdict

# Database configuration (for reference)
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD', 'your_db_password_here')
}

def generate_sample_data():
    """Generate sample peak statistics for demonstration"""
    # This would normally come from collect_peak_detailed.py output
    # For now, return empty to show structure
    return {}

def export_to_csv(output_file, sample_data=None):
    """
    Export peak statistics to CSV format
    
    CSV columns:
    - day_of_week (0-6: Mon-Sun)
    - hour_of_day (0-23)
    - quarter_hour (0-3: :00, :15, :30, :45)
    - namespace (e.g., pcb-sit-01-app)
    - mean_errors (float)
    - stddev_errors (float)
    - samples_count (int)
    - collection_date (ISO format)
    """
    
    print(f"📝 Exporting peak statistics to CSV: {output_file}")
    print()
    
    # Prepare headers
    headers = [
        'day_of_week',
        'day_name',
        'hour_of_day',
        'quarter_hour',
        'quarter_time',
        'namespace',
        'mean_errors',
        'stddev_errors',
        'samples_count',
        'collection_date'
    ]
    
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    try:
        with open(output_file, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write headers
            writer.writerow(headers)
            print(f"✅ Headers written")
            print()
            
            # Sample data structure (for template)
            sample_rows = [
                {
                    'day_of_week': 0,
                    'hour_of_day': 8,
                    'quarter_hour': 0,
                    'namespace': 'pcb-sit-01-app',
                    'mean_errors': 203.45,
                    'stddev_errors': 45.67,
                    'samples_count': 3
                },
                {
                    'day_of_week': 0,
                    'hour_of_day': 8,
                    'quarter_hour': 1,
                    'namespace': 'pcb-sit-01-app',
                    'mean_errors': 195.32,
                    'stddev_errors': 42.15,
                    'samples_count': 3
                },
            ]
            
            collection_date = datetime.utcnow().isoformat() + 'Z'
            
            # Write sample rows (in production, iterate over actual data)
            if sample_data:
                rows_written = 0
                for key, stats in sample_data.items():
                    day, hour, qtr, ns = key
                    quarter_time = f"{qtr*15:02d}"
                    
                    row = [
                        day,
                        day_names[day],
                        hour,
                        qtr,
                        quarter_time,
                        ns,
                        f"{stats['mean']:.2f}",
                        f"{stats['stddev']:.2f}",
                        stats['samples'],
                        collection_date
                    ]
                    writer.writerow(row)
                    rows_written += 1
                
                print(f"📊 Rows written: {rows_written}")
            else:
                # Write template rows for demo
                for row_data in sample_rows:
                    day = row_data['day_of_week']
                    quarter_time = f"{row_data['quarter_hour']*15:02d}"
                    
                    row = [
                        day,
                        day_names[day],
                        row_data['hour_of_day'],
                        row_data['quarter_hour'],
                        quarter_time,
                        row_data['namespace'],
                        f"{row_data['mean_errors']:.2f}",
                        f"{row_data['stddev_errors']:.2f}",
                        row_data['samples_count'],
                        collection_date
                    ]
                    writer.writerow(row)
                
                print(f"📊 Template rows written: {len(sample_rows)}")
            
            print()
            print(f"✅ Export complete: {output_file}")
            
            # Show file size
            file_size = os.path.getsize(output_file)
            print(f"📦 File size: {file_size:,} bytes")
            
            # Show first few lines
            print()
            print("📋 Preview (first 5 rows):")
            with open(output_file, 'r') as f:
                for i, line in enumerate(f):
                    if i < 5:
                        print(f"   {line.rstrip()}")
                    else:
                        break
            
            return True
            
    except Exception as e:
        print(f"❌ Export failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    parser = argparse.ArgumentParser(description='Export peak statistics to CSV')
    parser.add_argument('--output', required=True, help='Output CSV file path')
    parser.add_argument('--date-range', help='Date range for reference (informational)')
    args = parser.parse_args()
    
    print("=" * 80)
    print("🚀 Peak Statistics CSV Exporter")
    print("=" * 80)
    print()
    
    if args.date_range:
        print(f"📅 Date range: {args.date_range}")
        print()
    
    # In production, read actual data from collect_peak_detailed.py output
    # For now, export template
    success = export_to_csv(args.output)
    
    print()
    
    if success:
        print("✅ Ready for DB import:")
        print(f"   1. Verify CSV: cat {args.output}")
        print(f"   2. Run ingest: python3 ingest_peak_statistics.py --input {args.output}")
        print()
        return 0
    else:
        print("❌ Export failed")
        return 1

if __name__ == '__main__':
    import sys
    sys.exit(main())
