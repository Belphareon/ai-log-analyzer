#!/usr/bin/env python3
"""
Analyze daily errors from fetched JSON
Usage: python analyze_daily.py --input data.json --output report.md
"""
import sys
import json
import argparse
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, '/home/jvsete/git/sas/ai-log-analyzer')
from app.services.pattern_detector import pattern_detector

def analyze_errors(data):
    """Analyze errors and generate report"""
    errors = data['errors']
    total = data['total_errors']
    sample_size = data['sample_size']
    
    print(f"Analyzing {sample_size:,} errors from {total:,} total...")
    
    # Cluster by pattern
    clusters = pattern_detector.cluster_errors(errors)
    
    # Calculate patterns with namespace breakdown
    patterns = []
    for normalized, error_list in clusters.items():
        if len(error_list) < 3:
            continue
        
        # Namespace breakdown
        namespaces = defaultdict(int)
        for e in error_list:
            ns = e.get('namespace', 'unknown')
            namespaces[ns] += 1
        
        # Extrapolate
        sample_count = len(error_list)
        extrapolated = int((sample_count / sample_size) * total) if sample_size > 0 else sample_count
        
        ns_extra = {}
        for ns, cnt in namespaces.items():
            ns_extra[ns] = int((cnt / sample_size) * total) if sample_size > 0 else cnt
        
        error_code = pattern_detector.extract_error_code(error_list[0]['message'])
        apps = list(set(e['app'] for e in error_list))
        
        patterns.append({
            'fingerprint': normalized[:80],
            'message_sample': error_list[0]['message'][:150],
            'count': extrapolated,
            'sample_count': sample_count,
            'error_code': error_code,
            'apps': apps[:5],
            'namespaces': ns_extra,
            'first_seen': min(e['timestamp'] for e in error_list),
            'last_seen': max(e['timestamp'] for e in error_list)
        })
    
    # Sort by count
    patterns.sort(key=lambda x: x['count'], reverse=True)
    
    return patterns

def generate_markdown_report(data, patterns, output_file):
    """Generate markdown report"""
    with open(output_file, 'w') as f:
        f.write(f"# Daily Error Report\n\n")
        f.write(f"**Period:** {data['period_start']} → {data['period_end']}\n\n")
        f.write(f"**Total Errors:** {data['total_errors']:,}\n\n")
        f.write(f"**Sample Size:** {data['sample_size']:,} ({data['coverage_percent']:.1f}% coverage)\n\n")
        f.write(f"**Unique Patterns Found:** {len(patterns)}\n\n")
        
        f.write("---\n\n")
        f.write("## Top 20 Error Patterns\n\n")
        
        for i, p in enumerate(patterns[:20], 1):
            f.write(f"### {i}. {p['fingerprint']}\n\n")
            f.write(f"**Estimated Total:** ~{p['count']:,} occurrences\n\n")
            f.write(f"**Sample Count:** {p['sample_count']}\n\n")
            if p['error_code']:
                f.write(f"**Error Code:** `{p['error_code']}`\n\n")
            f.write(f"**Affected Apps:** {', '.join(p['apps'])}\n\n")
            f.write(f"**Namespaces:**\n")
            for ns, cnt in sorted(p['namespaces'].items(), key=lambda x: -x[1]):
                f.write(f"- `{ns}`: ~{cnt:,}\n")
            f.write(f"\n**Sample Message:**\n```\n{p['message_sample']}\n```\n\n")
            f.write(f"**First seen:** {p['first_seen']}\n\n")
            f.write(f"**Last seen:** {p['last_seen']}\n\n")
            f.write("---\n\n")
        
        # Add related errors analysis
        add_related_analysis(f, data["errors"], data["total_errors"], data["sample_size"])

def analyze_related_errors(errors):
    """Find related errors by case ID, card ID, and temporal proximity"""
    import re
    from datetime import datetime, timedelta
    
    # Group by case ID
    case_groups = {}
    card_groups = {}
    
    for e in errors:
        msg = e['message']
        
        # Extract case IDs
        case_matches = re.findall(r'[Cc]ase\s+(\d+)', msg)
        for case_id in case_matches:
            if case_id not in case_groups:
                case_groups[case_id] = []
            case_groups[case_id].append(e)
        
        # Extract card IDs
        card_matches = re.findall(r'[Cc]ard.*?id\s+(\d+)', msg)
        for card_id in card_matches:
            if card_id not in card_groups:
                card_groups[card_id] = []
            card_groups[card_id].append(e)
    
    # Temporal clustering - group errors within 15 min window
    temporal_clusters = find_temporal_clusters(errors, window_minutes=15)
    
    # Cross-app analysis for case IDs
    cross_app_cases = analyze_cross_app_correlation(case_groups)
    
    # Sort by occurrence
    top_cases = sorted(case_groups.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    top_cards = sorted(card_groups.items(), key=lambda x: len(x[1]), reverse=True)[:5]
    
    return {
        'cases': top_cases, 
        'cards': top_cards,
        'temporal_clusters': temporal_clusters,
        'cross_app_cases': cross_app_cases
    }

def find_temporal_clusters(errors, window_minutes=15):
    """Find error clusters within time window"""
    from datetime import datetime, timedelta
    
    # Sort by timestamp
    sorted_errors = sorted(errors, key=lambda e: e['timestamp'])
    
    clusters = []
    current_cluster = []
    cluster_start = None
    
    for e in sorted_errors:
        ts = datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00'))
        
        if not current_cluster:
            current_cluster = [e]
            cluster_start = ts
        else:
            time_diff = (ts - cluster_start).total_seconds() / 60
            
            if time_diff <= window_minutes:
                current_cluster.append(e)
            else:
                # Save cluster if significant
                if len(current_cluster) >= 5:
                    clusters.append({
                        'start': cluster_start.isoformat(),
                        'errors': current_cluster,
                        'duration_min': time_diff
                    })
                
                # Start new cluster
                current_cluster = [e]
                cluster_start = ts
    
    # Don't forget last cluster
    if len(current_cluster) >= 5:
        clusters.append({
            'start': cluster_start.isoformat(),
            'errors': current_cluster,
            'duration_min': 0
        })
    
    # Sort by cluster size
    clusters.sort(key=lambda c: len(c['errors']), reverse=True)
    return clusters[:10]  # Top 10 clusters

def analyze_cross_app_correlation(case_groups):
    """Analyze how errors spread across apps for same case ID"""
    cross_app = []
    
    for case_id, case_errors in case_groups.items():
        # Group by app and namespace
        app_breakdown = {}
        ns_breakdown = {}
        
        for e in case_errors:
            app = e.get('app', 'unknown')
            ns = e.get('namespace', 'unknown')
            
            if ns not in ns_breakdown:
                ns_breakdown[ns] = {'apps': set(), 'count': 0, 'errors': []}
            
            ns_breakdown[ns]['apps'].add(app)
            ns_breakdown[ns]['count'] += 1
            ns_breakdown[ns]['errors'].append(e)
        
        # Only include cases affecting multiple apps on same namespace
        for ns, data in ns_breakdown.items():
            if len(data['apps']) > 1:
                cross_app.append({
                    'case_id': case_id,
                    'namespace': ns,
                    'apps': list(data['apps']),
                    'count': data['count'],
                    'errors': data['errors']
                })
    
    # Sort by number of affected apps
    cross_app.sort(key=lambda x: (len(x['apps']), x['count']), reverse=True)
    return cross_app[:5]  # Top 5 cross-app cases

def add_related_analysis(f, errors, total, sample_size):
    """Add related errors section to report"""
    related = analyze_related_errors(errors)
    
    # Temporal clusters
    if related.get('temporal_clusters'):
        f.write("\n---\n\n## ⏰ Temporal Clusters - Error Bursts\n\n")
        f.write("Error bursts within 15-minute windows show potential cascading failures:\n\n")
        
        for i, cluster in enumerate(related['temporal_clusters'][:5], 1):
            extrapolated = int((len(cluster['errors']) / sample_size) * total) if sample_size > 0 else len(cluster['errors'])
            f.write(f"### Cluster {i}: {cluster['start']}\n\n")
            f.write(f"**Burst Size:** ~{extrapolated:,} errors (sample: {len(cluster['errors'])})\n\n")
            
            # Affected apps
            apps = list(set(e.get('app', 'unknown') for e in cluster['errors']))
            f.write(f"**Affected Apps ({len(apps)}):** {', '.join(apps[:10])}\n\n")
            
            # Namespace breakdown
            ns_count = {}
            for e in cluster['errors']:
                ns = e.get('namespace', 'unknown')
                ns_count[ns] = ns_count.get(ns, 0) + 1
            
            f.write("**Namespaces:**\n")
            for ns, cnt in sorted(ns_count.items(), key=lambda x: -x[1])[:3]:
                ns_extra = int((cnt / sample_size) * total) if sample_size > 0 else cnt
                f.write(f"- `{ns}`: ~{ns_extra:,}\n")
            f.write("\n")
    
    # Cross-app correlation
    if related.get('cross_app_cases'):
        f.write("\n---\n\n## � Cross-App Error Propagation\n\n")
        f.write("Cases affecting multiple applications on the same environment:\n\n")
        
        for item in related['cross_app_cases']:
            extrapolated = int((item['count'] / sample_size) * total) if sample_size > 0 else item['count']
            f.write(f"### Case {item['case_id']} @ `{item['namespace']}`\n\n")
            f.write(f"**Total Errors:** ~{extrapolated:,}\n\n")
            f.write(f"**Affected Apps ({len(item['apps'])}):** {', '.join(item['apps'])}\n\n")
            
            # Show error chain timeline
            errors_sorted = sorted(item['errors'], key=lambda e: e['timestamp'])
            f.write("**Error Chain:**\n")
            for j, e in enumerate(errors_sorted[:5], 1):
                ts = e['timestamp'][11:19]  # Just HH:MM:SS
                msg_short = e['message'][:80]
                f.write(f"{j}. `{ts}` [{e.get('app', 'unknown')}] `{msg_short}...`\n")
            f.write("\n")
    
    # Case ID groups
    if related['cases']:
        f.write("\n---\n\n## �🔗 Related Errors - Case IDs\n\n")
        f.write("Errors grouped by Case ID show error chains and processing failures:\n\n")
        
        for case_id, case_errors in related['cases']:
            extrapolated = int((len(case_errors) / sample_size) * total) if sample_size > 0 else len(case_errors)
            f.write(f"### Case ID {case_id}\n\n")
            f.write(f"**Occurrences:** ~{extrapolated:,} (sample: {len(case_errors)})\n\n")
            
            # Namespaces
            ns_count = {}
            for e in case_errors:
                ns = e.get('namespace', 'unknown')
                ns_count[ns] = ns_count.get(ns, 0) + 1
            
            f.write("**Affected Namespaces:**\n")
            for ns, cnt in sorted(ns_count.items(), key=lambda x: -x[1]):
                ns_extra = int((cnt / sample_size) * total) if sample_size > 0 else cnt
                f.write(f"- `{ns}`: ~{ns_extra:,}\n")
            
            # Error chain
            patterns = {}
            for e in case_errors:
                msg_short = e['message'][:120]
                patterns[msg_short] = patterns.get(msg_short, 0) + 1
            
            f.write(f"\n**Error Chain ({len(patterns)} unique patterns):**\n")
            for i, (pattern, cnt) in enumerate(sorted(patterns.items(), key=lambda x: -x[1])[:3], 1):
                cnt_extra = int((cnt / sample_size) * total) if sample_size > 0 else cnt
                f.write(f"{i}. (~{cnt_extra:,}x) `{pattern}...`\n")
            f.write("\n")
    
    # Card ID groups
    if related['cards']:
        f.write("\n---\n\n## 💳 Related Errors - Card IDs\n\n")
        
        for card_id, card_errors in related['cards']:
            extrapolated = int((len(card_errors) / sample_size) * total) if sample_size > 0 else len(card_errors)
            f.write(f"### Card ID {card_id}\n\n")
            f.write(f"**Occurrences:** ~{extrapolated:,}\n\n")
            
            # Top error for this card
            msg_sample = card_errors[0]['message'][:150]
            f.write(f"**Sample:** `{msg_sample}`\n\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Analyze daily errors')
    parser.add_argument('--input', required=True, help='Input JSON file')
    parser.add_argument('--output', required=True, help='Output markdown file')
    
    args = parser.parse_args()
    
    print(f"Loading {args.input}...")
    with open(args.input, 'r') as f:
        data = json.load(f)
    
    patterns = analyze_errors(data)
    
    generate_markdown_report(data, patterns, args.output)
    
    print(f"✅ Report saved to {args.output}")
    print(f"   Found {len(patterns)} unique error patterns")
    if patterns:
        print(f"   Top issue: {patterns[0]['fingerprint'][:60]} (~{patterns[0]['count']:,} occurrences)")
