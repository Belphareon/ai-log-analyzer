#!/usr/bin/env python3
"""Trace ID based root cause analysis"""
import json
import re
from collections import defaultdict
from datetime import datetime

def load_data(json_file):
    """Load errors from JSON"""
    with open(json_file) as f:
        data = json.load(f)
    return data.get('errors', [])

def group_by_trace(errors):
    """Group errors by trace_id"""
    traces = defaultdict(list)
    for e in errors:
        trace_id = e.get('trace_id', 'no-trace')
        if trace_id:
            traces[trace_id].append(e)
    return traces

def find_root_cause(trace_errors):
    """Find root cause in a trace - first app to generate error"""
    if not trace_errors:
        return None
    
    # Sort by timestamp
    sorted_errors = sorted(trace_errors, key=lambda x: x.get('timestamp', ''))
    
    # First error is usually root cause
    return sorted_errors[0]

def analyze_trace_chain(trace_id, trace_errors):
    """Analyze single trace chain"""
    root = find_root_cause(trace_errors)
    
    if not root:
        return None
    
    # Group by app
    by_app = defaultdict(list)
    for e in trace_errors:
        app = e.get('app', 'unknown')
        by_app[app].append(e)
    
    return {
        'trace_id': trace_id,
        'error_count': len(trace_errors),
        'app_count': len(by_app),
        'root_cause': {
            'app': root.get('app', 'unknown'),
            'message': root.get('message', ''),
            'timestamp': root.get('timestamp', '')
        },
        'apps_affected': list(by_app.keys()),
        'error_chain': [
            {
                'app': e.get('app'),
                'timestamp': e.get('timestamp'),
                'message': e.get('message')[:100]
            }
            for e in sorted(trace_errors, key=lambda x: x.get('timestamp', ''))[:5]
        ]
    }

def deduplicate_by_root_cause(traces):
    """Group traces by root cause to find recurring issues"""
    root_causes = defaultdict(list)
    
    for trace_id, trace_errors in traces.items():
        analysis = analyze_trace_chain(trace_id, trace_errors)
        if analysis:
            # Use first error message as key
            root_msg = analysis['root_cause']['message'][:100]
            root_causes[root_msg].append(analysis)
    
    return root_causes

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Trace-based root cause analysis')
    parser.add_argument('--input', required=True, help='Input JSON file')
    parser.add_argument('--output', required=True, help='Output markdown file')
    
    args = parser.parse_args()
    
    print(f"Loading {args.input}...")
    errors = load_data(args.input)
    print(f"Total errors: {len(errors)}")
    
    # Group by trace
    traces = group_by_trace(errors)
    print(f"Unique traces: {len(traces)}")
    
    # Analyze traces
    trace_analyses = {}
    for trace_id, trace_errors in traces.items():
        trace_analyses[trace_id] = analyze_trace_chain(trace_id, trace_errors)
    
    # Deduplicate by root cause
    root_causes = deduplicate_by_root_cause(traces)
    
    # Generate report
    with open(args.output, 'w') as f:
        f.write("# Trace-Based Root Cause Analysis\n\n")
        f.write(f"**Total Errors:** {len(errors):,}\n")
        f.write(f"**Unique Traces:** {len(traces):,}\n")
        f.write(f"**Unique Root Causes:** {len(root_causes)}\n\n")
        
        # Sort by frequency
        sorted_causes = sorted(
            root_causes.items(),
            key=lambda x: sum(a['error_count'] for a in x[1]),
            reverse=True
        )
        
        f.write("## Root Causes Ranked by Impact\n\n")
        
        for i, (root_msg, cause_analyses) in enumerate(sorted_causes[:20], 1):
            total_errors = sum(a['error_count'] for a in cause_analyses)
            total_traces = len(cause_analyses)
            affected_apps = set()
            for analysis in cause_analyses:
                affected_apps.update(analysis['apps_affected'])
            
            f.write(f"### {i}. Root Cause (Impact: {total_errors:,} errors, {total_traces} traces)\n\n")
            f.write(f"**Message:** `{root_msg}...`\n\n")
            f.write(f"**Affected Apps:** {', '.join(sorted(affected_apps))}\n\n")
            f.write(f"**Traces:** {total_traces}\n\n")
            
            # Show first 3 error chains
            f.write("**Error Chains:**\n\n")
            for j, analysis in enumerate(cause_analyses[:3], 1):
                f.write(f"{j}. Trace `{analysis['trace_id'][:16]}...`\n")
                f.write(f"   - Errors: {analysis['error_count']}\n")
                f.write(f"   - Apps: {', '.join(analysis['apps_affected'])}\n")
                f.write(f"   - Flow:\n")
                for step in analysis['error_chain']:
                    ts = step['timestamp'][11:19] if step['timestamp'] else '?'
                    f.write(f"     - `{ts}` [{step['app']}] {step['message']}\n")
                f.write("\n")
            
            f.write("---\n\n")
        
        f.write("\n## Statistics\n\n")
        f.write(f"- Average errors per trace: {len(errors) / len(traces):.1f}\n")
        f.write(f"- Traces by app affected:\n")
        app_trace_count = defaultdict(int)
        for analysis in trace_analyses.values():
            if analysis:
                for app in analysis['apps_affected']:
                    app_trace_count[app] += 1
        
        for app, count in sorted(app_trace_count.items(), key=lambda x: -x[1])[:10]:
            f.write(f"  - {app}: {count} traces\n")
    
    print(f"✅ Report saved to {args.output}")

if __name__ == '__main__':
    main()
