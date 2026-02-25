#!/usr/bin/env python3
"""
Analyze what error types are in the uncovered buckets
================================================================
"""

import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

repo = Path('/home/jvsete/git/ai-log-analyzer')

# Load source cache
with open(repo / 'ai-data' / 'source_logs_24h_cache.json') as f:
    source_records = json.load(f)

# Parse timestamps and build index
records_by_bucket_ns = {}

for rec in source_records:
    ts_str = rec.get('timestamp', '')
    if not ts_str:
        continue
    
    # Parse ISO format
    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    ns = rec.get('namespace', 'unknown')
    
    # 15-min bucket
    bucket_min = (ts.minute // 15) * 15
    bucket_hour = ts.hour
    bucket_ts = ts.replace(minute=bucket_min, second=0, microsecond=0)
    bucket_key = f"{bucket_ts.strftime('%Y-%m-%d %H:%M')}|{ns}"
    
    if bucket_key not in records_by_bucket_ns:
        records_by_bucket_ns[bucket_key] = []
    
    records_by_bucket_ns[bucket_key].append(rec)

print("="*120)
print("ERROR TYPES IN UNCOVERED BUCKETS")
print("="*120)

uncovered_buckets = [
    ('2026-02-24 07:30', 'pcb-dev-01-app', 35898),
    ('2026-02-24 07:30', 'pcb-sit-01-app', 32460),
    ('2026-02-24 07:45', 'pcb-dev-01-app', 28145),
    ('2026-02-24 07:45', 'pcb-sit-01-app', 31862),
    ('2026-02-24 08:00', 'pcb-sit-01-app', 16972),
    ('2026-02-24 13:30', 'pcb-dev-01-app', 12044),
    ('2026-02-24 13:30', 'pcb-sit-01-app', 11061),
    ('2026-02-24 13:45', 'pcb-dev-01-app', 34565),
    ('2026-02-24 13:45', 'pcb-sit-01-app', 32254),
    ('2026-02-24 14:00', 'pcb-dev-01-app', 17548),
    ('2026-02-24 14:00', 'pcb-sit-01-app', 32977),
]

all_error_types = Counter()
for bucket_time, namespace, expected_count in uncovered_buckets:
    bucket_key = f"{bucket_time}|{namespace}"
    recs = records_by_bucket_ns.get(bucket_key, [])
    
    error_types = Counter()
    for rec in recs:
        msg = rec.get('message', '')
        # Try to extract error type from message
        if '#' in msg:
            parts = msg.split('#')
            if len(parts) > 1:
                error_id = parts[0]  # e.g., "ITO-154"
                error_types[error_id] += 1
        else:
            error_types['Unknown'] += 1
    
    all_error_types.update(error_types)
    
    print(f"\n{bucket_time} | {namespace:20s} | Expected: {expected_count:6,}, Found: {len(recs):6,}")
    print(f"   Top error types:")
    for et, count in error_types.most_common(5):
        print(f"      {et:15s}: {count:6,}")

print("\n" + "="*120)
print("TOP 20 ERROR TYPES ACROSS ALL UNCOVERED BUCKETS")
print("="*120)
for et, count in all_error_types.most_common(20):
    print(f"  {et:30s}: {count:6,} occurrences")

# Now load detected peaks and check which error types they cover
print("\n" + "="*120)
print("DETECTED PEAKS - WHAT ERROR TYPES DO THEY COVER?")
print("="*120)

with open(repo / 'ai-data' / 'active_peaks_24h_investigation.json') as f:
    data = json.load(f)
    peaks = data.get('peaks', [])

for peak in peaks[:5]:  # First 5 peaks
    peak_id = peak.get('peak_id')
    problem_key = peak.get('problem_key')
    error_count = peak.get('detected_occurrences_24h', 0)
    
    print(f"\n{peak_id}: {problem_key}")
    print(f"  Detected occurrences: {error_count:,}")
    print(f"  Matched problem keys: {peak.get('matched_problem_keys', [])}")

print("\n" + "="*120)
print("KEY INSIGHT")
print("="*120)
print("""
The top error types in uncovered buckets (ITO-xxx) are DIFFERENT from the error types
that were detected as peaks (auth:card_servicing, etc.).

This means the pipeline's incident detection never recognized these error types as anomalies,
so they were never included in any peak's incident collection.

WHY?
- Baseline for these error types might be HIGH (so ratio < 3.0)
- OR: These errors were never seen in baseline period
- OR: They come from different fingerprints/components not in the registry

SOLUTION:
1. Lower SPIKE_THRESHOLD from 3.0 to 2.0-2.5
2. Add ABSOLUTE COUNT THRESHOLD (e.g., any 15m with >20k errors = spike)
3. Analyze baseline rates for the top error types
""")
