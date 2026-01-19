#!/usr/bin/env python3
"""
Analyze and Track - Intelligent Analysis + Error Pattern Tracking

This module integrates:
1. Trace-based root cause analysis (from intelligent_analysis.py)
2. Error pattern tracking (to error_patterns table)
3. Known issues matching

Used by run_pipeline.py for steps 2-3 and 5a.
"""

import os
import sys
import json
import hashlib
import psycopg2
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv

# Add scripts dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_unlimited import fetch_unlimited

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}


class TraceAnalyzer:
    """
    Trace-based root cause analysis.
    Groups errors by trace_id and finds the first error in each chain.
    """
    
    def __init__(self, errors):
        self.errors = errors
        self.trace_groups = defaultdict(list)
        self._group_by_trace_id()
    
    def _group_by_trace_id(self):
        """Group all errors by trace_id"""
        for error in self.errors:
            trace_id = error.get('trace_id', 'NO_TRACE')
            if trace_id:  # Skip empty trace IDs
                self.trace_groups[trace_id].append(error)
    
    def get_trace_chain(self, trace_id):
        """Get full error chain for given trace_id, sorted by timestamp"""
        errors = self.trace_groups.get(trace_id, [])
        return sorted(errors, key=lambda e: e.get('timestamp', ''))
    
    def find_root_cause(self, trace_id):
        """Find root cause (first error) in trace chain"""
        chain = self.get_trace_chain(trace_id)
        return chain[0] if chain else None
    
    def get_root_causes_summary(self):
        """
        Get summary of all root causes.
        Returns: list of dicts with root cause info
        """
        root_causes = {}
        
        for trace_id, errors in self.trace_groups.items():
            if trace_id == 'NO_TRACE':
                continue
                
            chain = sorted(errors, key=lambda e: e.get('timestamp', ''))
            if not chain:
                continue
            
            root_error = chain[0]
            app = root_error.get('application', 'unknown')
            msg = root_error.get('message', '')[:200]
            namespace = root_error.get('namespace', 'unknown')
            
            # Create unique key
            cause_key = f"{app}:{msg[:100]}"
            
            if cause_key not in root_causes:
                root_causes[cause_key] = {
                    'app': app,
                    'message': msg,
                    'namespace': namespace,
                    'trace_ids': [],
                    'total_errors': 0,
                    'first_seen': root_error.get('timestamp', ''),
                    'last_seen': root_error.get('timestamp', ''),
                    'affected_apps': set(),
                    'affected_namespaces': set()
                }
            
            rc = root_causes[cause_key]
            rc['trace_ids'].append(trace_id)
            rc['total_errors'] += len(errors)
            rc['affected_namespaces'].add(namespace)
            
            for e in errors:
                rc['affected_apps'].add(e.get('application', 'unknown'))
                if e.get('timestamp', '') < rc['first_seen']:
                    rc['first_seen'] = e.get('timestamp', '')
                if e.get('timestamp', '') > rc['last_seen']:
                    rc['last_seen'] = e.get('timestamp', '')
        
        # Convert sets to lists for JSON serialization
        for rc in root_causes.values():
            rc['affected_apps'] = list(rc['affected_apps'])
            rc['affected_namespaces'] = list(rc['affected_namespaces'])
        
        # Sort by total_errors descending
        return sorted(root_causes.values(), key=lambda x: x['total_errors'], reverse=True)
    
    def get_stats(self):
        """Get overall statistics"""
        return {
            'total_traces': len(self.trace_groups),
            'total_errors': sum(len(e) for e in self.trace_groups.values()),
            'traces_with_multiple_errors': sum(1 for e in self.trace_groups.values() if len(e) > 1)
        }


class ErrorPatternTracker:
    """
    Track error patterns in the database.
    Creates hash-based patterns for recurring errors.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.cursor = conn.cursor()
    
    def _create_pattern_hash(self, namespace, error_type, message_prefix):
        """Create MD5 hash for error pattern"""
        pattern_str = f"{namespace}:{error_type}:{message_prefix[:100]}"
        return hashlib.md5(pattern_str.encode()).hexdigest()
    
    def _extract_error_type(self, message):
        """Extract error type from message"""
        # Common patterns
        if 'Exception' in message:
            # Find the exception name
            import re
            match = re.search(r'(\w+Exception)', message)
            if match:
                return match.group(1)
        if '404' in message:
            return 'NotFound'
        if '500' in message or '503' in message:
            return 'ServerError'
        if '403' in message:
            return 'Forbidden'
        if '401' in message:
            return 'Unauthorized'
        return 'Unknown'
    
    def _calculate_severity(self, error_count):
        """Calculate severity based on error count per 15min"""
        if error_count >= 500:
            return 'critical'
        elif error_count >= 200:
            return 'high'
        elif error_count >= 50:
            return 'medium'
        else:
            return 'low'
    
    def track_errors(self, errors):
        """
        Track errors and update error_patterns table.
        
        Args:
            errors: list of error dicts from fetch_unlimited
        
        Returns:
            dict with tracking stats
        """
        # Group errors by pattern
        patterns = defaultdict(lambda: {
            'count': 0,
            'first_seen': None,
            'last_seen': None,
            'messages': []
        })
        
        for error in errors:
            namespace = error.get('namespace', 'unknown')
            message = error.get('message', '')[:500]
            timestamp = error.get('timestamp', '')
            error_type = self._extract_error_type(message)
            
            pattern_hash = self._create_pattern_hash(namespace, error_type, message)
            
            p = patterns[pattern_hash]
            p['count'] += 1
            p['namespace'] = namespace
            p['error_type'] = error_type
            p['message'] = message[:500]
            
            if not p['first_seen'] or timestamp < p['first_seen']:
                p['first_seen'] = timestamp
            if not p['last_seen'] or timestamp > p['last_seen']:
                p['last_seen'] = timestamp
        
        # Update database
        new_patterns = 0
        updated_patterns = 0
        
        for pattern_hash, data in patterns.items():
            severity = self._calculate_severity(data['count'])
            
            try:
                self.cursor.execute("""
                    INSERT INTO ailog_peak.error_patterns 
                    (namespace, error_type, error_message, pattern_hash, 
                     first_seen, last_seen, occurrence_count, avg_errors_per_15min, severity)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (pattern_hash) DO UPDATE SET
                        last_seen = GREATEST(error_patterns.last_seen, EXCLUDED.last_seen),
                        occurrence_count = error_patterns.occurrence_count + 1,
                        avg_errors_per_15min = (error_patterns.avg_errors_per_15min * error_patterns.occurrence_count + EXCLUDED.avg_errors_per_15min) 
                                               / (error_patterns.occurrence_count + 1),
                        severity = EXCLUDED.severity
                    RETURNING (xmax = 0) AS inserted
                """, (
                    data['namespace'],
                    data['error_type'],
                    data['message'],
                    pattern_hash,
                    data['first_seen'],
                    data['last_seen'],
                    1,  # occurrence_count for new
                    data['count'],  # avg_errors_per_15min
                    severity
                ))
                
                result = self.cursor.fetchone()
                if result and result[0]:  # inserted (xmax = 0)
                    new_patterns += 1
                else:
                    updated_patterns += 1
                    
            except Exception as e:
                print(f"   ⚠️ Error tracking pattern: {e}")
        
        self.conn.commit()
        
        return {
            'total_errors': len(errors),
            'unique_patterns': len(patterns),
            'new_patterns': new_patterns,
            'updated_patterns': updated_patterns
        }


class KnownIssuesMatcher:
    """
    Match errors against known issues database.
    """
    
    def __init__(self, conn):
        self.conn = conn
        self.cursor = conn.cursor()
        self._load_known_issues()
    
    def _load_known_issues(self):
        """Load active known issues from database"""
        self.cursor.execute("""
            SELECT id, issue_name, error_type_pattern, affected_namespace, affected_app_name
            FROM ailog_peak.known_issues
            WHERE status = 'active'
        """)
        self.known_issues = self.cursor.fetchall()
    
    def match_error(self, error):
        """
        Check if error matches any known issue.
        
        Returns: known_issue_id or None
        """
        namespace = error.get('namespace', '')
        app = error.get('application', '')
        message = error.get('message', '')
        
        for issue in self.known_issues:
            issue_id, issue_name, error_pattern, ns_pattern, app_pattern = issue
            
            # Match namespace
            if ns_pattern and ns_pattern not in namespace:
                continue
            
            # Match app
            if app_pattern and app_pattern not in app:
                continue
            
            # Match error pattern
            if error_pattern and error_pattern not in message:
                continue
            
            # All conditions match
            return issue_id
        
        return None
    
    def match_errors(self, errors):
        """
        Match list of errors against known issues.
        
        Returns:
            dict with matching stats and matched errors
        """
        matched = []
        unmatched = []
        
        for error in errors:
            issue_id = self.match_error(error)
            if issue_id:
                matched.append({'error': error, 'known_issue_id': issue_id})
            else:
                unmatched.append(error)
        
        return {
            'total_errors': len(errors),
            'matched_count': len(matched),
            'unmatched_count': len(unmatched),
            'matched_errors': matched[:100],  # Limit for memory
            'sample_unmatched': unmatched[:10]  # Sample for analysis
        }


def analyze_period(date_from, date_to, conn=None):
    """
    Main function: Analyze errors for a time period.
    
    Args:
        date_from: ISO format start date (with Z suffix)
        date_to: ISO format end date (with Z suffix)
        conn: Optional DB connection (will create if not provided)
    
    Returns:
        dict with analysis results
    """
    print(f"\n📊 Analyzing period: {date_from} → {date_to}")
    
    # Fetch errors from ES
    print("   🔄 Fetching errors from Elasticsearch...")
    errors = fetch_unlimited(date_from, date_to, batch_size=5000)
    
    if not errors:
        print("   ⚠️ No errors fetched")
        return {'error': 'no_errors_fetched'}
    
    print(f"   ✅ Fetched {len(errors):,} errors")
    
    # Trace analysis
    print("   🔍 Running trace-based root cause analysis...")
    trace_analyzer = TraceAnalyzer(errors)
    trace_stats = trace_analyzer.get_stats()
    root_causes = trace_analyzer.get_root_causes_summary()[:10]  # Top 10
    
    print(f"   ✅ Found {trace_stats['total_traces']:,} unique traces")
    print(f"   ✅ Identified {len(root_causes)} root cause patterns")
    
    results = {
        'period': {'from': date_from, 'to': date_to},
        'total_errors': len(errors),
        'trace_stats': trace_stats,
        'top_root_causes': root_causes
    }
    
    # Database operations (if connection provided)
    if conn:
        # Track error patterns
        print("   📝 Tracking error patterns...")
        tracker = ErrorPatternTracker(conn)
        pattern_stats = tracker.track_errors(errors)
        results['pattern_stats'] = pattern_stats
        print(f"   ✅ {pattern_stats['new_patterns']} new, {pattern_stats['updated_patterns']} updated patterns")
        
        # Match known issues
        print("   🔗 Matching against known issues...")
        matcher = KnownIssuesMatcher(conn)
        match_stats = matcher.match_errors(errors)
        results['known_issues_match'] = {
            'matched': match_stats['matched_count'],
            'unmatched': match_stats['unmatched_count']
        }
        print(f"   ✅ {match_stats['matched_count']} matched, {match_stats['unmatched_count']} unmatched")
    
    return results


def main():
    """CLI interface for standalone testing"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze and Track Errors')
    parser.add_argument('--from', dest='date_from', required=True, help='Start date (ISO format with Z)')
    parser.add_argument('--to', dest='date_to', required=True, help='End date (ISO format with Z)')
    parser.add_argument('--no-db', action='store_true', help='Skip database operations')
    args = parser.parse_args()
    
    print("=" * 80)
    print("🔬 ANALYZE AND TRACK - Error Analysis Pipeline")
    print("=" * 80)
    
    conn = None
    if not args.no_db:
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            print("✅ Connected to database")
        except Exception as e:
            print(f"⚠️ Database connection failed: {e}")
            print("   Running without database operations")
    
    results = analyze_period(args.date_from, args.date_to, conn)
    
    if conn:
        conn.close()
    
    # Print summary
    print("\n" + "=" * 80)
    print("📊 ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"   Total errors: {results.get('total_errors', 0):,}")
    
    if 'trace_stats' in results:
        ts = results['trace_stats']
        print(f"   Unique traces: {ts.get('total_traces', 0):,}")
        print(f"   Multi-error traces: {ts.get('traces_with_multiple_errors', 0):,}")
    
    if 'top_root_causes' in results and results['top_root_causes']:
        print(f"\n🔴 TOP ROOT CAUSES:")
        for i, rc in enumerate(results['top_root_causes'][:5], 1):
            print(f"   {i}. {rc['app']}: {rc['message'][:60]}...")
            print(f"      Errors: {rc['total_errors']}, Traces: {len(rc['trace_ids'])}")
    
    if 'pattern_stats' in results:
        ps = results['pattern_stats']
        print(f"\n📝 ERROR PATTERNS:")
        print(f"   New: {ps.get('new_patterns', 0)}, Updated: {ps.get('updated_patterns', 0)}")
    
    print("\n✅ Analysis complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
