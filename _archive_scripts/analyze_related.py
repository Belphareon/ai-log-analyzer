#!/usr/bin/env python3
"""Analyzuje související error patterns"""
import json

with open('/tmp/daily_2025-11-10.json', 'r') as f:
    data = json.load(f)

errors = data['errors']

# Najdi všechny case IDs
case_ids = {}
for e in errors:
    msg = e['message']
    import re
    matches = re.findall(r'case\s+(\d+)', msg, re.I)
    for case_id in matches:
        if case_id not in case_ids:
            case_ids[case_id] = []
        case_ids[case_id].append(e)

# Top case IDs
top_cases = sorted(case_ids.items(), key=lambda x: len(x[1]), reverse=True)[:5]

print("=== TOP 5 PROBLEMATIC CASE IDs (Nov 10) ===\n")
for case_id, case_errors in top_cases:
    print(f"Case ID {case_id}: {len(case_errors)} errors")
    
    # Unique error patterns
    patterns = {}
    for e in case_errors:
        # Normalize
        msg = e['message'][:100]
        patterns[msg] = patterns.get(msg, 0) + 1
    
    print(f"  Unique patterns: {len(patterns)}")
    print(f"  Namespaces:")
    ns_count = {}
    for e in case_errors:
        ns = e.get('namespace', 'unknown')
        ns_count[ns] = ns_count.get(ns, 0) + 1
    for ns, cnt in sorted(ns_count.items(), key=lambda x: -x[1]):
        print(f"    - {ns}: {cnt}")
    
    print(f"  Error chain:")
    for pattern, cnt in sorted(patterns.items(), key=lambda x: -x[1])[:3]:
        print(f"    {cnt}x: {pattern}")
    print()
