#!/usr/bin/env python3
"""
Fix timezone offset in collected .txt files
Shift all times by +1 hour (UTC -> CET conversion)

Example:
  Thu 06:00 -> Thu 07:00
  Thu 23:00 -> Fri 00:00
  Sun 23:00 -> Mon 00:00
"""

import sys
import re
import argparse
from pathlib import Path


def shift_time_plus_one_hour(day_name, hour):
    """
    Shift time by +1 hour, handling day rollover
    
    Args:
        day_name: Mon, Tue, Wed, Thu, Fri, Sat, Sun
        hour: 0-23
    
    Returns: (new_day_name, new_hour)
    """
    
    days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    
    new_hour = hour + 1
    new_day_name = day_name
    
    if new_hour >= 24:
        # Rollover to next day
        new_hour = 0
        day_idx = days.index(day_name)
        new_day_idx = (day_idx + 1) % 7
        new_day_name = days[new_day_idx]
    
    return new_day_name, new_hour


def fix_timezone_in_file(input_file, output_file):
    """
    Fix timezone in .txt file by shifting all times +1 hour
    
    Pattern format:
       Pattern N: Day HH:MM - namespace
    
    Example:
       Pattern 93: Thu 06:00 - pcb-ch-sit-01-app
       ->
       Pattern 93: Thu 07:00 - pcb-ch-sit-01-app
    """
    
    print(f"📖 Reading: {input_file}")
    
    try:
        with open(input_file, 'r') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ File not found: {input_file}")
        return False
    
    # Regex to match pattern lines: "Pattern N: Day HH:MM - namespace"
    pattern_regex = r'(Pattern \d+: )(\w+) (\d+):(\d+)( - .+)'
    
    def replace_time(match):
        """Replace function for re.sub"""
        prefix = match.group(1)      # "Pattern N: "
        day_name = match.group(2)    # "Thu"
        hour = int(match.group(3))   # 6
        minute = int(match.group(4)) # 0
        suffix = match.group(5)      # " - pcb-ch-sit-01-app"
        
        # Shift time by +1 hour
        new_day, new_hour = shift_time_plus_one_hour(day_name, hour)
        
        # Build new line
        return f"{prefix}{new_day} {new_hour:02d}:{minute:02d}{suffix}"
    
    # Replace all pattern lines
    fixed_content = re.sub(pattern_regex, replace_time, content)
    
    # Count changes
    original_matches = re.findall(pattern_regex, content)
    print(f"✅ Found {len(original_matches)} patterns to fix")
    
    # Write output
    print(f"💾 Writing: {output_file}")
    with open(output_file, 'w') as f:
        f.write(fixed_content)
    
    print(f"✅ Fixed timezone offset (+1h)")
    
    return True


def main():
    parser = argparse.ArgumentParser(description='Fix timezone offset in .txt files (+1h UTC->CET)')
    parser.add_argument('--input', required=True, help='Input .txt file')
    parser.add_argument('--output', required=True, help='Output .txt file (can be same as input)')
    args = parser.parse_args()
    
    print("="*80)
    print("🕐 Timezone Fix - Shift +1 hour (UTC -> CET)")
    print("="*80)
    
    success = fix_timezone_in_file(args.input, args.output)
    
    if success:
        print("\n✅ Done!")
        return 0
    else:
        print("\n❌ Failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
