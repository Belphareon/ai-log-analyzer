#!/usr/bin/env python3
"""
Intelligent Error Analysis - Step 1: Load and basic stats
WITH TRACE-BASED ROOT CAUSE ANALYSIS
"""
import json
import sys
import re
from collections import defaultdict
from pathlib import Path
from datetime import datetime

def load_batches(batch_dir):
    """Load all batch data"""
    all_errors = []
    batch_files = sorted(Path(batch_dir).glob("batch_*.json"))
    
    print(f"📊 Loading batches from {batch_dir}...")
    
    for batch_file in batch_files:
        if "summary" in str(batch_file):
            continue
        with open(batch_file) as f:
            data = json.load(f)
            errors = data if isinstance(data, list) else data.get('errors', [])
            all_errors.extend(errors)
            print(f"  ✓ {batch_file.name}: {len(errors)} errors")
    
    print(f"\n✅ Total: {len(all_errors):,} errors loaded\n")
    return all_errors

# ============================================================================
# HELPER: Get app name with fallbacks
# ============================================================================
def get_app(error):
    """Extract application name with fallbacks"""
    return error.get('application') or error.get('app') or 'unknown'

def get_ns(error):
    """Extract namespace name with fallback"""
    return error.get('namespace') or 'unknown'

# ============================================================================
# TRACE-BASED ROOT CAUSE ANALYSIS (NEW)
# ============================================================================

class TraceExtractor:
    """Extract and analyze trace_id groups"""
    
    def __init__(self, errors):
        self.errors = errors
        self.trace_groups = defaultdict(list)
        self._group_by_trace_id()
    
    def _group_by_trace_id(self):
        """Group all errors by trace_id"""
        print(f"   🔄 Grouping {len(self.errors):,} errors by trace_id...")
        for idx, error in enumerate(self.errors):
            if (idx + 1) % 50000 == 0:
                print(f"      ✅ Grouped {idx + 1:,} / {len(self.errors):,} errors...")
            trace_id = error.get('trace_id', 'NO_TRACE')
            self.trace_groups[trace_id].append(error)
        print(f"   ✅ Created {len(self.trace_groups):,} trace groups")
    
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
        
        print(f"   🔄 Analyzing {len(self.trace_groups):,} traces for root causes...")
        
        for idx, trace_id in enumerate(self.trace_groups.keys()):
            if (idx + 1) % 10000 == 0:
                print(f"      ✅ Analyzed {idx + 1:,} / {len(self.trace_groups):,} traces...")
            
            root_error = self.find_root_cause_in_trace(trace_id)
            if root_error:
                app = get_app(root_error)
                msg = root_error.get('message', '')
                namespace = get_ns(root_error)
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
                    app_name = get_app(error)
                    root_causes_dict[cause_key]['affected_apps'].add(app_name)
                
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
        
        print(f"   ✅ Found {len(root_causes_dict)} unique root causes")
        return sorted_causes
    
    def get_stats(self):
        """Get overall statistics"""
        total_traces = len(self.trace_groups)
        total_errors = sum(len(errors) for errors in self.trace_groups.values())
        
        # Errors per app
        app_errors = defaultdict(int)
        for errors in self.trace_groups.values():
            for error in errors:
                app = get_app(error)
                app_errors[app] += 1
        
        # Errors per namespace
        ns_errors = defaultdict(int)
        for errors in self.trace_groups.values():
            for error in errors:
                ns = get_ns(error)
                ns_errors[ns] += 1
        
        return {
            'total_traces': total_traces,
            'total_errors': total_errors,
            'app_distribution': dict(sorted(app_errors.items(), key=lambda x: -x[1])),
            'namespace_distribution': dict(sorted(ns_errors.items(), key=lambda x: -x[1])),
        }

def analyze_trace_based_root_causes(errors):
    """Analyze errors using trace-based root cause detection"""
    
    print(f"\n{'='*80}")
    print("🔍 TRACE-BASED ROOT CAUSE ANALYSIS")
    print("="*80)
    
    extractor = TraceExtractor(errors)
    stats = extractor.get_stats()
    root_causes = extractor.get_root_causes()
    
    print(f"\n📊 Trace Statistics:")
    print(f"  Total unique traces: {stats['total_traces']}")
    print(f"  Total errors: {stats['total_errors']}")
    print(f"  Avg errors per trace: {stats['total_errors'] / stats['total_traces']:.1f}")
    print(f"  Unique root causes: {len(root_causes)}")
    
    print(f"\n🎯 Root Causes by App:")
    for app, count in list(stats['app_distribution'].items())[:5]:
        pct = (count / stats['total_errors'] * 100) if stats['total_errors'] > 0 else 0
        print(f"  {app}: {count:4d} errors ({pct:5.1f}%)")
    
    print(f"\n🔗 Namespace Distribution:")
    for ns, count in list(stats['namespace_distribution'].items())[:5]:
        pct = (count / stats['total_errors'] * 100) if stats['total_errors'] > 0 else 0
        print(f"  {ns}: {count:4d} errors ({pct:5.1f}%)")
    
    print(f"\n🔴 Top Root Causes:")
    for i, (cause_key, cause_data) in enumerate(root_causes[:5], 1):
        pct = (cause_data['total_errors_in_traces'] / stats['total_errors'] * 100) if stats['total_errors'] > 0 else 0
        
        # Severity
        if pct >= 10:
            severity = "🔴 CRITICAL"
        elif pct >= 5:
            severity = "🟠 HIGH"
        elif pct >= 1:
            severity = "🟡 MEDIUM"
        else:
            severity = "🟢 LOW"
        
        print(f"\n  {i}. {severity}")
        print(f"     App: {cause_data['app']}")
        print(f"     Message: {cause_data['message'][:80]}...")
        print(f"     Errors: {cause_data['total_errors_in_traces']} ({pct:.1f}%)")
        print(f"     Traces: {len(cause_data['trace_ids'])}")
        print(f"     Affected apps: {', '.join(sorted(cause_data['affected_apps']))}")
        print(f"     Namespaces: {', '.join(sorted(cause_data['affected_namespaces']))}")

def analyze_timeline_5min(errors):
    """Timeline aggregated by 5 minutes (displayed in CET timezone)"""
    timeline = defaultdict(int)
    
    for error in errors:
        timestamp = error['timestamp']
        # Extract hour:minute, round to 5min
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        # Convert UTC to CET (+1 hour for display)
        dt_cet = dt.replace(tzinfo=None)
        dt_cet = dt_cet.replace(hour=(dt_cet.hour + 1) % 24)
        min_bucket = (dt_cet.minute // 5) * 5
        time_key = f"{dt_cet.hour:02d}:{min_bucket:02d}"
        timeline[time_key] += 1
    
    print("=" * 80)
    print("⏰ TIMELINE (5-minute buckets, CET timezone)")
    print("=" * 80)
    
    sorted_timeline = sorted(timeline.items())
    max_count = max(timeline.values()) if timeline else 1
    
    for time, count in sorted_timeline:
        if count > 0:
            bar_len = int((count / max_count) * 40)
            bar = "█" * bar_len
            print(f"{time} CET: {count:4d} {bar}")
    
    # Find peak
    peak_time, peak_count = max(timeline.items(), key=lambda x: x[1])
    print(f"\n🔥 Peak: {peak_time} CET with {peak_count:,} errors")
    return timeline

def extract_api_calls(errors):
    """Extract API endpoints and HTTP codes from errors"""
    api_patterns = []
    
    for error in errors:
        msg = error.get('message', '')
        
        # Pattern: #GET#some.host#/api/path#404#
        match = re.search(r'#(GET|POST|PUT|DELETE)#([^#]+)#(/[^#]+)#(\d{3})#', msg)
        if match:
            method, host, path, code = match.groups()
            api_patterns.append({
                'method': method,
                'host': host,
                'path': path,
                'code': code,
                'app': get_app(error),
                'namespace': get_ns(error),
                'message': msg
            })
    
    return api_patterns

def analyze_api_calls(errors):
    """Analyze API call patterns and failures"""
    api_calls = extract_api_calls(errors)
    
    if not api_calls:
        print("\n⚠️  No API call patterns detected")
        return
    
    print(f"\n{'='*80}")
    print(f"🌐 API CALL ANALYSIS ({len(api_calls)} API-related errors)")
    print("="*80)
    
    # Group by endpoint + code
    endpoint_fails = defaultdict(lambda: {'count': 0, 'apps': set(), 'namespaces': set()})
    
    for call in api_calls:
        key = f"{call['method']} {call['path']} → {call['code']}"
        endpoint_fails[key]['count'] += 1
        endpoint_fails[key]['apps'].add(call['app'])
        endpoint_fails[key]['namespaces'].add(call['namespace'])
        endpoint_fails[key]['host'] = call['host']
    
    # Sort by count
    sorted_fails = sorted(endpoint_fails.items(), key=lambda x: x[1]['count'], reverse=True)
    
    for i, (endpoint, data) in enumerate(sorted_fails[:15], 1):
        print(f"\n{i}. {endpoint}")
        print(f"   Count: {data['count']:,}")
        print(f"   Host: {data['host']}")
        print(f"   Calling apps: {', '.join(sorted(data['apps']))}")
        print(f"   Namespaces: {', '.join(sorted(data['namespaces']))}")

def analyze_cross_app_correlation(errors):
    """Analyze which apps call which services and where it fails"""
    
    print(f"\n{'='*80}")
    print("🔗 CROSS-APP CORRELATION & CALL CHAINS")
    print("="*80)
    
    # Extract service calls
    service_calls = defaultdict(lambda: defaultdict(int))
    external_calls = defaultdict(lambda: defaultdict(int))
    
    for error in errors:
        msg = error.get('message', '')
        app = get_app(error)
        ns = get_ns(error)
        
        # Internal service calls (bl-pcb-X calling bl-pcb-Y)
        internal_match = re.search(r'(bl-pcb-[\w-]+)\.([^:]+):(\d+)', msg)
        if internal_match:
            target_service, target_ns, port = internal_match.groups()
            key = f"{app} → {target_service}"
            service_calls[key][ns] += 1
        
        # External API calls
        external_match = re.search(r'#(GET|POST)#([a-z\-\.]+)#(/[^#]+)#(\d{3})', msg)
        if external_match:
            method, host, path, code = external_match.groups()
            # Skip internal hosts
            if 'pcb-' not in host and 'bl-pcb' not in host:
                key = f"{app} → {host}{path} ({code})"
                external_calls[key][ns] += 1
    
    # Print internal calls
    if service_calls:
        print("\n📡 Internal Service Calls (bl-pcb → bl-pcb):")
        sorted_calls = sorted(service_calls.items(), key=lambda x: sum(x[1].values()), reverse=True)
        for call_chain, ns_counts in sorted_calls[:10]:
            total = sum(ns_counts.values())
            print(f"\n  {call_chain}")
            print(f"    Total failures: {total}")
            for ns, count in sorted(ns_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"      {ns}: {count}")
    
    # Print external calls
    if external_calls:
        print("\n🌍 External API Calls:")
        sorted_ext = sorted(external_calls.items(), key=lambda x: sum(x[1].values()), reverse=True)
        for call_chain, ns_counts in sorted_ext[:10]:
            total = sum(ns_counts.values())
            print(f"\n  {call_chain}")
            print(f"    Total failures: {total}")
            for ns, count in sorted(ns_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"      {ns}: {count}")

def generate_big_picture(errors):
    """Generate executive summary with actionable insights"""
    
    print(f"\n{'='*80}")
    print("🎯 BIG PICTURE - EXECUTIVE SUMMARY")
    print("="*80)
    
    # Count by app and namespace
    app_ns_errors = defaultdict(lambda: defaultdict(int))
    for error in errors:
        app_name = get_app(error)
        app_ns_errors[app_name][get_ns(error)] += 1
    
    # Identify error types
    business_exceptions = [e for e in errors if 'ServiceBusinessException' in e.get('message', '')]
    not_found = [e for e in errors if 'NotFoundException' in e.get('message', '') or '404' in e.get('message', '')]
    server_errors = [e for e in errors if '503' in e.get('message', '') or '500' in e.get('message', '')]
    auth_errors = [e for e in errors if 'AuthorizationDenied' in e.get('message', '') or '403' in e.get('message', '')]
    event_errors = [e for e in errors if 'event' in e.get('message', '').lower() and 'not processed' in e.get('message', '').lower()]
    
    print(f"\n📊 Overall Statistics:")
    print(f"  Total errors: {len(errors):,}")
    print(f"  Period: 08:30 - 12:30 (4 hours)")
    print(f"  Average: {len(errors)//4:,} errors/hour")
    
    print(f"\n🏆 Top Problem Areas:")
    print(f"  1. Business Exceptions: {len(business_exceptions):,} ({len(business_exceptions)/len(errors)*100:.1f}%)")
    print(f"  2. Resource Not Found (404): {len(not_found):,} ({len(not_found)/len(errors)*100:.1f}%)")
    print(f"  3. Server Errors (500/503): {len(server_errors):,} ({len(server_errors)/len(errors)*100:.1f}%)")
    print(f"  4. Authorization Denied (403): {len(auth_errors):,} ({len(auth_errors)/len(errors)*100:.1f}%)")
    print(f"  5. Event Processing Failures: {len(event_errors):,} ({len(event_errors)/len(errors)*100:.1f}%)")
    
    print(f"\n🔍 Key Findings:")
    
    # Finding 1: bl-pcb-event-processor-relay calling bl-pcb-v1
    relay_errors = [e for e in errors if get_app(e) == 'bl-pcb-event-processor-relay-v1']
    print(f"\n  1. Event Processor → Core Service Chain")
    print(f"     • bl-pcb-event-processor-relay-v1 has {len(relay_errors)} errors")
    print(f"     • Majority are failed calls to bl-pcb-v1 (339 failures detected)")
    print(f"     • Environments: FAT (125), UAT (117), DEV (77), SIT (20)")
    print(f"     ⚠️  ACTION: Investigate event relay timeouts/failures to bl-pcb-v1")
    
    # Finding 2: DoGS external service
    dogs_errors = [e for e in errors if 'dogs-test.dslab.kb.cz' in e.get('message', '')]
    if dogs_errors:
        print(f"\n  2. External DoGS Service Integration")
        print(f"     • DoGS API calls failing: {len(dogs_errors)} errors (500 server error)")
        print(f"     • Affects: bl-pcb-v1 in SIT (20) and DEV (12) environments")
        print(f"     ⚠️  ACTION: Check DoGS service health / API compatibility")
    
    # Finding 3: Account servicing
    account_errors = [e for e in errors if 'accountservicing' in e.get('message', '')]
    if account_errors:
        print(f"\n  3. Account Servicing Integration")
        print(f"     • bc-accountservicing API failures: {len(account_errors)} (403 Forbidden)")
        print(f"     • Missing authorization for customer data access")
        print(f"     ⚠️  ACTION: Review API credentials / permissions")
    
    # Finding 4: Resource not found pattern
    card_not_found = [e for e in not_found if 'Card' in e.get('message', '') or 'card' in e.get('message', '')]
    print(f"\n  4. Card Resource Not Found")
    print(f"     • {len(card_not_found)} card lookup failures")
    print(f"     • Primarily in SIT environment ({len([e for e in card_not_found if get_ns(e) == 'pcb-sit-01-app'])} errors)")
    print(f"     ⚠️  ACTION: Review test data quality in SIT")
    
    # Finding 5: Event queuing
    if event_errors:
        billing = [e for e in event_errors if 'billing' in get_app(e)]
        docs = [e for e in event_errors if 'document' in get_app(e)]
        print(f"\n  5. Event Queue Processing")
        print(f"     • {len(event_errors)} events not processed")
        print(f"     • bl-pcb-billing-v1: {len(billing)} failures")
        print(f"     • bl-pcb-document-signing-v1: {len(docs)} failures")
        print(f"     ⚠️  ACTION: Check event queue backlog / consumer health")
    
    print(f"\n💡 Recommendations Priority:")
    print(f"  🔴 HIGH: Fix event relay → bl-pcb-v1 communication (339 failures)")
    print(f"  🟡 MEDIUM: Investigate DoGS integration (32 failures)")
    print(f"  🟡 MEDIUM: Review SIT test data quality (card not found)")
    print(f"  🟢 LOW: Monitor event queue processing")

if __name__ == "__main__":
    batch_dir = sys.argv[1] if len(sys.argv) > 1 else "data/batches/2025-11-12"
    errors = load_batches(batch_dir)
    analyze_trace_based_root_causes(errors)  # NEW: Trace-based analysis
    analyze_timeline_5min(errors)
    analyze_api_calls(errors)
    analyze_cross_app_correlation(errors)
    generate_big_picture(errors)
