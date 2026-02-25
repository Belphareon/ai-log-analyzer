#!/usr/bin/env python3
"""
Analýza: Proč 29 vysokých bucketů není detekováno?
======================================================

Procedura:
1. Načti source_logs_24h_cache.json (raw events)
2. Načti active_peaks_24h_investigation.json (detected peaks)
3. Pro každý UNCOVERED bucket:
   - Identifikuj error typy v něm
   - Spočítej jaká je jejich baseline rate (historická)
   - Spočítej EWMA ratio
   - Spočítej MAD ratio
   - Zjisti proč nedošlo k detekci
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
import os
import sys

repo = Path('/home/jvsete/git/ai-log-analyzer')
os.chdir(repo)
sys.path.insert(0, str(repo / 'scripts'))

from dotenv import load_dotenv
from scripts.core.baseline_loader import BaselineLoader
from scripts.regular_phase import get_db_connection

load_dotenv(repo / '.env')
load_dotenv(repo / 'config/.env')

OUT_DIR = repo / 'ai-data'

# Uncovered high buckets (from validation report)
UNCOVERED = [
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
    ('2026-02-24 13:45', 'pcb-sit-01-app', 32254),
    ('2026-02-24 14:00', 'pcb-dev-01-app', 17548),
    ('2026-02-24 14:00', 'pcb-sit-01-app', 32977),
    ('2026-02-24 14:15', 'pcb-dev-01-app', 437),
    ('2026-02-24 14:15', 'pcb-sit-01-app', 5267),
    ('2026-02-24 14:30', 'pcb-fat-01-app', 2845),
    ('2026-02-24 14:30', 'pcb-uat-01-app', 2720),
]

def parse_ts(s: str):
    return datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)

def fmt_ts(ts):
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return ts.strftime('%Y-%m-%d %H:%M')

# Load source cache
source_file = OUT_DIR / 'source_logs_24h_cache.json'
print(f"Loading source cache: {source_file}")
with open(source_file) as f:
    source_data = json.load(f)

# Parse to datetime range
if isinstance(source_data, dict):
    records = source_data.get('records', [])
else:
    records = source_data

records_by_ns_bucket = defaultdict(list)
for r in records:
    ts_str = r.get('@timestamp', '')
    if not ts_str:
        continue
    ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
    ns = r.get('kubernetes.namespace_name', 'unknown')
    
    # 15-min bucket
    bucket_minute = (ts.minute // 15) * 15
    bucket_ts = ts.replace(minute=bucket_minute, second=0, microsecond=0)
    bucket_key = (bucket_ts, ns)
    records_by_ns_bucket[bucket_key].append(r)

print(f"Built {len(records_by_ns_bucket)} namespace-bucket combinations")

# Load baseline
try:
    db_conn = get_db_connection()
    baseline_loader = BaselineLoader(db_conn)
    print("Connected to DB for baseline")
except Exception as e:
    print(f"⚠️  Could not connect to DB: {e}")
    baseline_loader = None

# Analyze each uncovered bucket
print("\n" + "="*120)
print("UNCOVERED BUCKET ANALYSIS - Why weren't they detected?")
print("="*120)

overall_stats = {
    'total_uncovered': len(UNCOVERED),
    'error_type_distribution': Counter(),
    'baseline_zero_count': 0,
    'low_ratio_count': 0,
    'high_baseline_count': 0,
    'no_baseline_data': 0,
}

for bucket_str, namespace, raw_count in UNCOVERED:
    ts = parse_ts(bucket_str)
    bucket_key = (ts, namespace)
    
    recs_in_bucket = records_by_ns_bucket.get(bucket_key, [])
    
    errors_by_type = Counter()
    for r in recs_in_bucket:
        et = r.get('error_type', 'Unknown')
        errors_by_type[et] += 1
    
    overall_stats['error_type_distribution'].update(errors_by_type)
    
    # Try to get baseline for top error types
    top_errors = errors_by_type.most_common(3)
    
    print(f"\n📊 {bucket_str} | {namespace} | RAW: {raw_count:,} errors")
    print(f"   Found {len(recs_in_bucket)} records in bucket")
    print(f"   Top error types: {top_errors}")
    
    analysis_reason = []
    
    if baseline_loader:
        for et, et_count in top_errors:
            if et == 'Unknown':
                continue
                
            try:
                baseline_rates = baseline_loader.load_historical_rates(
                    error_types=[et],
                    lookback_days=7,
                    min_samples=3
                )
                
                if et in baseline_rates:
                    baseline_rate = baseline_rates[et]
                    # current_rate is errors per minute for 15-min window
                    current_rate = et_count / 15.0  # 15 minutes
                    
                    if baseline_rate == 0:
                        analysis_reason.append(f"{et}: baseline=0, current={et_count}")
                        overall_stats['baseline_zero_count'] += 1
                    else:
                        ratio = current_rate / baseline_rate if baseline_rate > 0 else float('inf')
                        if ratio < 3.0:
                            analysis_reason.append(f"{et}: ratio={ratio:.2f} (baseline={baseline_rate:.2f}/min, current={current_rate:.2f}/min)")
                            overall_stats['low_ratio_count'] += 1
                        else:
                            analysis_reason.append(f"{et}: ratio={ratio:.2f} ✅ (should have triggered!)")
                        
                        if baseline_rate > 10:
                            overall_stats['high_baseline_count'] += 1
                else:
                    analysis_reason.append(f"{et}: No baseline data")
                    overall_stats['no_baseline_data'] += 1
                    
            except Exception as e:
                analysis_reason.append(f"{et}: Error loading baseline: {e}")
    else:
        analysis_reason.append("No DB connection - can't load baseline")
        overall_stats['no_baseline_data'] += 1
    
    if analysis_reason:
        for reason in analysis_reason:
            print(f"      → {reason}")
    
    print()

print("\n" + "="*120)
print("SUMMARY STATISTICS")
print("="*120)
print(f"Total uncovered buckets analyzed: {overall_stats['total_uncovered']}")
print(f"  - Reason: Low ratio (< 3.0): {overall_stats['low_ratio_count']}")
print(f"  - Reason: Baseline = 0: {overall_stats['baseline_zero_count']}")
print(f"  - Reason: High baseline (> 10/min): {overall_stats['high_baseline_count']}")
print(f"  - Reason: No baseline data: {overall_stats['no_baseline_data']}")
print(f"\nTop error types in uncovered buckets:")
for et, count in overall_stats['error_type_distribution'].most_common(10):
    print(f"  {et}: {count}")

print("\n" + "="*120)
print("RECOMMENDATIONS FOR DETECTION IMPROVEMENT")
print("="*120)
print("""
Možnosti k zlepšení detekce:

1. **Zníži SPIKE_THRESHOLD** z 3.0 na 2.5 nebo 2.0
   - Current: needs 3x baseline to trigger
   - Proposed: 2.5x baseline should catch more spikes
   - Trade-off: More false positives

2. **Zníži spike_mad_threshold** z 3.0 na 2.0
   - More robust detection for outliers
   
3. **Přidej absolute count threshold** 
   - Pokud bucket_count > 10,000 errors => spike
   - Nezávisí na baseline, pouze na absolutní velikosti

4. **Zlepši baseline loading**
   - Check if historical baseline je správně nastavena
   - Zvětši lookback_days z 7 na 14 pro stabilnější baseline

5. **Cross-namespace analysis**
   - Pokud vidíš stejný error type vysoký v pcb-dev+pcb-sit+pcb-fat = PATTERN
   - Spines synchronně vícenárodnostnímspike by měl být detectován
""")

if baseline_loader:
    db_conn.close()
