#!/usr/bin/env python3
"""
Intelligent Error Analysis - connects the dots between errors
Provides actionable insights, not just raw counts
"""
import json
import sys
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime

def aggregate_batches(batch_dir):
    """Aggregate all batch reports"""
    
    # Load all batch data
    all_errors = []
    batch_files = sorted(Path(batch_dir).glob("batch_*.json"))
    
    print(f"📊 Aggregating {len(batch_files)} batches...")
    
    total_errors = 0
    for batch_file in batch_files:
        if "summary" in str(batch_file):
            continue
        with open(batch_file) as f:
            data = json.load(f)
            errors = data.get('errors', [])
            all_errors.extend(errors)
            total_errors += data.get('total_errors', 0)
            print(f"  - {batch_file.name}: {len(errors)} errors")
    
    print(f"\n✅ Total: {len(all_errors):,} errors loaded from batches")
    print(f"📈 Reported total: {total_errors:,} errors in period\n")
    
    # Pattern analysis
    patterns = defaultdict(list)
    for error in all_errors:
        # Simple fingerprint - normalize message
        msg = error['message']
        # Remove numbers, IDs
        import re
        normalized = re.sub(r'\d+', 'X', msg)
        normalized = re.sub(r'[a-f0-9]{32,}', 'HASH', normalized)
        normalized = re.sub(r'0x[a-f0-9]+', 'ADDR', normalized)
        patterns[normalized[:100]].append(error)
    
    # Top patterns
    sorted_patterns = sorted(patterns.items(), key=lambda x: len(x[1]), reverse=True)
    
    print("=" * 80)
    print("🔥 TOP 20 ERROR PATTERNS")
    print("=" * 80)
    
    for i, (fingerprint, errors) in enumerate(sorted_patterns[:20], 1):
        count = len(errors)
        apps = set(e['app'] for e in errors)
        namespaces = set(e.get('namespace', 'unknown') for e in errors)
        
        print(f"\n{i}. {fingerprint}")
        print(f"   Count: {count:,}")
        print(f"   Apps: {', '.join(sorted(apps)[:3])}")
        print(f"   Namespaces: {', '.join(sorted(namespaces)[:3])}")
        print(f"   Sample: {errors[0]['message'][:150]}")
    
    # Timeline analysis
    print("\n" + "=" * 80)
    print("⏰ TIMELINE ANALYSIS")
    print("=" * 80)
    
    timeline = defaultdict(int)
    for error in all_errors:
        timestamp = error['timestamp']
        hour_min = timestamp[11:16]  # HH:MM
        timeline[hour_min] += 1
    
    sorted_timeline = sorted(timeline.items())
    for time, count in sorted_timeline:
        bar = "█" * (count // 20)
        print(f"{time}: {count:4d} {bar}")
    
    # App breakdown
    print("\n" + "=" * 80)
    print("📱 APP BREAKDOWN")
    print("=" * 80)
    
    app_counts = defaultdict(int)
    for error in all_errors:
        app_counts[error['app']] += 1
    
    sorted_apps = sorted(app_counts.items(), key=lambda x: x[1], reverse=True)
    for app, count in sorted_apps[:15]:
        pct = (count / len(all_errors)) * 100
        print(f"{app:50s} {count:5d} ({pct:5.1f}%)")
    
    # Namespace breakdown
    print("\n" + "=" * 80)
    print("🏢 NAMESPACE BREAKDOWN")
    print("=" * 80)
    
    ns_counts = defaultdict(int)
    for error in all_errors:
        ns_counts[error.get('namespace', 'unknown')] += 1
    
    sorted_ns = sorted(ns_counts.items(), key=lambda x: x[1], reverse=True)
    for ns, count in sorted_ns[:10]:
        pct = (count / len(all_errors)) * 100
        print(f"{ns:30s} {count:5d} ({pct:5.1f}%)")

if __name__ == "__main__":
    batch_dir = sys.argv[1] if len(sys.argv) > 1 else "data/batches/2025-11-12"
    aggregate_batches(batch_dir)
