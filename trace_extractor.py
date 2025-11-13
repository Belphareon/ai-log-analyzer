#!/usr/bin/env python3
"""
Trace Extractor - group errors by trace_id and detect root causes
"""
import json
from collections import defaultdict
from datetime import datetime
import argparse

class TraceExtractor:
    """Extract and analyze trace_id groups"""
    
    def __init__(self, errors):
        self.errors = errors
        self.trace_groups = defaultdict(list)
        self._group_by_trace_id()
    
    def _group_by_trace_id(self):
        """Group all errors by trace_id"""
        for error in self.errors:
            trace_id = error.get('trace_id', 'NO_TRACE')
            self.trace_groups[trace_id].append(error)
    
    def get_trace_chain(self, trace_id):
        """Get full error chain for given trace_id, sorted by timestamp"""
        errors = self.trace_groups.get(trace_id, [])
        return sorted(errors, key=lambda e: e.get('timestamp', ''))
    
    def find_root_cause_in_trace(self, trace_id):
        """Find root cause (first error) in trace chain"""
        chain = self.get_trace_chain(trace_id)
        if chain:
            return chain[0]  # First error chronologically
        return None
    
    def get_root_causes(self):
        """Find root cause for each unique trace_id"""
        root_causes_dict = {}  # key: normalized message, value: list of root causes
        
        for trace_id in self.trace_groups.keys():
            root_error = self.find_root_cause_in_trace(trace_id)
            if root_error:
                app = root_error.get('app', 'unknown')
                msg = root_error.get('message', '')
                namespace = root_error.get('namespace', 'unknown')
                timestamp = root_error.get('timestamp', '')
                
                # Create key from app + first 100 chars of message
                cause_key = f"{app}: {msg[:100]}"
                
                if cause_key not in root_causes_dict:
                    root_causes_dict[cause_key] = {
                        'app': app,
                        'message': msg[:150],
                        'trace_ids': [],
                        'first_seen': timestamp,
                        'last_seen': timestamp,
                        'total_errors_in_traces': 0,
                        'affected_namespaces': set(),
                        'affected_apps': set(),
                    }
                
                # Update stats
                root_causes_dict[cause_key]['trace_ids'].append(trace_id)
                root_causes_dict[cause_key]['total_errors_in_traces'] += len(self.trace_groups[trace_id])
                root_causes_dict[cause_key]['affected_namespaces'].add(namespace)
                
                # Collect all affected apps from this trace
                for error in self.trace_groups[trace_id]:
                    root_causes_dict[cause_key]['affected_apps'].add(error.get('app', 'unknown'))
                
                # Update timestamps
                chain = self.get_trace_chain(trace_id)
                if chain:
                    root_causes_dict[cause_key]['first_seen'] = min(
                        root_causes_dict[cause_key]['first_seen'],
                        chain[0].get('timestamp', '')
                    )
                    root_causes_dict[cause_key]['last_seen'] = max(
                        root_causes_dict[cause_key]['last_seen'],
                        chain[-1].get('timestamp', '')
                    )
        
        # Sort by total errors descending
        sorted_causes = sorted(
            root_causes_dict.items(),
            key=lambda x: x[1]['total_errors_in_traces'],
            reverse=True
        )
        
        return sorted_causes
    
    def get_stats(self):
        """Get overall statistics"""
        total_traces = len(self.trace_groups)
        total_errors = sum(len(errors) for errors in self.trace_groups.values())
        
        # Errors per app
        app_errors = defaultdict(int)
        for errors in self.trace_groups.values():
            for error in errors:
                app = error.get('app', 'unknown')
                app_errors[app] += 1
        
        # Errors per namespace
        ns_errors = defaultdict(int)
        for errors in self.trace_groups.values():
            for error in errors:
                ns = error.get('namespace', 'unknown')
                ns_errors[ns] += 1
        
        return {
            'total_traces': total_traces,
            'total_errors': total_errors,
            'app_distribution': dict(sorted(app_errors.items(), key=lambda x: -x[1])),
            'namespace_distribution': dict(sorted(ns_errors.items(), key=lambda x: -x[1])),
        }

def main():
    parser = argparse.ArgumentParser(description='Extract trace_id groups and find root causes')
    parser.add_argument('--input', required=True, help='Input JSON file from fetch')
    parser.add_argument('--output', required=True, help='Output JSON file with root causes')
    
    args = parser.parse_args()
    
    # Load errors
    with open(args.input) as f:
        data = json.load(f)
    
    errors = data.get('errors', [])
    print(f"📊 Loaded {len(errors)} errors")
    
    # Extract traces
    extractor = TraceExtractor(errors)
    
    # Get stats
    stats = extractor.get_stats()
    print(f"\n📈 Statistics:")
    print(f"   Total traces: {stats['total_traces']}")
    print(f"   Total errors: {stats['total_errors']}")
    print(f"\n🎯 App Distribution:")
    for app, count in list(stats['app_distribution'].items())[:5]:
        pct = (count / stats['total_errors'] * 100) if stats['total_errors'] > 0 else 0
        print(f"   {app}: {count} errors ({pct:.1f}%)")
    print(f"\n🔗 Namespace Distribution:")
    for ns, count in list(stats['namespace_distribution'].items())[:5]:
        pct = (count / stats['total_errors'] * 100) if stats['total_errors'] > 0 else 0
        print(f"   {ns}: {count} errors ({pct:.1f}%)")
    
    # Find root causes
    root_causes = extractor.get_root_causes()
    
    print(f"\n🔍 Root Causes Found: {len(root_causes)}")
    for i, (cause_key, cause_data) in enumerate(root_causes[:5], 1):
        pct = (cause_data['total_errors_in_traces'] / stats['total_errors'] * 100) if stats['total_errors'] > 0 else 0
        print(f"\n   {i}. {cause_data['app']}")
        print(f"      Message: {cause_data['message'][:80]}...")
        print(f"      Errors: {cause_data['total_errors_in_traces']} ({pct:.1f}%)")
        print(f"      Traces: {len(cause_data['trace_ids'])}")
        print(f"      Apps affected: {', '.join(sorted(cause_data['affected_apps']))}")
        print(f"      Namespaces: {', '.join(sorted(cause_data['affected_namespaces']))}")
    
    # Save output
    output = {
        'period_start': data.get('period_start'),
        'period_end': data.get('period_end'),
        'stats': stats,
        'root_causes': [
            {
                'rank': i,
                'app': cause_data['app'],
                'message': cause_data['message'],
                'errors_count': cause_data['total_errors_in_traces'],
                'errors_percent': round((cause_data['total_errors_in_traces'] / stats['total_errors'] * 100), 1) if stats['total_errors'] > 0 else 0,
                'trace_ids_count': len(cause_data['trace_ids']),
                'trace_ids': cause_data['trace_ids'][:10],  # First 10 for reference
                'affected_apps': sorted(list(cause_data['affected_apps'])),
                'affected_namespaces': sorted(list(cause_data['affected_namespaces'])),
                'first_seen': cause_data['first_seen'],
                'last_seen': cause_data['last_seen'],
            }
            for i, (_, cause_data) in enumerate(root_causes, 1)
        ]
    }
    
    with open(args.output, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n✅ Root causes saved to {args.output}")

if __name__ == '__main__':
    main()
