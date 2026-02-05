#!/usr/bin/env python3
"""
GENERATE DAILY REPORT
=====================

Generuje denní reporty z DB.

Použití:
    python generate_daily_report.py --from-db --days 14 --output ./reports
    python generate_daily_report.py --from-db --date-from 2026-01-08 --date-to 2026-01-21
"""

import os
import sys
import argparse
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from collections import defaultdict
import hashlib

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'pipeline'))

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

from pipeline.incident import (
    Incident, IncidentCollection, IncidentSeverity, IncidentCategory,
)
from pipeline.daily_report_models import KnownIssuesRegistry
from pipeline.daily_report_generator import DailyReportGenerator
from pipeline.daily_report_formatter import DailyReportFormatter


def guess_category(error_type: str, message: str) -> IncidentCategory:
    """Odhadne kategorii"""
    text = f"{error_type} {message}".lower()
    
    if any(kw in text for kw in ['database', 'sql', 'jdbc', 'connection pool', 'deadlock', 'postgres']):
        return IncidentCategory.DATABASE
    if any(kw in text for kw in ['timeout', 'timed out', 'read timed']):
        return IncidentCategory.TIMEOUT
    if any(kw in text for kw in ['connection refused', 'connection reset', 'network', 'dns', 'econnrefused']):
        return IncidentCategory.NETWORK
    if any(kw in text for kw in ['401', '403', 'unauthorized', 'forbidden', 'auth', 'token']):
        return IncidentCategory.AUTH
    if any(kw in text for kw in ['404', 'not found', 'validation', 'invalid', 'illegalargument']):
        return IncidentCategory.BUSINESS
    if any(kw in text for kw in ['memory', 'oom', 'heap', 'outofmemory']):
        return IncidentCategory.MEMORY
    if any(kw in text for kw in ['external', '503', '500', 'upstream', 'service unavailable']):
        return IncidentCategory.EXTERNAL
    
    return IncidentCategory.UNKNOWN


def load_from_db(date_from: datetime, date_to: datetime) -> IncidentCollection:
    """Načte z DB"""
    import psycopg2
    
    print(f"📥 Loading from database...")
    print(f"   Period: {date_from.strftime('%Y-%m-%d')} to {date_to.strftime('%Y-%m-%d')}")
    
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
    )
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            timestamp, namespace, original_value, reference_value,
            is_new, is_spike, is_burst, is_cross_namespace,
            error_type, error_message, score, severity
        FROM ailog_peak.peak_investigation
        WHERE timestamp >= %s AND timestamp < %s
        ORDER BY timestamp
    """, (date_from, date_to + timedelta(days=1)))
    
    rows = cursor.fetchall()
    print(f"   Loaded {len(rows):,} records")
    
    cursor.close()
    conn.close()
    
    if not rows:
        return IncidentCollection(
            run_id=f"db-{date_from.strftime('%Y%m%d')}-{date_to.strftime('%Y%m%d')}",
            run_timestamp=datetime.now(timezone.utc),
            pipeline_version="4.0",
            input_records=0,
        )
    
    # Group by fingerprint
    grouped = defaultdict(list)
    for row in rows:
        (timestamp, namespace, original_value, reference_value,
         is_new, is_spike, is_burst, is_cross_namespace,
         error_type, error_message, score, severity) = row
        
        fp = hashlib.md5(f"{error_type}:{error_message}".encode()).hexdigest()[:16]
        grouped[fp].append(row)
    
    print(f"   Found {len(grouped):,} unique fingerprints")
    
    collection = IncidentCollection(
        run_id=f"db-{date_from.strftime('%Y%m%d')}-{date_to.strftime('%Y%m%d')}",
        run_timestamp=datetime.now(timezone.utc),
        pipeline_version="4.0",
        input_records=len(rows),
    )
    
    for fp, fp_rows in grouped.items():
        row = fp_rows[0]
        (timestamp, namespace, original_value, reference_value,
         is_new, is_spike, is_burst, is_cross_namespace,
         error_type, error_message, score, severity) = row
        
        namespaces = list(set(r[1] for r in fp_rows if r[1]))
        total_count = sum(r[2] or 0 for r in fp_rows)
        avg_ref = sum(r[3] or 0 for r in fp_rows) / len(fp_rows) if fp_rows else 0
        
        timestamps = [r[0] for r in fp_rows if r[0]]
        first_seen = min(timestamps) if timestamps else None
        last_seen = max(timestamps) if timestamps else None
        
        inc = Incident(
            id=f"db-{fp[:8]}",
            fingerprint=fp,
            pipeline_version="4.0",
        )
        
        inc.normalized_message = error_message or ''
        inc.error_type = error_type or 'Unknown'
        inc.namespaces = namespaces
        inc.apps = list(set(ns.replace('-app', '').rsplit('-', 2)[0] for ns in namespaces[:5]))
        
        inc.time.first_seen = first_seen
        inc.time.last_seen = last_seen
        if first_seen and last_seen:
            inc.time.duration_sec = int((last_seen - first_seen).total_seconds())
        
        inc.stats.current_count = total_count
        inc.stats.current_rate = total_count / len(fp_rows) if fp_rows else 0
        inc.stats.baseline_rate = avg_ref
        inc.stats.trend_ratio = (total_count / len(fp_rows) / avg_ref) if avg_ref > 0 else 1.0
        
        inc.flags.is_new = any(r[4] for r in fp_rows)
        inc.flags.is_spike = any(r[5] for r in fp_rows)
        inc.flags.is_burst = any(r[6] for r in fp_rows)
        inc.flags.is_cross_namespace = any(r[7] for r in fp_rows)
        
        inc.score = max(r[10] or 0 for r in fp_rows)
        
        sev_map = {
            'critical': IncidentSeverity.CRITICAL,
            'high': IncidentSeverity.HIGH,
            'medium': IncidentSeverity.MEDIUM,
            'low': IncidentSeverity.LOW,
            'info': IncidentSeverity.INFO,
        }
        inc.severity = sev_map.get(severity, IncidentSeverity.INFO)
        inc.category = guess_category(error_type, error_message)
        inc.subcategory = 'from_db'
        
        collection.add_incident(inc)
    
    print(f"   Created {collection.total_incidents:,} incidents")
    return collection


def main():
    parser = argparse.ArgumentParser(description='Generate daily analysis report')
    parser.add_argument('--from-db', action='store_true', required=True)
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--date-from', type=str)
    parser.add_argument('--date-to', type=str)
    parser.add_argument('--output', type=str, default='./reports')
    parser.add_argument('--format', choices=['all', 'console', 'markdown', 'json'], default='all')
    parser.add_argument('--registry', type=str)
    parser.add_argument('--update-registry', action='store_true')
    
    args = parser.parse_args()
    
    # Date range
    if args.date_from and args.date_to:
        date_from = datetime.strptime(args.date_from, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        date_to = datetime.strptime(args.date_to, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    else:
        date_to = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        date_from = date_to - timedelta(days=args.days)
    
    # Load data
    collection = load_from_db(date_from, date_to)
    
    if collection.total_incidents == 0:
        print("❌ No data")
        return 1
    
    # Registry
    registry = KnownIssuesRegistry()
    if args.registry:
        print(f"📚 Loading registry from {args.registry}")
        registry = KnownIssuesRegistry.load_yaml(args.registry)
        print(f"   Known errors: {len(registry.errors)}")
        print(f"   Known peaks: {len(registry.peaks)}")
    
    # Generate
    print(f"\n🔍 Generating report...")
    generator = DailyReportGenerator(registry=registry)
    bundle = generator.generate_bundle(collection, update_registry=args.update_registry)
    print(f"   Generated {len(bundle.daily_reports)} daily reports")
    
    # Format
    formatter = DailyReportFormatter()
    
    if args.format == 'console':
        print("\n" + formatter.to_console(bundle))
    else:
        print("\n" + formatter.to_console(bundle))
        
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        if args.format == 'all':
            files = formatter.save_all(bundle, str(output_dir))
            print(f"\n📄 Reports saved:")
            for fmt, path in files.items():
                print(f"   {fmt}: {path}")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if args.format == 'markdown':
                path = output_dir / f"report_{timestamp}.md"
                with open(path, 'w') as f:
                    f.write(formatter.to_markdown(bundle))
            else:
                path = output_dir / f"report_{timestamp}.json"
                with open(path, 'w') as f:
                    f.write(formatter.to_json(bundle))
            print(f"\n📄 Saved: {path}")
    
    # Save registry
    if args.update_registry and args.registry:
        print(f"\n📚 Saving registry...")
        registry.save_yaml(args.registry)
        print(f"   Errors: {len(registry.errors)}, Peaks: {len(registry.peaks)}")
    
    print("\n✅ Done")
    return 0


if __name__ == '__main__':
    sys.exit(main())
