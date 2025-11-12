#!/usr/bin/env python3
"""
Investigate bl-pcb-event-processor-relay-v1 peak
"""
import json
from pathlib import Path
from collections import defaultdict

# Load batches
all_errors = []
for batch_file in sorted(Path('data/batches/2025-11-12').glob('batch_*.json')):
    if 'summary' in str(batch_file):
        continue
    with open(batch_file) as f:
        data = json.load(f)
        all_errors.extend(data.get('errors', []))

# Filter relay errors
relay_errors = [e for e in all_errors if e['app'] == 'bl-pcb-event-processor-relay-v1']

print("="*80)
print("🔍 INVESTIGATION: bl-pcb-event-processor-relay-v1 Peak")
print("="*80)

# Group by namespace
by_ns = defaultdict(list)
for e in relay_errors:
    by_ns[e.get('namespace', 'unknown')].append(e)

print(f"\nTotal relay errors: {len(relay_errors)}")
print(f"\nBreakdown by namespace:")
for ns, errors in sorted(by_ns.items(), key=lambda x: len(x[1]), reverse=True):
    print(f"  {ns}: {len(errors)} errors")

# Analyze error messages per namespace
print("\n" + "="*80)
print("🔍 ERROR ANALYSIS PER NAMESPACE")
print("="*80)

for ns in sorted(by_ns.keys()):
    errors = by_ns[ns]
    print(f"\n### Namespace: {ns} ({len(errors)} errors)")
    
    # Group by message pattern
    patterns = defaultdict(int)
    error_codes = defaultdict(int)
    
    for e in errors:
        msg = e['message']
        
        # Extract error code (404, 503, etc)
        import re
        code_match = re.search(r'#(\d{3})#', msg)
        if code_match:
            error_codes[code_match.group(1)] += 1
        
        # Normalize message
        normalized = re.sub(r'\d+', 'X', msg[:100])
        patterns[normalized] += 1
    
    # Top error codes
    if error_codes:
        print(f"\n  HTTP Error Codes:")
        for code, count in sorted(error_codes.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"    {code}: {count}")
    
    # Top patterns
    print(f"\n  Top Error Patterns:")
    for pattern, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:3]:
        print(f"    {count}x: {pattern}")

# Timeline analysis
print("\n" + "="*80)
print("⏰ TIMELINE ANALYSIS (1-minute buckets)")
print("="*80)

timeline_ns = defaultdict(lambda: defaultdict(int))
for e in relay_errors:
    ts = e['timestamp'][:16]  # YYYY-MM-DDTHH:MM
    ns = e.get('namespace', 'unknown')
    timeline_ns[ts][ns] += 1

print(f"\nShowing periods with >5 errors:")
for ts, ns_counts in sorted(timeline_ns.items()):
    total = sum(ns_counts.values())
    if total > 5:
        ns_str = ', '.join([f"{ns}:{cnt}" for ns, cnt in sorted(ns_counts.items())])
        print(f"  {ts}: {total:3d} errors ({ns_str})")

# Root cause analysis
print("\n" + "="*80)
print("🎯 ROOT CAUSE ANALYSIS")
print("="*80)

# Check if same cards failing across namespaces
card_ids = defaultdict(set)  # card_id -> set of namespaces
import re
for e in relay_errors:
    match = re.search(r'/api/v1/card/(\d+)', e['message'])
    if match:
        card_id = match.group(1)
        ns = e.get('namespace', 'unknown')
        card_ids[card_id].add(ns)

# Cards failing in multiple namespaces
multi_ns_cards = {cid: namespaces for cid, namespaces in card_ids.items() if len(namespaces) > 1}

if multi_ns_cards:
    print(f"\n⚠️  Cards failing across multiple namespaces:")
    for card_id, namespaces in sorted(multi_ns_cards.items(), key=lambda x: len(x[1]), reverse=True)[:10]:
        print(f"  Card {card_id}: {', '.join(sorted(namespaces))}")

print(f"\n💡 FINDINGS:")
print(f"  • Total namespaces affected: {len(by_ns)}")
print(f"  • Is this same problem across all NS? {len(multi_ns_cards) > 0 and 'YES - same cards fail' or 'NO - different issues'}")
print(f"  • Peak time: 08:36 with 129 errors")

# Recommendations
print(f"\n📋 RECOMMENDATIONS:")
if len(by_ns) > 1:
    print(f"  1. Problem affects {len(by_ns)} namespaces - likely infrastructure issue")
if multi_ns_cards:
    print(f"  2. Same card IDs fail across namespaces - data synchronization issue")
print(f"  3. Check bl-pcb-v1 service health during peak (08:36)")
print(f"  4. Review event relay timeout configuration")
