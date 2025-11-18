#!/usr/bin/env python3
"""
Trace-Based Root Cause Report Generator
"""
import json
import argparse
from datetime import datetime

def generate_report(root_causes_file, output_file):
    """Generate markdown report from root causes"""
    
    with open(root_causes_file) as f:
        data = json.load(f)
    
    stats = data['stats']
    root_causes = data['root_causes']
    
    with open(output_file, 'w') as f:
        # Header
        f.write("# Trace-Based Root Cause Analysis Report\n\n")
        f.write(f"**Period:** {data['period_start']} → {data['period_end']}\n\n")
        
        # Overall stats
        f.write("## 📊 Overall Statistics\n\n")
        f.write(f"- **Total Errors:** {stats['total_errors']:,}\n")
        f.write(f"- **Unique Trace IDs:** {stats['total_traces']:,}\n")
        f.write(f"- **Unique Root Causes:** {len(root_causes)}\n")
        f.write(f"- **Avg errors per trace:** {stats['total_errors'] / stats['total_traces']:.1f}\n\n")
        
        # App distribution
        f.write("## 🎯 App Impact Distribution\n\n")
        for app, count in stats['app_distribution'].items():
            pct = (count / stats['total_errors'] * 100)
            bar_length = int(pct / 2)  # 50% = 25 chars
            bar = "█" * bar_length + "░" * (25 - bar_length)
            f.write(f"- **{app}**: {count:5d} errors ({pct:5.1f}%) {bar}\n")
        f.write("\n")
        
        # Namespace distribution
        f.write("## 🔗 Namespace Distribution\n\n")
        total_ns_errors = sum(stats['namespace_distribution'].values())
        for ns, count in stats['namespace_distribution'].items():
            pct = (count / total_ns_errors * 100)
            bar_length = int(pct / 4)  # 100% = 25 chars
            bar = "█" * bar_length + "░" * (25 - bar_length)
            f.write(f"- **{ns}**: {count:5d} errors ({pct:5.1f}%) {bar}\n")
        f.write("\n")
        
        # Root causes
        f.write(f"## 🔍 Root Causes (Top {min(10, len(root_causes))})\n\n")
        
        for cause in root_causes[:10]:
            rank = cause['rank']
            app = cause['app']
            msg = cause['message']
            errors = cause['errors_count']
            pct = cause['errors_percent']
            traces = cause['trace_ids_count']
            apps = ', '.join(cause['affected_apps'][:3])
            namespaces = ', '.join(cause['affected_namespaces'])
            first_seen = cause['first_seen']
            last_seen = cause['last_seen']
            
            # Severity based on percentage
            if pct >= 10:
                severity = "🔴 CRITICAL"
            elif pct >= 5:
                severity = "🟠 HIGH"
            elif pct >= 1:
                severity = "🟡 MEDIUM"
            else:
                severity = "🟢 LOW"
            
            f.write(f"### {rank}. {severity} {app}\n\n")
            f.write(f"**Message:** `{msg[:120]}...`\n\n")
            f.write(f"- **Errors:** {errors:,} ({pct:.1f}%)\n")
            f.write(f"- **Trace IDs:** {traces}\n")
            f.write(f"- **First seen:** {first_seen}\n")
            f.write(f"- **Last seen:** {last_seen}\n")
            f.write(f"- **Duration:** {first_seen} → {last_seen}\n")
            f.write(f"- **Affected Apps:** {apps}...\n")
            f.write(f"- **Namespaces:** {namespaces}\n")
            trace_samples = [t for t in cause['trace_ids'][:3] if t]  # Filter out None values
            if trace_samples:
                f.write(f"- **Sample trace IDs:** {', '.join(str(t) for t in trace_samples)}\n\n")
            else:
                f.write(f"- **Sample trace IDs:** (not available)\n\n")
        
        # Analysis summary
        f.write("## 📋 Analysis Summary\n\n")
        
        # Primary vs Secondary
        if root_causes:
            primary = root_causes[0]
            primary_pct = primary['errors_percent']
            
            if primary_pct > 50:
                f.write(f"🎯 **PRIMARY ISSUE:** {primary['app']}\n\n")
                f.write(f"This single root cause accounts for {primary_pct:.1f}% of all errors.\n")
                f.write(f"Message: `{primary['message'][:100]}...`\n\n")
                f.write(f"**Affected applications:** {', '.join(primary['affected_apps'])}\n\n")
                f.write(f"**Recommendation:** Focus on fixing this root cause on {primary['app']} first.\n\n")
            else:
                f.write(f"⚠️ **MULTIPLE ISSUES:** No single dominant root cause.\n\n")
                f.write(f"Top 3 causes account for {sum(cause['errors_percent'] for cause in root_causes[:3]):.1f}% of errors.\n")
                f.write(f"Needs systematic investigation of each root cause.\n\n")

def main():
    parser = argparse.ArgumentParser(description='Generate trace-based root cause report')
    parser.add_argument('--input', required=True, help='Input JSON from trace_extractor')
    parser.add_argument('--output', required=True, help='Output markdown report')
    
    args = parser.parse_args()
    
    generate_report(args.input, args.output)
    print(f"✅ Report generated: {args.output}")

if __name__ == '__main__':
    main()
