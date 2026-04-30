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
from core.problem_registry import dominant_count_entry, extract_flow, is_test_peak_counts
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


def _select_behavior_steps(problem: Any, flow: Any = None, max_steps: int = 5) -> List[Dict[str, Any]]:
    summary_steps = getattr(problem, 'trace_flow_summary', None) or []
    selected: List[Dict[str, Any]] = []

    for step in summary_steps[:max_steps]:
        if not isinstance(step, dict):
            continue
        selected.append({
            'app': step.get('app', '?'),
            'message': step.get('message', ''),
            'count': int(step.get('count', 1) or 1),
            'share_pct': step.get('share_pct'),
            'apps': step.get('apps', []) or [],
            'namespaces': step.get('namespaces', []) or [],
            'trace_ids': step.get('trace_ids', []) or [],
        })

    if selected:
        return selected

    if not flow or not getattr(flow, 'steps', None):
        return []

    for step in _select_trace_steps(flow, max_steps=max_steps, min_steps=max_steps):
        selected.append({
            'app': getattr(step, 'app', '?'),
            'message': getattr(step, 'message', ''),
            'count': 1,
        })
    return selected


def _format_behavior_step(step: Dict[str, Any], index: int = 0) -> str:
    """Format a single behavior step. Uses _extract_useful_content for message cleaning."""
    from analysis.trace_analysis import _extract_useful_content, _smart_trim

    app = str(step.get('app', '?') or '?')
    raw_message = str(step.get('message', '') or '')
    message = _smart_trim(raw_message)
    if not message:
        message = raw_message[:200]

    count = step.get('count')
    share_pct = step.get('share_pct')
    count_text = f" ({count:,}×)" if isinstance(count, int) and count > 1 else ""
    share_text = f" [{share_pct:.0f}%]" if isinstance(share_pct, (int, float)) and share_pct > 0 else ""

    prefix = f"{index}. " if index > 0 else ""
    return f"{prefix}{app}{count_text}{share_text}: {message}"


def _summarize_behavior_steps(steps: List[Dict[str, Any]], limit: int = 3) -> str:
    """Build numbered behavior summary, deduplicating against already-seen messages."""
    from analysis.trace_analysis import _extract_useful_content, normalize_message
    parts = []
    seen = set()
    idx = 0
    for step in (steps or []):
        if idx >= limit:
            break
        raw_msg = str(step.get('message', '') or '')
        extracted = _extract_useful_content(raw_msg)
        dedup_key = normalize_message(extracted or raw_msg)[:80].lower()
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        idx += 1
        parts.append(_format_behavior_step(step, index=idx))
    return "\n".join(parts)[:600]


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


def _merge_peak_clusters(
    peak_problems: List[Any],
    trace_overlap_threshold: float = 0.50,
) -> List[List[Any]]:
    """
    Merge peak problems that describe the same underlying issue into clusters.

    Merge criteria (any one is sufficient):
    1. Shared dominant trace: >50% trace ID overlap (same causal chain)
    2. Same error_class AND same dominant namespace

    Returns list of clusters. Each cluster is a list of problems, first = highest score.
    """
    if not peak_problems:
        return []
    if len(peak_problems) == 1:
        return [peak_problems]

    def _problem_traces(p: Any) -> set:
        """Get set of trace IDs from a problem's incidents."""
        traces = set()
        for inc in (getattr(p, 'incidents', []) or []):
            tc = getattr(inc, 'trace_event_counts', {}) or {}
            traces.update(tc.keys())
            for tid in (getattr(inc, 'trace_ids', []) or []):
                if tid:
                    traces.add(tid)
        return traces

    def _problem_dominant_ns(p: Any) -> str:
        """Get the dominant namespace for a problem."""
        ns_counts: Dict[str, int] = {}
        for inc in (getattr(p, 'incidents', []) or []):
            inc_ns = getattr(inc, 'namespace_event_counts', {}) or {}
            for ns, cnt in inc_ns.items():
                if ns:
                    ns_counts[ns] = ns_counts.get(ns, 0) + int(cnt or 0)
        if not ns_counts:
            namespaces = getattr(p, 'namespaces', set()) or set()
            return next(iter(namespaces), '')
        return max(ns_counts, key=ns_counts.get)

    # Phase 1: Build data for each problem
    problem_data = []
    for p in peak_problems:
        traces = _problem_traces(p)
        ec = str(getattr(p, 'error_class', '') or '').lower()
        dom_ns = _problem_dominant_ns(p)
        problem_data.append({
            'problem': p,
            'traces': traces,
            'error_class': ec,
            'dominant_ns': dom_ns,
        })

    # Phase 2: Greedy clustering
    n = len(problem_data)
    cluster_of = list(range(n))  # union-find parent

    def _find(i: int) -> int:
        while cluster_of[i] != i:
            cluster_of[i] = cluster_of[cluster_of[i]]
            i = cluster_of[i]
        return i

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            # Always root at the lower index (higher score, since list is pre-sorted)
            if ra > rb:
                ra, rb = rb, ra
            cluster_of[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            # Criterion 1: trace overlap
            ti, tj = problem_data[i]['traces'], problem_data[j]['traces']
            if ti and tj:
                overlap = len(ti & tj)
                smaller = min(len(ti), len(tj))
                if smaller > 0 and (overlap / smaller) >= trace_overlap_threshold:
                    _union(i, j)
                    continue

            # Criterion 2: same error_class + same dominant namespace
            if (problem_data[i]['error_class'] and
                problem_data[i]['error_class'] == problem_data[j]['error_class'] and
                problem_data[i]['dominant_ns'] and
                problem_data[i]['dominant_ns'] == problem_data[j]['dominant_ns']):
                _union(i, j)

    # Build clusters
    clusters_map: Dict[int, List[Any]] = {}
    for i in range(n):
        root = _find(i)
        clusters_map.setdefault(root, []).append(problem_data[i]['problem'])
    
    return list(clusters_map.values())


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


def _merge_count_map(target: Dict[str, int], source: Optional[Dict[str, Any]]) -> None:
    for key, value in (source or {}).items():
        if not key:
            continue
        try:
            count = int(value or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        target[str(key)] = target.get(str(key), 0) + count


def _sorted_count_map(counts: Optional[Dict[str, int]]) -> Dict[str, int]:
    return {
        key: value
        for key, value in sorted((counts or {}).items(), key=lambda kv: (-kv[1], kv[0]))
    }


def _should_send_peak_alert(
    payload: Dict[str, Any],
    state_entry: Dict[str, Any],
    now_utc: datetime,
) -> Tuple[bool, str]:
    cooldown_min = int(os.getenv('ALERT_COOLDOWN_MIN', '45'))
    heartbeat_min = int(os.getenv('ALERT_HEARTBEAT_MIN', '120'))
    min_delta_pct = float(os.getenv('ALERT_MIN_DELTA_PCT', '30'))

    if payload.get('is_test_peak'):
        originator = str(payload.get('test_originator_application', '') or '')
        suffix = f":{originator}" if originator else ''
        return False, f'test_peak_suppressed{suffix}'

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
    app_counts: Dict[str, int] = {}
    originator_application_counts: Dict[str, int] = {}
    trace_counts: Dict[str, int] = {}
    error_type_counts: Dict[str, int] = {}
    raw_error_count = 0

    for inc in signal_incidents:
        count = 1
        if hasattr(inc, 'stats') and hasattr(inc.stats, 'current_count'):
            try:
                count = max(1, int(inc.stats.current_count))
            except (TypeError, ValueError):
                count = 1
        raw_error_count += count

        incident_app_counts = getattr(inc, 'app_event_counts', {}) or {}
        if incident_app_counts:
            _merge_count_map(app_counts, incident_app_counts)
        else:
            for app in (getattr(inc, 'apps', []) or []):
                if app:
                    app_counts[app] = app_counts.get(app, 0) + count

        incident_ns_counts = getattr(inc, 'namespace_event_counts', {}) or {}
        if incident_ns_counts:
            _merge_count_map(namespace_counts, incident_ns_counts)
        else:
            for ns in (getattr(inc, 'namespaces', []) or []):
                if ns:
                    namespace_counts[ns] = namespace_counts.get(ns, 0) + count

        _merge_count_map(originator_application_counts, getattr(inc, 'originator_application_counts', {}) or {})
        incident_trace_counts = getattr(inc, 'trace_event_counts', {}) or {}
        if incident_trace_counts:
            _merge_count_map(trace_counts, incident_trace_counts)
        else:
            for trace_id in (getattr(inc, 'trace_ids', []) or []):
                if trace_id:
                    trace_counts[trace_id] = trace_counts.get(trace_id, 0) + 1

        err_type = getattr(inc, 'error_type', None) or 'UnknownError'
        error_type_counts[err_type] = error_type_counts.get(err_type, 0) + count

    namespace_counts = _sorted_count_map(namespace_counts)
    app_counts = _sorted_count_map(app_counts)
    originator_application_counts = _sorted_count_map(originator_application_counts)
    trace_counts = _sorted_count_map(trace_counts)

    # Filter out insignificant NS from display (below 1% of total or < 100 errors)
    total_ns_errors = sum(namespace_counts.values())
    if total_ns_errors > 0:
        ns_threshold = max(100, total_ns_errors * 0.01)
        namespace_counts_display = {ns: cnt for ns, cnt in namespace_counts.items() if cnt >= ns_threshold}
        if not namespace_counts_display:
            # Keep at least the top one
            namespace_counts_display = dict(list(namespace_counts.items())[:1])
    else:
        namespace_counts_display = namespace_counts

    affected_apps = list(app_counts.keys()) if app_counts else sorted(problem.apps)
    affected_namespaces = list(namespace_counts_display.keys()) if namespace_counts_display else sorted(problem.namespaces)

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
    if trace_counts:
        trace_id = next(iter(trace_counts.keys()))
    if flow and getattr(flow, 'trace_id', None):
        trace_id = trace_id or str(getattr(flow, 'trace_id', '') or '')

    trace_steps = _select_behavior_steps(problem, flow, max_steps=5)
    if not trace_id and trigger_incident is not None:
        trace_id = str(getattr(trigger_incident, 'trace_id', '') or '')
    if not trace_id:
        trace_id = str(getattr(problem, 'representative_trace_id', '') or '')

    current_window_errors = raw_error_count or problem.total_occurrences
    test_originator_application, _ = dominant_count_entry(originator_application_counts)
    is_test_peak = is_test_peak_counts(originator_application_counts, current_window_errors)
    previous_average_errors = None
    if known_peak and getattr(known_peak, 'occurrences', 0):
        peak_occurrences = max(1, int(getattr(known_peak, 'occurrences', 0) or 0))
        historical_raw = int(getattr(known_peak, 'raw_error_count', 0) or 0)
        if historical_raw > 0:
            previous_average_errors = historical_raw / peak_occurrences

    # Trend state machine:
    # - First window (new peak or not continuing): always 'rising'
    # - Subsequent continuing windows: compare to historical average
    trend = None
    if not is_known or not is_continues:
        # First window of this peak → rising by definition
        trend = 'rising'
    elif previous_average_errors and previous_average_errors > 0:
        ratio_to_avg = current_window_errors / previous_average_errors
        if ratio_to_avg >= 1.2:
            trend = 'rising'
        elif ratio_to_avg <= 0.8:
            trend = 'falling'
        else:
            trend = 'stable'
    else:
        trend = 'rising'

    if known_peak and getattr(known_peak, 'app_counts', None):
        known_apps = set((getattr(known_peak, 'app_counts', {}) or {}).keys())
    else:
        known_apps = set(getattr(known_peak, 'affected_apps', []) or []) if known_peak else set()
    if known_peak and getattr(known_peak, 'namespace_counts', None):
        known_namespaces = set((getattr(known_peak, 'namespace_counts', {}) or {}).keys())
    else:
        known_namespaces = set(getattr(known_peak, 'affected_namespaces', []) or []) if known_peak else set()
    new_apps = sorted(set(affected_apps) - known_apps)
    new_namespaces = sorted(set(affected_namespaces) - known_namespaces)
    continuation_summary = None
    if is_known and is_continues:
        continuation_summary = {
            'trend': trend,
            'current_window_errors': int(current_window_errors),
            'previous_average_errors': int(previous_average_errors) if previous_average_errors else None,
            'new_apps': new_apps,
            'new_namespaces': new_namespaces,
            'top_error_types': top_error_types_text,
        }

    trace_steps_for_email = trace_steps

    # Root cause: use infer_problem_root_cause with behavior dedup
    from analysis.trace_analysis import infer_problem_root_cause as _infer_rc
    rc_result = _infer_rc(problem, behavior_steps=trace_steps)
    root_cause = None
    if rc_result and rc_result.get('message'):
        root_cause = {
            'service': rc_result.get('service', '?'),
            'message': rc_result.get('message', ''),
            'confidence': rc_result.get('confidence', 'medium'),
        }
    else:
        # Fallback to trace_root_cause
        rc = getattr(problem, 'trace_root_cause', None)
        if rc:
            root_cause = {
                'service': rc.get('service', '?'),
                'message': rc.get('message', ''),
                'confidence': rc.get('confidence', 'medium'),
            }
        elif getattr(problem, 'root_cause', None):
            rc_obj = problem.root_cause
            root_cause = {
                'service': getattr(rc_obj, 'service', '?'),
                'message': getattr(rc_obj, 'message', ''),
                'confidence': getattr(rc_obj, 'confidence', 'medium'),
            }

    propagation_info = None
    propagation = getattr(problem, 'propagation_result', None)
    if propagation and propagation.service_count > 1:
        propagation_info = {
            'type': propagation.propagation_type,
            'service_count': propagation.service_count,
            'duration_ms': propagation.propagation_time_ms
        }

    # Digest root cause text: deduplicated against behavior
    digest_root_cause = ''
    if root_cause:
        digest_root_cause = str(root_cause.get('message', '') or root_cause.get('service', '') or '')
    if not digest_root_cause and known_peak and getattr(known_peak, 'root_cause', None):
        digest_root_cause = str(getattr(known_peak, 'root_cause', '') or '')
    if not digest_root_cause and getattr(problem, 'root_cause', None):
        digest_root_cause = str(getattr(problem, 'root_cause', '') or '')

    behavior_text = ''
    if trace_steps:
        behavior_text = _summarize_behavior_steps(trace_steps, limit=3)
    if not behavior_text:
        behavior_text = str(peak_error_details or '')

    # Originator line
    originator_display = ''
    if originator_application_counts:
        top_orig = sorted(originator_application_counts.items(), key=lambda kv: -kv[1])[:3]
        originator_display = ', '.join(f"{name}({count})" for name, count in top_orig)

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
        'affected_apps': affected_apps[:5],
        'affected_namespaces': affected_namespaces[:5],
        'app_counts': dict(list(app_counts.items())[:5]),
        'namespace_counts': namespace_counts_display,
        'originator_application_counts': originator_application_counts,
        'originator_display': originator_display,
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
        'behavior_text': behavior_text,
        'detail_message': behavior_text,
        'is_test_peak': is_test_peak,
        'test_originator_application': test_originator_application,
    }


def _build_cluster_payload(
    cluster: List[Any],
    trace_flows: Dict[str, List[Any]],
    known_peaks: Dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    window_minutes: int,
) -> Optional[Dict[str, Any]]:
    """
    Build a merged payload for a cluster of related peak problems.

    Uses the highest-scoring problem as the primary (error_class, behavior, root_cause)
    and sums counts, merges apps/NS across all problems in the cluster.
    """
    if not cluster:
        return None
    
    # Primary = first (highest score)
    primary = cluster[0]
    payload = _build_peak_alert_payload(
        primary, trace_flows, known_peaks,
        window_start, window_end, window_minutes,
    )
    if not payload:
        return None

    if len(cluster) == 1:
        return payload

    # Merge counts from other problems in cluster
    for secondary in cluster[1:]:
        sec_payload = _build_peak_alert_payload(
            secondary, trace_flows, known_peaks,
            window_start, window_end, window_minutes,
        )
        if not sec_payload:
            continue
        
        # Sum error count
        payload['error_count'] = int(payload.get('error_count', 0)) + int(sec_payload.get('error_count', 0))
        
        # Merge app_counts
        for app, cnt in (sec_payload.get('app_counts', {}) or {}).items():
            payload['app_counts'][app] = payload['app_counts'].get(app, 0) + int(cnt or 0)
        
        # Merge namespace_counts
        for ns, cnt in (sec_payload.get('namespace_counts', {}) or {}).items():
            payload['namespace_counts'][ns] = payload['namespace_counts'].get(ns, 0) + int(cnt or 0)
        
        # Merge originator_application_counts
        for orig, cnt in (sec_payload.get('originator_application_counts', {}) or {}).items():
            payload['originator_application_counts'][orig] = payload['originator_application_counts'].get(orig, 0) + int(cnt or 0)

    # Re-sort and limit app_counts to top 5
    sorted_apps = dict(sorted(payload['app_counts'].items(), key=lambda kv: -kv[1])[:5])
    payload['app_counts'] = sorted_apps
    payload['affected_apps'] = list(sorted_apps.keys())
    
    # Re-sort namespace_counts
    payload['namespace_counts'] = dict(sorted(payload['namespace_counts'].items(), key=lambda kv: -kv[1]))
    payload['affected_namespaces'] = list(payload['namespace_counts'].keys())[:5]

    # Re-evaluate test peak with merged originator counts
    merged_errors = int(payload.get('error_count', 0))
    payload['is_test_peak'] = is_test_peak_counts(payload['originator_application_counts'], merged_errors)
    test_orig, _ = dominant_count_entry(payload['originator_application_counts'])
    payload['test_originator_application'] = test_orig

    # Re-build originator display
    top_orig = sorted(payload['originator_application_counts'].items(), key=lambda kv: -kv[1])[:3]
    payload['originator_display'] = ', '.join(f"{name}({count})" for name, count in top_orig)

    payload['cluster_size'] = len(cluster)

    return payload


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
            app_counts=payload.get('app_counts', {}),
            affected_namespaces=payload.get('affected_namespaces', []),
            namespace_counts=payload.get('namespace_counts', {}),
            trace_steps=payload.get('trace_steps', []),
            behavior_text=payload.get('behavior_text', ''),
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
    behavior_steps = _select_behavior_steps(problem, flow)

    if behavior_steps:
        lines.append("")
        lines.append(f"Behavior (dominant patterns): {len(behavior_steps)} items")
        trace_id = getattr(problem, 'representative_trace_id', None) or getattr(flow, 'trace_id', None)
        if trace_id:
            lines.append(f"TraceID: {trace_id}")
        lines.append("")

        for step in behavior_steps:
            lines.append(_format_behavior_step(step))

    if getattr(problem, 'trace_root_cause', None):
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
            namespace_event_counts = getattr(incident, 'namespace_event_counts', {}) or {}
            top_namespace = ''
            if namespace_event_counts:
                top_namespace = max(namespace_event_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
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
                top_namespace or (incident.namespaces[0] if incident.namespaces else 'unknown'),
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
            namespace_event_counts = getattr(incident, 'namespace_event_counts', {}) or {}
            if namespace_event_counts:
                for ns, count in namespace_event_counts.items():
                    if ns:
                        ns_totals[ns] = ns_totals.get(ns, 0) + int(count or 0)
            else:
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
            registry_problems=_registry.problems if _registry is not None else None,
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

            # Write-back behavior from problem-level behavior summary
            if aggregate.trace_flow_summary:
                behavior_msg = _summarize_behavior_steps(aggregate.trace_flow_summary, limit=3)
                if behavior_msg and behavior_msg != entry.behavior:
                    entry.behavior = behavior_msg[:500]
                    write_back_count += 1

            # Write-back severity and score
            if aggregate.max_severity and aggregate.max_severity != 'info':
                entry_sev = getattr(entry, '_enriched_severity', None)
                if entry_sev != aggregate.max_severity:
                    entry._enriched_severity = aggregate.max_severity
            if aggregate.max_score > 0:
                entry._enriched_score = aggregate.max_score

        if write_back_count > 0:
            print(f"\n📝 Write-back: updated enriched fields for {write_back_count} problems")
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
                
                # Select ALL peak problems (no limit), then cluster
                peak_problems = _select_peak_problems(enriched_problems, limit=0)
                clusters = _merge_peak_clusters(peak_problems)
                print(f"ℹ️ Peak problems: {len(peak_problems)} → {len(clusters)} cluster(s)")
                
                sent_alerts = 0
                suppressed_alerts = 0
                alert_state = _load_alert_state(registry)
                alert_peaks = alert_state.get('peaks', {})
                now_utc = datetime.now(timezone.utc)
                cooldown_min = int(os.getenv('ALERT_COOLDOWN_MIN', '45'))
                dispatch_payloads: List[Dict[str, Any]] = []

                for cluster in clusters[:max_alerts]:
                    payload = _build_cluster_payload(
                        cluster,
                        peak_trace_flows or {},
                        known_peaks_snapshot,
                        window_start,
                        window_end,
                        window_minutes,
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

                    # Trend override: if no alert was sent to user recently,
                    # this is effectively the "first alert" → always "rising"
                    last_sent = _parse_dt(state_entry.get('last_sent_at'))
                    if not last_sent or (now_utc - last_sent) > timedelta(minutes=window_minutes * 2):
                        if payload.get('trend') and payload['trend'] != 'rising':
                            print(f"ℹ️ Trend override for {peak_key}: {payload['trend']} → rising (first alert)")
                            payload['trend'] = 'rising'

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

                # Write-back enriched root_cause and behavior to PeakEntry
                peak_wb_count = 0
                for payload in dispatch_payloads:
                    pk = payload.get('peak_key', '')
                    if not pk or pk not in registry.peaks:
                        continue
                    peak_entry = registry.peaks[pk]
                    rc_text = str(payload.get('root_cause_text', '') or '')
                    bh_text = str(payload.get('behavior_text', '') or '')
                    if rc_text and rc_text != peak_entry.root_cause:
                        peak_entry.root_cause = rc_text[:500]
                        peak_wb_count += 1
                    if bh_text and bh_text != peak_entry.behavior:
                        peak_entry.behavior = bh_text[:500]
                        peak_wb_count += 1
                    # NOTE: r69 fields (behavior_steps, root_cause_service,
                    # root_cause_confidence, total_messages) replaced by
                    # PeakEntry.contributing_problems which is populated
                    # organically during _update_peak. Render-time formatters
                    # in TableExporter resolve the contributing problem keys
                    # against ProblemEntry to produce per-pattern peak detail.
                if peak_wb_count > 0:
                    print(f"   📝 Peak write-back: enriched {peak_wb_count} fields")

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
