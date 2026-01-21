#!/usr/bin/env python3
"""
REGULAR PHASE - Hlavní pipeline pro cron (každých 15 minut)
===========================================================

Spouští se každých 15 minut pro zpracování nových dat s peak detection.

Použití:
    python regular_phase.py
    python regular_phase.py --output data/reports/
    python regular_phase.py --quiet  # pro cron
"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR / 'v4'))

from core.fetch_unlimited import fetch_unlimited

# Import V4 pipeline
from v4.pipeline_v4 import PipelineV4
from v4.phase_f_report import PhaseF_Report
from v4.incident import IncidentSeverity

# DB
try:
    import psycopg2
    HAS_DB = True
except ImportError:
    HAS_DB = False

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')


def get_db_connection():
    """Get database connection (uses DDL user for INSERT operations)"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_DDL_USER', os.getenv('DB_USER')),
        password=os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD'))
    )


def save_incidents_to_db(collection, conn) -> int:
    """Save incidents to database - BATCH INSERT"""
    cursor = conn.cursor()
    
    # Set role for DDL operations
    cursor.execute("SET ROLE role_ailog_analyzer_ddl")
    
    if not collection.incidents:
        return 0
    
    # Prepare data for batch insert
    data = []
    for incident in collection.incidents:
        ts = incident.time.first_seen or datetime.now(timezone.utc)
        data.append((
            ts,
            ts.weekday(),
            ts.hour,
            ts.minute // 15,
            incident.namespaces[0] if incident.namespaces else 'unknown',
            incident.stats.current_count,  # original_value
            int(incident.stats.baseline_rate) if incident.stats.baseline_rate > 0 else incident.stats.current_count,  # reference_value
            incident.flags.is_new,
            incident.flags.is_spike,
            incident.flags.is_burst,
            incident.flags.is_cross_namespace,
            incident.error_type or '',
            (incident.normalized_message or '')[:500],
            'v4_pipeline',
            incident.score,
            incident.severity.value
        ))
    
    # Batch insert using execute_values (much faster)
    try:
        from psycopg2.extras import execute_values
        
        execute_values(cursor, """
            INSERT INTO ailog_peak.peak_investigation
            (timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
             original_value, reference_value, 
             is_new, is_spike, is_burst, is_cross_namespace,
             error_type, error_message, detection_method, score, severity)
            VALUES %s
        """, data, page_size=1000)
        
        conn.commit()
        return len(data)
    except Exception as e:
        print(f" ⚠️  Batch insert error: {e}")
        conn.rollback()
        return 0


def update_error_patterns(collection, conn) -> int:
    """Update error_patterns table with fingerprints"""
    cursor = conn.cursor()
    updated = 0
    
    for incident in collection.incidents:
        try:
            ts = incident.time.first_seen or datetime.now(timezone.utc)
            
            cursor.execute("""
                INSERT INTO ailog_peak.error_patterns
                (namespace, error_type, error_message, pattern_hash, 
                 first_seen, last_seen, occurrence_count, severity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pattern_hash) DO UPDATE SET
                    last_seen = GREATEST(error_patterns.last_seen, EXCLUDED.last_seen),
                    occurrence_count = error_patterns.occurrence_count + 1,
                    updated_at = NOW()
            """, (
                incident.namespaces[0] if incident.namespaces else 'unknown',
                incident.error_type,
                incident.normalized_message[:500],
                incident.fingerprint,
                ts,
                incident.time.last_seen or ts,
                incident.stats.current_count,
                incident.severity.value
            ))
            updated += 1
        except:
            pass
    
    conn.commit()
    return updated


def send_alerts(collection, webhook_url: str = None):
    """Send alerts for critical/high incidents"""
    critical = [i for i in collection.incidents if i.severity == IncidentSeverity.CRITICAL]
    high = [i for i in collection.incidents if i.severity == IncidentSeverity.HIGH]
    
    if not critical and not high:
        return
    
    print(f"\n🚨 ALERTS: {len(critical)} critical, {len(high)} high")
    
    # TODO: Implement Teams/Slack webhook
    if webhook_url:
        try:
            import requests
            payload = {
                "@type": "MessageCard",
                "themeColor": "FF0000" if critical else "FFA500",
                "summary": f"AI Log Analyzer: {len(critical)} critical, {len(high)} high incidents",
                "sections": [{
                    "activityTitle": "🚨 Incident Alert",
                    "facts": [
                        {"name": "Critical", "value": str(len(critical))},
                        {"name": "High", "value": str(len(high))},
                        {"name": "Time", "value": datetime.now().strftime("%Y-%m-%d %H:%M")},
                    ]
                }]
            }
            requests.post(webhook_url, json=payload, timeout=10)
        except Exception as e:
            print(f"   ⚠️  Alert send failed: {e}")


def run_regular_pipeline(
    date_from: str = None,
    date_to: str = None,
    output_dir: str = None,
    dry_run: bool = False,
    quiet: bool = False
) -> dict:
    """
    Spustí regular pipeline pro jedno 15-min okno.
    """
    start_time = datetime.now()
    
    if not quiet:
        print("=" * 70)
        print("🚀 REGULAR PHASE - 15-minute Pipeline")
        print(f"   Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
    
    # Determine time window
    now = datetime.now(timezone.utc)
    
    if date_from and date_to:
        window_start = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        window_end = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
    else:
        # Align to 15-min boundary (process previous window)
        minute = (now.minute // 15) * 15
        window_end = now.replace(minute=minute, second=0, microsecond=0)
        window_start = window_end - timedelta(minutes=15)
    
    window_start_str = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    window_end_str = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    if not quiet:
        print(f"\n📅 Window: {window_start_str} → {window_end_str}")
    
    # Fetch from ES
    errors = fetch_unlimited(window_start_str, window_end_str)
    
    if errors is None:
        if not quiet:
            print("   ❌ Fetch failed")
        return {'status': 'error', 'reason': 'fetch_failed'}
    
    if len(errors) == 0:
        if not quiet:
            print("   ✅ No errors in this window")
        return {
            'status': 'success',
            'window': {'start': window_start_str, 'end': window_end_str},
            'error_count': 0,
            'incidents': 0
        }
    
    if not quiet:
        print(f"   📥 Fetched {len(errors):,} errors")
    
    # Create and run V4 pipeline
    pipeline = PipelineV4(
        spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
        ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
    )
    
    run_id = f"regular-{window_start.strftime('%Y%m%d-%H%M')}"
    
    if quiet:
        # Suppress pipeline output in quiet mode
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            collection = pipeline.run(errors, run_id=run_id)
    else:
        collection = pipeline.run(errors, run_id=run_id)
    
    if not quiet:
        print(f"\n📊 Results:")
        print(f"   Incidents: {collection.total_incidents}")
        print(f"   By severity: {collection.by_severity}")
    
    # Save to DB
    saved_incidents = 0
    if not dry_run and HAS_DB:
        try:
            conn = get_db_connection()
            saved_incidents = save_incidents_to_db(collection, conn)
            update_error_patterns(collection, conn)
            conn.close()
            
            if not quiet:
                print(f"\n💾 Saved {saved_incidents} incidents to DB")
        except Exception as e:
            if not quiet:
                print(f"   ⚠️  DB error: {e}")
    elif dry_run and not quiet:
        print("\n   ⏭️  DRY RUN - not saving to DB")
    
    # Save report
    if output_dir:
        reporter = PhaseF_Report()
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        files = reporter.save_snapshot(collection, str(output_path))
        if not quiet:
            print(f"\n💾 Reports saved to: {output_dir}")
    
    # Send alerts
    webhook_url = os.getenv('TEAMS_WEBHOOK_URL')
    if collection.by_severity.get('critical', 0) > 0 or collection.by_severity.get('high', 0) > 0:
        send_alerts(collection, webhook_url)
    
    # Duration
    duration = (datetime.now() - start_time).total_seconds()
    
    if not quiet:
        print("\n" + "=" * 70)
        print(f"✅ REGULAR PHASE COMPLETE ({duration:.1f}s)")
        print("=" * 70)
    
    return {
        'status': 'success',
        'window': {'start': window_start_str, 'end': window_end_str},
        'error_count': len(errors),
        'incidents': collection.total_incidents,
        'saved': saved_incidents,
        'by_severity': collection.by_severity,
        'duration_sec': duration
    }


def main():
    parser = argparse.ArgumentParser(description='Regular Phase - 15-minute Pipeline')
    parser.add_argument('--from', dest='date_from', help='Start time (ISO format)')
    parser.add_argument('--to', dest='date_to', help='End time (ISO format)')
    parser.add_argument('--output', type=str, help='Output directory for reports')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no DB writes')
    parser.add_argument('--quiet', action='store_true', help='Minimal output (for cron)')
    
    args = parser.parse_args()
    
    result = run_regular_pipeline(
        date_from=args.date_from,
        date_to=args.date_to,
        output_dir=args.output,
        dry_run=args.dry_run,
        quiet=args.quiet
    )
    
    # Exit code
    if result.get('status') == 'error':
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
