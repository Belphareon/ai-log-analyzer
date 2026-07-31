#!/usr/bin/env python3
"""
BACKFILL - S KOMPLETNÍ REGISTRY INTEGRACÍ + PROBLEM-CENTRIC ANALYSIS
=====================================================================

1. Registry se načítá PŘED pipeline
2. Lookup funguje (známé fingerprinty nejsou marked as NEW)
3. first_seen/last_seen = event timestamps, NE run timestamps
4. Peaks se ukládají
5. Problem_key místo 1:1 fingerprint
6. Správné ukončení (cleanup connections)
7. Detekce již zpracovaných dnů

- Incidenty se agregují do PROBLÉMŮ (problem_key)
- Report iteruje přes problémy, NE incidenty
- Root cause inference (deterministicky z trace)
- Propagation analysis (služby, ne boolean)
- Version impact analysis
- Category refinement (automatická reklasifikace unknown)
- CSV/JSON exporty oddělené od reportu

Použití:
    python backfill.py --days 14
    python backfill.py --from "2026-01-06" --to "2026-01-20"
    python backfill.py --days 14 --workers 4
"""

import os
import sys
import argparse
import json
import yaml
import atexit
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from typing import Dict, List, Optional, Tuple, Any

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent))  # Add parent to path so we can import core/
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from core.fetch_unlimited import (
    INDICES,
    _load_monitored_namespaces,
    fetch_unlimited,
)
from core.problem_registry import ProblemRegistry, compute_problem_key
from core.baseline_loader import BaselineLoader
from core.delivery_persistence import (
    persist_notification_deliveries,
    summarize_delivery_outcomes,
)
from core.run_persistence import build_query_hash, persist_analysis_run
from core.streaming_aggregator import StreamingAggregator
from pipeline import Pipeline
from pipeline.incident import IncidentCollection
from pipeline.phase_f_report import PhaseF_Report

# Table exports
try:
    from exports import TableExporter, export_errors_table
    HAS_EXPORTS = True
except ImportError:
    HAS_EXPORTS = False

# DB
try:
    import psycopg2
    HAS_DB = True
except ImportError:
    HAS_DB = False

from dotenv import load_dotenv
load_dotenv(SCRIPT_DIR.parent / '.env')
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')

# Incident Analysis (legacy)
try:
    from incident_analysis import (
        IncidentAnalysisEngine,
        IncidentReportFormatter,
        IncidentAnalysisResult,
    )
    from incident_analysis.knowledge_base import KnowledgeBase
    from incident_analysis.knowledge_matcher import KnowledgeMatcher
    from incident_analysis.models import calculate_priority
    HAS_INCIDENT_ANALYSIS = True
except ImportError as e:
    HAS_INCIDENT_ANALYSIS = False
    print(f"⚠️ Incident Analysis import failed: {e}")

# Problem-Centric Analysis
try:
    from analysis import (
        aggregate_by_problem_key,
        ProblemReportGenerator,
        ProblemExporter,
        get_representative_traces,
    )
    HAS_PROBLEM_ANALYSIS = True
except ImportError as e:
    HAS_PROBLEM_ANALYSIS = False
    print(f"⚠️ Problem Analysis import failed: {e}")

# Teams Notifications
HAS_TEAMS = False
try:
    # Try direct import first
    from core.teams_notifier import TeamsNotifier
    HAS_TEAMS = True
    print("✅ TeamsNotifier imported successfully")
except ModuleNotFoundError:
    # Fallback: try adding explicit path
    try:
        import importlib.util
        team_path = SCRIPT_DIR.parent / 'core' / 'teams_notifier.py'
        spec = importlib.util.spec_from_file_location("teams_notifier", str(team_path))
        teams_notifier_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(teams_notifier_module)
        TeamsNotifier = teams_notifier_module.TeamsNotifier
        HAS_TEAMS = True
    except Exception as e:
        HAS_TEAMS = False
        print(f"⚠️ Teams notifier not available: {e}")
except Exception as e:
    HAS_TEAMS = False
    print(f"⚠️ Teams notifier import failed: {e}")


# =============================================================================
# GLOBALS
# =============================================================================

_global_registry = None
_global_problem_report = None  # Store problem report for Teams notification

# Thread-safe print
_print_lock = threading.Lock()
_global_problem_report = None  # Store problem report for Teams notification

def safe_print(*args, **kwargs):
    """Thread-safe print with flush"""
    with _print_lock:
        print(*args, **kwargs, flush=True)


def _contextualize_delivery_results(
    results: List[Dict[str, Any]],
    dedup_key: str,
    metadata: Dict[str, Any],
    success: bool,
) -> List[Dict[str, Any]]:
    if not results:
        results = [{
            'destination': 'notification_aggregate',
            'status': 'delivered' if success else 'failed',
            'provider_message': 'Notifier returned aggregate result only',
        }]
    return [{
        **result,
        'dedup_key': dedup_key,
        'metadata': metadata,
    } for result in results]


# Global registry (shared between workers)
_global_registry: Optional[ProblemRegistry] = None
_global_registry_lock = threading.Lock()

# Processed days tracking
_processed_days: set = set()
_processed_days_lock = threading.Lock()


# =============================================================================
# DB CONNECTION
# =============================================================================

def get_db_connection():
    """Get database connection - uses DDL user for write operations
    
    CRITICAL: DDL user (ailog_analyzer_ddl_user_d1) must execute SET ROLE role_ailog_analyzer_ddl
    to gain permissions on ailog_peak schema. This is mandatory.
    """
    user = os.getenv('DB_DDL_USER') or os.getenv('DB_USER')
    password = os.getenv('DB_DDL_PASSWORD') or os.getenv('DB_PASSWORD')
    
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=user,
        password=password,
        connect_timeout=30,
        options='-c statement_timeout=300000'  # 5 min
    )
    
    # MANDATORY: Set role for DDL operations
    cursor = conn.cursor()
    set_db_role(cursor)
    cursor.close()
    
    return conn


def set_db_role(cursor) -> None:
    """Set DDL role after login - REQUIRED for schema access.
    
    DDL user (ailog_analyzer_ddl_user_d1) must SET ROLE to role_ailog_analyzer_ddl
    to gain USAGE/CREATE permissions on ailog_peak schema.
    """
    ddl_role = os.getenv('DB_DDL_ROLE') or 'role_ailog_analyzer_ddl'
    try:
        cursor.execute(f"SET ROLE {ddl_role}")
    except Exception as e:
        safe_print(f"⚠️ Warning: Could not set role {ddl_role}: {e}")
        # Continue anyway - user may have direct permissions


def check_day_processed(date: datetime) -> bool:
    """Return True only for an authoritative complete backfill run."""
    if not HAS_DB:
        return False

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = date_start + timedelta(days=1)
        query_hash = build_query_hash(INDICES, _load_monitored_namespaces())

        cursor.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM ailog_peak.analysis_runs
                WHERE run_type = 'backfill'
                  AND window_start = %s
                  AND window_end = %s
                  AND query_hash = %s
                  AND status = 'complete'
                  AND superseded_by_run_id IS NULL
            )
        """, (date_start, date_end, query_hash))

        complete = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        return bool(complete)

    except Exception as e:
        safe_print(f"⚠️ Error checking day {date.strftime('%Y-%m-%d')}: {e}")
        return False


# =============================================================================
# REGISTRY MANAGEMENT
# =============================================================================

def init_registry(registry_dir: str) -> ProblemRegistry:
    """
    Inicializuje globální registry.
    
    CRITICAL: Musí se volat PŘED spuštěním workerů!
    """
    global _global_registry
    
    with _global_registry_lock:
        if _global_registry is None:
            _global_registry = ProblemRegistry(registry_dir)
            _global_registry.load()
            
            safe_print(f"\n📋 Registry loaded:")
            safe_print(f"   Problems: {len(_global_registry.problems)}")
            safe_print(f"   Peaks: {len(_global_registry.peaks)}")
            safe_print(f"   Known fingerprints: {len(_global_registry.fingerprint_index)}")
        
        return _global_registry


def get_registry() -> Optional[ProblemRegistry]:
    """Vrátí globální registry (thread-safe read)."""
    return _global_registry


def update_registry_from_incidents(
    incidents: List[Any],
    event_timestamps: Dict[str, Tuple[datetime, datetime]]
) -> bool:
    """
    Aktualizuje registry z incidentů.
    
    CRITICAL: event_timestamps obsahuje skutečné časy eventů!
    """
    global _global_registry
    
    if _global_registry is None:
        return False
    
    with _global_registry_lock:
        return _global_registry.update_and_save(incidents, event_timestamps)


# =============================================================================
# WORKER
# =============================================================================

def process_day_worker(date: datetime, dry_run: bool = False, skip_processed: bool = True) -> dict:
    """
    Worker function - zpracuje jeden den.

    - Kontroluje zda den již byl zpracován
    - Používá globální registry
    - Propaguje event timestamps
    """
    date_str = date.strftime('%Y-%m-%d')
    thread_name = threading.current_thread().name
    
    result = {
        'status': 'error',
        'date': date_str,
        'error_count': 0,
        'collection': None,
        'incidents': 0,
        'event_timestamps': {},
        'window_start': None,
        'window_end': None,
        'expected_count': None,
        'fetched_count': 0,
        'error': None,
        'skipped': False,
    }
    
    try:
        # Check if already processed
        if skip_processed and check_day_processed(date):
            safe_print(f" ⏭️ [{thread_name}] {date_str} - Already processed, skipping")
            result['status'] = 'skipped'
            result['skipped'] = True
            return result
        
        # 1. Fetch
        safe_print(f" 📅 [{thread_name}] {date_str} - Fetching...")
        
        date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_to = date_from + timedelta(days=1)
        result['window_start'] = date_from
        result['window_end'] = date_to
        fetch_stats = {}
        aggregator = StreamingAggregator()
        errors = fetch_unlimited(
            date_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
            date_to.strftime("%Y-%m-%dT%H:%M:%SZ"),
            page_consumer=aggregator.ingest_page,
            collect_results=False,
            stats_out=fetch_stats,
        )
        result['expected_count'] = fetch_stats.get('expected')
        result['fetched_count'] = fetch_stats.get('fetched', aggregator.total_records)
        
        if errors is None:
            aggregator.close()
            result['status'] = 'error'
            result['error'] = 'Fetch returned None'
        elif not fetch_stats.get('complete'):
            aggregator.close()
            result['status'] = 'error'
            result['error'] = fetch_stats.get('reason') or 'Fetch incomplete'
        elif aggregator.total_records == 0:
            aggregator.close()
            collection = IncidentCollection(
                run_id=f"backfill-{date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
                run_timestamp=datetime.now(timezone.utc),
                pipeline_version=os.getenv('IMAGE_TAG', '1.0'),
                input_records=0,
                time_range_start=date_from,
                time_range_end=date_to,
            )
            result['collection'] = collection
            result['status'] = 'no_data'
        else:
            result['error_count'] = aggregator.total_records
            safe_print(f" 📥 [{thread_name}] {date_str} - {aggregator.total_records:,} errors, running pipeline...")
            
            # 2. Pipeline with registry
            registry = get_registry()
            known_fps = registry.get_all_known_fingerprints() if registry else set()

            # P93/CAP peak detection
            peak_detector = None
            try:
                from core.peak_detection import PeakDetector
                peak_db_conn = get_db_connection()
                peak_detector = PeakDetector(conn=peak_db_conn)
            except Exception as e:
                safe_print(f"   ⚠️ [{thread_name}] P93/CAP peak detector unavailable: {e}")

            pipeline = Pipeline(
                ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
                peak_detector=peak_detector,
            )

            # Inject registry into Phase C (critical for is_problem_key_known() lookup!)
            if registry:
                pipeline.phase_c.registry = registry
            pipeline.phase_c.known_fingerprints = known_fps.copy()

            # Load historical baseline from DB (same as regular_phase.py)
            historical_baseline = {}
            try:
                db_conn = get_db_connection()
                baseline_loader = BaselineLoader(db_conn)

                fingerprints = list(aggregator.acc)

                if fingerprints:
                    historical_baseline = baseline_loader.load_fingerprint_rates(
                        fingerprints=fingerprints,
                        analysis_window_start=date_from,
                        lookback_days=7,
                        min_samples=3
                    )
                    safe_print(f"   📊 [{thread_name}] Loaded baseline for {len(historical_baseline)}/{len(fingerprints)} fingerprints")

                db_conn.close()
            except Exception as e:
                safe_print(f"   ⚠️ [{thread_name}] Baseline loading failed (non-blocking): {e}")
                historical_baseline = {}

            pipeline.phase_b.historical_baseline = historical_baseline

            try:
                collection = pipeline.run_streaming(
                    aggregator,
                    run_id=f"backfill-{date.strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}",
                )
            finally:
                aggregator.close()
            
            # 3. Extract event timestamps
            event_timestamps = {}
            for incident in collection.incidents:
                fp = incident.fingerprint
                first_ts = incident.time.first_seen
                last_ts = incident.time.last_seen
                
                if first_ts and last_ts:
                    event_timestamps[fp] = (first_ts, last_ts)
            
            result['collection'] = collection
            result['incidents'] = collection.total_incidents
            result['event_timestamps'] = event_timestamps
            result['status'] = 'success'

            safe_print(f" ✅ [{thread_name}] {date_str} - {collection.total_incidents} incidents")
            
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)
        import traceback
        traceback.print_exc()
    
    return result


# =============================================================================
# REPORT GENERATION
# =============================================================================

def run_incident_analysis_daily(all_incidents, start_date, end_date, output_dir=None, quiet=False):
    """Spustí Incident Analysis na agregovaných datech."""
    if not HAS_INCIDENT_ANALYSIS:
        safe_print("   ⚠️ Incident Analysis not available")
        return "⚠️ Incident Analysis module not available"
    
    formatter = IncidentReportFormatter()
    
    if not all_incidents.incidents:
        result = IncidentAnalysisResult(
            incidents=[],
            total_incidents=0,
            analysis_start=start_date,
            analysis_end=end_date,
        )
        report = formatter.format_daily(result)
        _save_report_daily(report, output_dir, start_date, end_date, quiet)
        return report
    
    try:
        engine = IncidentAnalysisEngine()
        result = engine.analyze(
            all_incidents.incidents,
            analysis_start=start_date,
            analysis_end=end_date,
        )
        
        # Knowledge matching
        kb_path = SCRIPT_DIR.parent / 'config' / 'known_issues'
        if kb_path.exists():
            kb = KnowledgeBase(str(kb_path))
            kb.load()
            
            matcher = KnowledgeMatcher(kb)
            result = matcher.enrich_incidents(result)
            
            for incident in result.incidents:
                incident.priority, incident.priority_reasons = calculate_priority(
                    knowledge_status=incident.knowledge_status,
                    severity=incident.severity,
                    blast_radius=incident.scope.blast_radius,
                    namespace_count=len(incident.scope.namespaces),
                    propagated=incident.propagation.propagated,
                    propagation_time_sec=incident.propagation.propagation_time_sec,
                )
        
        report = formatter.format_daily(result)
        _save_report_daily(report, output_dir, start_date, end_date, quiet)
        
        return report
        
    except Exception as e:
        safe_print(f"   ⚠️ Incident Analysis error: {e}")
        import traceback
        traceback.print_exc()
        return f"⚠️ Incident Analysis error: {e}"


def _save_report_daily(report: str, output_dir, start_date, end_date, quiet: bool):
    """Uloží daily report."""
    if not output_dir:
        output_dir = SCRIPT_DIR / 'reports'
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    start_str = start_date.strftime('%Y%m%d') if hasattr(start_date, 'strftime') else str(start_date)[:10].replace('-', '')
    end_str = end_date.strftime('%Y%m%d') if hasattr(end_date, 'strftime') else str(end_date)[:10].replace('-', '')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    filename = f"incident_analysis_daily_{start_str}_{end_str}_{timestamp}.txt"
    filepath = output_path / filename
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report)
    
    if not quiet:
        safe_print(f"   📄 Report saved: {filepath}")


# =============================================================================
# MAIN BACKFILL
# =============================================================================

def run_backfill(
    days: int = 14,
    date_from: str = None,
    date_to: str = None,
    output_dir: str = None,
    dry_run: bool = False,
    workers: int = 1,
    skip_analysis: bool = False,
    skip_processed: bool = True,
) -> dict:
    """
    Hlavní backfill funkce.

    - Načte registry PŘED zpracováním
    - Aktualizuje registry PO zpracování
    - Používá event timestamps
    - Ukládá peaks
    """
    
    # ==========================================================================
    # CALCULATE DATE RANGE
    # ==========================================================================
    now = datetime.now(timezone.utc)
    
    if date_from and date_to:
        start_date = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end_date = now - timedelta(days=1)
        start_date = end_date - timedelta(days=days-1)
    
    dates = []
    current = start_date
    while current <= end_date:
        dates.append(current)
        current += timedelta(days=1)
    
    safe_print("=" * 70)
    safe_print("🔄 BACKFILL - With Registry Integration")
    safe_print("=" * 70)
    safe_print(f"\n📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    safe_print(f" Total days: {len(dates)}")
    safe_print(f" Workers: {workers}")
    safe_print(f" Skip processed: {skip_processed}")
    safe_print(f" DB insert: MAIN THREAD (not workers)")
    
    # ==========================================================================
    # LOAD REGISTRY (CRITICAL!)
    # ==========================================================================
    # IMPORTANT: Registry MUST be on persistence volume!
    # Use REGISTRY_DIR env var if set, otherwise fall back to project registry/ dir
    registry_base = os.getenv('REGISTRY_DIR') or str(SCRIPT_DIR.parent / 'registry')
    registry_dir = Path(registry_base)
    init_registry(str(registry_dir))
    
    # ==========================================================================
    # PROCESS DAYS
    # ==========================================================================
    results = []
    collections_to_save = []
    all_event_timestamps = {}
    
    WORKER_TIMEOUT = 600  # 10 min per day
    
    safe_print(f"\n🚀 Starting {len(dates)} days with {workers} parallel workers...")
    
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for date in dates:
                future = executor.submit(process_day_worker, date, dry_run, skip_processed)
                futures[future] = date
            
            safe_print(f" 📤 Submitted {len(futures)} tasks\n")
            
            completed = 0
            for future in as_completed(futures):
                completed += 1
                date = futures[future]
                date_str = date.strftime('%Y-%m-%d')
                
                try:
                    result = future.result(timeout=WORKER_TIMEOUT)
                    results.append(result)
                    
                    if result['status'] in {'success', 'no_data'} and result.get('collection'):
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
            
            result = process_day_worker(date, dry_run, skip_processed)
            results.append(result)
            
            if result['status'] in {'success', 'no_data'} and result.get('collection'):
                collections_to_save.append((date_str, result['collection']))
    
    # ==========================================================================
    # DB INSERT (MAIN THREAD)
    # ==========================================================================
    total_saved = 0
    
    committed_collections = []
    if not dry_run and collections_to_save:
        safe_print(f"\n💾 Persisting {len(collections_to_save)} complete runs (main thread)...")
        monitored_namespaces = _load_monitored_namespaces()

        for date_str, collection in collections_to_save:
            result = next(item for item in results if item['date'] == date_str)
            try:
                persistence = persist_analysis_run(
                    connection_factory=get_db_connection,
                    collection=collection,
                    run_type='backfill',
                    window_start=result['window_start'],
                    window_end=result['window_end'],
                    monitored_namespaces=monitored_namespaces,
                    expected_count=result['expected_count'],
                    fetched_count=result['fetched_count'],
                    source_index=INDICES,
                )
            except Exception as e:
                result['status'] = 'error'
                result['error'] = str(e)
                safe_print(f" ❌ {date_str}: persistence failed: {e}")
                continue

            result.update(persistence)
            result['saved'] = persistence['incident_rows']
            total_saved += persistence['incident_rows']
            committed_collections.append((date_str, collection))
            all_event_timestamps.update(result.get('event_timestamps', {}))
            safe_print(
                f" ✅ {date_str}: {persistence['persisted_events']:,} events, "
                f"{persistence['fact_rows']:,} facts, "
                f"{persistence['namespace_rows']:,} namespace rows, "
                f"{persistence['incident_rows']:,} incidents"
            )

        safe_print(f" ✅ Total incident rows committed: {total_saved}")
    elif dry_run:
        committed_collections = list(collections_to_save)

    collections_to_save = committed_collections
    
    # ==========================================================================
    # UPDATE REGISTRY (CRITICAL!)
    # ==========================================================================
    if collections_to_save and not dry_run:
        safe_print(f"\n📝 Updating registry with event timestamps...")
        
        all_incidents = []
        for date_str, collection in collections_to_save:
            all_incidents.extend(collection.incidents)
        
        if not update_registry_from_incidents(all_incidents, all_event_timestamps):
            error = 'Registry update failed after database commit'
            safe_print(f" ❌ {error}")
            return {
                'status': 'error',
                'delivery_error': error,
                'days_processed': len(results),
                'total_saved': total_saved,
            }
    
    # ==========================================================================
    # AGGREGATE FOR REPORT
    # ==========================================================================
    from pipeline.incident import IncidentCollection
    
    success_count = sum(1 for r in results if r['status'] == 'success')
    error_count = sum(1 for r in results if r['status'] == 'error')
    no_data_count = sum(1 for r in results if r['status'] == 'no_data')
    skipped_count = sum(1 for r in results if r.get('skipped', False))
    total_errors = sum(r.get('error_count', 0) for r in results)
    total_incidents = sum(r.get('incidents', 0) for r in results)
    
    all_incidents_collection = IncidentCollection(
        run_id=f"backfill-{start_date.strftime('%Y%m%d')}-{end_date.strftime('%Y%m%d')}",
        run_timestamp=datetime.now(timezone.utc),
        pipeline_version="1.0",
        input_records=total_errors,
    )
    
    for date_str, collection in collections_to_save:
        if collection:
            for inc in collection.incidents:
                all_incidents_collection.add_incident(inc)
    
    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    safe_print("\n" + "=" * 70)
    safe_print("📊 BACKFILL SUMMARY")
    safe_print("=" * 70)
    
    safe_print(f"\n Days processed: {len(results)}")
    safe_print(f" ✅ Successful: {success_count}")
    safe_print(f" ⏭️  Skipped: {skipped_count}")
    safe_print(f" ⚪ No data: {no_data_count}")
    safe_print(f" ❌ Failed: {error_count}")
    safe_print(f"\n Total errors fetched: {total_errors:,}")
    safe_print(f" Total incidents: {total_incidents}")
    safe_print(f" Saved to DB: {total_saved}")
    
    if results:
        safe_print(f"\n Per-day breakdown:")
        for r in sorted(results, key=lambda x: x['date']):
            status_icon = {
                'success': '✅',
                'error': '❌',
                'no_data': '⚪',
                'skipped': '⏭️'
            }.get(r['status'], '?')
            saved = r.get('saved', 0)
            incidents = r.get('incidents', 0)
            safe_print(f" {status_icon} {r['date']}: {incidents} incidents, {saved} saved")
    
    last_report_path = None

    # ==========================================================================
    # PROBLEM-CENTRIC ANALYSIS REPORT
    # ==========================================================================
    if all_incidents_collection.total_incidents > 0 and HAS_PROBLEM_ANALYSIS and not skip_analysis:
        safe_print("\n" + "=" * 70)
        safe_print("🔍 PROBLEM ANALYSIS")
        safe_print("=" * 70)

        # 1. Agreguj incidenty do problémů
        safe_print(f"\n📊 Aggregating incidents...")
        problems = aggregate_by_problem_key(all_incidents_collection.incidents)
        safe_print(f"   ✓ Aggregated {len(all_incidents_collection.incidents)} incidents into {len(problems)} problems")

        # 2. Získej reprezentativní traces (pro legacy root cause)
        safe_print(f"   Getting representative traces...")
        trace_flows = get_representative_traces(problems)
        safe_print(f"   ✓ Got traces for {len(trace_flows)} problems")

        # 3. Generuj problem-centric report
        reports_dir = output_dir or str(SCRIPT_DIR / 'reports')

        generator = ProblemReportGenerator(
            problems=problems,
            trace_flows=trace_flows,
            analysis_start=start_date,
            analysis_end=end_date,
            run_id=all_incidents_collection.run_id,
            registry_problems=_global_registry.problems if _global_registry is not None else None,
        )

        # Textový report
        problem_report = generator.generate_text_report(max_problems=20)
        safe_print(problem_report)
        
        # Store for Teams notification
        global _global_problem_report
        _global_problem_report = problem_report

        if not dry_run:
            report_files = generator.save_reports(reports_dir, prefix="problem_report")
            last_report_path = report_files.get('text')
            safe_print(f"\n📄 Problem reports saved:")
            safe_print(f"   Text: {report_files.get('text')}")
            safe_print(f"   JSON: {report_files.get('json')}")

            exporter = ProblemExporter(
                problems=problems,
                run_id=all_incidents_collection.run_id,
                analysis_date=datetime.now(timezone.utc),
            )
            csv_files = exporter.export_all(reports_dir)
            safe_print(f"\n📊 CSV exports saved:")
            for name, path in csv_files.items():
                safe_print(f"   {name}: {path}")

    elif all_incidents_collection.total_incidents > 0:
        # Fallback: Legacy incident report
        reporter = PhaseF_Report()
        safe_print("\n")
        safe_print(reporter.to_console(all_incidents_collection))

        if output_dir and not dry_run:
            report_files = reporter.save_snapshot(all_incidents_collection, output_dir)
            safe_print(f"\n📄 Detailed reports saved:")
            safe_print(f"   JSON: {report_files.get('json')}")
            safe_print(f"   Markdown: {report_files.get('markdown')}")
    
    # Save summary JSON
    if output_dir and not dry_run:
        summary_path = Path(output_dir) / f"backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        
        json_results = []
        for r in results:
            r_copy = {k: v for k, v in r.items() if k not in ('collection', 'event_timestamps')}
            json_results.append(r_copy)
        
        with open(summary_path, 'w') as f:
            json.dump({
                'backfill_version': '1.0',
                'backfill_date': datetime.now().isoformat(),
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'summary': {
                    'days_processed': len(results),
                    'successful': success_count,
                    'skipped': skipped_count,
                    'failed': error_count,
                    'no_data': no_data_count,
                    'total_errors': total_errors,
                    'total_incidents': total_incidents,
                    'total_saved': total_saved,
                },
                'results': json_results
            }, f, indent=2, default=str)
        
        safe_print(f"\n💾 Summary saved: {summary_path}")

    # ==========================================================================
    # EXPORT TABLES (CSV, MD, JSON)
    # ==========================================================================
    if HAS_EXPORTS and _global_registry is not None and not dry_run:
        # CRITICAL: Always export to SCRIPT_DIR/exports, NOT to --output dir
        # CSV uploader expects files in /app/scripts/exports/latest/
        exports_dir = SCRIPT_DIR / 'exports'
        safe_print(f"\n📊 Exporting tables to {exports_dir}...")

        try:
            exporter = TableExporter(_global_registry)
            export_files = exporter.export_all(str(exports_dir))
            safe_print(f"   ✅ Errors table: errors_table_latest.csv/md/json")
            safe_print(f"   ✅ Peaks table: peaks_table_latest.csv/md/json")
        except Exception as e:
            safe_print(f"   ⚠️ Export error: {e}")

    safe_print("\n" + "=" * 70)
    safe_print("✅ BACKFILL COMPLETE")
    safe_print("=" * 70)
    
    publication_outcomes: List[Dict[str, Any]] = []
    notification_outcomes: List[Dict[str, Any]] = []
    date_range_key = (
        f'{start_date.date().isoformat()}:{end_date.date().isoformat()}'
    )

    # ==========================================================================
    # PUBLISH TO CONFLUENCE
    # ==========================================================================
    if _global_problem_report and not dry_run:
        try:
            safe_print("\n📋 Publishing to Confluence...")
            # Dynamic import to avoid requiring recent_incidents_publisher at startup
            import importlib.util
            pub_path = SCRIPT_DIR / 'recent_incidents_publisher.py'
            spec = importlib.util.spec_from_file_location("recent_incidents_publisher", str(pub_path))
            pub_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(pub_module)
            
            confluence_success = bool(pub_module.main(report_path=last_report_path))
            publication_outcomes.append({
                'dedup_key': f'backfill-recent-incidents:{date_range_key}',
                'destination': 'confluence_recent_incidents',
                'status': 'delivered' if confluence_success else 'failed',
                'provider_message': (
                    'Confluence page updated'
                    if confluence_success
                    else 'Publisher returned unsuccessful status'
                ),
                'metadata': {
                    'report_path': str(last_report_path or ''),
                    'date_range': date_range_key,
                },
            })
            if confluence_success:
                safe_print("✅ Confluence published successfully")
            else:
                safe_print("⚠️ Confluence publication skipped or failed")
        except Exception as e:
            publication_outcomes.append({
                'dedup_key': f'backfill-recent-incidents:{date_range_key}',
                'destination': 'confluence_recent_incidents',
                'status': 'failed',
                'provider_message': str(e),
                'metadata': {'date_range': date_range_key},
            })
            safe_print(f"⚠️ Confluence publication failed: {e}")
    elif not dry_run:
        publication_outcomes.append({
            'dedup_key': f'backfill-recent-incidents:{date_range_key}',
            'destination': 'confluence_recent_incidents',
            'status': 'skipped',
            'provider_message': 'No problem report generated',
            'metadata': {'date_range': date_range_key},
        })
    
    # ==========================================================================
    # SEND TEAMS NOTIFICATION
    # ==========================================================================
    if HAS_TEAMS and not dry_run:
        try:
            notifier = TeamsNotifier()
            if notifier.is_enabled():
                now_utc = datetime.now(timezone.utc)
                report_hour_raw = os.getenv('BACKFILL_SUCCESS_REPORT_HOUR_UTC', '7')
                try:
                    report_hour = max(0, min(23, int(report_hour_raw)))
                except (TypeError, ValueError):
                    report_hour = 7

                registry_base = os.getenv('REGISTRY_DIR') or str(SCRIPT_DIR.parent / 'registry')
                marker_path = Path(registry_base) / '.last_backfill_success_report_utc_date'
                today = now_utc.date().isoformat()
                already_sent_today = False
                try:
                    already_sent_today = marker_path.exists() and marker_path.read_text().strip() == today
                except Exception:
                    already_sent_today = False

                # NOTE: use >= instead of == — the CronJob schedule may not fire exactly
                # on report_hour (e.g. schedule "5 */2 * * *" only runs on even hours),
                # so an exact-hour match can permanently suppress the daily digest.
                should_send = (error_count > 0) or (now_utc.hour >= report_hour and not already_sent_today)

                if should_send:
                    registry_stats = _global_registry.get_stats() if _global_registry else {}
                    success = notifier.send_backfill_completed(
                        days_processed=len(results),
                        successful_days=success_count,
                        failed_days=error_count,
                        total_incidents=total_incidents,
                        saved_count=total_saved,
                        registry_updates={
                            'problems': registry_stats.get('new_problems_added', 0),
                            'total_peaks': registry_stats.get('total_peaks', 0),
                            'new_peaks': registry_stats.get('new_peaks_added', 0),
                        },
                        duration_minutes=(now_utc - now).total_seconds() / 60.0,
                        problem_report=_global_problem_report
                    )
                    notification_outcomes.extend(_contextualize_delivery_results(
                        notifier.get_last_delivery_results(),
                        f'backfill-summary:{date_range_key}',
                        {
                            'date_range': date_range_key,
                            'failed_days': error_count,
                            'total_incidents': total_incidents,
                        },
                        success,
                    ))
                    if success:
                        if error_count == 0:
                            marker_path.parent.mkdir(parents=True, exist_ok=True)
                            marker_path.write_text(today)
                        safe_print("✅ Notification sent (email/Teams)")
                    else:
                        safe_print("⚠️ Notification failed")
                else:
                    for destination in notifier.get_configured_destinations():
                        notification_outcomes.append({
                            'dedup_key': f'backfill-summary:{date_range_key}',
                            'destination': destination,
                            'status': 'suppressed',
                            'provider_message': 'Daily success-report cadence',
                            'metadata': {'date_range': date_range_key},
                        })
                    safe_print("ℹ️ Backfill success report suppressed (daily cadence)")
            else:
                for destination in notifier.get_configured_destinations():
                    notification_outcomes.append({
                        'dedup_key': f'backfill-summary:{date_range_key}',
                        'destination': destination,
                        'status': 'skipped',
                        'provider_message': 'Notifier disabled or unconfigured',
                        'metadata': {'date_range': date_range_key},
                    })
                safe_print("⚠️ Teams notifier not enabled (check TEAMS_ENABLED and TEAMS_WEBHOOK_URL)")
        except Exception as e:
            notification_outcomes.append({
                'dedup_key': f'backfill-summary:{date_range_key}',
                'destination': 'notification_runtime',
                'status': 'failed',
                'provider_message': str(e),
                'metadata': {'date_range': date_range_key},
            })
            safe_print(f"⚠️ Teams notification failed: {e}")
    elif not dry_run:
        notification_outcomes.append({
            'dedup_key': f'backfill-summary:{date_range_key}',
            'destination': 'notification_unavailable',
            'status': 'skipped',
            'provider_message': 'Teams notifier module unavailable',
            'metadata': {'date_range': date_range_key},
        })

    delivery_outcomes = publication_outcomes + notification_outcomes
    delivery_summary = summarize_delivery_outcomes(delivery_outcomes)
    if not dry_run and delivery_outcomes:
        try:
            if publication_outcomes:
                persist_notification_deliveries(
                    get_db_connection,
                    publication_outcomes,
                    notification_type='backfill_publication',
                    window_start=start_date,
                )
            if notification_outcomes:
                persist_notification_deliveries(
                    get_db_connection,
                    notification_outcomes,
                    notification_type='backfill_summary',
                    window_start=start_date,
                )
        except Exception as e:
            delivery_summary = {
                **delivery_summary,
                'status': 'failed',
                'audit_error': str(e),
            }
            safe_print(f"❌ Delivery audit persistence failed: {e}")

    if delivery_summary['status'] == 'failed':
        safe_print(
            f"❌ Delivery failed for {len(delivery_summary['failed_dedup_keys'])} "
            "payload(s)"
        )

    return {
        'days_processed': len(results),
        'success_count': success_count,
        'skipped_count': skipped_count,
        'error_count': error_count,
        'total_errors': total_errors,
        'total_incidents': total_incidents,
        'total_saved': total_saved,
        'delivery_status': delivery_summary['status'],
        'delivery_error_count': len(delivery_summary['failed_dedup_keys']) + int(
            bool(delivery_summary.get('audit_error'))
        ),
    }


# =============================================================================
# CLEANUP
# =============================================================================

def cleanup():
    """Registry writes happen only in the post-commit transaction."""


# Register cleanup
atexit.register(cleanup)

def signal_handler(signum, frame):
    """Handle termination signals"""
    print(f"\n⚠️ Received signal {signum}, cleaning up...")
    cleanup()
    sys.exit(1)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Backfill - With Registry Integration')
    parser.add_argument('--days', type=int, default=14, help='Number of days (default: 14)')
    parser.add_argument('--from', dest='date_from', help='Start date')
    parser.add_argument('--to', dest='date_to', help='End date')
    parser.add_argument('--output', type=str, help='Output directory')
    parser.add_argument('--dry-run', action='store_true', help='No DB writes')
    parser.add_argument('--workers', type=int, default=1, help='Parallel workers (default: 1)')
    parser.add_argument('--no-analysis', action='store_true', help='Skip incident analysis')
    parser.add_argument('--force', action='store_true', help='Process even already processed days')
    
    args = parser.parse_args()
    
    result = run_backfill(
        days=args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        output_dir=args.output,
        dry_run=args.dry_run,
        workers=args.workers,
        skip_analysis=args.no_analysis,
        skip_processed=not args.force,
    )
    
    return 0 if (
        result['error_count'] == 0
        and result.get('delivery_status') != 'failed'
    ) else 1


if __name__ == '__main__':
    sys.exit(main())
