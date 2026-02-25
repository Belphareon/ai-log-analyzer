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
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from core.fetch_unlimited import fetch_unlimited
from core.problem_registry import ProblemRegistry
from core.baseline_loader import BaselineLoader
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


def _floor_to_window(ts: datetime, window_minutes: int) -> datetime:
    if not ts:
        return ts
    minute = (ts.minute // window_minutes) * window_minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


def _normalize_message_for_dedup(message: str) -> str:
    if not message:
        return ""
    normalized = message
    normalized = re.sub(r'[0-9a-fA-F]{8,}', '<ID>', normalized)
    normalized = re.sub(r'\d+', '<ID>', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized.lower()


def _select_trace_steps(flow, max_steps: int = 7, min_steps: int = 5) -> List[Any]:
    if not flow or not getattr(flow, 'steps', None):
        return []

    unique_steps = []
    seen = set()
    for step in flow.steps:
        app = getattr(step, 'app', '?')
        msg = getattr(step, 'message', '')
        key = (app, _normalize_message_for_dedup(msg))
        if key in seen:
            continue
        seen.add(key)
        unique_steps.append(step)

    if len(unique_steps) <= max_steps:
        return unique_steps

    head_count = max_steps - 1
    selected = unique_steps[:head_count]
    last = unique_steps[-1]
    if last not in selected:
        selected.append(last)
    return selected


def _severity_icon_for_peak(score: float, ratio: Optional[float]) -> str:
    if ratio is not None:
        if ratio >= 100:
            return '🔴'
        if ratio >= 10:
            return '🟠'
        if ratio >= 3:
            return '🟡'
        return '⚪'

    if score >= 80:
        return '🔴'
    if score >= 60:
        return '🟠'
    if score >= 40:
        return '🟡'
    return '⚪'


def _select_peak_problem(problems: Dict[str, Any]) -> Optional[Any]:
    if not problems:
        return None

    peak_problems = [p for p in problems.values() if p.has_spike or p.has_burst]
    if not peak_problems:
        return None

    peak_problems.sort(key=lambda p: (p.max_score, p.total_occurrences), reverse=True)
    return peak_problems[0]


def _build_peak_notification(
    problem: Any,
    trace_flows: Dict[str, List[Any]],
    known_peaks: Dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    window_minutes: int
) -> Optional[str]:
    if not problem:
        return None

    peak_type = 'SPIKE' if problem.has_spike else 'BURST'
    peak_key = f"PEAK:{problem.category}:{problem.flow}:{peak_type.lower()}"

    known_peak = known_peaks.get(peak_key)
    is_known = known_peak is not None
    is_continues = False
    if known_peak and known_peak.last_seen:
        is_continues = known_peak.last_seen >= (window_start - timedelta(minutes=window_minutes))

    known_label = "NEW"
    if is_known:
        known_label = f"KNOWN ({known_peak.id})"

    peak_window_start = _floor_to_window(known_peak.first_seen, window_minutes) if (is_continues and known_peak and known_peak.first_seen) else window_start
    peak_window_start_text = peak_window_start.strftime('%Y-%m-%d %H:%M') if peak_window_start else window_start.strftime('%Y-%m-%d %H:%M')
    peak_window_end_text = window_end.strftime('%Y-%m-%d %H:%M') if window_end else ""

    ratio = None
    ratio_incident = None
    for inc in problem.incidents:
        if not (inc.flags.is_spike or inc.flags.is_burst):
            continue
        if inc.stats.baseline_rate > 0:
            r = inc.stats.current_rate / inc.stats.baseline_rate
            if ratio is None or r > ratio:
                ratio = r
                ratio_incident = inc

    icon = _severity_icon_for_peak(problem.max_score, ratio)

    header_title = "Peak CONTINUES" if is_continues else "Peak"
    lines = [
        "─" * 50,
        f"{icon} {header_title}: {problem.category} / {problem.error_class} — {known_label}",
        "─" * 50,
    ]

    lines.append(f"Severity: {problem.max_severity.upper()} (score: {problem.max_score:.0f})")
    lines.append(f"Occurrences: {problem.total_occurrences:,} across {problem.incident_count} incidents")

    if is_continues:
        lines.append(f"Window: {peak_window_start_text}")
    else:
        lines.append(f"Window: {peak_window_start_text} - {peak_window_end_text}")

    if problem.first_seen and problem.last_seen:
        duration_sec = int((problem.last_seen - problem.first_seen).total_seconds())
        lines.append(
            f"Event time: {problem.first_seen.strftime('%Y-%m-%d %H:%M')} - "
            f"{problem.last_seen.strftime('%H:%M')} ({duration_sec}s)"
        )

    ns_count = len(problem.namespaces)
    if ns_count <= 1:
        lines.append(f"Scope: {len(problem.apps)} apps")
    else:
        lines.append(f"Scope: {len(problem.apps)} apps, {ns_count} namespaces")
    if problem.apps:
        lines.append(f"  Apps: {', '.join(sorted(problem.apps)[:5])}")
    if problem.namespaces:
        if ns_count <= 1:
            lines.append(f"  Namespace: {', '.join(sorted(problem.namespaces)[:1])}")
        else:
            lines.append(f"  Namespaces: {', '.join(sorted(problem.namespaces)[:5])}")

    flow_list = trace_flows.get(problem.problem_key, []) if trace_flows else []
    flow = flow_list[0] if flow_list else None

    if flow and getattr(flow, 'steps', None):
        lines.append("")
        lines.append(f"Behavior (trace flow): {len(flow.steps)} messages")
        lines.append(f"TraceID: {flow.trace_id}")
        lines.append("")

        steps = _select_trace_steps(flow, max_steps=7, min_steps=5)
        for step in steps:
            app = getattr(step, 'app', '?')
            msg = getattr(step, 'message', '')
            lines.append(f"{app}")
            lines.append(f"\"{msg}\"")

    if not is_continues and getattr(problem, 'trace_root_cause', None):
        rc = problem.trace_root_cause
        confidence = rc.get('confidence', 'unknown')
        lines.append("")
        lines.append(f"Inferred root cause [{confidence}]:")
        lines.append(f"  - {rc.get('service', '?')}: {rc.get('message', '')}")

    if not is_continues:
        propagation = getattr(problem, 'propagation_result', None)
        if propagation and propagation.service_count > 1:
            lines.append("")
            lines.append(f"Propagation [{propagation.propagation_type}]:")
            lines.append(f"  {propagation.to_short_string()}")
            if propagation.propagation_time_ms > 0:
                total_sec = int(propagation.propagation_time_ms / 1000)
                minutes = total_sec // 60
                seconds = total_sec % 60
                lines.append(f"  Duration: {minutes}m {seconds}s")

    return "\n".join(lines)


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
        options='-c statement_timeout=60000'  # 1 min
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
        print(f"⚠️ Warning: Could not set role {ddl_role}: {e}")
        # Continue anyway - user may have direct permissions


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
                int(incident.stats.baseline_rate) if incident.stats.baseline_rate > 0 else 0,
                incident.stats.baseline_median if incident.stats.baseline_median > 0 else None,
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
             original_value, reference_value, baseline_mean,
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
    
    # IMPORTANT: Registry MUST be on persistence volume!
    registry_base = os.getenv('REGISTRY_DIR') or str(SCRIPT_DIR.parent / 'registry')
    registry_dir = Path(registry_base)
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
    
    known_peaks_snapshot = dict(registry.peaks) if registry else {}

    # ==========================================================================
    # LOAD HISTORICAL BASELINE FROM DB
    # ==========================================================================
    historical_baseline = {}
    try:
        db_conn = get_db_connection()
        baseline_loader = BaselineLoader(db_conn)
        
        # Zjisti jaké error_types jsou v aktuálním okně
        if errors:
            # Zjisti error_type z normalizace - VŠECHNY, ne jen prvních 1000!
            from pipeline.phase_a_parse import PhaseA_Parser
            parser = PhaseA_Parser()
            all_error_types = set()
            for error in errors:
                msg = error.get('message', '')
                error_type = parser.extract_error_type(msg)
                if error_type and error_type != 'Unknown':
                    all_error_types.add(error_type)
            
            # Načti baseline pro ALL error_types
            if all_error_types:
                historical_baseline = baseline_loader.load_historical_rates(
                    error_types=list(all_error_types),
                    lookback_days=7,
                    min_samples=3
                )
                print(f"   📊 Loaded baseline for {len(historical_baseline)}/{len(all_error_types)} error types")
        
        db_conn.close()
    except Exception as e:
        print(f"   ⚠️ Baseline loading failed (non-blocking): {e}")
        historical_baseline = {}

    # ==========================================================================
    # RUN PIPELINE
    # ==========================================================================
    pipeline = PipelineV6(
        spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
        ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
    )
    
    # ← NOVÉ: Injektuj historické baseline do Phase B
    # POZOR: BaselineLoader vrací data keyed by error_type, ne fingerprint!
    # Použij error_type_baseline pro správný lookup v Phase B.
    pipeline.phase_b.error_type_baseline = historical_baseline
    
    # ← KRITICKÉ: Inject registry do Phase C (aby mohl dělat is_problem_key_known lookup!)
    pipeline.phase_c.registry = registry
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
    
    problem_report_text = None
    enriched_problems = None
    peak_trace_flows = None

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
        peak_trace_flows = trace_flows

        # 3. Generuj problem-centric report
        report_dir = output_dir or str(SCRIPT_DIR / 'reports')

        generator = ProblemReportGenerator(
            problems=problems,
            trace_flows=trace_flows,
            analysis_start=window_start,
            analysis_end=window_end,
            run_id=run_id,
        )
        enriched_problems = generator.problems

        # Textový report (zkrácený pro 15-min okno)
        problem_report = generator.generate_text_report(max_problems=10)
        problem_report_text = problem_report

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
    # SEND PEAKS NOTIFICATION (EMAIL ONLY)
    # ==========================================================================
    if HAS_TEAMS and collection.incidents:
        try:
            # OPRAVA: Rozšířit definici "peaks" aby včetně high-score problémů
            # Původní: pouze spike OR burst
            # Nově: spike OR burst OR high-score anomalies
            peaks_detected = sum(
                1 for inc in collection.incidents
                if (inc.flags.is_spike or inc.flags.is_burst or 
                    getattr(inc, 'score', 0) >= 70)  # Add high-score filter
            )
            spikes_count = sum(1 for inc in collection.incidents if inc.flags.is_spike)
            bursts_count = sum(1 for inc in collection.incidents if inc.flags.is_burst)
            high_score_count = sum(
                1 for inc in collection.incidents 
                if getattr(inc, 'score', 0) >= 70 and not (inc.flags.is_spike or inc.flags.is_burst)
            )

            if peaks_detected > 0 and enriched_problems:
                peak_problem = _select_peak_problem(enriched_problems)
                peak_message = _build_peak_notification(
                    peak_problem,
                    peak_trace_flows or {},
                    known_peaks_snapshot,
                    window_start,
                    window_end,
                    window_minutes
                )
                notifier = TeamsNotifier()
                if notifier.is_enabled():
                    registry_stats = _registry.get_stats() if _registry else {}
                    notifier.send_regular_phase_completed(
                        new_incidents=result.get('incidents', 0),
                        total_processed=collection.total_incidents,
                        peaks_detected=peaks_detected,
                        errors=result.get('error_count', 0),
                        registry_updated=bool(collection.incidents),
                        duration_seconds=(datetime.now(timezone.utc) - now).total_seconds(),
                        problem_report=None,
                        peaks_info={
                            'total': peaks_detected,
                            'new': registry_stats.get('new_peaks_added', 0),
                            'spikes': spikes_count,
                            'bursts': bursts_count,
                            'high_score': high_score_count  # Add to info
                        },
                        summary_override=peak_message
                    )
                    print("✅ Peaks notification sent")
        except Exception as e:
            print(f"⚠️ Teams notification failed: {e}")
            # Fallback to email for critical alerts
            try:
                from core.email_notifier import EmailNotifier
                email_notifier = EmailNotifier()
                if email_notifier.is_enabled():
                    critical_count = sum(
                        1 for inc in collection.incidents 
                        if inc.flags.is_spike or inc.flags.is_burst or inc.score >= 80
                    )
                    email_body = f"""AI Log Analyzer - CRITICAL ALERT

Window: {window_start.strftime('%H:%M')} - {window_end.strftime('%H:%M')}

⚠️ CRITICAL ISSUES DETECTED

  • Critical Issues: {critical_count}
  • Total Incidents: {collection.total_incidents}
  • Spikes: {sum(1 for inc in collection.incidents if inc.flags.is_spike)}
  • Bursts: {sum(1 for inc in collection.incidents if inc.flags.is_burst)}

Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

See wiki for details: https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis
"""
                    email_notifier._send_email(
                        f"[AI Log Analyzer] ⚠️ CRITICAL ALERT - {critical_count} issues detected",
                        email_body
                    )
                    print("📧 Critical alert sent via email")
            except Exception as email_err:
                print(f"⚠️ Email fallback also failed: {email_err}")
    
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
