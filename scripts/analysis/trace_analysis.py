#!/usr/bin/env python3
"""
Trace Analysis - Trace-based flow analýza
==========================================

Používá trace_id k sestavení flow:
1. Seskupí incidenty podle trace_id
2. Seřadí podle timestamp
3. Vytvoří flow (služba1 → služba2 → služba3)
4. Zkrátí flow pro report (2 první + 1 poslední)


"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import Counter, defaultdict


# =============================================================================
# MESSAGE NORMALIZATION
# =============================================================================

# Patterns pro normalizaci message
_UUID_PATTERN = re.compile(
    r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'
)
_HEX_ID_PATTERN = re.compile(r'\b[0-9a-fA-F]{24,64}\b')  # Mongo IDs, trace IDs, etc.
_NUMERIC_ID_PATTERN = re.compile(r'\b(?:id|ID|Id)[=:]\s*\d+\b')  # id=12345
_TIMESTAMP_ISO_PATTERN = re.compile(
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'
)
_TIMESTAMP_EPOCH_PATTERN = re.compile(r'\b1[0-9]{9,12}\b')  # Unix timestamps

_ROOT_CAUSE_NEGATIVE_PATTERNS = [
    re.compile(r'step processing failed, context stepcontext', re.IGNORECASE),
    re.compile(r'asynchronous case processing not started', re.IGNORECASE),
    re.compile(r'an unexpected error occurred', re.IGNORECASE),
    re.compile(r'processing of step .* has failed', re.IGNORECASE),
    re.compile(r'handle fault', re.IGNORECASE),
    re.compile(r'error handled\.?$', re.IGNORECASE),
    re.compile(r'exception error handled\.?$', re.IGNORECASE),
]

_ROOT_CAUSE_POSITIVE_PATTERNS = [
    re.compile(r'called service', re.IGNORECASE),
    re.compile(r'processing errors', re.IGNORECASE),
    re.compile(r'loadbridgexmlrequest', re.IGNORECASE),
    re.compile(r'not permitted', re.IGNORECASE),
    re.compile(r'access denied|forbidden|unauthorized', re.IGNORECASE),
    re.compile(r'timeout|connection|refused', re.IGNORECASE),
    re.compile(r'sql|database|constraint', re.IGNORECASE),
    re.compile(r'resource not found', re.IGNORECASE),
    re.compile(r'token scopes|operation not allowed', re.IGNORECASE),
    re.compile(r'is not filled|not all required data|required field', re.IGNORECASE),
    re.compile(r'validation error|validation failed|invalid value|missing field|missing required|must not be null|cannot be null|nesmí mít hodnotu Null|nesmí být prázdná', re.IGNORECASE),
    re.compile(r'null pointer|npe|nullpointerexception', re.IGNORECASE),
    re.compile(r'jsonparseexception', re.IGNORECASE),
    re.compile(r'invalid user id', re.IGNORECASE),
]


_HANDLE_FAULT_MESSAGE_RE = re.compile(
    r'Handle fault\. Error:.*?message=([^,\]]+)', re.IGNORECASE
)
_SPEED_ITO_RE = re.compile(
    r'^(SPEED-\d+|ITO-\d+)#([^#]*)#([^#]*)#([^#]*)#([^#]*)#([^#]*)#([^#]*)#([^#]*)#?(.*)$'
)
_ERROR_HANDLED_RE = re.compile(r'^\w+(?:Exception|Error)\s+error\s+handled\.?$', re.IGNORECASE)
_CASE_PROCESSING_RE = re.compile(
    r'(?:an unexpected error occurred during (?:case )?step processing|'
    r'asynchronous case processing not started|'
    r'unexpected exception occurred invoking async method|'
    r'step processing (?:error|failed),?\s*context\s*stepcontext|'
    r'processing of step .* has failed)',
    re.IGNORECASE,
)


def _extract_useful_content(msg: str) -> str:
    """
    Extract the most informative part from a raw ES message.

    Rules:
    - '... error handled.' → empty (useless wrapper)
    - 'Handle fault. Error: ...message=X...' → extract X
    - Stack trace → first line only (exception: message)
    - SPEED-101/ITO codes → compact: Service#Method → HTTP_code (+ trailing detail)
    - Case processing wrappers → empty (useless)
    - Everything else → as-is
    """
    if not msg:
        return ''
    text = msg.strip()

    # 1. "XxxException error handled." → useless
    if _ERROR_HANDLED_RE.match(text):
        return ''

    # 2. Case processing wrappers → useless
    if _CASE_PROCESSING_RE.search(text):
        return ''

    # 3. Handle fault → extract message= field
    hf = _HANDLE_FAULT_MESSAGE_RE.search(text)
    if hf:
        extracted = hf.group(1).strip().rstrip(']').strip()
        if extracted and extracted.lower() not in ('null', '<null>', 'service exception'):
            return extracted
        # If message= is generic, try detail= field
        detail_match = re.search(r'detail=([^,\]]+)', text)
        if detail_match:
            detail_val = detail_match.group(1).strip().rstrip(']').strip()
            if detail_val and detail_val.lower() not in ('null', '<null>'):
                return extracted + ' / ' + detail_val if extracted else detail_val
        return extracted or ''

    # 4. SPEED-101/ITO structured codes → compact form
    sm = _SPEED_ITO_RE.match(text)
    if sm:
        prefix = sm.group(1)   # e.g. SPEED-101
        service = sm.group(6)  # e.g. CardServiceImpl
        method = sm.group(7)   # e.g. getCardDetail
        http = sm.group(8)     # e.g. 404
        trailing = sm.group(9).strip().rstrip('#').strip()  # any trailing info
        parts = []
        if service and service != 'n/a':
            parts.append(service)
        if method and method != 'n/a':
            parts.append(method)
        compact = '#'.join(parts) if parts else prefix
        if http and http != 'n/a':
            compact += f' → {http}'
        if trailing:
            compact += f' ({trailing[:120]})'
        return compact

    # 5. Stack trace → first line
    if '\n' in text:
        first_line = text.split('\n', 1)[0].rstrip()
        return first_line

    return text


def _smart_trim(msg: str, max_len: int = 250) -> str:
    """
    Smart message trim:
    - First runs _extract_useful_content to get the informative part
    - Then trims if still too long, never cutting mid-word
    """
    extracted = _extract_useful_content(msg)
    if not extracted:
        return ''
    if len(extracted) <= max_len:
        return extracted

    # Trim at last space/period before max_len
    cut_at = max_len - 3
    space_pos = extracted.rfind(' ', 0, cut_at)
    dot_pos = extracted.rfind('.', 0, cut_at)
    cut = max(space_pos, dot_pos)
    if cut > max_len // 2:
        return extracted[:cut] + '...'
    return extracted[:cut_at] + '...'


def _message_signal_score(message: str) -> int:
    """Score message informativeness. High = specific/useful, low/negative = wrapper/generic."""
    if not message:
        return 0

    score = 0
    lowered = message.lower()

    # Length bonus
    if len(lowered) >= 40:
        score += 1

    # Instant disqualify: pure wrappers
    if _ERROR_HANDLED_RE.match(message.strip()):
        return -10
    if _CASE_PROCESSING_RE.search(lowered):
        return -5

    for pattern in _ROOT_CAUSE_POSITIVE_PATTERNS:
        if pattern.search(lowered):
            score += 3

    for pattern in _ROOT_CAUSE_NEGATIVE_PATTERNS:
        if pattern.search(lowered):
            score -= 3

    return score


def normalize_message(message: str) -> str:
    """
    Normalizuje message odstraněním UUIDs, IDs a timestamps.

    Zachovává strukturu a smysl message, pouze odstraňuje variabilní části.

    Args:
        message: Původní message

    Returns:
        Normalizovaná message
    """
    if not message:
        return message

    result = message

    # 1. UUID -> <UUID>
    result = _UUID_PATTERN.sub('<UUID>', result)

    # 2. Hex IDs (24-64 chars) -> <ID>
    result = _HEX_ID_PATTERN.sub('<ID>', result)

    # 3. Numeric IDs (id=12345) -> id=<N>
    result = _NUMERIC_ID_PATTERN.sub('id=<N>', result)

    # 4. ISO timestamps -> <TS>
    result = _TIMESTAMP_ISO_PATTERN.sub('<TS>', result)

    # 5. Epoch timestamps -> <TS>
    result = _TIMESTAMP_EPOCH_PATTERN.sub('<TS>', result)

    # Cleanup: multiple spaces -> single space
    result = re.sub(r'\s+', ' ', result).strip()

    return result


def _incident_occurrence_count(incident: Any) -> int:
    if hasattr(incident, 'stats') and getattr(incident, 'stats', None):
        try:
            current_count = int(getattr(incident.stats, 'current_count', 0) or 0)
        except (TypeError, ValueError):
            current_count = 0
        if current_count > 0:
            return current_count

    trace_info = getattr(incident, 'trace_info', None)
    if trace_info:
        try:
            trace_count = int(getattr(trace_info, 'trace_count', 0) or 0)
        except (TypeError, ValueError):
            trace_count = 0
        if trace_count > 0:
            return trace_count

    raw_samples = getattr(incident, 'raw_samples', None) or []
    if raw_samples:
        return len(raw_samples)

    return 1


def _best_incident_message(incident: Any) -> str:
    """Pick the most informative message from an incident's raw_samples + normalized_message."""
    candidates: List[str] = []

    raw_samples = getattr(incident, 'raw_samples', None) or []
    for sample in raw_samples:
        text = str(sample or '').strip()
        if text:
            candidates.append(text)

    normalized = str(getattr(incident, 'normalized_message', '') or '').strip()
    if normalized:
        candidates.append(normalized)

    if not candidates:
        return ''

    # Rank by: extracted content signal > length
    def _candidate_rank(message: str) -> Tuple[int, int]:
        extracted = _extract_useful_content(message)
        if not extracted:
            return (-100, 0)
        return (_message_signal_score(extracted), len(extracted))

    return max(candidates, key=_candidate_rank)


def summarize_problem_patterns(problem: Any, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Summarize dominant message patterns across incidents in a problem.

    Uses _extract_useful_content to clean messages before grouping.
    Filters out wrappers ('... error handled.', 'Handle fault...', case processing).
    Deduplicates by normalized extracted content.
    """
    incidents = getattr(problem, 'incidents', None) or []
    if not incidents:
        return []

    pattern_map: Dict[str, Dict[str, Any]] = {}
    total_occurrences = max(1, int(getattr(problem, 'total_occurrences', 0) or 0))

    skipped_raw: List[Tuple[Any, str]] = []  # (incident, raw_message) for fallback

    for incident in incidents:
        best_raw = _best_incident_message(incident)
        extracted = _extract_useful_content(best_raw)
        if not extracted:
            # Try normalized_message directly
            extracted = _extract_useful_content(
                str(getattr(incident, 'normalized_message', '') or '')
            )
        if not extracted:
            # Save for fallback if ALL messages are wrappers
            raw_fallback = best_raw or str(getattr(incident, 'normalized_message', '') or '')
            if raw_fallback:
                skipped_raw.append((incident, raw_fallback))
            continue

        normalized_key = normalize_message(extracted)
        if not normalized_key:
            continue

        count = _incident_occurrence_count(incident)
        entry = pattern_map.setdefault(normalized_key, {
            'normalized_key': normalized_key,
            'message': extracted,
            'signal': _message_signal_score(extracted),
            'count': 0,
            'app_counts': Counter(),
            'namespace_counts': Counter(),
            'trace_counts': Counter(),
        })

        entry['count'] += count
        new_signal = _message_signal_score(extracted)
        if new_signal > entry['signal']:
            entry['signal'] = new_signal
            entry['message'] = extracted

        # Use per-entity counts from incident if available
        app_event_counts = getattr(incident, 'app_event_counts', {}) or {}
        if app_event_counts:
            for app, ac in app_event_counts.items():
                if app:
                    entry['app_counts'][app] += int(ac or 0)
        else:
            for app in getattr(incident, 'apps', None) or []:
                if app:
                    entry['app_counts'][app] += count

        ns_event_counts = getattr(incident, 'namespace_event_counts', {}) or {}
        if ns_event_counts:
            for ns, nc in ns_event_counts.items():
                if ns:
                    entry['namespace_counts'][ns] += int(nc or 0)
        else:
            for namespace in getattr(incident, 'namespaces', None) or []:
                if namespace:
                    entry['namespace_counts'][namespace] += count

        for trace_id in getattr(incident, 'trace_ids', None) or []:
            if trace_id:
                entry['trace_counts'][trace_id] += 1

    # Fallback: if ALL incidents were wrappers, re-add them with raw messages
    if not pattern_map and skipped_raw:
        for incident, raw_msg in skipped_raw:
            normalized_key = normalize_message(raw_msg)
            if not normalized_key:
                continue
            count = _incident_occurrence_count(incident)
            entry = pattern_map.setdefault(normalized_key, {
                'normalized_key': normalized_key,
                'message': raw_msg[:250],
                'signal': -1,
                'count': 0,
                'app_counts': Counter(),
                'namespace_counts': Counter(),
                'trace_counts': Counter(),
            })
            entry['count'] += count
            for app in getattr(incident, 'apps', None) or []:
                if app:
                    entry['app_counts'][app] += count
            for ns in getattr(incident, 'namespaces', None) or []:
                if ns:
                    entry['namespace_counts'][ns] += count

    # Filter out any entries that still have low signal (wrappers that slipped through)
    useful_entries = [e for e in pattern_map.values() if e['signal'] >= -2]
    if not useful_entries:
        useful_entries = list(pattern_map.values())

    ordered = sorted(
        useful_entries,
        key=lambda item: (
            -item['signal'],
            -item['count'],
            item['normalized_key'],
        )
    )

    summary: List[Dict[str, Any]] = []
    seen_messages: set = set()
    for item in ordered:
        if len(summary) >= limit:
            break
        # Deduplicate: skip if a very similar message is already in summary
        trimmed = _smart_trim(item['message'])
        # Never store empty message - fallback to raw
        display_msg = trimmed if trimmed else item['message'][:250]
        dedup_key = normalize_message(display_msg or item['normalized_key'])[:80].lower()
        if dedup_key in seen_messages:
            continue
        seen_messages.add(dedup_key)

        app_counts = sorted(item['app_counts'].items(), key=lambda kv: (-kv[1], kv[0]))
        namespace_counts = sorted(item['namespace_counts'].items(), key=lambda kv: (-kv[1], kv[0]))
        trace_counts = sorted(item['trace_counts'].items(), key=lambda kv: (-kv[1], kv[0]))
        dominant_app = app_counts[0][0] if app_counts else '?'
        summary.append({
            'app': dominant_app,
            'message': display_msg,
            'count': int(item['count']),
            'share_pct': round((item['count'] / total_occurrences) * 100, 1),
            'apps': [name for name, _ in app_counts[:5]],
            'namespaces': [name for name, _ in namespace_counts[:5]],
            'trace_ids': [name for name, _ in trace_counts[:3]],
            'signal': int(item['signal']),
        })

    return summary


def infer_problem_root_cause(
    problem: Any,
    behavior_patterns: Optional[List[Dict[str, Any]]] = None,
    behavior_steps: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Select root cause from dominant patterns.

    Rules:
    - Never return wrapper ('... error handled.', 'Handle fault...')
    - Never return same message as a behavior step (avoid duplication)
    - Prefer: specific business error > SPEED/ITO code > exception message > error_class
    """
    patterns = behavior_patterns or summarize_problem_patterns(problem, limit=8)
    if not patterns:
        return None

    # Build set of behavior messages for dedup
    behavior_messages: set = set()
    for step in (behavior_steps or []):
        msg = normalize_message(str(step.get('message', '') or ''))[:80].lower()
        if msg:
            behavior_messages.add(msg)

    def _rc_rank(item: Dict[str, Any]) -> Tuple[int, int, int]:
        msg = str(item.get('message', '') or '')
        signal = int(item.get('signal', 0) or 0)
        count = int(item.get('count', 0) or 0)
        # Penalize if same as behavior step
        dedup_key = normalize_message(msg)[:80].lower()
        dup_penalty = -50 if dedup_key in behavior_messages else 0
        return (dup_penalty, signal, count)

    candidates = [p for p in patterns if p.get('signal', 0) >= 0]
    if not candidates:
        candidates = patterns

    best = max(candidates, key=_rc_rank)
    signal = int(best.get('signal', 0) or 0)
    confidence = 'high' if signal >= 3 else ('medium' if signal > 0 else 'low')

    return {
        'service': best.get('app', '?'),
        'message': str(best.get('message', '') or ''),
        'level': 'ERROR' if signal > 0 else 'WARN',
        'timestamp': None,
        'confidence': confidence,
    }


@dataclass
class TraceStep:
    """Jeden krok v trace flow."""
    timestamp: datetime
    app: str                             # Deployment/service name
    level: str                           # ERROR, WARN, INFO
    message: str                         # Zkrácená message
    namespace: str = ""
    error_type: str = ""

    # Metadata
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'app': self.app,
            'level': self.level,
            'message': self.message[:200],  # Truncate
            'namespace': self.namespace,
            'error_type': self.error_type,
        }

    def __str__(self) -> str:
        return f"[{self.timestamp.strftime('%H:%M:%S.%f')[:-3]}] {self.app}: {self.level} - {self.message[:60]}"


@dataclass
class TraceFlow:
    """Kompletní flow pro jeden trace_id."""
    trace_id: str
    steps: List[TraceStep] = field(default_factory=list)

    # Agregované info
    duration_ms: int = 0
    service_count: int = 0
    error_count: int = 0

    def add_step(self, step: TraceStep):
        """Přidá krok (bez sortování - sort až na konci)."""
        self.steps.append(step)
        # POZOR: Nesortujeme zde! Volej finalize() po přidání všech kroků.

    def finalize(self):
        """Seřadí kroky a přepočítá metriky. Volat po add_step()."""
        if not self.steps:
            return

        # Sort jednou na konci (ne po každém add_step)
        self.steps.sort(key=lambda s: s.timestamp)

        # Přepočítej metriky
        if len(self.steps) >= 2:
            self.duration_ms = int(
                (self.steps[-1].timestamp - self.steps[0].timestamp).total_seconds() * 1000
            )

        self.service_count = len(set(s.app for s in self.steps))
        self.error_count = sum(1 for s in self.steps if s.level in ('ERROR', 'FATAL'))

    @property
    def services(self) -> List[str]:
        """Seznam služeb v pořadí, jak se objevily."""
        seen = set()
        result = []
        for step in self.steps:
            if step.app not in seen:
                seen.add(step.app)
                result.append(step.app)
        return result

    @property
    def first_error(self) -> Optional[TraceStep]:
        """První ERROR v trace."""
        for step in self.steps:
            if step.level in ('ERROR', 'FATAL'):
                return step
        return None

    @property
    def root_service(self) -> str:
        """První služba v trace (pravděpodobný root)."""
        return self.steps[0].app if self.steps else "unknown"

    def to_dict(self) -> dict:
        return {
            'trace_id': self.trace_id,
            'steps': [s.to_dict() for s in self.steps],
            'duration_ms': self.duration_ms,
            'service_count': self.service_count,
            'error_count': self.error_count,
            'services': self.services,
            'root_service': self.root_service,
        }


def build_trace_flow(incidents: List[Any], trace_id: str) -> TraceFlow:
    """
    Sestaví trace flow z incidentů s daným trace_id.

    Args:
        incidents: Seznam incidentů (všechny, ne jen ty s trace_id)
        trace_id: ID trace pro sestavení

    Returns:
        TraceFlow s seřazenými kroky
    """
    flow = TraceFlow(trace_id=trace_id)

    for incident in incidents:
        # Zkontroluj, zda incident patří do tohoto trace
        incident_traces = set()
        if hasattr(incident, 'trace_ids'):
            incident_traces.update(incident.trace_ids)
        if hasattr(incident, 'trace_info') and incident.trace_info:
            incident_traces.update(incident.trace_info.trace_ids)

        if trace_id not in incident_traces:
            continue

        # Vytvoř step pro každou app v incidentu
        for app in incident.apps:
            # Použij first_seen jako timestamp (nebo current time)
            ts = incident.time.first_seen or datetime.utcnow()

            # Level podle flags
            level = "ERROR"
            if incident.flags.is_spike or incident.flags.is_burst:
                level = "ERROR"
            elif incident.score < 40:
                level = "WARN"

            step = TraceStep(
                timestamp=ts,
                app=app,
                level=level,
                message=incident.normalized_message or "",
                namespace=incident.namespaces[0] if incident.namespaces else "",
                error_type=incident.error_type or "",
            )
            flow.add_step(step)

    # Finalizuj (sort + metriky) až po přidání všech kroků
    flow.finalize()
    return flow


def summarize_trace_flow(flow: TraceFlow, max_steps: int = 3) -> List[TraceStep]:
    """
    Zkrátí trace flow pro report.

    Pravidlo:
    - Pokud <= max_steps: vrátí vše
    - Jinak: 2 první + 1 poslední

    Args:
        flow: TraceFlow ke zkrácení
        max_steps: Maximum kroků v summary

    Returns:
        Seznam zkrácených kroků
    """
    if len(flow.steps) <= max_steps:
        return flow.steps

    # 2 první + 1 poslední
    return [
        flow.steps[0],
        flow.steps[1],
        flow.steps[-1],
    ]


def group_incidents_by_trace(
    incidents: List[Any]
) -> Dict[str, List[Any]]:
    """
    Seskupí incidenty podle trace_id.

    Args:
        incidents: Seznam incidentů

    Returns:
        Dict[trace_id, List[incidents]]
    """
    result: Dict[str, List[Any]] = defaultdict(list)

    for incident in incidents:
        trace_ids = set()

        if hasattr(incident, 'trace_ids'):
            trace_ids.update(incident.trace_ids)
        if hasattr(incident, 'trace_info') and incident.trace_info:
            trace_ids.update(incident.trace_info.trace_ids)

        for trace_id in trace_ids:
            if trace_id:  # Skip empty
                result[trace_id].append(incident)

    return dict(result)


def get_representative_traces(
    problems: Dict[str, Any],  # ProblemAggregate
    max_traces_per_problem: int = 3
) -> Dict[str, List[TraceFlow]]:
    """
    Vybere reprezentativní traces pro každý problém.

    Kritéria výběru:
    1. Traces s nejvíce službami
    2. Traces s nejvíce errory
    3. Nejdelší traces

    Args:
        problems: Dict[problem_key, ProblemAggregate]
        max_traces_per_problem: Max traces per problém

    Returns:
        Dict[problem_key, List[TraceFlow]]
    """
    result: Dict[str, List[TraceFlow]] = {}

    for problem_key, problem in problems.items():
        # Seskup incidenty podle trace
        trace_groups = group_incidents_by_trace(problem.incidents)

        if not trace_groups:
            result[problem_key] = []
            continue

        # Postav flows
        flows = []
        for trace_id, trace_incidents in trace_groups.items():
            flow = build_trace_flow(trace_incidents, trace_id)
            if flow.steps:  # Jen non-empty
                flows.append(flow)

        # Seřaď podle priority
        flows.sort(key=lambda f: (
            -f.service_count,
            -f.error_count,
            -f.duration_ms
        ))

        result[problem_key] = flows[:max_traces_per_problem]

    return result


def format_trace_flow_text(flow: TraceFlow, summarize: bool = True) -> str:
    """
    Formátuje trace flow jako text pro report.

    Args:
        flow: TraceFlow k formátování
        summarize: Pokud True, zkrátí na 3 kroky

    Returns:
        Formátovaný text
    """
    steps = summarize_trace_flow(flow) if summarize else flow.steps

    lines = [f"Trace: {flow.trace_id[:16]}..."]
    lines.append(f"  Duration: {flow.duration_ms}ms | Services: {flow.service_count} | Errors: {flow.error_count}")
    lines.append(f"  Flow: {' → '.join(flow.services[:5])}")
    lines.append("")

    for i, step in enumerate(steps):
        marker = "├──" if i < len(steps) - 1 else "└──"
        lines.append(f"  {marker} [{step.timestamp.strftime('%H:%M:%S')}] {step.app}")
        lines.append(f"      {step.level}: {step.message[:80]}")

    if len(flow.steps) > len(steps):
        lines.append(f"  ... ({len(flow.steps) - len(steps)} more steps)")

    return "\n".join(lines)


def save_trace_details(
    flow: TraceFlow,
    output_dir: str,
    prefix: str = "trace"
) -> str:
    """
    Uloží detailní trace flow do souboru.

    Args:
        flow: TraceFlow k uložení
        output_dir: Adresář pro výstup
        prefix: Prefix názvu souboru

    Returns:
        Cesta k uloženému souboru
    """
    from pathlib import Path
    import json

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Sanitize trace_id pro filename
    safe_id = flow.trace_id.replace('/', '_').replace('\\', '_')[:32]
    filename = f"{prefix}_{safe_id}.json"
    filepath = output_path / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(flow.to_dict(), f, indent=2, default=str)

    return str(filepath)


# =============================================================================
# BEHAVIOR / TRACE FLOW ENRICHMENT
# =============================================================================

def select_representative_trace(
    trace_ids: set,
    incidents_by_trace: Dict[str, List[Any]]
) -> Optional[str]:
    """
    Vybere reprezentativní trace pro problém.

    Kritéria (deterministická, žádná náhoda):
    1. Preferuj trace s ERROR (+10)
    2. Preferuj trace s více kroky (+1 per incident)
    3. Preferuj trace s větším fan-out (+1 per unique service)
    4. Při shodě: první abecedně (pro konzistenci)

    Args:
        trace_ids: Set trace IDs pro problém
        incidents_by_trace: Dict[trace_id, List[incidents]]

    Returns:
        Vybraný trace_id nebo None
    """
    if not trace_ids:
        return None

    best_trace = None
    best_score = -1

    for trace_id in sorted(trace_ids):  # sorted pro determinismus
        incidents = incidents_by_trace.get(trace_id, [])
        if not incidents:
            continue

        # Skóre = počet kroků
        score = len(incidents)

        # Bonus za ERROR flagy (+10)
        has_error = any(
            getattr(i, 'flags', None) and
            (i.flags.is_spike or i.flags.is_burst or i.score >= 60)
            for i in incidents
        )
        if has_error:
            score += 10

        # Bonus za fan-out (unique services) - tie-breaker
        unique_services = set()
        for incident in incidents:
            if hasattr(incident, 'apps'):
                unique_services.update(incident.apps)
        score += len(unique_services)

        if score > best_score:
            best_score = score
            best_trace = trace_id

    return best_trace


def summarize_trace_flow_to_dict(flow: TraceFlow) -> List[Dict[str, Any]]:
    """
    Zkrátí trace flow na 2+1 kroky a vrátí jako list of dicts.

    Format:
    [
        {"app": "svc1", "message": "...", "level": "ERROR", "ts": "..."},
        {"app": "svc2", "message": "...", "level": "WARN", "ts": "..."},
        {"app": "svc3", "message": "...", "level": "ERROR", "ts": "..."},
    ]

    Args:
        flow: TraceFlow k zpracování

    Returns:
        List of step dicts (max 3)
    """
    if not flow.steps:
        return []

    unique_steps: List[TraceStep] = []
    seen = set()
    for step in flow.steps:
        key = (step.app, normalize_message(step.message))
        if key in seen:
            continue
        seen.add(key)
        unique_steps.append(step)

    if len(unique_steps) <= 3:
        steps = unique_steps
    else:
        first = unique_steps[0]
        last = unique_steps[-1]
        middle_candidates = unique_steps[1:-1] if len(unique_steps) > 2 else []

        first_norm = normalize_message(first.message)
        if normalize_message(last.message) == first_norm:
            for candidate in reversed(unique_steps[1:-1]):
                if normalize_message(candidate.message) != first_norm:
                    last = candidate
                    break

        if middle_candidates:
            best_middle = max(
                middle_candidates,
                key=lambda s: (_message_signal_score(s.message), -s.timestamp.timestamp() if s.timestamp else 0),
            )
            steps = [first, best_middle, last]
        else:
            steps = [first, last]

        deduped = []
        seen_norm = set()
        for step in steps:
            norm = normalize_message(step.message)
            if norm in seen_norm:
                continue
            seen_norm.add(norm)
            deduped.append(step)
        steps = deduped

    return [
        {
            'app': step.app,
            'message': _smart_trim(step.message),
            'level': step.level,
            'ts': step.timestamp.isoformat() if step.timestamp else None,
        }
        for step in steps
    ]


def infer_trace_root_cause(flow: TraceFlow) -> Optional[Dict[str, Any]]:
    """
    Odvodí root cause z trace flow (deterministicky).

    Pravidlo: první ERROR v trace = root cause.
    Fallback: první WARN, pak první krok.

    Confidence levels:
    - high: ERROR a zároveň první krok v trace
    - medium: ERROR ale ne první krok
    - low: pouze WARN nebo INFO (žádný ERROR)

    Args:
        flow: TraceFlow k analýze

    Returns:
        Dict s root cause info včetně confidence
    """
    if not flow.steps:
        return None

    first_step = flow.steps[0]

    error_candidates = [
        (idx, step) for idx, step in enumerate(flow.steps)
        if step.level in ('ERROR', 'FATAL')
    ]

    if error_candidates:
        best_idx, best_step = max(
            error_candidates,
            key=lambda item: (_message_signal_score(item[1].message), -item[0]),
        )
        best_score = _message_signal_score(best_step.message)

        if best_score <= 0:
            for idx, step in error_candidates:
                if _message_signal_score(step.message) >= 2:
                    best_idx, best_step = idx, step
                    best_score = _message_signal_score(step.message)
                    break

        confidence = 'high' if best_score >= 2 else ('medium' if best_idx <= 2 else 'low')
        return {
            'service': best_step.app,
            'message': normalize_message(best_step.message[:300]),
            'level': best_step.level,
            'timestamp': best_step.timestamp.isoformat() if best_step.timestamp else None,
            'confidence': confidence,
        }

    # 2. Fallback na první WARN - confidence low
    for step in flow.steps:
        if step.level == 'WARN':
            return {
                'service': step.app,
                'message': normalize_message(step.message[:300]),
                'level': step.level,
                'timestamp': step.timestamp.isoformat() if step.timestamp else None,
                'confidence': 'low',
            }

    # 3. Fallback na první krok - confidence low
    return {
        'service': first_step.app,
        'message': normalize_message(first_step.message[:300]),
        'level': first_step.level,
        'timestamp': first_step.timestamp.isoformat() if first_step.timestamp else None,
        'confidence': 'low',
    }


def store_full_trace(
    flow: TraceFlow,
    output_dir: str,
    problem_key: str = ""
) -> str:
    """
    Uloží plný trace flow do .log souboru.

    Format:
        2026-01-15T10:30:00 payment-service ERROR Connection pool exhausted
        2026-01-15T10:30:01 card-service WARN Retrying request
        ...

    Args:
        flow: TraceFlow k uložení
        output_dir: Výstupní adresář
        problem_key: Volitelný problem key pro název souboru

    Returns:
        Cesta k souboru
    """
    from pathlib import Path

    output_path = Path(output_dir) / 'traces'
    output_path.mkdir(parents=True, exist_ok=True)

    # Název souboru
    safe_trace_id = flow.trace_id.replace('/', '_').replace('\\', '_')[:24]
    safe_problem = problem_key.replace(':', '_')[:30] if problem_key else 'unknown'
    filename = f"trace_{safe_problem}_{safe_trace_id}.log"
    filepath = output_path / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# Trace: {flow.trace_id}\n")
        f.write(f"# Duration: {flow.duration_ms}ms\n")
        f.write(f"# Services: {', '.join(flow.services)}\n")
        f.write(f"# Errors: {flow.error_count}\n")
        f.write("#" + "=" * 70 + "\n\n")

        for step in flow.steps:
            ts = step.timestamp.isoformat() if step.timestamp else "?"
            f.write(f"{ts} {step.app:30} {step.level:6} {step.message}\n")

    return str(filepath)


def enrich_problem_with_trace(
    problem: Any,
    incidents_by_trace: Dict[str, List[Any]] = None,
    output_dir: str = None
) -> Any:
    """
    Obohatí problém o trace behavior data.

    Přidá:
    - representative_trace_id
    - trace_flow_summary (2+1)
    - trace_root_cause

    Args:
        problem: ProblemAggregate
        incidents_by_trace: Volitelné předpočítané seskupení
        output_dir: Pokud zadáno, uloží plný trace do souboru

    Returns:
        Stejný problém s doplněnými trace daty
    """
    if not problem.trace_ids:
        return problem

    # Seskup incidenty pokud není předáno
    if incidents_by_trace is None:
        incidents_by_trace = group_incidents_by_trace(problem.incidents)

    # 1. Vyber reprezentativní trace
    trace_id = select_representative_trace(problem.trace_ids, incidents_by_trace)
    if not trace_id:
        return problem

    problem.representative_trace_id = trace_id

    # 2. Postav flow
    flow = build_trace_flow(problem.incidents, trace_id)
    if not flow.steps:
        return problem

    # 3. Problem-level behavior summary napric incidenty (ne fake per-app trace flow)
    behavior_patterns = summarize_problem_patterns(problem)
    problem.trace_flow_summary = behavior_patterns or summarize_trace_flow_to_dict(flow)

    # 4. Root cause preferuj z dominantnich patternu problemu, fallback na trace
    #    Pass behavior_steps to dedup: root cause != behavior step
    problem.trace_root_cause = infer_problem_root_cause(
        problem,
        behavior_patterns=behavior_patterns,
        behavior_steps=behavior_patterns,
    )
    if not problem.trace_root_cause:
        problem.trace_root_cause = infer_trace_root_cause(flow)

    # 5. Ulož plný trace (volitelně)
    if output_dir:
        store_full_trace(flow, output_dir, problem.problem_key)

    return problem


def enrich_all_problems_with_traces(
    problems: Dict[str, Any],
    output_dir: str = None,
    verbose: bool = False
) -> Dict[str, Any]:
    """
    Obohatí všechny problémy o trace behavior.

    Args:
        problems: Dict[problem_key, ProblemAggregate]
        output_dir: Volitelný adresář pro plné traces
        verbose: Pokud True, vypisuje progress

    Returns:
        Stejný dict s obohacenými problémy
    """
    total = len(problems)
    enriched = 0

    for i, problem in enumerate(problems.values(), 1):
        enrich_problem_with_trace(problem, output_dir=output_dir)

        if problem.representative_trace_id:
            enriched += 1

        # Progress každých 100 problémů nebo na konci
        if verbose and (i % 100 == 0 or i == total):
            print(f"   Trace enrichment: {i}/{total} ({enriched} with traces)", flush=True)

    return problems
