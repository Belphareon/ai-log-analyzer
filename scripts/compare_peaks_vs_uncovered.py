#!/usr/bin/env python3
"""
Compare detected peaks vs uncovered buckets
============================================
"""

import json
from pathlib import Path
from datetime import datetime, timezone

repo = Path('/home/jvsete/git/ai-log-analyzer')

# Load detected peaks
with open(repo / 'ai-data' / 'active_peaks_24h_investigation.json') as f:
    data = json.load(f)
    detected_peaks = data.get('peaks', [])

# Uncovered buckets
uncovered_buckets = [
    ('2026-02-23 15:30', 'pcb-sit-01-app', 322),
    ('2026-02-23 16:45', 'pcb-dev-01-app', 336),
    ('2026-02-23 16:45', 'pcb-fat-01-app', 335),
    ('2026-02-23 16:45', 'pcb-uat-01-app', 335),
    ('2026-02-23 17:00', 'pcb-dev-01-app', 2397),
    ('2026-02-23 17:00', 'pcb-fat-01-app', 2450),
    ('2026-02-23 17:00', 'pcb-uat-01-app', 2450),
    ('2026-02-23 21:30', 'pcb-sit-01-app', 540),
    ('2026-02-24 05:00', 'pcb-dev-01-app', 278),
    ('2026-02-24 05:00', 'pcb-sit-01-app', 437),
    ('2026-02-24 05:00', 'pcb-uat-01-app', 580),
    ('2026-02-24 07:30', 'pcb-dev-01-app', 35898),
    ('2026-02-24 07:30', 'pcb-sit-01-app', 32460),
    ('2026-02-24 07:45', 'pcb-dev-01-app', 28145),
    ('2026-02-24 07:45', 'pcb-sit-01-app', 31862),
    ('2026-02-24 08:00', 'pcb-sit-01-app', 16972),
    ('2026-02-24 08:45', 'pcb-sit-01-app', 248),
    ('2026-02-24 11:30', 'pcb-sit-01-app', 201),
    ('2026-02-24 12:00', 'pcb-sit-01-app', 225),
    ('2026-02-24 13:30', 'pcb-dev-01-app', 12044),
    ('2026-02-24 13:30', 'pcb-sit-01-app', 11061),
    ('2026-02-24 13:45', 'pcb-dev-01-app', 34565),
    ('2026-02-24 13:45','pcb-sit-01-app', 32254),
    ('2026-02-24 14:00', 'pcb-dev-01-app', 17548),
    ('2026-02-24 14:00', 'pcb-sit-01-app', 32977),
    ('2026-02-24 14:15', 'pcb-dev-01-app', 437),
    ('2026-02-24 14:15', 'pcb-sit-01-app', 5267),
    ('2026-02-24 14:30', 'pcb-fat-01-app', 2845),
    ('2026-02-24 14:30', 'pcb-uat-01-app', 2720),
]

print("="*120)
print("DETECTED PEAKS IN INVESTIGATION")
print("="*120)

for peak in detected_peaks:
    peak_id = peak.get('peak_id', '?')
    problem_key = peak.get('problem_key', '?')
    peak_type = peak.get('peak_type', '?').upper()
    windows = peak.get('peak_windows', [])
    namespaces = set(w['namespace'] for w in windows)
    
    print(f"\n{peak_id}: {problem_key} ({peak_type})")
    print(f"  Namespaces: {', '.join(sorted(namespaces))}")
    print(f"  Windows: {len(windows)}")
    for w in sorted(windows, key=lambda x: x['from'])[:3]:
        print(f"    - {w['namespace']}: {w['from']} to {w['to']} ({w['bucket_count_sum']} errors)")
    if len(windows) > 3:
        print(f"    ... and {len(windows)-3} more")

print("\n" + "="*120)
print("UNCOVERED HIGH BUCKETS (NOT in detected peaks)")
print("="*120)

def parse_ts(s):
    return datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)

def window_overlaps(bucket_ts, ns, peak_windows):
    """Check if bucket overlaps any peak window"""
    bucket_start = bucket_ts
    bucket_end = bucket_ts.replace(minute=bucket_ts.minute+15 if bucket_ts.minute < 45 else 0,
                                    hour=bucket_ts.hour if bucket_ts.minute < 45 else bucket_ts.hour+1)
    
    for w in peak_windows:
        w_start = parse_ts(w['from'])
        w_end = parse_ts(w['to'])
        w_ns = w['namespace']
        
        if w_ns != ns:
            continue
        
        # Check overlap
        if w_start < bucket_end and bucket_start < w_end:
            return True, w
    
    return False, None

print(f"\nTotal uncovered buckets: {len(uncovered_buckets)}\n")

for bucket_ts_str, namespace, count in sorted(uncovered_buckets, key=lambda x: (x[0], x[1])):
    bucket_ts = parse_ts(bucket_ts_str)
    
    # Check if ANY peak window covers this
    is_covered = False
    covering_peak = None
    for peak in detected_peaks:
        peak_id = peak.get('peak_id')
        windows = peak.get('peak_windows', [])
        overlaps, window = window_overlaps(bucket_ts, namespace, windows)
        if overlaps:
            is_covered = True
            covering_peak = peak_id
            break
    
    status = "✅ COVERED" if is_covered else "❌ UNCOVERED"
    print(f"{status} | {bucket_ts_str} | {namespace:20s} | {count:6,} errors" + 
          (f" (by {covering_peak})" if is_covered else ""))

print("\n" + "="*120)
print("ANALYSIS SUMMARY")
print("="*120)
print(f"\nDetected peaks: {len(detected_peaks)}")
print(f"Uncovered buckets: {len(uncovered_buckets)}")

# Count by error magnitude
high_500k = sum(1 for _, _, c in uncovered_buckets if c >= 10000)
others = len(uncovered_buckets) - high_500k
print(f"\nUncovered buckets by magnitude:")
print(f"  >= 10,000 errors: {high_500k}")
print(f"  < 10,000 errors: {others}")

# Total errors in uncovered
total_uncovered_errors = sum(c for _, _, c in uncovered_buckets)
print(f"\nTotal errors in uncovered buckets: {total_uncovered_errors:,}")
