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
import threading
import time

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR / 'v4'))

from core.fetch_unlimited import fetch_unlimited
from v4.pipeline_v4 import PipelineV4
from v4.phase_f_report import PhaseF_Report

# DB
try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_DB = True
except ImportError:
    HAS_DB = False

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

# Incident Analysis v5.2
try:
    from incident_analysis import (
        IncidentAnalysisEngine,
        IncidentReportFormatter,
    )
    from incident_analysis.knowledge_base import KnowledgeBase
    from incident_analysis.knowledge_matcher import KnowledgeMatcher
    from incident_analysis.models import calculate_priority
    HAS_INCIDENT_ANALYSIS = True
except ImportError:
    HAS_INCIDENT_ANALYSIS = False


def run_incident_analysis_daily(all_incidents, start_date, end_date):
    """
    Spustí Incident Analysis na agregovaných datech z backfillu.
    
    Pro backfill používáme daily mode - agregace přes celé období.
    
    Returns:
        str: Formátovaný report nebo None
    """
    if not HAS_INCIDENT_ANALYSIS:
        safe_print("   ⚠️  Incident Analysis not available")
        return None
    
    if not all_incidents.incidents:
        return None
    
    try:
        # 1. Analyzuj incidenty
        engine = IncidentAnalysisEngine()
        result = engine.analyze(
            all_incidents.incidents,
            analysis_start=start_date,
            analysis_end=end_date,
        )
        
        if result.total_incidents == 0:
            return None
        
        # 2. Knowledge matching
        kb_path = SCRIPT_DIR.parent / 'config' / 'known_issues'
        if kb_path.exists():
            kb = KnowledgeBase(str(kb_path))
            kb.load()
            
            matcher = KnowledgeMatcher(kb)
            result = matcher.enrich_incidents(result)
            
            # Přepočti priority
            for incident in result.incidents:
                incident.priority, incident.priority_reasons = calculate_priority(
                    knowledge_status=incident.knowledge_status,
                    severity=incident.severity,
                    blast_radius=incident.scope.blast_radius,
                    namespace_count=len(incident.scope.namespaces),
                    propagated=incident.scope.propagated,
                    propagation_time_sec=incident.scope.propagation_time_sec,
                )
        
        # 3. Formátuj jako daily report (ne 15min)
        formatter = IncidentReportFormatter()
        report = formatter.format_daily(result)
        
        return report
        
    except Exception as e:
        safe_print(f"   ⚠️  Incident Analysis error: {e}")
        return None


# Thread-safe print
_print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print with flush"""
    with _print_lock:
        print(*args, **kwargs, flush=True)


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_DDL_USER', os.getenv('DB_USER')),
        password=os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD')),
        connect_timeout=30,
        options='-c statement_timeout=300000' # 5 min statement timeout
    )


def save_incidents_to_db(collection, date_str: str) -> int:
    """
    Save incidents to database - RUNS IN MAIN THREAD ONLY
    Returns number of saved records or 0 on error
    """
    if not HAS_DB:
        safe_print(f" ⚠️ {date_str} - No DB driver")
        return 0
    
    if not collection or not collection.incidents:
        return 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SET ROLE role_ailog_analyzer_ddl")
        
        # Prepare data
        data = []
        for incident in collection.incidents:
            ts = incident.time.first_seen or datetime.now(timezone.utc)
            data.append((
                ts,
                ts.weekday(),
                ts.hour,
                ts.minute // 15,
                incident.namespaces[0] if incident.namespaces else 'unknown',
                incident.stats.current_count,
                int(incident.stats.baseline_rate) if incident.stats.baseline_rate > 0 else incident.stats.current_count,
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
        
        execute_values(cursor, """
            INSERT INTO ailog_peak.peak_investigation
            (timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
             original_value, reference_value, 
             is_new, is_spike, is_burst, is_cross_namespace,
             error_type, error_message, detection_method, score, severity)
            VALUES %s
        """, data, page_size=1000)
        
        conn.commit()
        cursor.close()
        conn.close()
        return len(data)
        
    except Exception as e:
        safe_print(f" ⚠️ {date_str} - DB error: {e}")
        return 0


def process_day_worker(date: datetime, dry_run: bool = False) -> dict:
    """
    Worker function - VŽDY vrátí výsledek, NIKDY nevisí.
    
    Vrací:
        {
            'status': 'success' | 'error' | 'no_data',
            'date': str,
            'error_count': int,
            'collection': IncidentCollection | None, # Pro DB insert v main
            'error': str | None
        }
    """
    date_str = date.strftime('%Y-%m-%d')
    thread_name = threading.current_thread().name
    
    # Default result - VŽDY se vrátí něco
    result = {
        'status': 'error',
        'date': date_str,
        'error_count': 0,
        'collection': None,
        'incidents': 0,
        'error': None
    }
    
    try:
        # 1. Fetch
        safe_print(f" 📅 [{thread_name}] {date_str} - Fetching...")
        
        date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = date.replace(hour=23, minute=59, second=59, microsecond=0)
        
        errors = fetch_unlimited(
            date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
            date_to.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        
        if errors is None:
            result['status'] = 'error'
            result['error'] = 'Fetch returned None'
        elif len(errors) == 0:
            result['status'] = 'no_data'
        else:
            result['error_count'] = len(errors)
            safe_print(f" 📥 [{thread_name}] {date_str} - {len(errors):,} errors, running pipeline...")
            
            # 2. Pipeline
            pipeline = PipelineV4(
                spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
                ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
            )
            
            collection = pipeline.run(errors, run_id=f"backfill-{date.strftime('%Y%m%d')}")
            
            result['collection'] = collection
            result['incidents'] = collection.total_incidents
            result['by_severity'] = collection.by_severity
            result['status'] = 'success'
            
            safe_print(f" ✅ [{thread_name}] {date_str} - Pipeline done: {collection.total_incidents} incidents")
        
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        safe_print(f" ❌ [{thread_name}] {date_str} - Exception: {e}")
    
    # VŽDY vrátit výsledek (po try/except, ne v finally)
    return result


def run_backfill(
    days: int = 14,
    date_from: str = None,
    date_to: str = None,
    output_dir: str = None,
    dry_run: bool = False,
    workers: int = 1,
    skip_analysis: bool = False
) -> dict:
    """
    Spustí backfill - workers dělají jen pipeline, DB insert v main threadu.
    """
    safe_print("=" * 70)
    safe_print("🔄 BACKFILL V2 - Fixed Concurrency Model")
    safe_print("=" * 70)
    
    # Determine date range
    if date_from and date_to:
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
    
    safe_print(f"\n📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    safe_print(f" Total days: {(end_date - start_date).days + 1}")
    safe_print(f" Workers: {workers}")
    safe_print(f" DB insert: MAIN THREAD (not workers)")
    
    if dry_run:
        safe_print(" Mode: DRY RUN")
    
    # Generate dates
    dates = []
    current_date = start_date
    while current_date <= end_date:
        dates.append(current_date)
        current_date += timedelta(days=1)
    
    # Process
    results = []
    collections_to_save = [] # (date_str, collection) tuples
    
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
        
        WORKER_TIMEOUT = 600 # 10 min per worker
        
        safe_print(f"\n🚀 Starting {len(dates)} days with {workers} parallel workers...")
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Submit all
            futures = {
                executor.submit(process_day_worker, d, dry_run): d 
                for d in dates
            }
            
            safe_print(f" 📤 Submitted {len(futures)} tasks\n")
            
            # Collect results with timeout
            completed = 0
            for future in as_completed(futures, timeout=WORKER_TIMEOUT * len(dates)):
                date = futures[future]
                date_str = date.strftime('%Y-%m-%d')
                completed += 1
                
                try:
                    result = future.result(timeout=WORKER_TIMEOUT)
                    results.append(result)
                    
                    # Collect for DB save (will run in main thread)
                    if result['status'] == 'success' and result.get('collection'):
                        collections_to_save.append((date_str, result['collection']))
                    
                    safe_print(f" ✓ [{completed}/{len(dates)}] {date_str} - {result['status']}")
                    
                except TimeoutError:
                    safe_print(f" ⏰ [{completed}/{len(dates)}] {date_str} - TIMEOUT")
                    results.append({
                        'status': 'error',
                        'date': date_str,
                        'error': f'Timeout after {WORKER_TIMEOUT}s'
                    })
                    
                except Exception as e:
                    safe_print(f" ❌ [{completed}/{len(dates)}] {date_str} - {e}")
                    results.append({
                        'status': 'error',
                        'date': date_str,
                        'error': str(e)
                    })
        
        safe_print(f"\n 🏁 All {completed} workers completed")
        
    else:
        # Sequential
        for i, date in enumerate(dates, 1):
            date_str = date.strftime('%Y-%m-%d')
            safe_print(f"\n[{i}/{len(dates)}] {date_str}")
            
            result = process_day_worker(date, dry_run)
            results.append(result)
            
            if result['status'] == 'success' and result.get('collection'):
                collections_to_save.append((date_str, result['collection']))
    
    # =========================================================
    # DB INSERT - RUNS IN MAIN THREAD (after all workers done)
    # =========================================================
    total_saved = 0
    
    if not dry_run and collections_to_save:
        safe_print(f"\n💾 Saving {len(collections_to_save)} collections to DB (main thread)...")
        
        for date_str, collection in collections_to_save:
            saved = save_incidents_to_db(collection, date_str)
            total_saved += saved
            
            # Update result with saved count
            for r in results:
                if r['date'] == date_str:
                    r['saved'] = saved
                    break
            
            safe_print(f" 💾 {date_str}: {saved} saved")
        
        safe_print(f" ✅ Total saved: {total_saved}")
    
    # =========================================================
    # AGGREGATE ALL INCIDENTS FOR REPORT
    # =========================================================
    from v4.incident import IncidentCollection
    from v4.phase_f_report import PhaseF_Report
    
    # Calculate totals first
    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = sum(1 for r in results if r['status'] == 'error')
    no_data_count = sum(1 for r in results if r['status'] == 'no_data')
    total_errors = sum(r.get('error_count', 0) for r in results)
    total_incidents = sum(r.get('incidents', 0) for r in results)
    
    # Merge all collections into one for reporting
    all_incidents = IncidentCollection(
        run_id=f"backfill-{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}",
        run_timestamp=datetime.now(timezone.utc),
        pipeline_version="4.0",
        input_records=total_errors,
    )
    
    for date_str, collection in collections_to_save:
        if collection:
            for inc in collection.incidents:
                all_incidents.add_incident(inc)
    
    # =========================================================
    # SUMMARY - ALWAYS RUNS
    # =========================================================
    safe_print("\n" + "=" * 70)
    safe_print("📊 BACKFILL SUMMARY")
    safe_print("=" * 70)
    
    safe_print(f"\n Days processed: {len(results)}")
    safe_print(f" ✅ Successful: {success_count}")
    safe_print(f" ⚪ No data: {no_data_count}")
    safe_print(f" ❌ Failed: {error_count}")
    safe_print(f"\n Total errors fetched: {total_errors:,}")
    safe_print(f" Total incidents: {total_incidents}")
    safe_print(f" Saved to DB: {total_saved}")
    
    # Per-day breakdown
    if results:
        safe_print(f"\n Per-day breakdown:")
        for r in sorted(results, key=lambda x: x['date']):
            status_icon = {'success': '✅', 'error': '❌', 'no_data': '⚪'}.get(r['status'], '?')
            saved = r.get('saved', 0)
            incidents = r.get('incidents', 0)
            safe_print(f" {status_icon} {r['date']}: {incidents} incidents, {saved} saved")
    
    # =========================================================
    # INCIDENT ANALYSIS REPORT (legacy)
    # =========================================================
    if all_incidents.total_incidents > 0:
        reporter = PhaseF_Report()
        
        safe_print("\n")
        safe_print(reporter.to_console(all_incidents))
        
        # Save detailed report files
        if output_dir:
            report_files = reporter.save_snapshot(all_incidents, output_dir)
            safe_print(f"\n📄 Detailed reports saved:")
            safe_print(f" JSON: {report_files.get('json')}")
            safe_print(f" Markdown: {report_files.get('markdown')}")
            safe_print(f" Summary: {report_files.get('summary')}")
    
    # =========================================================
    # INCIDENT ANALYSIS v5.2 (daily mode)
    # =========================================================
    if HAS_INCIDENT_ANALYSIS and all_incidents.total_incidents > 0 and not skip_analysis:
        safe_print("\n" + "=" * 70)
        safe_print("🔍 INCIDENT ANALYSIS v5.2 (Daily Mode)")
        safe_print("=" * 70)
        
        analysis_report = run_incident_analysis_daily(
            all_incidents,
            start_date,
            end_date
        )
        
        if analysis_report:
            safe_print(analysis_report)
    
    # Save summary JSON
    if output_dir:
        summary_path = Path(output_dir) / f"backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Clean results for JSON (remove collection objects)
        json_results = []
        for r in results:
            r_copy = {k: v for k, v in r.items() if k != 'collection'}
            json_results.append(r_copy)
        
        with open(summary_path, 'w') as f:
            json.dump({
                'backfill_date': datetime.now().isoformat(),
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'summary': {
                    'days_processed': len(results),
                    'successful': success_count,
                    'failed': error_count,
                    'no_data': no_data_count,
                    'total_errors': total_errors,
                    'total_incidents': total_incidents,
                    'total_saved': total_saved,
                },
                'results': json_results
            }, f, indent=2, default=str)
        
        safe_print(f"\n💾 Summary saved: {summary_path}")
    
    safe_print("\n" + "=" * 70)
    safe_print("✅ BACKFILL COMPLETE")
    safe_print("=" * 70)
    
    return {
        'days_processed': len(results),
        'success_count': success_count,
        'error_count': error_count,
        'total_errors': total_errors,
        'total_incidents': total_incidents,
        'total_saved': total_saved,
    }


def main():
    parser = argparse.ArgumentParser(description='Backfill V2 - Fixed Concurrency')
    parser.add_argument('--days', type=int, default=14, help='Number of days (default: 14)')
    parser.add_argument('--from', dest='date_from', help='Start date')
    parser.add_argument('--to', dest='date_to', help='End date')
    parser.add_argument('--output', type=str, help='Output directory')
    parser.add_argument('--dry-run', action='store_true', help='No DB writes')
    parser.add_argument('--workers', type=int, default=1, help='Parallel workers (default: 1)')
    parser.add_argument('--no-analysis', action='store_true', help='Skip incident analysis')
    
    args = parser.parse_args()
    
    result = run_backfill(
        days=args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        output_dir=args.output,
        dry_run=args.dry_run,
        workers=args.workers,
        skip_analysis=args.no_analysis
    )
    
    return 0 if result['error_count'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())



    