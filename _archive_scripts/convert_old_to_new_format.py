#!/usr/bin/env python3
"""
Convert old format files (without timestamp) to new DATA| format with timestamp.

Old format: Human-readable report with Pattern N: ... lines
New format: DATA|TIMESTAMP|day_of_week|hour|quarter|namespace|mean|stddev|samples

Usage:
    python3 convert_old_to_new_format.py --input /tmp/peak_fixed_2025_12_01.txt --output /tmp/peak_2025_12_01_CONVERTED.txt
    
The script extracts date from filename and reconstructs timestamp from (date, hour, quarter).
"""

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path


def extract_date_from_filename(filename):
    """
    Extract date from filename like: peak_fixed_2025_12_01.txt → 2025-12-01
    Also handles: peak_fixed_2025_12_02_03.txt → 2025-12-02 (uses first date)
    """
    # Pattern: YYYY_MM_DD
    match = re.search(r'(\d{4})_(\d{2})_(\d{2})', filename)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    
    raise ValueError(f"Cannot extract date from filename: {filename}")


def parse_old_format_line(line):
    """
    Parse old format line like:
    "   Pattern 1: Mon 11:15 - pcb-dev-01-app"
    "      Mean: 10.00, StdDev: 0.00, Samples: 1"
    
    Returns dict with parsed data or None if not a pattern line
    """
    # Pattern line: "Pattern N: Day HH:MM - namespace"
    pattern_match = re.match(r'\s+Pattern\s+\d+:\s+(\w+)\s+(\d{1,2}):(\d{2})\s+-\s+(.+)', line)
    if pattern_match:
        day_name, hour_str, minute_str, namespace = pattern_match.groups()
        
        # Convert day name to day_of_week (0-6)
        days = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
        day_of_week = days.get(day_name)
        
        hour = int(hour_str)
        minute = int(minute_str)
        quarter = minute // 15
        
        return {
            'day_of_week': day_of_week,
            'hour': hour,
            'quarter': quarter,
            'namespace': namespace.strip()
        }
    
    # Stats line: "Mean: X.XX, StdDev: Y.YY, Samples: Z"
    stats_match = re.match(r'\s+Mean:\s+([\d.]+),\s+StdDev:\s+([\d.]+),\s+Samples:\s+(\d+)', line)
    if stats_match:
        mean, stddev, samples = stats_match.groups()
        return {
            'mean': float(mean),
            'stddev': float(stddev),
            'samples': int(samples)
        }
    
    return None


def convert_file(input_file, output_file):
    """
    Convert old format file to new DATA| format with timestamp.
    """
    input_path = Path(input_file)
    
    # Extract date from filename
    try:
        base_date = extract_date_from_filename(input_path.name)
        print(f"📅 Extracted date from filename: {base_date}")
    except ValueError as e:
        print(f"❌ Error: {e}")
        return False
    
    # Parse date
    date_obj = datetime.strptime(base_date, "%Y-%m-%d")
    
    # Read and parse old format
    data_lines = []
    current_pattern = None
    
    with open(input_file, 'r') as f:
        for line in f:
            parsed = parse_old_format_line(line)
            
            if parsed:
                if 'day_of_week' in parsed:
                    # This is a pattern line
                    current_pattern = parsed
                elif 'mean' in parsed and current_pattern:
                    # This is a stats line, combine with current pattern
                    current_pattern.update(parsed)
                    
                    # Reconstruct timestamp
                    timestamp = date_obj.replace(
                        hour=current_pattern['hour'],
                        minute=current_pattern['quarter'] * 15,
                        second=0,
                        microsecond=0
                    )
                    
                    # Create DATA line
                    data_line = (
                        f"DATA|{timestamp.strftime('%Y-%m-%dT%H:%M:%S')}|"
                        f"{current_pattern['day_of_week']}|"
                        f"{current_pattern['hour']}|"
                        f"{current_pattern['quarter']}|"
                        f"{current_pattern['namespace']}|"
                        f"{current_pattern['mean']:.2f}|"
                        f"{current_pattern['stddev']:.2f}|"
                        f"{current_pattern['samples']}"
                    )
                    data_lines.append(data_line)
                    current_pattern = None
    
    # Write converted data
    with open(output_file, 'w') as f:
        f.write("="*80 + "\n")
        f.write(f"🔄 CONVERTED FROM OLD FORMAT\n")
        f.write(f"Source: {input_path.name}\n")
        f.write(f"Date: {base_date}\n")
        f.write(f"Converted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*80 + "\n")
        f.write("\n")
        f.write("Format: DATA|TIMESTAMP|day_of_week|hour|quarter|namespace|mean|stddev|samples\n")
        f.write("\n")
        
        for line in data_lines:
            f.write(line + "\n")
    
    print(f"✅ Converted {len(data_lines)} data lines")
    print(f"✅ Output: {output_file}")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='Convert old format to new DATA| format with timestamp')
    parser.add_argument('--input', required=True, help='Input file (old format)')
    parser.add_argument('--output', required=True, help='Output file (new format)')
    args = parser.parse_args()
    
    print("="*80)
    print("🔄 Converting old format to new DATA| format")
    print("="*80)
    print()
    
    success = convert_file(args.input, args.output)
    
    if success:
        print()
        print("✅ Conversion complete!")
        return 0
    else:
        print()
        print("❌ Conversion failed!")
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
