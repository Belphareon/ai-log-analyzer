#!/usr/bin/env python3
"""
REGULAR PHASE - 15-minute Pipeline s Registry integrací
=======================================================

1. Registry se načítá a aktualizuje
2. Event timestamps se používají správně
3. Peaks se ukládají
4. Správné ukončení scriptu

Použití:
    python regular_phase.py                    # Poslední 15 min
    python regular_phase.py --window 30        # Posledních 30 min
    python regular_phase.py --dry-run          # Bez ukládání
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
from core.problem_registry import extract_flow
from core.baseline_loader import BaselineLoader
from pipeline import Pipeline
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


def _format_utc_local(ts: datetime) -> str:
    """Format timestamp explicitly as UTC and local time to avoid TZ confusion."""
    aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    utc_text = aware.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    local_dt = aware.astimezone()
    offset = local_dt.strftime('%z')
    offset_text = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    local_text = local_dt.strftime('%Y-%m-%d %H:%M:%S')
    return f"{utc_text} | local {local_text} (UTC{offset_text})"


def _registry_snapshot(registry: ProblemRegistry) -> Dict[str, int]:
    """Small registry snapshot for validator delta logs."""
    total_occurrences = sum(int(getattr(p, 'occurrences', 0) or 0) for p in registry.problems.values())
    return {
        'problems': len(registry.problems),
        'peaks': len(registry.peaks),
        'occurrences': total_occurrences,
    }


def _one_line_error(err: Exception) -> str:
    """Normalize multiline exceptions to one line for readable logs."""
    return " | ".join(str(err).splitlines())


def _normalize_message_for_dedup(message: str) -> str:
    if not message:
        return ""
    normalized = message
    normalized = re.sub(r'[0-9a-fA-F]{8,}', '<ID>', normalized)
    normalized = re.sub(r'\d+', '<ID>', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized.lower()


def _trace_message_signal_score(message: str) -> int:
    if not message:
        return 0
    text = message.lower()

    negative_hits = [
        'step processing failed, context stepcontext',
        'asynchronous case processing not started',
        'an unexpected error occurred',
        'processing of step',
        'handle fault',
    ]
    positive_hits = [
        'called service',
        'processing errors',
        'loadbridgexmlrequest',
        'not permitted',
        'resource not found',
        'token scopes',
        'operation not allowed',
        'timeout',
        'connection',
        'sql',
    ]

    score = 1 if len(text) >= 40 else 0
    score += sum(3 for needle in positive_hits if needle in text)
    score -= sum(3 for needle in negative_hits if needle in text)
    return score


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

    signal_steps = [s for s in unique_steps if _trace_message_signal_score(getattr(s, 'message', '')) > 0]
    if len(signal_steps) >= min_steps:
        selected = signal_steps[:max_steps - 1]
        last = unique_steps[-1]
        if last not in selected:
            selected.append(last)
        return selected

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


def _select_peak_problems(problems: Dict[str, Any], limit: int = 3) -> List[Any]:
    if not problems:
        return []

    peak_problems = [p for p in problems.values() if p.has_spike or p.has_burst]
    if not peak_problems:
        return []

    peak_problems.sort(key=lambda p: (p.max_score, p.total_occurrences), reverse=True)
    if limit <= 0:
        return peak_problems
    return peak_problems[:limit]


def _alert_state_path(registry: ProblemRegistry) -> Path:
    return Path(registry.registry_dir) / 'alert_state_regular_phase.json'


def _load_alert_state(registry: ProblemRegistry) -> Dict[str, Any]:
    path = _alert_state_path(registry)
    if not path.exists():
        return {'peaks': {}}

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get('peaks'), dict):
            return data
    except Exception as e:
        print(f"⚠️ Alert state load failed: {_one_line_error(e)}")
    return {'peaks': {}}


def _save_alert_state(registry: ProblemRegistry, state: Dict[str, Any]) -> None:
    path = _alert_state_path(registry)
    tmp_path = path.with_suffix('.json.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _should_send_peak_alert(
    payload: Dict[str, Any],
    state_entry: Dict[str, Any],
    now_utc: datetime,
) -> Tuple[bool, str]:
    cooldown_min = int(os.getenv('ALERT_COOLDOWN_MIN', '45'))
    heartbeat_min = int(os.getenv('ALERT_HEARTBEAT_MIN', '120'))
    min_delta_pct = float(os.getenv('ALERT_MIN_DELTA_PCT', '30'))

    if not state_entry:
        return True, 'first_seen_in_state'

    if not payload.get('is_known', False):
        return True, 'new_peak'

    last_window = str(state_entry.get('last_sent_window') or '')
    current_window = str(payload.get('window_key') or '')
    if last_window and current_window and last_window == current_window:
        return False, 'same_window_duplicate'

    last_trend = str(state_entry.get('last_trend') or '')
    trend = str(payload.get('trend') or '')
    if trend and last_trend and trend != last_trend:
        return True, 'trend_changed'

    current_count = int(payload.get('error_count', 0) or 0)
    last_count = int(state_entry.get('last_error_count', 0) or 0)
    if current_count > 0 and last_count > 0:
        delta_pct = abs(current_count - last_count) / max(last_count, 1) * 100.0
        if delta_pct >= min_delta_pct:
            return True, f'count_delta_{delta_pct:.1f}_pct'

    if payload.get('new_apps') or payload.get('new_namespaces'):
        return True, 'scope_changed'

    cooldown_until = _parse_dt(state_entry.get('cooldown_until'))
    if cooldown_until and now_utc < cooldown_until:
        return False, 'cooldown_active'

    last_sent_at = _parse_dt(state_entry.get('last_sent_at'))
    if last_sent_at and (now_utc - last_sent_at) >= timedelta(minutes=heartbeat_min):
        return True, 'heartbeat'

    if cooldown_min <= 0:
        return False, 'no_trigger'

    return False, 'no_material_change'


def _build_peak_alert_payload(
    problem: Any,
    trace_flows: Dict[str, List[Any]],
    known_peaks: Dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    window_minutes: int,
) -> Optional[Dict[str, Any]]:
    if not problem:
        return None

    # Calculate peak metadata aligned to actual trigger incident
    peak_incidents = [
        inc for inc in (getattr(problem, 'incidents', []) or [])
        if (getattr(getattr(inc, 'flags', None), 'is_spike', False) or
            getattr(getattr(inc, 'flags', None), 'is_burst', False))
    ]
    signal_incidents = peak_incidents or (getattr(problem, 'incidents', []) or [])

    def _incident_ratio(inc: Any) -> float:
        try:
            baseline = float(getattr(getattr(inc, 'stats', None), 'baseline_rate', 0.0) or 0.0)
            current = float(getattr(getattr(inc, 'stats', None), 'current_rate', 0.0) or 0.0)
            if baseline > 0:
                return current / baseline
        except Exception:
            pass
        return 0.0

    trigger_incident = None
    if peak_incidents:
        trigger_incident = max(
            peak_incidents,
            key=lambda inc: (
                _incident_ratio(inc),
                int(getattr(getattr(inc, 'stats', None), 'current_count', 0) or 0),
                float(getattr(inc, 'score', 0.0) or 0.0),
            )
        )

    if trigger_incident and getattr(trigger_incident.flags, 'is_spike', False):
        peak_type = 'SPIKE'
    elif trigger_incident and getattr(trigger_incident.flags, 'is_burst', False):
        peak_type = 'BURST'
    else:
        peak_type = 'SPIKE' if problem.has_spike else 'BURST'

    if trigger_incident is not None:
        incident_category = (
            trigger_incident.category.value
            if hasattr(trigger_incident.category, 'value')
            else str(trigger_incident.category)
        )
        incident_flow = extract_flow(
            [a for a in (getattr(trigger_incident, 'apps', []) or []) if a],
            [n for n in (getattr(trigger_incident, 'namespaces', []) or []) if n],
        )
        peak_key = f"PEAK:{incident_category}:{incident_flow}:{peak_type.lower()}"
    else:
        peak_key = f"PEAK:{problem.category}:{problem.flow}:{peak_type.lower()}"

    peak_identifier = peak_key
    if trigger_incident:
        for ev in getattr(trigger_incident, 'evidence', []) or []:
            if getattr(ev, 'rule', '') != 'spike_p93_cap':
                continue
            msg = getattr(ev, 'message', '') or ''
            match = re.search(r"peak_id=([^\)\s]+)", msg)
            if match:
                peak_identifier = match.group(1)
                break

    known_peak = known_peaks.get(peak_key)
    is_known = known_peak is not None
    is_continues = False
    continuation_lookback_min = int(os.getenv('ALERT_CONTINUATION_LOOKBACK_MIN', '60'))
    if known_peak and known_peak.last_seen:
        is_continues = known_peak.last_seen >= (window_start - timedelta(minutes=max(continuation_lookback_min, window_minutes)))

    peak_window_start = window_start
    peak_id = known_peak.id if is_known else ""

    ratio = None
    for inc in signal_incidents:
        if not (inc.flags.is_spike or inc.flags.is_burst):
            continue
        if inc.stats.baseline_rate > 0:
            r = inc.stats.current_rate / inc.stats.baseline_rate
            if ratio is None or r > ratio:
                ratio = r

    icon = _severity_icon_for_peak(problem.max_score, ratio)

    flow_list = trace_flows.get(problem.problem_key, []) if trace_flows else []
    flow = flow_list[0] if flow_list else None
    trace_steps = []
    namespace_counts: Dict[str, int] = {}
    error_type_counts: Dict[str, int] = {}
    affected_apps = set()
    affected_namespaces = set()
    raw_error_count = 0

    for inc in signal_incidents:
        ns_list = [ns for ns in (getattr(inc, 'namespaces', []) or []) if ns]
        count = 1
        if hasattr(inc, 'stats') and hasattr(inc.stats, 'current_count'):
            try:
                count = max(1, int(inc.stats.current_count))
            except (TypeError, ValueError):
                count = 1
        raw_error_count += count

        for app in (getattr(inc, 'apps', []) or []):
            if app:
                affected_apps.add(app)

        err_type = getattr(inc, 'error_type', None) or 'UnknownError'
        error_type_counts[err_type] = error_type_counts.get(err_type, 0) + count

        for ns in ns_list:
            affected_namespaces.add(ns)
            namespace_counts[ns] = namespace_counts.get(ns, 0) + count

    top_error_types = sorted(error_type_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_error_types_text = ', '.join(f"{name} ({cnt})" for name, cnt in top_error_types) if top_error_types else 'N/A'
    error_class_raw = problem.error_class or 'unknownerror'
    error_class_l = str(error_class_raw).lower()
    if error_class_l in {'unknownerror', 'unknown_error', 'unknown'}:
        error_class = 'unknown (fallback classifier)'
        peak_error_details = f"classified as unknown; top error types: {top_error_types_text}"
    else:
        error_class = error_class_raw
        peak_error_details = f"top error types: {top_error_types_text}"

    trace_id = ''
    if flow and getattr(flow, 'trace_id', None):
        trace_id = str(getattr(flow, 'trace_id', '') or '')

    if flow and getattr(flow, 'steps', None):
        steps = _select_trace_steps(flow, max_steps=7, min_steps=5)
        for step in steps:
            trace_steps.append({
                'app': getattr(step, 'app', '?'),
                'message': getattr(step, 'message', '')
            })
    if not trace_id and trigger_incident is not None:
        trace_id = str(getattr(trigger_incident, 'trace_id', '') or '')

    current_window_errors = raw_error_count or problem.total_occurrences
    previous_average_errors = None
    if known_peak and getattr(known_peak, 'occurrences', 0):
        peak_occurrences = max(1, int(getattr(known_peak, 'occurrences', 0) or 0))
        historical_raw = int(getattr(known_peak, 'raw_error_count', 0) or 0)
        if historical_raw > 0:
            previous_average_errors = historical_raw / peak_occurrences

    # Trend logic: digest shows historical trend; real-time trends use previous_window (see table_exporter.py)
    trend = 'stable'
    if previous_average_errors and previous_average_errors > 0:
        ratio_to_avg = current_window_errors / previous_average_errors
        if ratio_to_avg >= 1.2:
            trend = 'rising'
        elif ratio_to_avg <= 0.8:
            trend = 'falling'

    known_apps = set(getattr(known_peak, 'affected_apps', []) or []) if known_peak else set()
    known_namespaces = set(getattr(known_peak, 'affected_namespaces', []) or []) if known_peak else set()
    new_apps = sorted(affected_apps - known_apps)
    new_namespaces = sorted(affected_namespaces - known_namespaces)
    continuation_summary = {
        'trend': trend,
        'current_window_errors': int(current_window_errors),
        'previous_average_errors': int(previous_average_errors) if previous_average_errors else None,
        'new_apps': new_apps,
        'new_namespaces': new_namespaces,
        'top_error_types': top_error_types_text,
    }

    trace_steps_for_email = trace_steps if not is_continues else []

    root_cause = None
    if not is_continues:
        rc = getattr(problem, 'trace_root_cause', None)
        if rc:
            root_cause = {
                'service': rc.get('service', '?'),
                'message': rc.get('message', '')
            }
        elif getattr(problem, 'root_cause', None):
            rc_obj = problem.root_cause
            root_cause = {
                'service': getattr(rc_obj, 'service', '?'),
                'message': getattr(rc_obj, 'message', '')
            }

    propagation_info = None
    if not is_continues:
        propagation = getattr(problem, 'propagation_result', None)
        if propagation and propagation.service_count > 1:
            propagation_info = {
                'type': propagation.propagation_type,
                'service_count': propagation.service_count,
                'duration_ms': propagation.propagation_time_ms
            }

    digest_root_cause = ''
    if root_cause:
        digest_root_cause = str(root_cause.get('message', '') or root_cause.get('service', '') or '')
    if not digest_root_cause and known_peak and getattr(known_peak, 'root_cause', None):
        digest_root_cause = str(getattr(known_peak, 'root_cause', '') or '')
    if not digest_root_cause and getattr(problem, 'root_cause', None):
        digest_root_cause = str(getattr(problem, 'root_cause', '') or '')

    digest_message = ''
    if trace_steps:
        digest_message = str(trace_steps[0].get('message', '') or '')
    if not digest_message:
        digest_message = str(peak_error_details or '')

    return {
        'peak_key': peak_key,
        'peak_identifier': peak_identifier,
        'peak_type': peak_type,
        'is_known': is_known,
        'is_continues': is_continues,
        'peak_id': peak_id,
        'error_class': error_class,
        'peak_error_details': peak_error_details,
        'error_count': int(current_window_errors),
        'window_start': peak_window_start,
        'window_end': window_end,
        'affected_apps': sorted(affected_apps) if affected_apps else (sorted(problem.apps) if problem.apps else []),
        'affected_namespaces': sorted(affected_namespaces) if affected_namespaces else (sorted(problem.namespaces) if problem.namespaces else []),
        'namespace_counts': namespace_counts,
        'trace_steps': trace_steps_for_email,
        'root_cause': root_cause,
        'propagation_info': propagation_info,
        'continuation_summary': continuation_summary,
        'severity_icon': icon,
        'trend': trend,
        'new_apps': new_apps,
        'new_namespaces': new_namespaces,
        'window_key': window_start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'trace_id': trace_id,
        'root_cause_text': digest_root_cause,
        'detail_message': digest_message,
    }


def _send_peak_alert_email(payload: Dict[str, Any]) -> bool:
    if not payload:
        return False

    try:
        from core.email_notifier import EmailNotifier

        email_notifier = EmailNotifier()
        if not email_notifier.is_enabled():
            print("⚠️ Email notifier not enabled")
            return False

        success = email_notifier.send_regular_phase_peak_alert_detailed(
            peak_error_class=payload.get('error_class', 'unknown'),
            peak_error_details=payload.get('peak_error_details', ''),
            peak_type=payload.get('peak_type', 'SPIKE'),
            peak_identifier=payload.get('peak_identifier', ''),
            is_known=bool(payload.get('is_known', False)),
            is_continues=bool(payload.get('is_continues', False)),
            peak_id=payload.get('peak_id', ''),
            error_count=int(payload.get('error_count', 0) or 0),
            window_start=payload.get('window_start'),
            window_end=payload.get('window_end'),
            affected_apps=payload.get('affected_apps', []),
            affected_namespaces=payload.get('affected_namespaces', []),
            namespace_counts=payload.get('namespace_counts', {}),
            trace_steps=payload.get('trace_steps', []),
            root_cause=payload.get('root_cause'),
            propagation_info=payload.get('propagation_info'),
            continuation_summary=payload.get('continuation_summary'),
            severity_icon=payload.get('severity_icon', '⚠️'),
        )

        if success:
            print("✅ Peak alert email sent")
            return True
        print("⚠️ Peak alert email failed")
        return False

    except Exception as e:
        print(f"⚠️ Error sending peak alert email: {e}")
        return False


def _send_peak_alert_digest(
    window_start: datetime,
    window_end: datetime,
    alerts: List[Dict[str, Any]],
    suppressed_count: int,
) -> bool:
    if not alerts:
        return False

    try:
        from core.email_notifier import EmailNotifier

        email_notifier = EmailNotifier()
        if not email_notifier.is_enabled():
            print("⚠️ Email notifier not enabled")
            return False

        return email_notifier.send_regular_phase_peak_digest(
            window_start=window_start,
            window_end=window_end,
            alerts=alerts,
            suppressed_count=suppressed_count,
        )
    except Exception as e:
        print(f"⚠️ Error sending peak digest email: {e}")
        return False


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
    continuation_lookback_min = int(os.getenv('ALERT_CONTINUATION_LOOKBACK_MIN', '60'))
    if known_peak and known_peak.last_seen:
        is_continues = known_peak.last_seen >= (window_start - timedelta(minutes=max(continuation_lookback_min, window_minutes)))

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

    # NEW FORMAT (simplified for regular phase)
    lines = [
        "[Log Analyzer] ⚠️ PEAK ALERTING - (last 15 mins)",
        "─" * 50,
        f"{icon} Peak: {problem.category} / {problem.error_class} — {known_label}",
        "─" * 50,
    ]

    # Known peak status
    known_status = "YES" if is_known else "NO"
    lines.append(f"Known peak - {known_status}")
    
    lines.append(f"Occurrences: {problem.total_occurrences:,} across {problem.incident_count} incidents")

    if problem.first_seen and problem.last_seen:
        duration_sec = int((problem.last_seen - problem.first_seen).total_seconds())
        event_time = f"Event time: {problem.first_seen.strftime('%Y-%m-%d %H:%M')} - {problem.last_seen.strftime('%H:%M')}"
        lines.append(event_time)
        lines.append(f"  Duration: {duration_sec}s")
    
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

    # Footer with wiki link
    lines.append("")
    lines.append("Detaily known peaku ZDE - https://wiki.kb.cz/spaces/CCAT/pages/1334314203/Known+Peaks+-+Daily+Update")

    return "\n".join(lines)


# =============================================================================
# DB CONNECTION
# =============================================================================

def get_db_connection(read_only: bool = False):
    """Get database connection.

    - read_only=True: uses DB_USER/DB_PASSWORD for SELECT workloads.
    - read_only=False: uses DDL user + SET ROLE for write workloads.
    
    CRITICAL: DDL user (ailog_analyzer_ddl_user_d1) must execute SET ROLE role_ailog_analyzer_ddl
    to gain permissions on ailog_peak schema. This is mandatory.
    """
    if read_only:
        user = os.getenv('DB_USER') or os.getenv('DB_DDL_USER')
        password = os.getenv('DB_PASSWORD') or os.getenv('DB_DDL_PASSWORD')
    else:
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
    
    if not read_only:
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
        
        data = []
        for incident in collection.incidents:
            ts = incident.time.first_seen or datetime.now(timezone.utc)
            # reference_value: store actual count (for BaselineLoader to use as historical data)
            # For regular phase: current_count = total_count = per-window count (correct granularity)
            ref_value = incident.stats.current_count if incident.stats.current_count > 0 else None
            # baseline_mean: use EWMA baseline rate (not median which is 0 for sparse windows)
            baseline_mean = round(incident.stats.baseline_rate, 2) if incident.stats.baseline_rate > 0 else None
            data.append((
                ts,
                ts.weekday(),
                ts.hour,
                ts.minute // 15,
                incident.namespaces[0] if incident.namespaces else 'unknown',
                incident.stats.current_count,                         # original_value
                ref_value,                                            # reference_value
                baseline_mean,                                        # baseline_mean
                incident.flags.is_new,
                incident.flags.is_spike,
                incident.flags.is_burst,
                incident.flags.is_cross_namespace,
                incident.error_type or '',
                (incident.normalized_message or '')[:500],
                'regular',
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


def save_namespace_totals_to_raw_data(collection: IncidentCollection) -> int:
    """
    Save namespace-level error totals to peak_raw_data.

    This feeds the P93/CAP threshold calculation (calculate_peak_thresholds.py).
    Each regular phase run adds one row per namespace with the total error count
    for that 15-min window. Over time this builds the dataset from which P93
    percentiles are calculated, making the system self-improving.
    """
    if not HAS_DB:
        return 0
    if not collection or not collection.incidents:
        return 0

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        set_db_role(cursor)

        # Aggregate total error count per namespace
        ns_totals = {}
        ts = None
        for incident in collection.incidents:
            inc_ts = incident.time.first_seen or datetime.now(timezone.utc)
            if ts is None:
                ts = inc_ts
            ns = incident.namespaces[0] if incident.namespaces else 'unknown'
            ns_totals[ns] = ns_totals.get(ns, 0) + incident.stats.current_count

        if not ns_totals or ts is None:
            if conn:
                conn.close()
            return 0

        data = []
        for ns, total_count in ns_totals.items():
            data.append((
                ts,
                ts.weekday(),
                ts.hour,
                ts.minute // 15,
                ns,
                total_count,      # error_count (current, possibly replaced)
                total_count,      # original_value (raw count for P93 calculation)
            ))

        execute_values(cursor, """
            INSERT INTO ailog_peak.peak_raw_data
            (timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
             error_count, original_value)
            VALUES %s
            ON CONFLICT (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
            DO UPDATE SET error_count = EXCLUDED.error_count,
                          original_value = EXCLUDED.original_value
        """, data, page_size=100)

        conn.commit()
        cursor.close()
        conn.close()
        return len(data)

    except Exception as e:
        print(f"   peak_raw_data save failed (non-blocking): {e}")
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
    print("🚀 REGULAR PHASE - 15-minute Pipeline")
    print(f"   Started: {_format_utc_local(now)}")
    print("=" * 70)
    
    print(f"\n📅 Window UTC: {window_start.strftime('%Y-%m-%dT%H:%M:%SZ')} → {window_end.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"   Window local: {window_start.astimezone().strftime('%Y-%m-%d %H:%M:%S')} → {window_end.astimezone().strftime('%Y-%m-%d %H:%M:%S')} ({datetime.now().astimezone().tzname()})")
    
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
    registry_before = _registry_snapshot(registry)
    
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
        db_conn = get_db_connection(read_only=True)
        baseline_loader = BaselineLoader(db_conn)
        
        # Zjisti jaké error_types jsou v aktuálním okně
        if errors:
            # Zjisti error_type z normalizace - VŠECHNY, ne jen prvních 1000!
            from pipeline.phase_a_parse import PhaseA_Parser
            parser = PhaseA_Parser()
            all_error_types = set()
            for error in errors:
                # Use extract_error_type_rich() to match Phase A pipeline behavior
                # (checks exception.type, error.type, stack_trace, then message)
                error_type = parser.extract_error_type_rich(error)
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
        print(f"   ⚠️ Baseline loading failed (non-blocking): {_one_line_error(e)}")
        historical_baseline = {}

    # ==========================================================================
    # RUN PIPELINE
    # ==========================================================================
    # P93/CAP peak detection (replaces EWMA/MAD for spike detection)
    peak_detector = None
    try:
        from core.peak_detection import PeakDetector
        peak_db_conn = get_db_connection(read_only=True)
        peak_detector = PeakDetector(conn=peak_db_conn)
        print("   P93/CAP peak detector loaded")
    except Exception as e:
        print(f"   P93/CAP peak detector unavailable (falling back to EWMA): {_one_line_error(e)}")

    pipeline = Pipeline(
        ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
        peak_detector=peak_detector,
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

        # Save namespace totals to peak_raw_data (feeds P93/CAP threshold calculation)
        raw_saved = save_namespace_totals_to_raw_data(collection)
        if raw_saved > 0:
            print(f"   Saved {raw_saved} namespace totals to peak_raw_data")

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

        registry_after = _registry_snapshot(registry)
        print("\n✅ VALIDATOR - Added data in this regular run:")
        print(f"   Window UTC: {window_start.strftime('%Y-%m-%dT%H:%M:%SZ')} → {window_end.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        print(f"   Fetched errors: +{result['error_count']:,}")
        print(f"   DB rows inserted: +{result.get('saved', 0):,}")
        print(f"   Registry occurrences delta: +{registry_after['occurrences'] - registry_before['occurrences']:,}")
        print(f"   Registry problems delta: +{registry_after['problems'] - registry_before['problems']:,}")
        print(f"   Registry peaks delta: +{registry_after['peaks'] - registry_before['peaks']:,}")
    
    problem_report_text = None
    enriched_problems = None
    peak_trace_flows = None

    # ==========================================================================
    # PROBLEM-CENTRIC ANALYSIS
    # ==========================================================================
    if collection.incidents and HAS_PROBLEM_ANALYSIS:
        print("\n🔍 Running Problem Analysis...")

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
    # WRITE-BACK ENRICHMENT TO REGISTRY
    # ==========================================================================
    if enriched_problems and _registry is not None:
        write_back_count = 0
        for pkey, aggregate in enriched_problems.items():
            if pkey not in _registry.problems:
                continue
            entry = _registry.problems[pkey]

            # Write-back root_cause from trace analysis (highest priority)
            rc = getattr(aggregate, 'root_cause', None)
            trc = getattr(aggregate, 'trace_root_cause', None)
            if trc and isinstance(trc, dict) and trc.get('message'):
                svc = trc.get('service', '')
                msg = trc.get('message', '')
                new_rc = f"{svc}: {msg}" if svc else msg
                if new_rc and new_rc != entry.root_cause:
                    entry.root_cause = new_rc[:500]
                    write_back_count += 1
            elif rc and hasattr(rc, 'message') and rc.message:
                new_rc = f"{rc.service}: {rc.message}" if rc.service else rc.message
                if new_rc and new_rc != entry.root_cause:
                    entry.root_cause = new_rc[:500]
                    write_back_count += 1

            # Write-back behavior from trace flow summary
            if aggregate.trace_flow_summary and not entry.behavior:
                steps = aggregate.trace_flow_summary
                if steps:
                    last_step = steps[-1] if isinstance(steps[-1], dict) else {}
                    behavior_msg = last_step.get('message', '')
                    if behavior_msg:
                        entry.behavior = behavior_msg[:500]

            # Write-back severity and score
            if aggregate.max_severity and aggregate.max_severity != 'info':
                entry_sev = getattr(entry, '_enriched_severity', None)
                if entry_sev != aggregate.max_severity:
                    entry._enriched_severity = aggregate.max_severity
            if aggregate.max_score > 0:
                entry._enriched_score = aggregate.max_score

        if write_back_count > 0:
            print(f"\n📝 Write-back: updated root_cause for {write_back_count} problems")
            try:
                _registry.save()
                print(f"   ✅ Registry saved with enriched data")
            except Exception as e:
                print(f"   ⚠️ Registry save failed: {e}")

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
    print("✅ REGULAR PHASE COMPLETE")
    print("=" * 70)
    
    # ==========================================================================
    # SEND PEAKS NOTIFICATION (EMAIL ONLY)
    # ==========================================================================
    if collection.incidents:
        try:
            # Detect peaks: spike OR burst OR high-score anomalies
            peaks_detected = sum(
                1 for inc in collection.incidents
                if (inc.flags.is_spike or inc.flags.is_burst or 
                    getattr(inc, 'score', 0) >= 70)
            )

            if peaks_detected > 0 and enriched_problems:
                max_alerts = int(os.getenv('MAX_PEAK_ALERTS_PER_WINDOW', '3'))
                digest_raw = os.getenv('ALERT_DIGEST_ENABLED', 'true').strip().lower()
                digest_enabled = digest_raw not in {'0', 'false', 'no', 'off'}
                peak_problems = _select_peak_problems(enriched_problems, limit=max_alerts)
                sent_alerts = 0
                suppressed_alerts = 0
                alert_state = _load_alert_state(registry)
                alert_peaks = alert_state.get('peaks', {})
                now_utc = datetime.now(timezone.utc)
                cooldown_min = int(os.getenv('ALERT_COOLDOWN_MIN', '45'))
                dispatch_payloads: List[Dict[str, Any]] = []

                for peak_problem in peak_problems:
                    payload = _build_peak_alert_payload(
                        peak_problem,
                        peak_trace_flows or {},
                        known_peaks_snapshot,
                        window_start,
                        window_end,
                        window_minutes
                    )
                    if not payload:
                        continue

                    peak_key = payload.get('peak_key', '')
                    state_entry = alert_peaks.get(peak_key, {}) if peak_key else {}
                    should_send, reason = _should_send_peak_alert(payload, state_entry, now_utc)

                    if not should_send:
                        suppressed_alerts += 1
                        if peak_key:
                            print(f"ℹ️ Peak alert suppressed for {peak_key}: {reason}")
                        continue

                    payload['send_reason'] = reason
                    dispatch_payloads.append(payload)

                if digest_enabled:
                    if dispatch_payloads and _send_peak_alert_digest(window_start, window_end, dispatch_payloads, suppressed_alerts):
                        sent_alerts = len(dispatch_payloads)
                    elif dispatch_payloads:
                        print("⚠️ Digest send failed, falling back to individual alerts")
                        for payload in dispatch_payloads:
                            if _send_peak_alert_email(payload):
                                sent_alerts += 1
                else:
                    for payload in dispatch_payloads:
                        if _send_peak_alert_email(payload):
                            sent_alerts += 1

                if sent_alerts > 0:
                    for payload in dispatch_payloads:
                        peak_key = payload.get('peak_key', '')
                        if not peak_key:
                            continue
                        alert_peaks[peak_key] = {
                            'last_sent_at': now_utc.isoformat(),
                            'last_sent_window': payload.get('window_key', ''),
                            'last_trend': payload.get('trend', ''),
                            'last_error_count': int(payload.get('error_count', 0) or 0),
                            'cooldown_until': (now_utc + timedelta(minutes=max(cooldown_min, 0))).isoformat(),
                            'last_reason': payload.get('send_reason', ''),
                        }

                alert_state['peaks'] = alert_peaks
                _save_alert_state(registry, alert_state)

                print(f"✅ Peak alerts dispatched: {sent_alerts}/{len(peak_problems)} (suppressed: {suppressed_alerts})")
                    
        except Exception as e:
            print(f"⚠️ Peak alert failed: {e}")
    
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
    parser = argparse.ArgumentParser(description='Regular Phase - 15-minute Pipeline')
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
