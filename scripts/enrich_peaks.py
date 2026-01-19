#!/usr/bin/env python3
"""
Enrich detected peaks with trace analysis details.

This script:
1. Finds peaks in peak_investigation with missing trace_id
2. Fetches errors from ES for that time window and namespace
3. Identifies the most representative trace_id 
4. Updates peak_investigation with trace_id and error details

Run after peak detection to add investigation context.
"""

import sys
import os
import json
import argparse
import psycopg2
from datetime import datetime, timedelta, timezone
from collections import Counter
from dotenv import load_dotenv

# Add scripts directory for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_unlimited import fetch_unlimited

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD')
}


def fetch_errors_for_window(timestamp, namespace, window_minutes=15):
    """
    Fetch all errors from ES for a specific time window and namespace.
    Returns list of error records with trace_id, message, app_name etc.
    """
    # Parse timestamp and create window
    if isinstance(timestamp, str):
        ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    else:
        ts = timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    
    # Window: timestamp to timestamp + window_minutes
    window_start = ts
    window_end = ts + timedelta(minutes=window_minutes)
    
    date_from = window_start.isoformat().replace('+00:00', 'Z')
    date_to = window_end.isoformat().replace('+00:00', 'Z')
    
    print(f"   Fetching errors for {namespace} in window {date_from} → {date_to}")
    
    errors = fetch_unlimited(date_from, date_to, batch_size=5000)
    
    if not errors:
        return []
    
    # Filter by namespace
    ns_errors = [e for e in errors if e.get('namespace') == namespace]
    print(f"   Found {len(ns_errors)} errors in namespace {namespace} (total: {len(errors)})")
    
    return ns_errors


def analyze_errors(errors):
    """
    Analyze errors to extract key details:
    - Most common trace_id (for investigation)
    - Most common error message pattern
    - Most common application
    - Error type classification
    """
    if not errors:
        return {
            'trace_id': None,
            'app_name': None,
            'error_type': 'unknown',
            'error_message': None,
            'affected_services': None
        }
    
    # Count trace_ids (ignore empty ones)
    trace_ids = [e.get('trace_id', '') for e in errors if e.get('trace_id')]
    trace_counter = Counter(trace_ids)
    
    # Most common trace_id (appears in most errors = likely root cause)
    most_common_trace = trace_counter.most_common(1)[0][0] if trace_counter else None
    
    # Count applications
    apps = [e.get('application', 'unknown') for e in errors if e.get('application')]
    app_counter = Counter(apps)
    most_common_app = app_counter.most_common(1)[0][0] if app_counter else None
    
    # Get error messages
    messages = [e.get('message', '')[:200] for e in errors if e.get('message')]
    
    # Simple error type classification based on message patterns
    error_type = 'unknown'
    sample_message = messages[0] if messages else None
    
    if sample_message:
        msg_lower = sample_message.lower()
        if 'timeout' in msg_lower or 'timed out' in msg_lower:
            error_type = 'timeout'
        elif 'connection' in msg_lower or 'refused' in msg_lower or 'connect' in msg_lower:
            error_type = 'connection'
        elif 'null' in msg_lower or 'nullpointer' in msg_lower:
            error_type = 'null_reference'
        elif 'sql' in msg_lower or 'database' in msg_lower or 'jdbc' in msg_lower:
            error_type = 'database'
        elif 'auth' in msg_lower or 'unauthorized' in msg_lower or '401' in msg_lower:
            error_type = 'authentication'
        elif '500' in msg_lower or 'internal server' in msg_lower:
            error_type = 'server_error'
        elif 'queue' in msg_lower or 'jms' in msg_lower or 'kafka' in msg_lower:
            error_type = 'messaging'
        elif 'memory' in msg_lower or 'outofmemory' in msg_lower or 'heap' in msg_lower:
            error_type = 'memory'
        else:
            error_type = 'application'
    
    # Affected services (unique apps with errors)
    affected = list(app_counter.keys())[:5]  # Top 5
    
    return {
        'trace_id': most_common_trace,
        'app_name': most_common_app,
        'error_type': error_type,
        'error_message': sample_message[:500] if sample_message else None,
        'affected_services': ', '.join(affected) if affected else None
    }


def enrich_peak(peak_id, timestamp, namespace, conn):
    """
    Enrich a single peak with trace analysis.
    """
    print(f"\n🔍 Enriching peak {peak_id}: {timestamp} | {namespace}")
    
    # Fetch errors from ES
    errors = fetch_errors_for_window(timestamp, namespace)
    
    if not errors:
        print(f"   ⚠️  No errors found in ES for this window")
        return False
    
    # Analyze errors
    analysis = analyze_errors(errors)
    
    print(f"   📊 Analysis:")
    print(f"      Trace ID: {analysis['trace_id'] or 'N/A'}")
    print(f"      App: {analysis['app_name'] or 'N/A'}")
    print(f"      Error type: {analysis['error_type']}")
    print(f"      Affected: {analysis['affected_services'] or 'N/A'}")
    
    # Update peak_investigation
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE ailog_peak.peak_investigation
            SET 
                trace_id = %s,
                app_name = %s,
                error_type = %s,
                error_message = %s,
                affected_services = %s,
                updated_at = NOW()
            WHERE peak_id = %s
        """, (
            analysis['trace_id'],
            analysis['app_name'],
            analysis['error_type'],
            analysis['error_message'],
            analysis['affected_services'],
            peak_id
        ))
        conn.commit()
        print(f"   ✅ Peak {peak_id} enriched successfully")
        return True
    except Exception as e:
        print(f"   ❌ Failed to update peak {peak_id}: {e}")
        conn.rollback()
        return False


def main():
    parser = argparse.ArgumentParser(description='Enrich detected peaks with trace analysis')
    parser.add_argument('--peak-id', type=int, help='Enrich specific peak by ID')
    parser.add_argument('--all', action='store_true', help='Enrich all peaks without trace_id')
    parser.add_argument('--status', default='new', help='Only peaks with this status (default: new)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without updating')
    
    args = parser.parse_args()
    
    if not args.peak_id and not args.all:
        parser.print_help()
        print("\n❌ Specify --peak-id or --all")
        return 1
    
    print("=" * 80)
    print("🔍 Peak Enrichment - Add Trace Analysis")
    print("=" * 80)
    
    # Connect to DB
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    # Get peaks to enrich
    if args.peak_id:
        cur.execute("""
            SELECT peak_id, timestamp, namespace 
            FROM ailog_peak.peak_investigation 
            WHERE peak_id = %s
        """, (args.peak_id,))
    else:
        cur.execute("""
            SELECT peak_id, timestamp, namespace 
            FROM ailog_peak.peak_investigation 
            WHERE (trace_id IS NULL OR trace_id = '')
              AND investigation_status = %s
            ORDER BY timestamp DESC
        """, (args.status,))
    
    peaks = cur.fetchall()
    print(f"\n📋 Found {len(peaks)} peaks to enrich\n")
    
    if not peaks:
        print("✅ All peaks already enriched!")
        return 0
    
    if args.dry_run:
        print("🔵 DRY RUN - showing peaks that would be enriched:\n")
        for peak_id, timestamp, namespace in peaks:
            print(f"   [{peak_id}] {timestamp} | {namespace}")
        return 0
    
    # Enrich each peak
    success = 0
    failed = 0
    
    for peak_id, timestamp, namespace in peaks:
        if enrich_peak(peak_id, timestamp, namespace, conn):
            success += 1
        else:
            failed += 1
    
    print("\n" + "=" * 80)
    print(f"📊 ENRICHMENT SUMMARY")
    print(f"   ✅ Enriched: {success}")
    print(f"   ❌ Failed: {failed}")
    print("=" * 80)
    
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
