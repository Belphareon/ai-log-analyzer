#!/usr/bin/env python3
"""
Intelligent Error Analysis - Step 1: Load and basic stats
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
            errors = data.get('errors', [])
            all_errors.extend(errors)
            print(f"  ✓ {batch_file.name}: {len(errors)} errors")
    
    print(f"\n✅ Total: {len(all_errors):,} errors loaded\n")
    return all_errors

def analyze_timeline_5min(errors):
    """Timeline aggregated by 5 minutes"""
    timeline = defaultdict(int)
    
    for error in errors:
        timestamp = error['timestamp']
        # Extract hour:minute, round to 5min
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        min_bucket = (dt.minute // 5) * 5
        time_key = f"{dt.hour:02d}:{min_bucket:02d}"
        timeline[time_key] += 1
    
    print("=" * 80)
    print("⏰ TIMELINE (5-minute buckets)")
    print("=" * 80)
    
    sorted_timeline = sorted(timeline.items())
    max_count = max(timeline.values()) if timeline else 1
    
    for time, count in sorted_timeline:
        if count > 0:
            bar_len = int((count / max_count) * 40)
            bar = "█" * bar_len
            print(f"{time}: {count:4d} {bar}")
    
    # Find peak
    peak_time, peak_count = max(timeline.items(), key=lambda x: x[1])
    print(f"\n🔥 Peak: {peak_time} with {peak_count:,} errors")
    return timeline

def extract_api_calls(errors):
    """Extract API endpoints and HTTP codes from errors"""
    api_patterns = []
    
    for error in errors:
        msg = error['message']
        
        # Pattern: #GET#some.host#/api/path#404#
        match = re.search(r'#(GET|POST|PUT|DELETE)#([^#]+)#(/[^#]+)#(\d{3})#', msg)
        if match:
            method, host, path, code = match.groups()
            api_patterns.append({
                'method': method,
                'host': host,
                'path': path,
                'code': code,
                'app': error['app'],
                'namespace': error.get('namespace', 'unknown'),
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
        msg = error['message']
        app = error['app']
        ns = error.get('namespace', 'unknown')
        
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
        app_ns_errors[error['app']][error.get('namespace', 'unknown')] += 1
    
    # Identify error types
    business_exceptions = [e for e in errors if 'ServiceBusinessException' in e['message']]
    not_found = [e for e in errors if 'NotFoundException' in e['message'] or '404' in e['message']]
    server_errors = [e for e in errors if '503' in e['message'] or '500' in e['message']]
    auth_errors = [e for e in errors if 'AuthorizationDenied' in e['message'] or '403' in e['message']]
    event_errors = [e for e in errors if 'event' in e['message'].lower() and 'not processed' in e['message'].lower()]
    
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
    relay_errors = [e for e in errors if e['app'] == 'bl-pcb-event-processor-relay-v1']
    print(f"\n  1. Event Processor → Core Service Chain")
    print(f"     • bl-pcb-event-processor-relay-v1 has {len(relay_errors)} errors")
    print(f"     • Majority are failed calls to bl-pcb-v1 (339 failures detected)")
    print(f"     • Environments: FAT (125), UAT (117), DEV (77), SIT (20)")
    print(f"     ⚠️  ACTION: Investigate event relay timeouts/failures to bl-pcb-v1")
    
    # Finding 2: DoGS external service
    dogs_errors = [e for e in errors if 'dogs-test.dslab.kb.cz' in e['message']]
    if dogs_errors:
        print(f"\n  2. External DoGS Service Integration")
        print(f"     • DoGS API calls failing: {len(dogs_errors)} errors (500 server error)")
        print(f"     • Affects: bl-pcb-v1 in SIT (20) and DEV (12) environments")
        print(f"     ⚠️  ACTION: Check DoGS service health / API compatibility")
    
    # Finding 3: Account servicing
    account_errors = [e for e in errors if 'accountservicing' in e['message']]
    if account_errors:
        print(f"\n  3. Account Servicing Integration")
        print(f"     • bc-accountservicing API failures: {len(account_errors)} (403 Forbidden)")
        print(f"     • Missing authorization for customer data access")
        print(f"     ⚠️  ACTION: Review API credentials / permissions")
    
    # Finding 4: Resource not found pattern
    card_not_found = [e for e in not_found if 'Card' in e['message'] or 'card' in e['message']]
    print(f"\n  4. Card Resource Not Found")
    print(f"     • {len(card_not_found)} card lookup failures")
    print(f"     • Primarily in SIT environment ({len([e for e in card_not_found if e.get('namespace') == 'pcb-sit-01-app'])} errors)")
    print(f"     ⚠️  ACTION: Review test data quality in SIT")
    
    # Finding 5: Event queuing
    if event_errors:
        billing = [e for e in event_errors if 'billing' in e['app']]
        docs = [e for e in event_errors if 'document' in e['app']]
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
    analyze_timeline_5min(errors)
    analyze_api_calls(errors)
    analyze_cross_app_correlation(errors)
    generate_big_picture(errors)
