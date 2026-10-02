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
import fcntl
import json
import atexit
import signal
import re
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Tuple, Optional, Any, List, Iterable
from zoneinfo import ZoneInfo

_DISPLAY_TZ = ZoneInfo(os.getenv('DISPLAY_TIMEZONE', 'Europe/Prague'))

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))
sys.path.insert(0, str(SCRIPT_DIR.parent))

from core.fetch_unlimited import (
    INDICES,
    LAST_FETCH_STATS,
    _load_monitored_namespaces,
    fetch_trace_context,
    fetch_unlimited,
)
from core.problem_registry import ProblemRegistry, extract_flow
from core.peak_classification import dominant_count_entry, is_test_peak_counts
from core.streaming_aggregator import StreamingAggregator
from core.baseline_loader import BaselineLoader
from core.delivery_persistence import (
    persist_notification_decisions,
    persist_notification_deliveries,
)
from core.notification_policy import decide_notification_candidates
from core.run_persistence import (
    load_peak_episodes_before,
    persist_analysis_run,
)
from core.namespace_contract import namespace_contract_hash
from core.peak_decision import materialize_decision_windows
from core.workflow_diagnostics import run_workflow_lifecycle_diagnostics
from pipeline import Pipeline
from pipeline.incident import IncidentCollection
from analysis.operational_cause import (
    build_cause_family,
    build_collection_cause_analysis,
    merge_cause_families,
)

# Table exports
try:
    from exports import TableExporter
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


def _fmt_prague(ts: Optional[datetime], fmt: str = '%Y-%m-%d %H:%M') -> str:
    """Format datetime to Prague timezone for user-facing display."""
    if not ts:
        return ""
    aware = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return aware.astimezone(_DISPLAY_TZ).strftime(fmt)


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
    count_text = f" ({count:,} events)" if isinstance(count, int) and count > 1 else ""

    prefix = f"{index}. " if index > 0 else ""
    return f"{prefix}{app}{count_text}: {message}"


def _behavior_steps_match(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Return true when two behavior rows are duplicate views of one event set."""
    from analysis.trace_analysis import normalize_message

    if str(left.get('app', '') or '') != str(right.get('app', '') or ''):
        return False
    if int(left.get('count', 0) or 0) != int(right.get('count', 0) or 0):
        return False

    def _tokens(step: Dict[str, Any]) -> set:
        message = normalize_message(str(step.get('message', '') or '')).lower()
        return {
            token for token in re.findall(r'[a-z0-9]+', message)
            if len(token) > 2 and token not in {'error', 'occurred', 'during'}
        }

    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens)) >= 0.75


def _pattern_behavior_text(pattern: Any) -> str:
    """Kompaktní real-propagation shrnutí pro peak email (z trace_timeline.TracePattern).

    Reálná propagace po časové ose + occurrences/total/avg + per-app counts.
    """
    if pattern is None or not getattr(pattern, 'representative', None):
        return ''
    path_list = getattr(pattern, 'propagation_path', None) or []
    path = ' \u2192 '.join(path_list[:5])
    if len(path_list) > 5:
        path += ' \u2192 \u2026'
    parts = [path] if path else []
    parts.append(
        f"{pattern.occurrences:,} traces, {pattern.total_errors:,} errors "
        f"(avg {pattern.avg_errors_per_occurrence:.1f}/trace)"
    )
    top = sorted((pattern.per_app_errors or {}).items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    if top:
        parts.append('per-app: ' + ', '.join(f"{a}({c:,})" for a, c in top))
    return ' | '.join(parts)


def _summarize_behavior_steps(steps: List[Dict[str, Any]], limit: int = 3) -> str:
    """Build numbered behavior summary, deduplicating against already-seen messages."""
    from analysis.trace_analysis import _extract_useful_content, normalize_message
    parts = []
    seen = set()
    selected: List[Dict[str, Any]] = []
    idx = 0
    for step in (steps or []):
        if idx >= limit:
            break
        raw_msg = str(step.get('message', '') or '')
        extracted = _extract_useful_content(raw_msg)
        dedup_key = normalize_message(extracted or raw_msg)[:80].lower()
        if dedup_key in seen:
            continue
        if any(_behavior_steps_match(step, previous) for previous in selected):
            continue
        seen.add(dedup_key)
        selected.append(step)
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


def _problem_cause_token_sequences(problem: Any) -> List[List[str]]:
    """Extract stable cause tokens used to correlate alternate log messages."""
    from analysis.trace_analysis import _extract_useful_content, normalize_message

    messages = [
        str(getattr(problem, 'normalized_message', '') or ''),
        *(str(message or '') for message in (getattr(problem, 'sample_messages', []) or [])),
    ]
    ignored = {
        'called', 'case', 'code', 'description', 'during', 'error', 'failed',
        'failure', 'operation', 'processing', 'service', 'step', 'unexpected',
    }
    sequences = []
    for message in messages:
        useful = _extract_useful_content(message) or message
        normalized = normalize_message(useful).lower()
        tokens = [
            token for token in re.findall(r'[a-z0-9]+', normalized)
            if len(token) > 2 and token not in ignored
        ]
        if tokens:
            sequences.append(tokens)
    return sequences


def _longest_shared_token_run(left: List[str], right: List[str]) -> int:
    previous = [0] * (len(right) + 1)
    longest = 0
    for left_token in left:
        current = [0] * (len(right) + 1)
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current[index] = previous[index - 1] + 1
                longest = max(longest, current[index])
        previous = current
    return longest


def _problem_traces(problem: Any) -> set:
    traces = set()
    for incident in (getattr(problem, 'incidents', []) or []):
        traces.update((getattr(incident, 'trace_event_counts', {}) or {}).keys())
        traces.update(
            trace_id for trace_id in (getattr(incident, 'trace_ids', []) or [])
            if trace_id
        )
    return traces


def _problems_share_event_traces(
    left: Any,
    right: Any,
    overlap_threshold: float = 0.50,
) -> bool:
    left_traces = _problem_traces(left)
    right_traces = _problem_traces(right)
    if not left_traces or not right_traces:
        return False
    overlap = len(left_traces & right_traces)
    return overlap / min(len(left_traces), len(right_traces)) >= overlap_threshold


def _problems_represent_same_events(left: Any, right: Any) -> bool:
    """Detect alternate log messages emitted for the same set of events."""
    left_count = int(getattr(left, 'total_occurrences', 0) or 0)
    right_count = int(getattr(right, 'total_occurrences', 0) or 0)
    if left_count <= 0 or left_count != right_count:
        return False

    left_apps = set(getattr(left, 'apps', set()) or set())
    right_apps = set(getattr(right, 'apps', set()) or set())
    left_namespaces = set(getattr(left, 'namespaces', set()) or set())
    right_namespaces = set(getattr(right, 'namespaces', set()) or set())
    if not left_apps.intersection(right_apps) or not left_namespaces.intersection(right_namespaces):
        return False

    left_sequences = _problem_cause_token_sequences(left)
    right_sequences = _problem_cause_token_sequences(right)
    return any(
        _longest_shared_token_run(left_sequence, right_sequence) >= 5
        for left_sequence in left_sequences
        for right_sequence in right_sequences
    )


def _merge_peak_clusters(
    peak_problems: List[Any],
    trace_overlap_threshold: float = 0.50,
) -> List[List[Any]]:
    """
    Merge peak problems that describe the same underlying issue into clusters.

    Merge criteria (any one is sufficient):
    1. Shared dominant trace: >50% trace ID overlap (same causal chain)
    2. Alternate log messages representing the same event set

    Returns list of clusters. Each cluster is a list of problems, first = highest score.
    """
    if not peak_problems:
        return []
    if len(peak_problems) == 1:
        return [peak_problems]

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
            if _problems_share_event_traces(
                problem_data[i]['problem'],
                problem_data[j]['problem'],
                trace_overlap_threshold,
            ):
                _union(i, j)
                continue

            # Criterion 2: same volume and scope with a shared concrete cause.
            if _problems_represent_same_events(
                problem_data[i]['problem'], problem_data[j]['problem']
            ):
                _union(i, j)

    # Build clusters
    clusters_map: Dict[int, List[Any]] = {}
    for i in range(n):
        root = _find(i)
        clusters_map.setdefault(root, []).append(problem_data[i]['problem'])
    
    return list(clusters_map.values())


def _alert_state_path(registry: ProblemRegistry) -> Path:
    return Path(registry.registry_dir) / 'alert_state_regular_phase.json'


def _load_alert_state_unlocked(registry: ProblemRegistry) -> Dict[str, Any]:
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


def _load_alert_state(registry: ProblemRegistry) -> Dict[str, Any]:
    path = _alert_state_path(registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix('.json.lock')
    with open(lock_path, 'w') as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_SH)
        try:
            return _load_alert_state_unlocked(registry)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


def _save_alert_state_unlocked(registry: ProblemRegistry, state: Dict[str, Any]) -> None:
    path = _alert_state_path(registry)
    tmp_path = path.with_suffix('.json.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def _record_delivered_peak_alerts(
    registry: ProblemRegistry,
    delivered_payloads: List[Dict[str, Any]],
    now_utc: datetime,
    cooldown_min: int,
) -> None:
    if not delivered_payloads:
        return

    path = _alert_state_path(registry)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix('.json.lock')
    with open(lock_path, 'w') as lock_fd:
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        try:
            alert_state = _load_alert_state_unlocked(registry)
            alert_peaks = alert_state.setdefault('peaks', {})
            for payload in delivered_payloads:
                alert_identity = _alert_identity(payload)
                if not alert_identity:
                    continue
                alert_peaks[alert_identity] = {
                    'last_sent_at': now_utc.isoformat(),
                    'last_sent_window': payload.get('window_key', ''),
                    'last_trend': payload.get('trend', ''),
                    'last_error_count': int(payload.get('error_count', 0) or 0),
                    'cooldown_until': (
                        now_utc + timedelta(minutes=max(cooldown_min, 0))
                    ).isoformat(),
                    'last_reason': payload.get('send_reason', ''),
                    'peak_key': payload.get('peak_key', ''),
                    'cause_signatures': _cause_signatures(payload),
                }
            _save_alert_state_unlocked(registry, alert_state)
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)


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


def _numeric_or_none(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _threshold_evidence(incidents: List[Any]) -> List[Dict[str, Any]]:
    """Return unique namespace-level Pxx/CAP decisions used for this payload."""
    decisions: Dict[Tuple[str, str, Optional[float]], Dict[str, Any]] = {}
    for incident in incidents:
        for evidence in getattr(incident, 'evidence', []) or []:
            if getattr(evidence, 'rule', '') != 'spike_p93_cap':
                continue
            details = getattr(evidence, 'details', {}) or {}
            namespace = str(details.get('namespace') or '')
            snapshot_id = str(details.get('threshold_snapshot_id') or '')
            observed_value = _numeric_or_none(getattr(evidence, 'current', None))
            p93_threshold = _numeric_or_none(details.get('p93_threshold'))
            percentile_level = _numeric_or_none(details.get('percentile_level'))
            percentile_threshold = _numeric_or_none(details.get('percentile_threshold'))
            cap_threshold = _numeric_or_none(details.get('cap_threshold'))
            threshold_candidates = [
                value for value in (percentile_threshold, p93_threshold, cap_threshold)
                if value is not None
            ]
            decision = {
                'namespace': namespace,
                'observed_value': observed_value,
                'p93_threshold': p93_threshold,
                'percentile_level': percentile_level,
                'percentile_threshold': percentile_threshold or p93_threshold,
                'cap_threshold': cap_threshold,
                'effective_threshold': min(threshold_candidates) if threshold_candidates else None,
                'triggered_by': str(details.get('triggered_by') or ''),
                'threshold_snapshot_id': snapshot_id,
                'fingerprint_contribution': _numeric_or_none(
                    details.get('fingerprint_contribution')
                ),
                'detector_version': str(details.get('detector_version') or ''),
            }
            decisions[(namespace, snapshot_id, observed_value)] = decision
    return sorted(
        decisions.values(),
        key=lambda decision: (
            -(decision.get('observed_value') or 0),
            decision.get('namespace') or '',
        ),
    )


def _cause_signatures(payload: Dict[str, Any]) -> List[str]:
    signatures = {
        str(family.get('signature') or '')
        for family in (payload.get('cause_families') or [])
        if isinstance(family, dict) and family.get('signature')
    }
    return sorted(signatures)


def _set_alert_identity(payload: Dict[str, Any]) -> str:
    signatures = _cause_signatures(payload)
    if signatures:
        payload['alert_identity'] = 'CAUSE:' + '+'.join(signatures)
    else:
        payload['alert_identity'] = str(
            payload.get('peak_key') or payload.get('peak_identifier') or ''
        )
    return payload['alert_identity']


def _alert_identity(payload: Dict[str, Any]) -> str:
    return str(payload.get('alert_identity') or _set_alert_identity(payload))


def _attach_cause_family(payload: Dict[str, Any]) -> Dict[str, Any]:
    family = build_cause_family(payload).to_dict()
    payload['cause_family'] = family
    payload['cause_families'] = [family]
    _set_alert_identity(payload)
    return payload


def _attach_authoritative_cause_families(
    payload: Dict[str, Any],
    cause_analysis: Any,
) -> bool:
    """Attach run-level cause evidence without hiding a scope mismatch."""
    source_raw_lines = int(payload.get('error_count', 0) or 0)
    payload_trace_ids = {
        str(trace_id)
        for trace_id in (payload.get('trace_counts') or {})
        if trace_id
    }
    payload_trace_counts = {
        str(trace_id): max(0, int(count or 0))
        for trace_id, count in (payload.get('trace_counts') or {}).items()
        if trace_id
    }

    def set_reconciliation(
        status: str,
        *,
        represented_raw_lines: int,
        represented_trace_ids: Iterable[str],
        reason: str,
    ) -> None:
        unexplained = max(0, source_raw_lines - represented_raw_lines)
        payload['cause_reconciliation'] = {
            'status': status,
            'source_raw_error_lines': source_raw_lines,
            'represented_raw_error_lines': represented_raw_lines,
            'unexplained_raw_lines': unexplained,
            'source_trace_ids': len(payload_trace_ids),
            'represented_trace_ids': len(set(represented_trace_ids)),
            'reason': reason,
        }
        payload['cause_evidence_status'] = status
        payload['unexplained_raw_lines'] = unexplained

    if not payload_trace_ids or cause_analysis is None:
        set_reconciliation(
            'degraded',
            represented_raw_lines=0,
            represented_trace_ids=(),
            reason=(
                'trace evidence unavailable'
                if not payload_trace_ids
                else 'cause analysis unavailable'
            ),
        )
        return False

    candidates = [
        family
        for family in (getattr(cause_analysis, 'families', None) or ())
        if family.trace_ids and set(family.trace_ids) & payload_trace_ids
    ]
    candidates.sort(
        key=lambda family: (
            -family.raw_error_lines,
            family.root_app,
            family.canonical_cause,
            family.signature,
        )
    )
    if not candidates:
        set_reconciliation(
            'degraded',
            represented_raw_lines=0,
            represented_trace_ids=(),
            reason='cause families have no trace overlap with payload',
        )
        return False

    represented_trace_ids = {
        str(trace_id)
        for family in candidates
        for trace_id in family.trace_ids
        if str(trace_id) in payload_trace_ids
    }
    represented_raw_lines = sum(family.raw_error_lines for family in candidates)
    is_complete = (
        represented_trace_ids == payload_trace_ids
        and represented_raw_lines == source_raw_lines
        and all(set(family.trace_ids).issubset(payload_trace_ids) for family in candidates)
    )
    if is_complete:
        attached_families = candidates
        set_reconciliation(
            'complete',
            represented_raw_lines=source_raw_lines,
            represented_trace_ids=represented_trace_ids,
            reason='trace and raw-line evidence reconciled',
        )
    else:
        attached_families = []
        remaining_raw_lines = source_raw_lines
        projected_trace_ids = set()
        for family in candidates:
            family_trace_ids = tuple(
                sorted(set(family.trace_ids) & payload_trace_ids)
            )
            trace_raw_lines = sum(
                payload_trace_counts.get(trace_id, 0)
                for trace_id in family_trace_ids
            )
            allocated_raw_lines = min(
                max(0, int(family.raw_error_lines or 0)),
                remaining_raw_lines,
                trace_raw_lines,
            )
            if allocated_raw_lines <= 0:
                continue
            traced_error_lines = min(
                allocated_raw_lines,
                max(0, int(family.traced_error_lines or 0)),
            )
            attached_families.append(replace(
                family,
                raw_error_lines=allocated_raw_lines,
                traced_error_lines=traced_error_lines,
                unsegmented_error_lines=allocated_raw_lines - traced_error_lines,
                trace_ids=family_trace_ids,
                representative_trace_id=(
                    family.representative_trace_id
                    if family.representative_trace_id in family_trace_ids
                    else (family_trace_ids[0] if family_trace_ids else '')
                ),
            ))
            remaining_raw_lines -= allocated_raw_lines
            projected_trace_ids.update(family_trace_ids)

        represented_raw_lines = source_raw_lines - remaining_raw_lines
        if not attached_families:
            set_reconciliation(
                'degraded',
                represented_raw_lines=0,
                represented_trace_ids=(),
                reason='cause families could not be projected to current scope',
            )
            return False
        set_reconciliation(
            'partial',
            represented_raw_lines=represented_raw_lines,
            represented_trace_ids=projected_trace_ids,
            reason='trace or raw-line evidence covers only part of current scope',
        )

    payload['cause_families'] = [family.to_dict() for family in attached_families]
    payload['cause_family'] = payload['cause_families'][0]
    _set_alert_identity(payload)
    return is_complete


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

    # (b) Reálná trace propagace z raw eventů má PŘEDNOST, pokud problém vlastní
    # trace pattern (ownership: jeho dominantní app == root-cause služba patternu).
    # Pak místo agregovaných "dominant patterns" ukážeme skutečnou propagaci po
    # časové ose + occurrences/total/avg + per-app counts (jako Recent Incidents).
    trace_pattern = getattr(problem, 'trace_pattern', None)
    if trace_pattern is not None and getattr(trace_pattern, 'representative', None):
        real_text = _pattern_behavior_text(trace_pattern)
        if real_text:
            behavior_text = real_text
        rc = getattr(trace_pattern, 'root_cause', None) or {}
        if rc.get('message'):
            root_cause = {
                'service': rc.get('service', '?'),
                'message': rc.get('message', ''),
                'confidence': rc.get('confidence', 'medium'),
            }
            digest_root_cause = str(rc.get('message') or rc.get('service') or '')
        path_list = getattr(trace_pattern, 'propagation_path', None) or []
        if len(path_list) > 1:
            # 'type' se v emailu zobrazí za "Propagation:" – dáme tam reálný path.
            propagation_info = {
                'type': ' \u2192 '.join(path_list[:5]),
                'service_count': len(path_list),
                'duration_ms': 0,
            }

    # Originator line
    originator_display = ''
    if originator_application_counts:
        top_orig = sorted(originator_application_counts.items(), key=lambda kv: -kv[1])[:3]
        originator_display = ', '.join(f"{name}({count})" for name, count in top_orig)

    payload = {
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
        'all_app_counts': app_counts,
        'all_namespace_counts': namespace_counts,
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
        'trace_counts': trace_counts,
        'root_cause_text': digest_root_cause,
        'behavior_text': behavior_text,
        'detail_message': behavior_text,
        'threshold_evidence': _threshold_evidence(signal_incidents),
        'is_test_peak': is_test_peak,
        'test_originator_application': test_originator_application,
    }
    return _attach_cause_family(payload)


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

    merged_behavior_steps = list(payload.get('trace_steps', []) or [])
    primary_family = build_cause_family(payload)
    cause_families = [primary_family]
    threshold_decisions = {
        (
            str(decision.get('namespace') or ''),
            str(decision.get('threshold_snapshot_id') or ''),
            decision.get('observed_value'),
        ): decision
        for decision in (payload.get('threshold_evidence') or [])
    }

    # Merge counts from other problems in cluster
    for secondary in cluster[1:]:
        sec_payload = _build_peak_alert_payload(
            secondary, trace_flows, known_peaks,
            window_start, window_end, window_minutes,
        )
        if not sec_payload:
            continue
        
        same_events = (
            _problems_share_event_traces(primary, secondary)
            or _problems_represent_same_events(primary, secondary)
        )
        secondary_family = build_cause_family(sec_payload)
        merge_index = None
        for index, family in enumerate(cause_families):
            if same_events or family.signature == secondary_family.signature:
                merge_index = index
                break
        if merge_index is None:
            cause_families.append(secondary_family)
        else:
            cause_families[merge_index] = merge_cause_families(
                cause_families[merge_index],
                secondary_family,
                same_events=same_events,
            )

        for decision in sec_payload.get('threshold_evidence') or []:
            decision_key = (
                str(decision.get('namespace') or ''),
                str(decision.get('threshold_snapshot_id') or ''),
                decision.get('observed_value'),
            )
            threshold_decisions[decision_key] = decision
        if same_events:
            payload['error_count'] = max(
                int(payload.get('error_count', 0)), int(sec_payload.get('error_count', 0))
            )
        else:
            payload['error_count'] = int(payload.get('error_count', 0)) + int(sec_payload.get('error_count', 0))
        
        # Use max for alias messages from one event set; sum independent signals.
        for app, cnt in (sec_payload.get('all_app_counts', {}) or {}).items():
            current = payload['all_app_counts'].get(app, 0)
            payload['all_app_counts'][app] = max(current, int(cnt or 0)) if same_events else current + int(cnt or 0)
        
        for ns, cnt in (sec_payload.get('all_namespace_counts', {}) or {}).items():
            current = payload['all_namespace_counts'].get(ns, 0)
            payload['all_namespace_counts'][ns] = max(current, int(cnt or 0)) if same_events else current + int(cnt or 0)
        
        # Merge originator_application_counts
        for orig, cnt in (sec_payload.get('originator_application_counts', {}) or {}).items():
            current = payload['originator_application_counts'].get(orig, 0)
            payload['originator_application_counts'][orig] = (
                max(current, int(cnt or 0)) if same_events else current + int(cnt or 0)
            )

        if not same_events:
            merged_behavior_steps.extend(sec_payload.get('trace_steps', []) or [])

    # Re-sort and limit app_counts to top 5
    payload['all_app_counts'] = _sorted_count_map(payload['all_app_counts'])
    sorted_apps = dict(list(payload['all_app_counts'].items())[:5])
    payload['app_counts'] = sorted_apps
    payload['affected_apps'] = list(sorted_apps.keys())
    
    # Re-sort namespace_counts
    payload['all_namespace_counts'] = _sorted_count_map(payload['all_namespace_counts'])
    payload['namespace_counts'] = payload['all_namespace_counts']
    payload['affected_namespaces'] = list(payload['namespace_counts'].keys())[:5]

    if merged_behavior_steps:
        payload['trace_steps'] = merged_behavior_steps
        payload['behavior_text'] = _summarize_behavior_steps(merged_behavior_steps, limit=3)
        payload['detail_message'] = payload['behavior_text']

    # Re-evaluate test peak with merged originator counts
    merged_errors = int(payload.get('error_count', 0))
    payload['is_test_peak'] = is_test_peak_counts(payload['originator_application_counts'], merged_errors)
    test_orig, _ = dominant_count_entry(payload['originator_application_counts'])
    payload['test_originator_application'] = test_orig

    # Re-build originator display
    top_orig = sorted(payload['originator_application_counts'].items(), key=lambda kv: -kv[1])[:3]
    payload['originator_display'] = ', '.join(f"{name}({count})" for name, count in top_orig)

    payload['cluster_size'] = len(cluster)
    cause_families.sort(
        key=lambda family: (
            -family.raw_error_lines,
            family.root_app,
            family.canonical_cause,
        )
    )
    payload['cause_families'] = [family.to_dict() for family in cause_families]
    payload['cause_family'] = payload['cause_families'][0]
    _set_alert_identity(payload)
    payload['threshold_evidence'] = sorted(
        threshold_decisions.values(),
        key=lambda decision: (
            -(decision.get('observed_value') or 0),
            decision.get('namespace') or '',
        ),
    )

    return payload


def _notification_destinations() -> List[str]:
    if os.getenv('TEAMS_ENABLED', 'false').strip().lower() not in {'true', '1', 'yes'}:
        return ['notification_disabled']
    destinations = []
    if os.getenv('TEAMS_WEBHOOK_URL', '').strip():
        destinations.append('teams_webhook')
    if os.getenv('TEAMS_EMAIL', '').strip():
        destinations.append('teams_email')
    return destinations or ['notification_unconfigured']


def _delivery_dedup_key(payload: Dict[str, Any]) -> str:
    alert_identity = _alert_identity(payload) or 'unknown-cause'
    window_key = str(
        payload.get('window_key')
        or payload.get('window_start')
        or 'unknown-window'
    )
    return f'{alert_identity}:{window_key}'[:500]


def _episode_policy_contexts(
    payload: Dict[str, Any],
    transitions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Resolve a rendered payload to all event-time transitions it represents."""
    payload_window = _parse_dt(payload.get('window_start'))
    if payload_window is None:
        return []
    payload_signatures = {
        str(family.get('signature') or '')
        for family in (payload.get('cause_families') or [])
        if isinstance(family, dict) and family.get('signature')
    }
    matches = []
    for transition in transitions or []:
        transition_window = _parse_dt(transition.get('window_start_utc'))
        if transition_window is None or transition_window != payload_window:
            continue
        signature = str(transition.get('cause_signature') or '')
        if payload_signatures and (not signature or signature not in payload_signatures):
            continue
        matches.append(transition)
    if matches:
        return sorted(
            matches,
            key=lambda transition: (
                str(transition.get('state') or ''),
                str(transition.get('episode_id') or ''),
            ),
        )

    same_window = [
        transition
        for transition in transitions or []
        if _parse_dt(transition.get('window_start_utc')) == payload_window
    ]
    return same_window if not payload_signatures else []


def _episode_policy_context(
    payload: Dict[str, Any],
    transitions: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the primary transition for legacy single-episode callers."""
    contexts = _episode_policy_contexts(payload, transitions)
    return contexts[0] if contexts else None


def _notification_decision_ids(payload: Dict[str, Any]) -> List[str]:
    decision_ids = [
        str(value).strip()
        for value in (payload.get('notification_decision_ids') or ())
        if str(value).strip()
    ]
    if decision_ids:
        return list(dict.fromkeys(decision_ids))
    decision_id = str(payload.get('notification_decision_id') or '').strip()
    return [decision_id]


def _policy_delivery_outcomes(
    payload: Dict[str, Any],
    status: str,
    provider_message: str,
) -> List[Dict[str, Any]]:
    peak_key = str(payload.get('peak_key', '') or '')
    alert_identity = _alert_identity(payload)
    return [
        {
            'dedup_key': _delivery_dedup_key(payload),
            'destination': destination,
            'status': status,
            'provider_message': provider_message,
            'notification_decision_id': decision_id,
            'metadata': {
                'attempt_kind': 'policy',
                'peak_key': peak_key,
                'alert_identity': alert_identity,
                'cause_signatures': _cause_signatures(payload),
                'window_key': payload.get('window_key', ''),
                'error_count': int(payload.get('error_count', 0) or 0),
            },
        }
        for decision_id in _notification_decision_ids(payload)
        for destination in _notification_destinations()
    ]


def _normalize_send_result(send_result: Any) -> Tuple[bool, List[Dict[str, Any]]]:
    if (
        isinstance(send_result, tuple)
        and len(send_result) == 2
        and isinstance(send_result[1], list)
    ):
        return bool(send_result[0]), send_result[1]
    return bool(send_result), []


def _payload_delivery_outcomes(
    payload: Dict[str, Any],
    outcomes: List[Dict[str, Any]],
    attempt_kind: str,
) -> List[Dict[str, Any]]:
    return [{
        **outcome,
        'dedup_key': _delivery_dedup_key(payload),
        'notification_decision_id': decision_id,
        'metadata': {
            'attempt_kind': attempt_kind,
            'peak_key': payload.get('peak_key', ''),
            'alert_identity': _alert_identity(payload),
            'cause_signatures': _cause_signatures(payload),
            'window_key': payload.get('window_key', ''),
            'send_reason': payload.get('send_reason', ''),
            'error_count': int(payload.get('error_count', 0) or 0),
            'notification_decision_id': decision_id,
            'policy_outcome': payload.get('policy_outcome', ''),
            'test_origin_label': payload.get('test_origin_label', ''),
        },
    } for decision_id in _notification_decision_ids(payload) for outcome in outcomes]


class PeakDispatchResult(list):
    def __init__(
        self,
        delivered_payloads: List[Dict[str, Any]],
        delivery_outcomes: List[Dict[str, Any]],
    ) -> None:
        super().__init__(delivered_payloads)
        self.delivery_outcomes = delivery_outcomes


def _send_peak_alert_email(
    payload: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]]]:
    if not payload:
        return False, []

    try:
        from core.email_notifier import EmailNotifier

        email_notifier = EmailNotifier()
        if not email_notifier.is_enabled():
            print("⚠️ Email notifier not enabled")
            return False, [{
                'destination': destination,
                'status': 'skipped',
                'provider_message': 'Notification delivery is disabled or unconfigured',
            } for destination in _notification_destinations()]

        operator_digest_enabled = os.getenv(
            'ALERT_OPERATOR_DIGEST_ENABLED', 'true'
        ).strip().lower() not in {'0', 'false', 'no', 'off'}
        if operator_digest_enabled:
            success = email_notifier.send_regular_phase_peak_digest(
                window_start=payload.get('window_start'),
                window_end=payload.get('window_end'),
                alerts=[payload],
                summary={
                    'raw_window_errors': int(payload.get('error_count', 0) or 0),
                },
            )
        else:
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
            return True, email_notifier.get_last_delivery_results()
        print("⚠️ Peak alert email failed")
        return False, email_notifier.get_last_delivery_results()

    except Exception as e:
        print(f"⚠️ Error sending peak alert email: {e}")
        return False, [{
            'destination': 'notification_runtime',
            'status': 'failed',
            'provider_message': _one_line_error(e),
        }]


def _send_peak_alert_digest(
    window_start: datetime,
    window_end: datetime,
    alerts: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]]]:
    if not alerts:
        return False, []

    try:
        from core.email_notifier import EmailNotifier

        email_notifier = EmailNotifier()
        if not email_notifier.is_enabled():
            print("⚠️ Email notifier not enabled")
            return False, [{
                'destination': destination,
                'status': 'skipped',
                'provider_message': 'Notification delivery is disabled or unconfigured',
            } for destination in _notification_destinations()]

        success = email_notifier.send_regular_phase_peak_digest(
            window_start=window_start,
            window_end=window_end,
            alerts=alerts,
            summary=summary,
        )
        return success, email_notifier.get_last_delivery_results()
    except Exception as e:
        print(f"⚠️ Error sending peak digest email: {e}")
        return False, [{
            'destination': 'notification_runtime',
            'status': 'failed',
            'provider_message': _one_line_error(e),
        }]


def _dispatch_peak_alerts(
    window_start: datetime,
    window_end: datetime,
    payloads: List[Dict[str, Any]],
    digest_enabled: bool,
    digest_summary: Dict[str, Any],
    digest_payloads: Optional[List[Dict[str, Any]]] = None,
) -> PeakDispatchResult:
    digest_alerts = digest_payloads if digest_payloads is not None else payloads
    if not payloads and not digest_alerts:
        return PeakDispatchResult([], [])

    delivery_outcomes: List[Dict[str, Any]] = []
    if digest_enabled:
        digest_success, digest_results = _normalize_send_result(
            _send_peak_alert_digest(
                window_start, window_end, digest_alerts, digest_summary
            )
        )
        for payload in digest_alerts:
            delivery_outcomes.extend(
                _payload_delivery_outcomes(payload, digest_results, 'digest')
            )
        if digest_success:
            return PeakDispatchResult(list(digest_alerts), delivery_outcomes)

    if digest_enabled:
        print("⚠️ Digest send failed, falling back to individual alerts")

    primary_payload_ids = {id(payload) for payload in payloads}
    for payload in digest_alerts:
        if id(payload) in primary_payload_ids:
            continue
        delivery_outcomes.extend(
            _payload_delivery_outcomes(
                payload,
                [{
                    'destination': destination,
                    'status': 'not_attempted',
                    'provider_message': (
                        'Digest delivery failed; digest-only candidate was not attempted individually'
                    ),
                } for destination in _notification_destinations()],
                'not_attempted',
            )
        )

    delivered = []
    for payload in payloads:
        success, individual_results = _normalize_send_result(
            _send_peak_alert_email(payload)
        )
        delivery_outcomes.extend(
            _payload_delivery_outcomes(payload, individual_results, 'individual')
        )
        if success:
            delivered.append(payload)
    return PeakDispatchResult(delivered, delivery_outcomes)


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
    peak_window_start_text = _fmt_prague(peak_window_start) or _fmt_prague(window_start)
    peak_window_end_text = _fmt_prague(window_end)

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
        event_time = f"Event time: {_fmt_prague(problem.first_seen)} - {_fmt_prague(problem.last_seen, '%H:%M')}"
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
        # POZN.: Nezobrazujeme jeden "TraceID" nad patterny – patterny jsou agregát
        # napříč VŠEMI trace problému (summarize_problem_patterns), ne kroky jednoho
        # trace. Jeden TraceID nahoře vytvářel dojem, že všechny zprávy patří jemu
        # (neseděly s ES). Reálný příklad trace je u jednotlivých patternů.
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
        # Cross-service scope BEZ kauzálních šipek / root / duration. Bez reálného
        # pořadí eventů nelze určit směr šíření – affected apps jsou vypsané výše.
        # Uvádíme jen faktický rozsah, když problém zasahuje víc namespaces.
        propagation = getattr(problem, 'propagation_result', None)
        if propagation and propagation.service_count > 1 and propagation.namespace_count > 1:
            lines.append("")
            lines.append(
                f"Spread: {propagation.service_count} services / "
                f"{propagation.namespace_count} namespaces"
            )

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

def _resolve_regular_window(
    window_minutes: int,
    replay_window_end: Optional[datetime] = None,
) -> Tuple[datetime, datetime, datetime]:
    now = datetime.now(timezone.utc)
    if replay_window_end is None:
        quarter = (now.minute // 15) * 15
        window_end = now.replace(minute=quarter, second=0, microsecond=0)
    else:
        if window_minutes != 15:
            raise ValueError('historical replay requires window_minutes=15')
        if replay_window_end.tzinfo is None or replay_window_end.utcoffset() is None:
            raise ValueError('replay_window_end must be timezone-aware')
        window_end = replay_window_end.astimezone(timezone.utc)
        if (
            window_end.minute % 15
            or window_end.second
            or window_end.microsecond
        ):
            raise ValueError('replay_window_end must align to a 15-minute UTC boundary')
    return now, window_end - timedelta(minutes=window_minutes), window_end


def _load_replay_threshold_bundle(
    peak_detector: Any,
    bundle_path: Path,
    window_start: datetime,
    monitored_namespaces: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    from core.calculate_peak_thresholds import (
        CALCULATION_VERSION,
        PERCENTILE_METHOD,
        POPULATION_GRAIN,
    )

    bundle = json.loads(bundle_path.read_text(encoding='utf-8'))
    metadata = bundle.get('metadata') or {}
    expected_percentile = float(os.getenv('PERCENTILE_LEVEL', '0.93'))
    expected_metadata = {
        'population_grain': POPULATION_GRAIN,
        'percentile_method': PERCENTILE_METHOD,
        'calculation_version': CALCULATION_VERSION,
    }
    mismatches = [
        f'{name}={metadata.get(name)} expected={expected}'
        for name, expected in expected_metadata.items()
        if metadata.get(name) != expected
    ]
    percentile_level = float(metadata.get('percentile_level', -1))
    if abs(percentile_level - expected_percentile) >= 1e-9:
        mismatches.append(
            f'percentile_level={percentile_level} expected={expected_percentile}'
        )
    training_cutoff = datetime.fromisoformat(
        str(metadata.get('training_cutoff', '')).replace('Z', '+00:00')
    )
    if training_cutoff.tzinfo is None or training_cutoff.utcoffset() is None:
        mismatches.append('training_cutoff must be timezone-aware')
    elif training_cutoff.astimezone(timezone.utc) > window_start:
        mismatches.append(
            f'training_cutoff={training_cutoff.isoformat()} exceeds '
            f'window_start={window_start.isoformat()}'
        )
    expected_namespaces = tuple(sorted({
        str(namespace).strip()
        for namespace in (monitored_namespaces or _load_monitored_namespaces())
        if str(namespace).strip()
    }))
    bundle_namespaces = tuple(sorted({
        str(namespace).strip()
        for namespace in (metadata.get('monitored_namespaces') or ())
        if str(namespace).strip()
    }))
    if bundle_namespaces != expected_namespaces:
        mismatches.append(
            f'monitored_namespaces={list(bundle_namespaces)} '
            f'expected={list(expected_namespaces)}'
        )
    expected_contract_hash = namespace_contract_hash(expected_namespaces)
    if metadata.get('namespace_contract_hash') != expected_contract_hash:
        mismatches.append(
            f'namespace_contract_hash={metadata.get("namespace_contract_hash")} '
            f'expected={expected_contract_hash}'
        )
    if mismatches:
        raise RuntimeError('incompatible replay threshold bundle: ' + '; '.join(mismatches))

    thresholds = {
        (str(row['namespace']), int(row['day_of_week'])): {
            'value': float(row['value']),
            'samples': int(row['samples']),
        }
        for row in bundle.get('thresholds', [])
    }
    caps = {
        str(namespace): {
            'value': float(row['value']),
            'samples': int(row['samples']),
        }
        for namespace, row in (bundle.get('caps') or {}).items()
    }
    bundle_id = str(bundle.get('bundle_id') or '')
    if not bundle_id or not thresholds or not caps:
        raise RuntimeError('replay threshold bundle is incomplete')
    peak_detector.load_thresholds_direct(
        thresholds,
        caps,
        snapshot_id=bundle_id,
    )
    return metadata


def run_regular_phase(
    window_minutes: int = 15,
    dry_run: bool = False,
    output_dir: str = None,
    replay_window_end: Optional[datetime] = None,
    audit_only: bool = False,
    replay_thresholds_json: Optional[Path] = None,
    replay_evaluate_policy: bool = False,
    replay_prior_episodes_json: Optional[Path] = None,
) -> dict:
    """
    Main regular phase function.
    
    Processes last N minutes of data and updates registry.
    """
    if replay_window_end is not None and window_minutes != 15:
        raise ValueError('historical replay requires window_minutes=15')
    if replay_window_end is not None and not dry_run:
        raise ValueError('historical replay requires dry_run=True')
    if audit_only and not dry_run:
        raise ValueError('audit_only requires dry_run=True')
    if replay_evaluate_policy and (
        not dry_run or replay_window_end is None or audit_only
    ):
        raise ValueError(
            'replay_evaluate_policy requires historical dry-run mode without audit-only'
        )
    if replay_thresholds_json is not None and (
        replay_window_end is None
        or not dry_run
        or (not audit_only and not replay_evaluate_policy)
    ):
        raise ValueError(
            'replay_thresholds_json requires historical dry-run audit or policy replay mode'
        )
    if replay_prior_episodes_json is not None and not replay_evaluate_policy:
        raise ValueError(
            'replay_prior_episodes_json requires replay_evaluate_policy'
        )
    now, window_start, window_end = _resolve_regular_window(
        window_minutes,
        replay_window_end,
    )
    
    print("=" * 70)
    print("🚀 REGULAR PHASE - 15-minute Pipeline")
    print(f"   Started: {_format_utc_local(now)}")
    print("=" * 70)
    
    print(f"\n📅 Window UTC: {window_start.strftime('%Y-%m-%dT%H:%M:%SZ')} → {window_end.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"   Window Prague: {_fmt_prague(window_start, '%Y-%m-%d %H:%M:%S')} → {_fmt_prague(window_end, '%Y-%m-%d %H:%M:%S')}")
    
    result = {
        'status': 'error',
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'error_count': 0,
        'expected_count': None,
        'fetched_count': 0,
        'fetch_complete': False,
        'incidents': 0,
        'saved': 0,
        'namespace_peak_audit': [],
    }
    
    # ==========================================================================
    # LOAD REGISTRY
    # ==========================================================================
    registry = init_registry()
    print(f"📋 Registry: {len(registry.fingerprint_index)} known fingerprints")
    registry_before = _registry_snapshot(registry)

    # Lifecycle evidence is INFO-level and independent of the ERROR pipeline.
    # Its own persistence/alerting contract is fail-closed, so a diagnostic
    # failure must not prevent normal peak collection from continuing.
    try:
        lifecycle_result = run_workflow_lifecycle_diagnostics(
            window_start,
            window_end,
            get_db_connection,
            dry_run=dry_run,
        )
        result['workflow_lifecycle'] = lifecycle_result
        lifecycle_status = lifecycle_result.get('status', 'unknown')
        print(f"🔄 Workflow lifecycle diagnostic: {lifecycle_status}")
        if lifecycle_result.get('error'):
            print(f"⚠️ Workflow lifecycle diagnostic failed closed: {lifecycle_result['error']}")
    except Exception as e:
        result['workflow_lifecycle'] = {
            'status': 'failed',
            'error': _one_line_error(e),
            'alerted': [],
        }
        print(f"⚠️ Workflow lifecycle diagnostic failed closed: {_one_line_error(e)}")
    
    # ==========================================================================
    # FETCH DATA
    # ==========================================================================
    aggregator = StreamingAggregator()
    try:
        errors = fetch_unlimited(
            window_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            page_consumer=aggregator.ingest_page,
            collect_results=False,
        )
    except Exception:
        aggregator.close()
        raise
    
    if errors is None:
        aggregator.close()
        print("❌ Fetch failed")
        result['status'] = 'error'
        result['error'] = 'Fetch returned None'
        return result

    result['expected_count'] = LAST_FETCH_STATS.get('expected')
    result['fetched_count'] = LAST_FETCH_STATS.get('fetched', aggregator.total_records)
    result['fetch_complete'] = bool(LAST_FETCH_STATS.get('complete'))

    if not result['fetch_complete']:
        aggregator.close()
        reason = LAST_FETCH_STATS.get('reason') or 'source count did not reconcile'
        print(f"❌ Fetch incomplete: {reason}")
        result['status'] = 'error'
        result['error'] = f'Fetch incomplete: {reason}'
        return result

    monitored_namespaces = _load_monitored_namespaces()
    run_id = (
        f"regular-{window_start.strftime('%Y%m%d-%H%M')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    
    if aggregator.total_records == 0:
        aggregator.close()
        collection = IncidentCollection(
            run_id=run_id,
            run_timestamp=now,
            pipeline_version=os.getenv('IMAGE_TAG', '1.0'),
            input_records=0,
            time_range_start=window_start,
            time_range_end=window_end,
        )
        collection.namespace_peak_decisions = [
            decision.to_dict()
            for decision in materialize_decision_windows(
                [],
                monitored_namespaces,
                window_starts=[window_start],
                stream_key='live',
                contract_hash=namespace_contract_hash(monitored_namespaces),
                run_id=run_id,
            )
        ]
        try:
            from core.peak_episode import materialize_episode_state
            prior_episodes = []
            if replay_prior_episodes_json is not None:
                prior_episodes = json.loads(
                    replay_prior_episodes_json.read_text(encoding='utf-8')
                )
            elif not dry_run:
                prior_episodes = load_peak_episodes_before(
                    get_db_connection,
                    stream_key='live',
                    before_window_start=window_start,
                )
            collection.peak_episodes, collection.peak_episode_transitions = (
                materialize_episode_state(
                    collection.namespace_peak_decisions,
                    [],
                    resolve_non_peak_windows=int(
                        os.getenv('EPISODE_RESOLVE_NON_PEAK_WINDOWS', '2')
                    ),
                    prior_episodes=prior_episodes,
                )
            )
            result['peak_episodes'] = collection.peak_episodes
            result['peak_episode_transitions'] = collection.peak_episode_transitions
        except Exception as e:
            print(f"❌ No-data episode materialization failed: {_one_line_error(e)}")
            result['status'] = 'error'
            result['error'] = str(e)
            return result
        if not dry_run:
            try:
                persistence = persist_analysis_run(
                    connection_factory=get_db_connection,
                    collection=collection,
                    run_type='regular',
                    window_start=window_start,
                    window_end=window_end,
                    monitored_namespaces=monitored_namespaces,
                    expected_count=LAST_FETCH_STATS.get('expected'),
                    fetched_count=0,
                    source_index=INDICES,
                )
                result.update(persistence)
            except Exception as e:
                print(f"❌ No-data run persistence failed: {_one_line_error(e)}")
                result['status'] = 'error'
                result['error'] = str(e)
                return result
        print("⚪ No errors in window; complete zero facts persisted")
        result['status'] = 'no_data'
        return result
    
    result['error_count'] = aggregator.total_records
    print(f"   📥 Fetched {aggregator.total_records:,} errors")
    # OOM guard: když fetch ořízl data (extrémní okno), report to dolů.
    if LAST_FETCH_STATS.get('truncated'):
        result['truncated'] = True
        result['truncated_reason'] = LAST_FETCH_STATS.get('reason')
        result['expected_total'] = LAST_FETCH_STATS.get('expected')
        print(f"   ⚠️ PARTIAL data: {LAST_FETCH_STATS.get('reason')} — counts are a lower bound")
    
    known_peaks_snapshot = dict(registry.peaks) if registry else {}

    # ==========================================================================
    # LOAD HISTORICAL BASELINE FROM DB
    # ==========================================================================
    historical_baseline = {}
    namespace_fingerprint_baselines = {}
    namespace_fingerprint_baseline_available = False
    try:
        db_conn = get_db_connection(read_only=True)
        baseline_loader = BaselineLoader(db_conn)
        
        if aggregator.total_records:
            fingerprints = list(aggregator.acc)
            if fingerprints:
                historical_baseline = baseline_loader.load_fingerprint_rates(
                    fingerprints=fingerprints,
                    analysis_window_start=window_start,
                    lookback_days=7,
                    min_samples=3
                )
                namespace_fingerprint_baselines = baseline_loader.load_namespace_fingerprint_rates(
                    namespace_fingerprints=[
                        (namespace, fingerprint)
                        for fingerprint, accumulator in aggregator.acc.items()
                        for namespace in accumulator.ns_bucket_counts
                    ],
                    analysis_window_start=window_start,
                    lookback_days=7,
                    min_samples=3,
                )
                namespace_fingerprint_baseline_available = True
                print(f"   📊 Loaded baseline for {len(historical_baseline)}/{len(fingerprints)} fingerprints")
                print(
                    "   📊 Loaded namespace fingerprint baseline for "
                    f"{len(namespace_fingerprint_baselines)} pairs"
                )
        
        db_conn.close()
    except Exception as e:
        print(f"   ⚠️ Baseline loading failed (non-blocking): {_one_line_error(e)}")
        historical_baseline = {}

    # ==========================================================================
    # RUN PIPELINE
    # ==========================================================================
    # Pxx/CAP peak detection (replaces EWMA/MAD for spike detection)
    peak_detector = None
    try:
        from core.peak_detection import PeakDetector
        if replay_thresholds_json is not None:
            peak_detector = PeakDetector()
            threshold_metadata = _load_replay_threshold_bundle(
                peak_detector,
                replay_thresholds_json,
                window_start,
                monitored_namespaces,
            )
            result['threshold_source'] = 'replay_memory_bundle'
            result['threshold_bundle'] = threshold_metadata
            print("   Pxx/CAP peak detector loaded from read-only replay bundle")
        else:
            peak_db_conn = get_db_connection(read_only=True)
            peak_detector = PeakDetector(conn=peak_db_conn)
            result['threshold_source'] = 'database_snapshot'
            print("   Pxx/CAP peak detector loaded")
    except Exception as e:
        result['status'] = 'error'
        result['error'] = (
            'Pxx/CAP peak detector initialization failed: '
            f'{_one_line_error(e)}'
        )
        print(f"❌ {result['error']}")
        aggregator.close()
        return result

    try:
        pipeline = Pipeline(
            ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
            peak_detector=peak_detector,
            monitored_namespaces=monitored_namespaces,
            stream_key='live',
            namespace_contract_hash=namespace_contract_hash(monitored_namespaces),
            build_trace_patterns=not audit_only,
        )

        pipeline.phase_b.historical_baseline = historical_baseline
        pipeline.phase_c.namespace_fingerprint_baselines = namespace_fingerprint_baselines
        pipeline.phase_c.namespace_fingerprint_baseline_available = (
            namespace_fingerprint_baseline_available
        )

        # ← KRITICKÉ: Inject registry do Phase C (aby mohl dělat is_problem_key_known lookup!)
        pipeline.phase_c.registry = registry
        pipeline.phase_c.known_fingerprints = registry.get_all_known_fingerprints().copy()

        collection = pipeline.run_streaming(aggregator, run_id=run_id)
        result['namespace_peak_audit'] = pipeline.phase_c.namespace_peak_audit
        result['family_baseline_available'] = namespace_fingerprint_baseline_available
        result['family_baseline_pairs'] = len(namespace_fingerprint_baselines)
    finally:
        aggregator.close()

    result['incidents'] = collection.total_incidents
    result['spike_incidents'] = [
        {
            'fingerprint': incident.fingerprint,
            'error_type': incident.error_type,
            'normalized_message': incident.normalized_message[:500],
            'apps': sorted(incident.apps),
            'namespaces': sorted(incident.namespaces),
            'current_count': incident.stats.current_count,
            'namespace_event_counts': incident.namespace_event_counts,
            'evidence': [
                evidence.to_dict()
                for evidence in incident.evidence
                if evidence.rule == 'spike_p93_cap'
            ],
        }
        for incident in collection.incidents
        if incident.flags.is_spike
    ]
    if audit_only:
        result['status'] = 'success'
        return result

    # #3: pro reprezentativní trace top problémů dotáhni VŠECHNY levely (WARN/INFO
    # před ERROR) a přepočítej root cause/propagaci z bohatší časové osy. Opt-in
    # (REP_TRACE_CONTEXT=1) – dělá extra ES dotaz jen na pár reprezentativních trace.
    if os.getenv('REP_TRACE_CONTEXT', '0').strip().lower() in {'1', 'true', 'yes', 'on'}:
        _patterns = getattr(collection, 'trace_patterns', None)
        if _patterns:
            try:
                from analysis.trace_timeline import enrich_patterns_with_trace_context
                _lookback = int(os.getenv('REP_TRACE_CONTEXT_LOOKBACK_MIN', '5'))
                _ctx_from = window_start - timedelta(minutes=max(0, _lookback))
                enrich_patterns_with_trace_context(
                    _patterns,
                    fetch_trace_context,
                    _ctx_from.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    window_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    top_n=int(os.getenv('REP_TRACE_CONTEXT_TOPN', '10')),
                )
                print("   ✅ Enriched representative traces with full-level context (#3)")
            except Exception as e:
                print(f"   ⚠️ Trace context enrichment failed (non-blocking): {_one_line_error(e)}")

    try:
        cause_analysis = build_collection_cause_analysis(collection)
        print(
            f"   ✅ Built {len(cause_analysis.families)} reconciled cause families "
            f"from {cause_analysis.source_raw_error_lines:,} ERROR lines"
        )
    except Exception as e:
        print(f"❌ Cause-family analysis failed: {_one_line_error(e)}")
        result['status'] = 'error'
        result['error'] = str(e)
        return result

    try:
        from core.peak_episode import materialize_episode_state
        prior_episodes = []
        if replay_prior_episodes_json is not None:
            try:
                prior_episodes = json.loads(
                    replay_prior_episodes_json.read_text(encoding='utf-8')
                )
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError(
                    f'cannot load replay prior episodes: {error}'
                ) from error
        elif not dry_run:
            try:
                prior_episodes = load_peak_episodes_before(
                    get_db_connection,
                    stream_key='live',
                    before_window_start=window_start,
                )
            except Exception as error:
                print(
                    '⚠️ Historical episode state unavailable; '
                    f'continuing with current run only: {_one_line_error(error)}'
                )
        collection.peak_episodes, collection.peak_episode_transitions = (
            materialize_episode_state(
                collection.namespace_peak_decisions,
                [family.to_dict() for family in cause_analysis.families],
                resolve_non_peak_windows=int(os.getenv('EPISODE_RESOLVE_NON_PEAK_WINDOWS', '2')),
                escalation_ratio=float(os.getenv('EPISODE_ESCALATION_RATIO', '1.5')),
                prior_episodes=prior_episodes,
            )
        )
        result['peak_episodes'] = collection.peak_episodes
        result['peak_episode_transitions'] = collection.peak_episode_transitions
    except Exception as e:
        print(f"❌ Peak episode correlation failed: {_one_line_error(e)}")
        result['status'] = 'error'
        result['error'] = str(e)
        return result

    if not dry_run:
        try:
            persistence = persist_analysis_run(
                connection_factory=get_db_connection,
                collection=collection,
                run_type='regular',
                window_start=window_start,
                window_end=window_end,
                monitored_namespaces=monitored_namespaces,
                expected_count=LAST_FETCH_STATS.get('expected'),
                fetched_count=result['error_count'],
                source_index=INDICES,
            )
            result.update(persistence)
            result['saved'] = persistence['incident_rows']
            print(
                f"\n💾 Committed complete run: {persistence['persisted_events']:,} events, "
                f"{persistence['fact_rows']:,} facts, "
                f"{persistence['namespace_rows']:,} namespace rows, "
                f"{persistence['incident_rows']:,} incidents, "
                f"{persistence['cause_family_rows']:,} cause families"
            )
        except Exception as e:
            print(f"❌ Run persistence failed: {_one_line_error(e)}")
            result['status'] = 'error'
            result['error'] = str(e)
            return result
    
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
    # UPDATE REGISTRY
    # ==========================================================================
    if collection.incidents and not dry_run:
        if not registry.update_and_save(collection.incidents, event_timestamps):
            print("❌ Registry update failed after database commit")
            result['status'] = 'error'
            result['error'] = 'Registry update failed after database commit'
            return result
        
        stats = registry.get_stats()
        print(f"\n📝 Registry updated:")
        print(f"   New problems: {stats['new_problems_added']}")
        print(f"   New peaks: {stats['new_peaks_added']}")

        registry_after = _registry_snapshot(registry)
        print("\n✅ VALIDATOR - Added data in this regular run:")
        print(f"   Window: {_fmt_prague(window_start, '%Y-%m-%d %H:%M:%S')} → {_fmt_prague(window_end, '%H:%M:%S')} Prague")
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
            trace_pattern_index=getattr(collection, 'trace_pattern_index', None),
            trace_timelines=getattr(collection, 'trace_timelines', None),
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
        if output_dir and not dry_run:
            report_files = generator.save_reports(output_dir, prefix="problem_report_15min")
            print(f"\n📄 Problem reports saved:")
            print(f"   Text: {report_files.get('text')}")
            print(f"   JSON: {report_files.get('json')}")

    elif collection.incidents and HAS_INCIDENT_ANALYSIS:
        # Fallback: Legacy incident analysis
        print("\n🔍 Running Incident Analysis (legacy)...")

        report_dir = output_dir or (SCRIPT_DIR / 'reports')
        report_output_dir = None if dry_run else str(report_dir)
        report = run_incident_analysis(
            collection, window_start, window_end, report_output_dir
        )

        # Print summary only (not full report for 15min runs)
        lines = report.split('\n')[:30]
        for line in lines:
            print(line)

    result['status'] = 'success'

    # ==========================================================================
    # WRITE-BACK ENRICHMENT TO REGISTRY
    # ==========================================================================
    if enriched_problems and _registry is not None and not dry_run:
        problem_enrichment_updates: Dict[str, Dict[str, Any]] = {}
        for pkey, aggregate in enriched_problems.items():
            if pkey not in _registry.problems:
                continue
            entry = _registry.problems[pkey]
            updates: Dict[str, Any] = {}

            # Write-back root_cause from trace analysis (highest priority)
            rc = getattr(aggregate, 'root_cause', None)
            trc = getattr(aggregate, 'trace_root_cause', None)
            if trc and isinstance(trc, dict) and trc.get('message'):
                svc = trc.get('service', '')
                msg = trc.get('message', '')
                new_rc = f"{svc}: {msg}" if svc else msg
                if new_rc and new_rc != entry.root_cause:
                    updates['root_cause'] = new_rc[:500]
            elif rc and hasattr(rc, 'message') and rc.message:
                new_rc = f"{rc.service}: {rc.message}" if rc.service else rc.message
                if new_rc and new_rc != entry.root_cause:
                    updates['root_cause'] = new_rc[:500]

            # Write-back behavior from problem-level behavior summary
            if aggregate.trace_flow_summary:
                behavior_msg = _summarize_behavior_steps(aggregate.trace_flow_summary, limit=3)
                if behavior_msg and behavior_msg != entry.behavior:
                    # Strip stack frames before storing (operator-friendly).
                    from core.problem_registry import _strip_stack_trace_for_storage
                    updates['behavior'] = _strip_stack_trace_for_storage(behavior_msg)[:500]

            # Write-back severity and score
            if aggregate.max_severity and aggregate.max_severity != 'info':
                if entry.enriched_severity != aggregate.max_severity:
                    updates['enriched_severity'] = aggregate.max_severity
            if aggregate.max_score > 0:
                if entry.enriched_score != aggregate.max_score:
                    updates['enriched_score'] = aggregate.max_score

            if updates:
                problem_enrichment_updates[pkey] = updates

        if problem_enrichment_updates:
            if not _registry.merge_enrichment_and_save(
                problem_enrichment_updates, {}
            ):
                print("❌ Registry enrichment merge failed")
                result['status'] = 'error'
                result['error'] = 'Registry enrichment merge failed'
                return result
            print(
                f"\n📝 Registry enrichment merged for "
                f"{len(problem_enrichment_updates)} problems"
            )

    # ==========================================================================
    # EXPORT TABLES (CSV, MD, JSON)
    # ==========================================================================
    if HAS_EXPORTS and _registry is not None and not dry_run:
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
    if collection.incidents and (not dry_run or replay_evaluate_policy):
        try:
            # Detect peaks: spike OR burst OR high-score anomalies
            peaks_detected = sum(
                1 for inc in collection.incidents
                if (inc.flags.is_spike or inc.flags.is_burst or 
                    getattr(inc, 'score', 0) >= 70)
            )

            # --- r77: Diagnostic summary (always logged for observability) ---
            _ep_count = len(enriched_problems) if enriched_problems else 0
            print(f"\n🔍 Peak gate: peaks_detected={peaks_detected}, enriched_problems={_ep_count}, "
                  f"peak_detector={'loaded' if peak_detector else 'NONE'}")
            if peaks_detected > 0 and not enriched_problems:
                print(f"   ⚠️ ALERT BLOCKED: peaks detected but enriched_problems is empty!")
            elif peaks_detected == 0 and collection.total_incidents > 0:
                print(f"   ℹ️ No peaks among {collection.total_incidents} incidents (no spike/burst/score>=70)")

            if peaks_detected > 0 and enriched_problems:
                max_alerts = int(os.getenv('MAX_PEAK_ALERTS_PER_WINDOW', '3'))
                digest_raw = os.getenv('ALERT_DIGEST_ENABLED', 'true').strip().lower()
                digest_enabled = digest_raw not in {'0', 'false', 'no', 'off'}
                
                # Select ALL peak problems (no limit), then cluster
                peak_problems = _select_peak_problems(enriched_problems, limit=0)
                all_peak_apps = sorted({
                    app
                    for problem in peak_problems
                    for app in (getattr(problem, 'apps', None) or [])
                    if app
                })
                all_peak_namespaces = sorted({
                    namespace
                    for problem in peak_problems
                    for namespace in (getattr(problem, 'namespaces', None) or [])
                    if namespace
                })
                clusters = _merge_peak_clusters(peak_problems)
                print(f"ℹ️ Peak problems: {len(peak_problems)} → {len(clusters)} correlated alert(s)")

                sent_alerts = 0
                suppressed_alerts = 0
                delivery_outcomes: List[Dict[str, Any]] = []
                alert_state = _load_alert_state(registry)
                alert_peaks = alert_state.get('peaks', {})
                now_utc = datetime.now(timezone.utc)
                cooldown_min = int(os.getenv('ALERT_COOLDOWN_MIN', '45'))
                policy_payloads: List[Dict[str, Any]] = []
                policy_candidates: List[Dict[str, Any]] = []
                episode_transitions = list(
                    getattr(collection, 'peak_episode_transitions', None) or []
                )

                for cluster in clusters:
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

                    _attach_authoritative_cause_families(payload, cause_analysis)

                    peak_key = payload.get('peak_key', '')
                    alert_identity = _alert_identity(payload)
                    state_entry = (
                        alert_peaks.get(alert_identity, {})
                        if alert_identity else {}
                    )
                    should_send, reason = _should_send_peak_alert(payload, state_entry, now_utc)

                    episode_contexts = _episode_policy_contexts(
                        payload,
                        episode_transitions,
                    )
                    if not episode_contexts:
                        episode_contexts = [None]

                    # Trend override: if no alert was sent to user recently,
                    # this is effectively the "first alert" → always "rising"
                    last_sent = _parse_dt(state_entry.get('last_sent_at'))
                    if not last_sent or (now_utc - last_sent) > timedelta(minutes=window_minutes * 2):
                        if payload.get('trend') and payload['trend'] != 'rising':
                            print(
                                f"ℹ️ Trend override for {alert_identity}: "
                                f"{payload['trend']} → rising (first alert)"
                            )
                            payload['trend'] = 'rising'

                    payload['send_reason'] = reason
                    policy_payloads.append(payload)
                    for episode_context in episode_contexts:
                        if episode_context:
                            episode_state = str(
                                episode_context.get('state') or 'CONTINUATION'
                            )
                        elif not state_entry:
                            episode_state = 'START'
                        elif payload.get('new_namespaces'):
                            episode_state = 'EXPANSION'
                        elif reason in {
                            'trend_changed',
                            'count_delta',
                            'scope_changed',
                            'heartbeat',
                        } or reason.startswith('count_delta_'):
                            episode_state = 'ESCALATION'
                        else:
                            episode_state = 'CONTINUATION'

                        candidate_id = (
                            episode_context.get('episode_id')
                            if episode_context else
                            alert_identity or peak_key or payload.get('window_key', '')
                        )
                        window_decision_id = str(
                            episode_context.get('window_decision_id')
                            if episode_context else
                            f"{payload.get('window_key', '')}:{candidate_id}"
                        )
                        material_change_reasons = (
                            list(episode_context.get('material_change_reasons') or [])
                            if episode_context
                            and episode_context.get('material_change_reasons')
                            else [reason]
                            if should_send and reason not in {'first_seen_in_state', 'new_peak'}
                            else []
                        )
                        cause_family = payload.get('cause_family') or {}
                        if episode_context:
                            cause_family = next(
                                (
                                    family
                                    for family in (payload.get('cause_families') or [])
                                    if family.get('signature') == episode_context.get(
                                        'cause_signature'
                                    )
                                ),
                                cause_family,
                            )
                        policy_candidates.append({
                            'episode_id': str(candidate_id),
                            'window_decision_id': window_decision_id,
                            'stream_key': 'live',
                            'episode_state': episode_state,
                            'assessment': cause_family.get('assessment', 'unknown'),
                            'confidence': cause_family.get('confidence', 'low'),
                            'namespace_ratio': max(
                                (
                                    float(item.get('observed_value') or 0)
                                    / float(item.get('effective_threshold') or 1)
                                )
                                for item in (payload.get('threshold_evidence') or [])
                                if float(item.get('effective_threshold') or 0) > 0
                            ) if any(
                                float(item.get('effective_threshold') or 0) > 0
                                for item in (payload.get('threshold_evidence') or [])
                            ) else 0,
                            'unique_operation_occurrences': cause_family.get(
                                'unique_operations'
                            ),
                            'material_change_reasons': material_change_reasons,
                            'no_material_change': reason == 'no_material_change',
                            'no_material_change_reason': reason,
                            'test_originator_application': payload.get(
                                'test_originator_application', ''
                            ),
                            '_payload': payload,
                            '_policy_context_available': bool(episode_context),
                        })
                        payload.setdefault('policy_episode_states', []).append(
                            episode_state
                        )
                        payload.setdefault('material_change_reasons', []).extend(
                            material_change_reasons
                        )
                        payload.setdefault('policy_candidate_reasons', {})[
                            str(candidate_id)
                        ] = reason
                        if 'policy_episode_state' not in payload:
                            payload['policy_episode_state'] = episode_state
                            payload['policy_candidate_reason'] = reason
                notification_decisions = decide_notification_candidates(
                    policy_candidates,
                    detail_limit=max_alerts,
                )
                payload_by_candidate_id = {
                    candidate['episode_id']: candidate['_payload']
                    for candidate in policy_candidates
                }
                context_by_candidate_id = {
                    candidate['episode_id']: candidate['_policy_context_available']
                    for candidate in policy_candidates
                }
                dispatch_payloads: List[Dict[str, Any]] = []
                digest_payloads: List[Dict[str, Any]] = []
                dispatch_payload_ids = set()
                digest_payload_ids = set()
                policy_summary = {
                    'candidates': len(notification_decisions),
                    'primary_send': 0,
                    'digest_only': 0,
                    'route_suppressed': 0,
                    'no_material_change': 0,
                }
                for decision in notification_decisions:
                    payload = payload_by_candidate_id[decision.episode_id]
                    payload.setdefault('notification_decision_ids', []).append(
                        decision.notification_decision_id
                    )
                    payload.setdefault('policy_outcomes_by_decision', {})[
                        decision.notification_decision_id
                    ] = decision.policy_outcome
                    payload.setdefault('policy_candidate_reasons', {})[
                        decision.notification_decision_id
                    ] = decision.candidate_reason
                    payload['notification_decision_id'] = payload[
                        'notification_decision_ids'
                    ][0]
                    payload['policy_outcome'] = decision.policy_outcome
                    payload['policy_detail_rank'] = decision.detail_rank
                    payload['policy_detail_limit'] = decision.detail_limit
                    payload['test_origin_label'] = decision.test_origin_label
                    policy_summary[decision.policy_outcome] += 1
                    if decision.policy_outcome == 'primary_send':
                        payload_id = id(payload)
                        if payload_id not in dispatch_payload_ids:
                            dispatch_payloads.append(payload)
                            dispatch_payload_ids.add(payload_id)
                        if payload_id not in digest_payload_ids:
                            digest_payloads.append(payload)
                            digest_payload_ids.add(payload_id)
                    elif decision.policy_outcome == 'digest_only':
                        payload_id = id(payload)
                        if payload_id not in digest_payload_ids:
                            digest_payloads.append(payload)
                            digest_payload_ids.add(payload_id)
                    else:
                        suppressed_alerts += 1

                for payload in policy_payloads:
                    if not any(
                        id(payload) == id(candidate)
                        for candidate in dispatch_payloads + digest_payloads
                    ):
                        delivery_outcomes.extend(
                            _policy_delivery_outcomes(
                                payload,
                                'not_attempted',
                                'all_episode_candidates_suppressed',
                            )
                        )

                missing_context_count = sum(
                    not context_by_candidate_id[decision.episode_id]
                    for decision in notification_decisions
                )
                if missing_context_count:
                    result['status'] = 'error'
                    result['error'] = (
                        'Notification policy context missing for '
                        f'{missing_context_count} candidate(s)'
                    )
                    print(f"❌ {result['error']}")
                    return result
                persistable_decisions = [
                    decision.to_dict() for decision in notification_decisions
                ]
                if not dry_run:
                    try:
                        persist_notification_decisions(
                            get_db_connection,
                            persistable_decisions,
                        )
                    except Exception as e:
                        result['status'] = 'error'
                        result['error'] = (
                            'Notification decision persistence failed: '
                            f'{_one_line_error(e)}'
                        )
                        print(f"❌ {result['error']}")
                        return result
                result['notification_policy'] = policy_summary
                result['notification_decisions'] = persistable_decisions

                digest_summary = {
                    'raw_window_errors': int(result.get('error_count', 0) or 0),
                    'detected_peak_problems': len(peak_problems),
                    'suppressed_alerts': suppressed_alerts,
                    'omitted_alerts': 0,
                    'max_alerts': max_alerts,
                    'affected_apps': all_peak_apps,
                    'affected_namespaces': all_peak_namespaces,
                    'notification_policy': policy_summary,
                }

                peak_enrichment_updates: Dict[str, Dict[str, Any]] = {}
                for payload in dispatch_payloads:
                    peak_key = payload.get('peak_key', '')
                    if not peak_key or peak_key not in registry.peaks:
                        continue
                    peak_entry = registry.peaks[peak_key]
                    updates: Dict[str, Any] = {}
                    root_cause = str(payload.get('root_cause_text', '') or '')
                    behavior = str(payload.get('behavior_text', '') or '')
                    if root_cause and root_cause != peak_entry.root_cause:
                        updates['root_cause'] = root_cause[:500]
                    if behavior and behavior != peak_entry.behavior:
                        updates['behavior'] = behavior[:500]
                    if updates:
                        peak_enrichment_updates[peak_key] = updates

                if not dry_run and peak_enrichment_updates:
                    if not registry.merge_enrichment_and_save(
                        {}, peak_enrichment_updates
                    ):
                        print("❌ Peak registry enrichment merge failed")
                        result['status'] = 'error'
                        result['error'] = 'Peak registry enrichment merge failed'
                        return result

                if replay_evaluate_policy:
                    replay_payloads = []
                    replay_payload_ids = set()
                    for payload in dispatch_payloads + digest_payloads:
                        payload_id = id(payload)
                        if payload_id in replay_payload_ids:
                            continue
                        replay_payload_ids.add(payload_id)
                        replay_payloads.extend(
                            _policy_delivery_outcomes(
                                payload,
                                'not_attempted',
                                'historical_replay',
                            )
                        )
                    delivered_payloads = PeakDispatchResult([], replay_payloads)
                else:
                    delivered_payloads = _dispatch_peak_alerts(
                        window_start,
                        window_end,
                        dispatch_payloads,
                        digest_enabled,
                        digest_summary,
                        digest_payloads=digest_payloads,
                    )
                delivery_outcomes.extend(delivered_payloads.delivery_outcomes)
                result['delivery_outcomes'] = delivery_outcomes
                if delivery_outcomes and not dry_run:
                    try:
                        persist_notification_deliveries(
                            get_db_connection,
                            delivery_outcomes,
                            notification_type='regular_peak',
                            run_id=run_id,
                            window_start=window_start,
                        )
                    except Exception as e:
                        result['status'] = 'error'
                        result['error'] = f'Delivery audit persistence failed: {_one_line_error(e)}'
                        print(f"❌ {result['error']}")
                        return result

                sent_alerts = len(delivered_payloads)
                _record_delivered_peak_alerts(
                    registry,
                    delivered_payloads,
                    now_utc,
                    cooldown_min,
                )

                delivered_keys = {
                    outcome['dedup_key']
                    for outcome in delivery_outcomes
                    if outcome.get('status') == 'delivered'
                }
                failed_keys = {
                    outcome['dedup_key']
                    for outcome in delivery_outcomes
                    if outcome.get('status') == 'failed'
                } - delivered_keys
                if failed_keys:
                    result['status'] = 'error'
                    result['error'] = (
                        f'{len(failed_keys)} peak alert payload(s) had no successful destination'
                    )
                    result['delivery_status'] = 'failed'
                elif any(
                    outcome.get('status') == 'failed'
                    for outcome in delivery_outcomes
                ):
                    result['delivery_status'] = 'partial'
                elif replay_evaluate_policy:
                    result['delivery_status'] = 'not_attempted'
                elif sent_alerts:
                    result['delivery_status'] = 'complete'
                elif suppressed_alerts:
                    result['delivery_status'] = 'suppressed'
                else:
                    result['delivery_status'] = 'skipped'

                print(f"✅ Peak alerts dispatched: {sent_alerts}/{len(peak_problems)} (suppressed: {suppressed_alerts})")

            # --- r77: Always record peak gate outcome in result ---
            result['peak_gate'] = {
                'peaks_detected': peaks_detected,
                'enriched_problems': _ep_count,
                'peak_detector_loaded': peak_detector is not None,
            }
                    
        except Exception as e:
            print(f"⚠️ Peak alert failed: {e}")
    
    return result


# =============================================================================
# CLEANUP
# =============================================================================

def cleanup():
    """Registry writes happen only in the post-commit transaction."""


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
    def parse_replay_window_end(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                'must be an ISO-8601 UTC timestamp, for example 2026-09-22T03:45:00Z'
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise argparse.ArgumentTypeError('must include a UTC offset or Z suffix')
        return parsed

    parser = argparse.ArgumentParser(description='Regular Phase - 15-minute Pipeline')
    parser.add_argument('--window', type=int, default=15, help='Window size in minutes (default: 15)')
    parser.add_argument('--dry-run', action='store_true', help='No DB writes')
    parser.add_argument('--output', type=str, help='Output directory for reports')
    parser.add_argument(
        '--replay-window-end',
        type=parse_replay_window_end,
        help='UTC end of a historical replay; requires --dry-run',
    )
    parser.add_argument(
        '--audit-only',
        action='store_true',
        help='Stop after detector evidence is collected; requires --dry-run',
    )
    parser.add_argument(
        '--replay-evaluate-policy',
        action='store_true',
        help='Evaluate episodes and notification policy without DB writes or delivery',
    )
    parser.add_argument(
        '--replay-prior-episodes-json',
        type=Path,
        help='Read prior episode state for a chained historical replay window',
    )
    parser.add_argument(
        '--result-json',
        type=Path,
        help='Write the structured run result to this JSON file',
    )
    parser.add_argument(
        '--replay-thresholds-json',
        type=Path,
        help='Read-only in-memory thresholds for historical audit replay',
    )
    
    args = parser.parse_args()
    if args.replay_window_end is not None and not args.dry_run:
        parser.error('--replay-window-end requires --dry-run')
    if args.audit_only and not args.dry_run:
        parser.error('--audit-only requires --dry-run')
    if args.replay_evaluate_policy and (
        not args.dry_run or args.replay_window_end is None or args.audit_only
    ):
        parser.error(
            '--replay-evaluate-policy requires --replay-window-end, --dry-run, and no --audit-only'
        )
    if args.replay_prior_episodes_json is not None and not args.replay_evaluate_policy:
        parser.error('--replay-prior-episodes-json requires --replay-evaluate-policy')
    if args.replay_thresholds_json is not None and (
        args.replay_window_end is None
        or not args.dry_run
        or (not args.audit_only and not args.replay_evaluate_policy)
    ):
        parser.error(
            '--replay-thresholds-json requires historical dry-run audit or policy replay mode'
        )
    
    result = run_regular_phase(
        window_minutes=args.window,
        dry_run=args.dry_run,
        output_dir=args.output,
        replay_window_end=args.replay_window_end,
        audit_only=args.audit_only,
        replay_thresholds_json=args.replay_thresholds_json,
        replay_evaluate_policy=args.replay_evaluate_policy,
        replay_prior_episodes_json=args.replay_prior_episodes_json,
    )
    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding='utf-8',
        )
    
    return 0 if result['status'] in ('success', 'no_data') else 1


if __name__ == '__main__':
    sys.exit(main())
