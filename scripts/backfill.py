#!/usr/bin/env python3
"""
BACKFILL - Zpracování historických dat s peak detection
========================================================

Zpracuje posledních N dní S peak detection (po INIT fázi).

Použití:
    python backfill.py --days 14
    python backfill.py --from "2026-01-06" --to "2026-01-20"
    python backfill.py --days 14 --output data/reports/
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
            'v4_backfill',
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


def process_day(
    date: datetime,
    pipeline: PipelineV4,
    dry_run: bool = False
) -> dict:
    """
    Zpracuje jeden den s peak detection.
    """
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=0)
    
    date_from_str = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_to_str = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    print(f"\n📅 {date.strftime('%Y-%m-%d')}")
    
    # Fetch from ES
    errors = fetch_unlimited(date_from_str, date_to_str)
    
    if errors is None:
        print(f"   ❌ Fetch failed")
        return {'status': 'error', 'date': date.strftime('%Y-%m-%d')}
    
    if len(errors) == 0:
        print(f"   ⚪ No errors")
        return {
            'status': 'no_data',
            'date': date.strftime('%Y-%m-%d'),
            'error_count': 0
        }
    
    print(f"   📥 {len(errors):,} errors", end='')
    
    # Run V4 pipeline
    run_id = f"backfill-{date.strftime('%Y%m%d')}"
    
    collection = pipeline.run(errors, run_id=run_id)
    
    print(f" → {collection.total_incidents} incidents", end='')
    
    # Save to DB
    if not dry_run and HAS_DB:
        try:
            conn = get_db_connection()
            saved = save_incidents_to_db(collection, conn)
            conn.close()
            print(f" → 💾 {saved} saved")
        except Exception as e:
            print(f" → ⚠️  DB error: {e}")
            saved = 0
    else:
        print(f" → ⏭️  dry run")
        saved = 0
    
    return {
        'status': 'success',
        'date': date.strftime('%Y-%m-%d'),
        'error_count': len(errors),
        'incidents': collection.total_incidents,
        'saved': saved,
        'by_severity': collection.by_severity
    }


def run_backfill(
    days: int = 14,
    date_from: str = None,
    date_to: str = None,
    output_dir: str = None,
    dry_run: bool = False,
    workers: int = 1
) -> dict:
    """
    Spustí backfill za N dní.
    """
    print("=" * 70)
    print("🔄 BACKFILL - Historical Data Processing")
    print("=" * 70)
    
    # Determine date range
    if date_from and date_to:
        # Parse flexible date formats
        for fmt in ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
            try:
                start_date = datetime.strptime(date_from.replace('Z', ''), fmt.replace('Z', ''))
                break
            except:
                continue
        for fmt in ['%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
            try:
                end_date = datetime.strptime(date_to.replace('Z', ''), fmt.replace('Z', ''))
                break
            except:
                continue
        
        start_date = start_date.replace(tzinfo=timezone.utc)
        end_date = end_date.replace(tzinfo=timezone.utc)
    else:
        end_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        start_date = end_date - timedelta(days=days - 1)
    
    print(f"\n📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"   Total days: {(end_date - start_date).days + 1}")
    print(f"   Workers: {workers}")
    
    if dry_run:
        print("   Mode: DRY RUN")
    
    # Generate list of dates
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)
    
    # Process days
    results = []
    
    if workers > 1:
        # Parallel processing
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        def process_day_wrapper(date):
            # Each thread gets its own pipeline
            pipeline = PipelineV4(
                spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
                ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
            )
            return process_day(date, pipeline, dry_run)
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(process_day_wrapper, d): d for d in dates}
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
    else:
        # Sequential processing
        pipeline = PipelineV4(
            spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
            ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
        )
        
        for date in dates:
            result = process_day(date, pipeline, dry_run)
            results.append(result)
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 BACKFILL SUMMARY")
    print("=" * 70)
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = sum(1 for r in results if r['status'] == 'error')
    no_data_count = sum(1 for r in results if r['status'] == 'no_data')
    total_errors = sum(r.get('error_count', 0) for r in results)
    total_incidents = sum(r.get('incidents', 0) for r in results)
    total_saved = sum(r.get('saved', 0) for r in results)
    
    print(f"\n   Days processed: {len(results)}")
    print(f"   ✅ Successful: {success_count}")
    print(f"   ⚪ No data: {no_data_count}")
    print(f"   ❌ Failed: {error_count}")
    print(f"\n   Total errors: {total_errors:,}")
    print(f"   Total incidents: {total_incidents}")
    print(f"   Saved to DB: {total_saved}")
    
    # Save summary
    if output_dir:
        summary_path = Path(output_dir) / f"backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(summary_path, 'w') as f:
            json.dump({
                'backfill_date': datetime.now().isoformat(),
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'total_errors': total_errors,
                'total_incidents': total_incidents,
                'results': results
            }, f, indent=2, default=str)
        
        print(f"\n💾 Summary: {summary_path}")
    
    print("\n" + "=" * 70)
    print("✅ BACKFILL COMPLETE")
    print("=" * 70)
    
    return {
        'days_processed': len(results),
        'success_count': success_count,
        'error_count': error_count,
        'total_errors': total_errors,
        'total_incidents': total_incidents,
        'total_saved': total_saved,
    }


def main():
    parser = argparse.ArgumentParser(description='Backfill - Historical Data Processing')
    parser.add_argument('--days', type=int, default=14, help='Number of days to backfill (default: 14)')
    parser.add_argument('--from', dest='date_from', help='Start date')
    parser.add_argument('--to', dest='date_to', help='End date')
    parser.add_argument('--output', type=str, help='Output directory for summary')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no DB writes')    parser.add_argument('--workers', type=int, default=1, help='Parallel workers (default: 1, try 4-8)')    
    args = parser.parse_args()
    
    result = run_backfill(
        days=args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        output_dir=args.output,
        dry_run=args.dry_run,
        workers=args.workers
    )
    
    return 0 if result['error_count'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
