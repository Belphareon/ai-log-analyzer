#!/usr/bin/env python3
"""
Peak Summary Table Generator - WITH FIXED DETECTION LOGIC
==========================================================

Vygeneruje tabulku peaků s OPRAVENOM logikou:
- Burst guardrails: skip if baseline < 0.5
- Spike fallback: new errors with 5+ count treated as spike
- Score-based filter: include score >= 70 incidents
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import re

def load_batch_files(batch_dir="/home/jvsete/git/ai-log-analyzer/ai-data/batches", limit=10):
    """Načti batch files"""
    batch_files = sorted(Path(batch_dir).glob("batch_*.json"), reverse=True)[:limit]
    
    all_records = []
    for batch_file in batch_files:
        try:
            with open(batch_file) as f:
                data = json.load(f)
                if isinstance(data, dict) and 'incidents' in data:
                    all_records.extend(data['incidents'])
                elif isinstance(data, list):
                    all_records.extend(data)
        except Exception as e:
            print(f"⚠️ Error loading {batch_file}: {e}")
    
    return all_records

def apply_fixed_logic(record):
    """Aplikuj FIXED detekční logiku"""
    
    # Extract fields
    is_spike = record.get('flags', {}).get('is_spike', False)
    is_burst = record.get('flags', {}).get('is_burst', False)
    baseline_ewma = record.get('stats', {}).get('baseline_ewma', 0)
    current_count = record.get('stats', {}).get('current_count', 0)
    score = record.get('score', 0)
    
    # OPRAVA #1: Burst guardrails - skip if baseline < 0.5
    if is_burst and baseline_ewma < 0.5:
        burst_removed_reason = f"baseline_too_low({baseline_ewma:.4f})"
        is_burst = False
    else:
        burst_removed_reason = None
    
    # OPRAVA #2: Spike fallback - new errors with 5+ count
    if not is_spike and baseline_ewma == 0 and current_count >= 5:
        is_spike = True
        spike_added_reason = "new_error_5plus"
    else:
        spike_added_reason = None
    
    # OPRAVA #3: Score-based incidents
    is_high_score = score >= 70
    
    return {
        'is_spike': is_spike,
        'is_burst': is_burst,
        'is_high_score': is_high_score,
        'score': score,
        'burst_removed_reason': burst_removed_reason,
        'spike_added_reason': spike_added_reason,
    }

def generate_table(records):
    """Generuj markdown tabulku peaků"""
    
    print("\n" + "=" * 100)
    print("🔍 PEAK DETECTION WITH FIXED LOGIC")
    print("=" * 100)
    
    # Filter by detection flags
    incidents = []
    for record in records:
        fixed = apply_fixed_logic(record)
        if fixed['is_spike'] or fixed['is_burst'] or fixed['is_high_score']:
            incidents.append({
                'record': record,
                'fixed': fixed
            })
    
    print(f"\n📊 Statistics:")
    print(f"   Total records processed: {len(records)}")
    print(f"   Incidents with peak flags: {len(incidents)}")
    
    old_spikes = sum(1 for r in records if r.get('flags', {}).get('is_spike'))
    old_bursts = sum(1 for r in records if r.get('flags', {}).get('is_burst'))
    
    new_spikes = sum(1 for i in incidents if i['fixed']['is_spike'])
    new_bursts = sum(1 for i in incidents if i['fixed']['is_burst'])
    high_scores = sum(1 for i in incidents if i['fixed']['is_high_score'])
    
    burst_removals = sum(1 for i in incidents if i['fixed']['burst_removed_reason'])
    spike_additions = sum(1 for i in incidents if i['fixed']['spike_added_reason'])
    
    print(f"\n📈 Spike detections:")
    print(f"   OLD: {old_spikes} spikes")
    print(f"   NEW: {new_spikes} spikes")
    print(f"   Difference: +{new_spikes - old_spikes} (new error type handling)")
    
    print(f"\n📈 Burst detections:")
    print(f"   OLD: {old_bursts} bursts") 
    print(f"   NEW: {new_bursts} bursts")
    print(f"   FALSE POSITIVES REMOVED: {burst_removals} (baseline < 0.5)")
    print(f"   Improvement: -{(100*burst_removals/(old_bursts or 1)):.1f}% noise")
    
    print(f"\n📧 High-score incidents (score >= 70):")
    print(f"   Count: {high_scores}")
    print(f"   → These will NOW trigger Teams notifications")
    
    print("\n" + "=" * 100)
    print("📋 PEAK DETAILS TABLE")
    print("=" * 100)
    
    # Build markdown table
    md = "\n| # | Fingerprint | Namespace | Error Type | Count | Peak/Baseline | Score | Type | New | Fix Applied |\n"
    md += "|---|---|---|---|---:|---:|---:|---|---|---|\n"
    
    for i, item in enumerate(sorted(incidents, key=lambda x: x['record'].get('score', 0), reverse=True)[:50], 1):
        rec = item['record']
        fix = item['fixed']
        
        fp = rec.get('fingerprint', 'unknown')[:12]
        ns = rec.get('namespaces', ['unknown'])[0] if rec.get('namespaces') else 'unknown'
        error_type = rec.get('error_type', 'unknown')[:15]
        count = int(rec.get('stats', {}).get('current_count', 0))
        score = int(rec.get('score', 0))
        
        baseline = rec.get('stats', {}).get('baseline_ewma', 0)
        if baseline > 0 and count > 0:
            ratio = f"{count/baseline:.1f}x"
        else:
            ratio = "-"
        
        peak_type = "spike" if fix['is_spike'] else ("burst" if fix['is_burst'] else "score")
        
        is_new = "NEW" if rec.get('flags', {}).get('is_new') else ""
        
        fix_applied = []
        if fix['burst_removed_reason']:
            fix_applied.append("❌ burst_removed")
        if fix['spike_added_reason']:
            fix_applied.append("✅ spike_added")
        fix_str = " ".join(fix_applied) or "-"
        
        md += f"| {i} | {fp} | {ns[:18]} | {error_type} | {count:>5} | {ratio:>11} | {score:>5} | {peak_type:<6} | {is_new:<3} | {fix_str} |\n"
    
    print(md)
    
    # Save do file
    output_path = f"/home/jvsete/git/ai-log-analyzer/ai-data/peak_summary_fixed_logic.md"
    with open(output_path, 'w') as f:
        f.write("# Peak Detection Summary - WITH FIXED LOGIC\n\n")
        f.write(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"## Statistics\n\n")
        f.write(f"- **Total incidents:** {len(incidents)}\n")
        f.write(f"- **Spikes (OLD):** {old_spikes} → **NEW:** {new_spikes} (+{new_spikes - old_spikes})\n")
        f.write(f"- **Bursts (OLD):** {old_bursts} → **NEW:** {new_bursts} (-{burst_removals} false positives)\n")
        f.write(f"- **High-score (≥70):** {high_scores} (NEW notification targets)\n\n")
        f.write("## Improvements Applied\n\n")
        f.write("1. **Burst false positives removed:** -{}% (baseline < 0.5 guardrail)\n".format(int(100*burst_removals/(old_bursts or 1))))
        f.write("2. **New error type handling:** {} new spikes detected (5+ count fallback)\n".format(spike_additions))
        f.write("3. **High-priority notifications:** {} incidents (score ≥ 70 enabled)\n\n".format(high_scores))
        f.write("## Peak Details\n")
        f.write(md)
    
    print(f"\n✅ Summary saved to: {output_path}")

if __name__ == '__main__':
    records = load_batch_files()
    if records:
        generate_table(records)
    else:
        print("❌ No batch files found")
