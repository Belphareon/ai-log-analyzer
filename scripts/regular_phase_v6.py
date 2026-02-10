#!/usr/bin/env python3
"""
REGULAR PHASE V6 - 15-minute Pipeline s Registry integrací
==========================================================

OPRAVY v6:
1. Registry se načítá a aktualizuje
2. Event timestamps se používají správně
3. Peaks se ukládají
4. Správné ukončení scriptu

Použití:
    python regular_phase_v6.py                    # Poslední 15 min
    python regular_phase_v6.py --window 30        # Posledních 30 min
    python regular_phase_v6.py --dry-run          # Bez ukládání
"""

import os
import sys
import argparse
import json
import atexit
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Tuple, Optional, Any

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from core.fetch_unlimited import fetch_unlimited
from core.problem_registry import ProblemRegistry
from pipeline import PipelineV6
from pipeline.incident import IncidentCollection

# Table exports
try:
    from exports import TableExporter
    HAS_EXPORTS = True
except ImportError:
    HAS_EXPORTS = False

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

# Problem-Centric Analysis V6.1
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
try:
    from core.teams_notifier import TeamsNotifier
    HAS_TEAMS = True
except ImportError:
    HAS_TEAMS = False


# =============================================================================
# GLOBALS
# =============================================================================

_registry: Optional[ProblemRegistry] = None


# =============================================================================
# DB CONNECTION
# =============================================================================

def get_db_connection():
    """Get database connection - uses DDL user for write operations"""
    # For INSERT/UPDATE/DELETE, must use DDL_USER (not APP_USER)
    # APP_USER (DB_USER) can only read data
    # NOTE: DDL user has direct INSERT/UPDATE/DELETE permissions - SET ROLE not needed!
    user = os.getenv('DB_DDL_USER') or os.getenv('DB_USER')
    password = os.getenv('DB_DDL_PASSWORD') or os.getenv('DB_PASSWORD')
    
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=user,
        password=password,
        connect_timeout=30,
        options='-c statement_timeout=60000'  # 1 min
    )


def set_db_role(cursor) -> None:
    """DEPRECATED - not needed!
    
    DDL user has direct INSERT/UPDATE/DELETE permissions.
    SET ROLE is not needed and fails with APP user.
    This function is kept for compatibility but does nothing.
    """
    pass


def save_incidents_to_db(collection: IncidentCollection) -> int:
    """Save incidents to database"""
    if not HAS_DB:
        print(" ⚠️ No DB driver available")
        return 0
    
    if not collection or not collection.incidents:
        return 0
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        set_db_role(cursor)
        
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
                'v6_regular',
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
        print(f" ⚠️ DB error: {e}")
        if conn:
            conn.close()
        return 0


# =============================================================================
# REGISTRY
# =============================================================================

def init_registry() -> Optional[ProblemRegistry]:
    """Initialize registry"""
    global _registry
    
    registry_dir = SCRIPT_DIR.parent / 'registry'
    _registry = ProblemRegistry(str(registry_dir))
    _registry.load()
    
    return _registry


def save_registry():
    """Save registry"""
    global _registry
    
    if _registry is not None:
        _registry.save()


# =============================================================================
# INCIDENT ANALYSIS
# =============================================================================

def run_incident_analysis(
    collection: IncidentCollection,
    window_start: datetime,
    window_end: datetime,
    output_dir: str = None,
) -> str:
    """Run incident analysis and generate report"""
    if not HAS_INCIDENT_ANALYSIS:
        return "⚠️ Incident Analysis module not available"
    
    formatter = IncidentReportFormatter()
    
    if not collection.incidents:
        result = IncidentAnalysisResult(
            incidents=[],
            total_incidents=0,
            analysis_start=window_start,
            analysis_end=window_end,
        )
        return formatter.format_15min(result)
    
    try:
        engine = IncidentAnalysisEngine()
        result = engine.analyze(
            collection.incidents,
            analysis_start=window_start,
            analysis_end=window_end,
        )
        
        # Knowledge matching
        kb_path = SCRIPT_DIR.parent / 'config' / 'known_issues'
        if kb_path.exists():
            kb = KnowledgeBase(str(kb_path))
            kb.load()
            
            matcher = KnowledgeMatcher(kb)
            result = matcher.enrich_incidents(result)
        
        report = formatter.format_15min(result)
        
        # Save report
        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filepath = output_path / f"incident_analysis_15min_{timestamp}.txt"
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(report)
            
            print(f"   📄 Report saved: {filepath}")
        
        return report
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"⚠️ Incident Analysis error: {e}"


# =============================================================================
# MAIN
# =============================================================================

def run_regular_phase(
    window_minutes: int = 15,
    dry_run: bool = False,
    output_dir: str = None,
) -> dict:
    """
    Main regular phase function.
    
    Processes last N minutes of data and updates registry.
    """
    now = datetime.now(timezone.utc)
    
    # Calculate window (align to quarter hours)
    quarter = (now.minute // 15) * 15
    window_end = now.replace(minute=quarter, second=0, microsecond=0)
    window_start = window_end - timedelta(minutes=window_minutes)
    
    print("=" * 70)
    print("🚀 REGULAR PHASE V6 - 15-minute Pipeline")
    print(f"   Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    print(f"\n📅 Window: {window_start.strftime('%Y-%m-%dT%H:%M:%SZ')} → {window_end.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    
    result = {
        'status': 'error',
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'error_count': 0,
        'incidents': 0,
        'saved': 0,
    }
    
    # ==========================================================================
    # LOAD REGISTRY
    # ==========================================================================
    registry = init_registry()
    print(f"📋 Registry: {len(registry.fingerprint_index)} known fingerprints")
    
    # ==========================================================================
    # FETCH DATA
    # ==========================================================================
    errors = fetch_unlimited(
        window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        window_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    
    if errors is None:
        print("❌ Fetch failed")
        result['status'] = 'error'
        result['error'] = 'Fetch returned None'
        return result
    
    if len(errors) == 0:
        print("⚪ No errors in window")
        result['status'] = 'no_data'
        return result
    
    result['error_count'] = len(errors)
    print(f"   📥 Fetched {len(errors):,} errors")
    
    # ==========================================================================
    # RUN PIPELINE
    # ==========================================================================
    pipeline = PipelineV6(
        spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
        ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
    )
    
    # Inject known fingerprints from registry
    pipeline.phase_c.known_fingerprints = registry.get_all_known_fingerprints().copy()
    
    run_id = f"regular-{now.strftime('%Y%m%d')}-{window_start.strftime('%H%M')}"
    collection = pipeline.run(errors, run_id=run_id)
    
    result['incidents'] = collection.total_incidents
    
    # ==========================================================================
    # EXTRACT EVENT TIMESTAMPS
    # ==========================================================================
    event_timestamps: Dict[str, Tuple[datetime, datetime]] = {}
    for incident in collection.incidents:
        fp = incident.fingerprint
        first_ts = incident.time.first_seen
        last_ts = incident.time.last_seen
        
        if first_ts and last_ts:
            event_timestamps[fp] = (first_ts, last_ts)
    
    # ==========================================================================
    # RESULTS
    # ==========================================================================
    print(f"\n📊 Results:")
    print(f"   Incidents: {collection.total_incidents}")
    print(f"   By severity: {collection.by_severity}")
    
    # ==========================================================================
    # SAVE TO DB
    # ==========================================================================
    if not dry_run and collection.incidents:
        saved = save_incidents_to_db(collection)
        result['saved'] = saved
        print(f"\n💾 Saved {saved} incidents to DB")
    
    # ==========================================================================
    # UPDATE REGISTRY
    # ==========================================================================
    if collection.incidents:
        registry.update_from_incidents(collection.incidents, event_timestamps)
        save_registry()
        
        stats = registry.get_stats()
        print(f"\n📝 Registry updated:")
        print(f"   New problems: {stats['new_problems_added']}")
        print(f"   New peaks: {stats['new_peaks_added']}")
    
    # ==========================================================================
    # PROBLEM-CENTRIC ANALYSIS (V6.1)
    # ==========================================================================
    if collection.incidents and HAS_PROBLEM_ANALYSIS:
        print("\n🔍 Running Problem Analysis V6.1...")

        # 1. Agreguj incidenty do problémů
        problems = aggregate_by_problem_key(collection.incidents)
        print(f"   Aggregated {len(collection.incidents)} incidents into {len(problems)} problems")

        # 2. Získej reprezentativní traces
        trace_flows = get_representative_traces(problems)

        # 3. Generuj problem-centric report
        report_dir = output_dir or str(SCRIPT_DIR / 'reports')

        generator = ProblemReportGenerator(
            problems=problems,
            trace_flows=trace_flows,
            analysis_start=window_start,
            analysis_end=window_end,
            run_id=run_id,
        )

        # Textový report (zkrácený pro 15-min okno)
        problem_report = generator.generate_text_report(max_problems=10)

        # Print jen summary pro 15-min
        lines = problem_report.split('\n')
        for line in lines[:40]:  # První část reportu
            print(line)

        # Ulož reporty
        if output_dir:
            report_files = generator.save_reports(output_dir, prefix="problem_report_15min")
            print(f"\n📄 Problem reports saved:")
            print(f"   Text: {report_files.get('text')}")
            print(f"   JSON: {report_files.get('json')}")

    elif collection.incidents and HAS_INCIDENT_ANALYSIS:
        # Fallback: Legacy incident analysis
        print("\n🔍 Running Incident Analysis (legacy)...")

        report_dir = output_dir or (SCRIPT_DIR / 'reports')
        report = run_incident_analysis(collection, window_start, window_end, str(report_dir))

        # Print summary only (not full report for 15min runs)
        lines = report.split('\n')[:30]
        for line in lines:
            print(line)

    result['status'] = 'success'

    # ==========================================================================
    # EXPORT TABLES (CSV, MD, JSON)
    # ==========================================================================
    if HAS_EXPORTS and _registry is not None:
        exports_dir = output_dir or (SCRIPT_DIR / 'exports')
        print(f"\n📊 Exporting tables to {exports_dir}...")

        try:
            exporter = TableExporter(_registry)
            exporter.export_all(str(exports_dir))
            print(f"   ✅ errors_table_latest.csv/md/json")
            print(f"   ✅ peaks_table_latest.csv/md/json")
        except Exception as e:
            print(f"   ⚠️ Export error: {e}")

    print("\n" + "=" * 70)
    print("✅ REGULAR PHASE V6 COMPLETE")
    print("=" * 70)
    
    # ==========================================================================
    # SEND TEAMS NOTIFICATION (ONLY IF CRITICAL ISSUES DETECTED)
    # ==========================================================================
    if HAS_TEAMS and collection.incidents:
        try:
            # Check if any incident has spike/burst/critical flags
            has_critical = any(
                inc.flags.is_spike or inc.flags.is_burst or inc.score >= 80
                for inc in collection.incidents
            )
            
            if has_critical:
                notifier = TeamsNotifier()
                if notifier.is_enabled():
                    critical_count = sum(
                        1 for inc in collection.incidents 
                        if inc.flags.is_spike or inc.flags.is_burst or inc.score >= 80
                    )
                    notifier.send_message({
                        "@type": "MessageCard",
                        "@context": "https://schema.org/extensions",
                        "summary": f"⚠️ Alert - {critical_count} critical issues detected",
                        "themeColor": "ff3333",
                        "sections": [
                            {
                                "activityTitle": "⚠️ CRITICAL ISSUES DETECTED",
                                "activitySubtitle": f"Window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')}",
                                "facts": [
                                    {"name": "Critical Issues", "value": str(critical_count)},
                                    {"name": "Total Incidents", "value": str(collection.total_incidents)},
                                    {"name": "Spikes", "value": str(sum(1 for inc in collection.incidents if inc.flags.is_spike))},
                                    {"name": "Bursts", "value": str(sum(1 for inc in collection.incidents if inc.flags.is_burst))},
                                ]
                            }
                        ]
                    })
                    print("✅ Critical alert sent to Teams")
        except Exception as e:
            print(f"⚠️ Teams notification failed: {e}")
    
    return result


# =============================================================================
# CLEANUP
# =============================================================================

def cleanup():
    """Ensure registry is saved on exit"""
    global _registry
    
    if _registry is not None:
        try:
            save_registry()
            print("\n✅ Cleanup: registry saved")
        except Exception as e:
            print(f"\n⚠️ Cleanup error: {e}")


atexit.register(cleanup)


def signal_handler(signum, frame):
    """Handle termination signals"""
    print(f"\n⚠️ Received signal {signum}, cleaning up...")
    cleanup()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description='Regular Phase V6 - 15-minute Pipeline')
    parser.add_argument('--window', type=int, default=15, help='Window size in minutes (default: 15)')
    parser.add_argument('--dry-run', action='store_true', help='No DB writes')
    parser.add_argument('--output', type=str, help='Output directory for reports')
    
    args = parser.parse_args()
    
    result = run_regular_phase(
        window_minutes=args.window,
        dry_run=args.dry_run,
        output_dir=args.output,
    )
    
    return 0 if result['status'] in ('success', 'no_data') else 1


if __name__ == '__main__':
    sys.exit(main())
