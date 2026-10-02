#!/usr/bin/env python3
"""
Trace Timeline - REÁLNÁ trace-centric analýza
=============================================

Cíl (dle vize uživatele): z jednoho trace_id složit dle časové osy, jak se
behavior propaguje napříč službami, a agregovat trace se STEJNÝM průběhem do
jednoho "known erroru"/alertu.

Klíčové metriky pro jeden trace-pattern:
  - occurrences        = počet UNIKÁTNÍCH trace_id se stejným průběhem
  - total_errors       = celkový počet error eventů napříč těmi trace
  - avg_per_occurrence = total_errors / occurrences
  - per_app_errors     = kolik erroru je na které aplikaci

Tohle je POCTIVÁ alternativa k fabrikovanému build_trace_flow: staví se výhradně
z reálných eventů (timestamp, app, message), ne z agregovaných incident počtů.

Příprava na AI agenta:
  - root cause i signature mají default heuristiku, ale jdou přepnout přes
    set_root_cause_strategy() / set_signature_strategy(). Bez agenta to funguje
    plně na heuristice; agent může později zlepšit přesnost beze změny volajících.
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from collections import Counter, defaultdict

from .trace_analysis import (
    _extract_useful_content,
    _message_signal_score,
    _smart_trim,
    normalize_message,
)

# Error type names that carry no useful classification on their own.
_UNINFORMATIVE_TYPES = frozenset({
    '', 'unknownerror', 'unknown', 'error', 'exception', 'runtimeexception',
})

# Memory guard pro stavění trace timelines (env-tunable). Velká okna (65k+ eventů)
# by jinak alokovala timeline pro každý trace bez limitu. Per-trace cap je vysoký
# (mega-trace = celá session může mít tisíce eventů, chceme je SPRÁVNě započítat;
# celkovou paměť drží _MAX_TRACES + fetch OOM guard z r81).
_MAX_TRACES = int(os.getenv('TRACE_TIMELINE_MAX_TRACES', '20000'))
_MAX_EVENTS_PER_TRACE = int(os.getenv('TRACE_TIMELINE_MAX_EVENTS_PER_TRACE', '10000'))


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class TraceEvent:
    """Jeden reálný event v trace (z raw recordu, nic se nedopočítává)."""
    timestamp: Optional[datetime]
    app: str
    error_class: str
    message: str            # ořezaná informativní část
    namespace: str = ""
    level: str = "ERROR"    # ERROR/WARN/INFO/... (jen když máme všechny levely)
    signal: int = 0         # informativnost message (vyšší = konkrétnější)
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None


@dataclass
class TraceTimeline:
    """Reálná časová osa jednoho trace_id."""
    trace_id: str
    events: List[TraceEvent] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        ts = [e.timestamp for e in self.events if e.timestamp]
        if len(ts) < 2:
            return 0
        return int((max(ts) - min(ts)).total_seconds() * 1000)

    @property
    def apps_in_order(self) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for e in self.events:
            if e.app not in seen:
                seen.add(e.app)
                out.append(e.app)
        return out

    @property
    def per_app_errors(self) -> Dict[str, int]:
        c: Counter = Counter()
        for e in self.events:
            c[e.app] += 1
        return dict(c)

    @property
    def error_count(self) -> int:
        return len(self.events)


@dataclass(frozen=True)
class OperationOccurrenceEstimate:
    count: Optional[int]
    method: str
    confidence: str
    reason: str = ""


@dataclass(frozen=True)
class OperationTimelineSegment:
    root_span_id: Optional[str]
    error_timeline: TraceTimeline
    context_timeline: Optional[TraceTimeline]


@dataclass
class TracePattern:
    """Skupina trace se stejným průběhem (= jeden known error / alert)."""
    signature: Tuple[Tuple[str, str], ...]
    trace_ids: List[str] = field(default_factory=list)
    representative: Optional[TraceTimeline] = None
    per_app_errors: Dict[str, int] = field(default_factory=dict)
    total_errors: int = 0

    # behavior story (pro rychlý debug)
    root_cause: Optional[Dict[str, Any]] = None
    propagation_path: List[str] = field(default_factory=list)
    outcome: Optional[Dict[str, Any]] = None

    @property
    def occurrences(self) -> int:
        """Počet unikátních trace = počet výskytů tohoto known erroru."""
        return len(self.trace_ids)

    @property
    def avg_errors_per_occurrence(self) -> float:
        return (self.total_errors / self.occurrences) if self.occurrences else 0.0

    def to_dict(self) -> dict:
        return {
            'signature': [list(s) for s in self.signature],
            'occurrences': self.occurrences,
            'total_errors': self.total_errors,
            'avg_per_occurrence': round(self.avg_errors_per_occurrence, 1),
            'per_app_errors': dict(sorted(self.per_app_errors.items(), key=lambda kv: (-kv[1], kv[0]))),
            'propagation_path': self.propagation_path,
            'root_cause': self.root_cause,
            'outcome': self.outcome,
            'representative_trace_id': self.representative.trace_id if self.representative else None,
            'example_trace_ids': self.trace_ids[:5],
        }


# =============================================================================
# ERROR CLASS (light, deduplikuje s problem_aggregator pravidly)
# =============================================================================

def _event_error_class(error_type: str, normalized_message: str) -> str:
    """Stabilní krátká třída chyby pro signature (app, class)."""
    et = (error_type or '').strip()
    if et and et.lower() not in _UNINFORMATIVE_TYPES:
        return et
    # Fallback: první informativní tokeny normalizované message.
    extracted = _extract_useful_content(normalized_message or '')
    norm = normalize_message(extracted or normalized_message or '')
    if not norm:
        return 'unknown'
    tokens = [t for t in norm.lower().split() if len(t) > 3][:4]
    return '_'.join(tokens) if tokens else 'unknown'


# =============================================================================
# BUILD TIMELINES FROM REAL RECORDS
# =============================================================================

def build_trace_timelines(records: List[Any]) -> Dict[str, TraceTimeline]:
    """
    Složí reálné časové osy z raw recordů (NormalizedRecord nebo duck-typed).

    Očekává atributy: trace_id, timestamp, app_name, namespace,
    normalized_message, error_type, (volitelně raw_message).
    """
    by_trace: Dict[str, List[Any]] = defaultdict(list)
    for r in records:
        tid = getattr(r, 'trace_id', None) or ''
        if not tid:
            continue
        by_trace[tid].append(r)

    timelines: Dict[str, TraceTimeline] = {}
    # Memory guard: zpracuj jen nejaktivnější trace + omez eventy/trace, aby velká
    # okna nezahltila paměť. Ladění přes TRACE_TIMELINE_MAX_* env proměnné.
    ordered_traces = sorted(by_trace.items(), key=lambda kv: len(kv[1]), reverse=True)
    if len(ordered_traces) > _MAX_TRACES:
        ordered_traces = ordered_traces[:_MAX_TRACES]
    for tid, recs in ordered_traces:
        if len(recs) > _MAX_EVENTS_PER_TRACE:
            recs = sorted(
                recs,
                key=lambda r: (getattr(r, 'timestamp', None) or datetime.max),
            )[:_MAX_EVENTS_PER_TRACE]
        recs_sorted = sorted(
            recs,
            key=lambda r: (getattr(r, 'timestamp', None) or datetime.max),
        )
        events: List[TraceEvent] = []
        for r in recs_sorted:
            app = getattr(r, 'app_name', None) or '?'
            etype = getattr(r, 'error_type', '') or ''
            norm_msg = getattr(r, 'normalized_message', '') or ''
            raw_msg = getattr(r, 'raw_message', '') or norm_msg
            useful = _extract_useful_content(raw_msg) or norm_msg
            events.append(TraceEvent(
                timestamp=getattr(r, 'timestamp', None),
                app=app,
                error_class=_event_error_class(etype, norm_msg),
                message=_smart_trim(useful) or useful[:200],
                namespace=getattr(r, 'namespace', '') or '',
                signal=_message_signal_score(useful),
                span_id=getattr(r, 'span_id', None),
                parent_span_id=getattr(r, 'parent_span_id', None),
            ))
        timelines[tid] = TraceTimeline(trace_id=tid, events=events)

    return timelines


def segment_operation_timelines(
    error_timeline: TraceTimeline,
    context_timeline: Optional[TraceTimeline] = None,
    expected_error_lines: Optional[int] = None,
) -> Tuple[List[OperationTimelineSegment], OperationOccurrenceEstimate]:
    """Split by proven root spans; otherwise return one unsplit timeline."""
    error_events = [
        event
        for event in error_timeline.events
        if (event.level or "ERROR").upper() in {"ERROR", "FATAL"}
    ]
    unsplit = [OperationTimelineSegment(None, error_timeline, context_timeline)]

    def trace_id_fallback(reason: str) -> OperationOccurrenceEstimate:
        max_errors = max(
            0, int(os.getenv("OPERATION_TRACE_FALLBACK_MAX_ERRORS", "100"))
        )
        max_duration_min = max(
            0, int(os.getenv("OPERATION_TRACE_FALLBACK_MAX_DURATION_MIN", "15"))
        )
        timestamps = [event.timestamp for event in error_events if event.timestamp]
        duration_seconds = (
            (max(timestamps) - min(timestamps)).total_seconds()
            if len(timestamps) >= 2
            else 0.0
        )
        if max_errors and len(error_events) > max_errors:
            return OperationOccurrenceEstimate(
                None,
                "unavailable",
                "low",
                "trace-ID fallback refused: "
                f"{len(error_events)} ERROR events exceed limit {max_errors}",
            )
        if max_duration_min and duration_seconds > max_duration_min * 60:
            return OperationOccurrenceEstimate(
                None,
                "unavailable",
                "low",
                "trace-ID fallback refused: "
                f"trace duration exceeds {max_duration_min} minutes",
            )
        return OperationOccurrenceEstimate(1, "trace_id", "medium", reason)

    if expected_error_lines is not None and len(error_events) != expected_error_lines:
        return (
            unsplit,
            OperationOccurrenceEstimate(
                None,
                "unavailable",
                "low",
                f"ERROR timeline incomplete ({len(error_events)}/{expected_error_lines})",
            ),
        )
    if not error_events:
        return (
            unsplit,
            OperationOccurrenceEstimate(
                None, "unavailable", "low", "no ERROR events available"
            ),
        )

    error_span_ids = [event.span_id for event in error_events]
    if not any(error_span_ids):
        return unsplit, trace_id_fallback(
            "span ancestry unavailable; trace-ID fallback"
        )
    if not all(error_span_ids):
        return (
            unsplit,
            OperationOccurrenceEstimate(
                None,
                "unavailable",
                "low",
                "span ancestry covers only part of the ERROR events",
            ),
        )

    parent_candidates: Dict[str, set[str]] = defaultdict(set)
    parentless_spans: set[str] = set()
    graph_events = list(error_timeline.events)
    if context_timeline is not None:
        graph_events.extend(context_timeline.events)
    for event in graph_events:
        span_id = (event.span_id or "").strip()
        if not span_id:
            continue
        parent_span_id = (event.parent_span_id or "").strip()
        if parent_span_id:
            parent_candidates[span_id].add(parent_span_id)
        else:
            parentless_spans.add(span_id)

    conflicting_spans = [
        span_id
        for span_id, parents in parent_candidates.items()
        if len(parents) > 1
    ]
    if conflicting_spans:
        return (
            unsplit,
            OperationOccurrenceEstimate(
                None,
                "unavailable",
                "low",
                "conflicting parent span metadata",
            ),
        )

    parent_by_span: Dict[str, Optional[str]] = {
        span_id: next(iter(parents))
        for span_id, parents in parent_candidates.items()
    }
    for span_id in parentless_spans:
        parent_by_span.setdefault(span_id, None)

    def resolve_root(span_id: str) -> Tuple[str, str]:
        current = span_id
        visited: set[str] = set()
        while True:
            if current in visited:
                return "cycle", current
            visited.add(current)
            if current not in parent_by_span:
                return "unresolved", current
            parent_span_id = parent_by_span[current]
            if not parent_span_id:
                return "resolved", current
            current = parent_span_id

    root_assignments: List[Tuple[TraceEvent, str]] = []
    roots: set[str] = set()
    unresolved_boundaries: set[str] = set()
    for event, error_span_id in zip(error_events, error_span_ids):
        status, boundary = resolve_root(str(error_span_id))
        if status == "cycle":
            return (
                unsplit,
                OperationOccurrenceEstimate(
                    None, "unavailable", "low", "cycle in span ancestry"
                ),
            )
        if status == "resolved":
            roots.add(boundary)
            root_assignments.append((event, boundary))
        else:
            unresolved_boundaries.add(boundary)

    if not unresolved_boundaries:
        context_by_root: Dict[str, List[TraceEvent]] = defaultdict(list)
        for event in (context_timeline.events if context_timeline else []):
            span_id = (event.span_id or "").strip()
            if not span_id:
                continue
            status, root = resolve_root(span_id)
            if status == "resolved" and root in roots:
                context_by_root[root].append(event)

        error_by_root: Dict[str, List[TraceEvent]] = defaultdict(list)
        root_order: List[str] = []
        for event, root in root_assignments:
            if root not in error_by_root:
                root_order.append(root)
            error_by_root[root].append(event)
        segments = [
            OperationTimelineSegment(
                root_span_id=root,
                error_timeline=TraceTimeline(error_timeline.trace_id, error_by_root[root]),
                context_timeline=(
                    TraceTimeline(error_timeline.trace_id, context_by_root[root])
                    if context_by_root[root]
                    else None
                ),
            )
            for root in root_order
        ]
        return (
            segments,
            OperationOccurrenceEstimate(len(segments), "root_span", "high"),
        )

    candidates = roots | unresolved_boundaries
    if len(candidates) == 1:
        return unsplit, trace_id_fallback(
            "root span unavailable; trace-ID fallback"
        )
    return (
        unsplit,
        OperationOccurrenceEstimate(
            None,
            "unavailable",
            "low",
            "multiple root/request candidates with incomplete span ancestry",
        ),
    )


def estimate_operation_occurrences(
    error_timeline: TraceTimeline,
    context_timeline: Optional[TraceTimeline] = None,
    expected_error_lines: Optional[int] = None,
) -> OperationOccurrenceEstimate:
    """Count operation roots only when every ERROR event is accounted for."""
    return segment_operation_timelines(
        error_timeline,
        context_timeline=context_timeline,
        expected_error_lines=expected_error_lines,
    )[1]


# =============================================================================
# SIGNATURE (pluggable)
# =============================================================================

def default_signature(timeline: TraceTimeline) -> Tuple[Tuple[str, str], ...]:
    """
    Průběh trace = sekvence (app, error_class) s collapsnutými po sobě jdoucími
    duplikáty. Zachycuje "jak se to propaguje" nezávisle na počtu opakování.
    """
    seq: List[Tuple[str, str]] = []
    for e in timeline.events:
        step = (e.app, e.error_class)
        if not seq or seq[-1] != step:
            seq.append(step)
    return tuple(seq)


_signature_strategy: Callable[[TraceTimeline], Tuple[Tuple[str, str], ...]] = default_signature


def set_signature_strategy(fn: Callable[[TraceTimeline], Tuple[Tuple[str, str], ...]]) -> None:
    """Hook pro AI agenta: nahradí výpočet průběhu (např. fuzzy clustering)."""
    global _signature_strategy
    _signature_strategy = fn


# =============================================================================
# ROOT CAUSE + BEHAVIOR (pluggable)
# =============================================================================

def default_root_cause(timeline: TraceTimeline) -> Optional[Dict[str, Any]]:
    """
    Pravděpodobný root cause z reálné časové osy.

    Heuristika (ne naivní "první error"): nejdřívější event s dostatečně
    informativní message (signal). Když žádný takový není, vezmi první event.
    confidence = high/medium/low dle signálu a pozice.
    """
    if not timeline.events:
        return None

    informative = [e for e in timeline.events if e.signal >= 2]
    chosen = informative[0] if informative else timeline.events[0]
    idx = timeline.events.index(chosen)

    if chosen.signal >= 3 and idx == 0:
        confidence = 'high'
    elif chosen.signal >= 2:
        confidence = 'medium'
    else:
        confidence = 'low'

    return {
        'service': chosen.app,
        'error_class': chosen.error_class,
        'message': chosen.message,
        'timestamp': chosen.timestamp.isoformat() if chosen.timestamp else None,
        'confidence': confidence,
    }


_root_cause_strategy: Callable[[TraceTimeline], Optional[Dict[str, Any]]] = default_root_cause


def set_root_cause_strategy(fn: Callable[[TraceTimeline], Optional[Dict[str, Any]]]) -> None:
    """Hook pro AI agenta: nahradí inferenci root cause (např. ML model)."""
    global _root_cause_strategy
    _root_cause_strategy = fn


def _outcome(timeline: TraceTimeline) -> Optional[Dict[str, Any]]:
    """Čím trace končí = jak se problém projeví navenek.

    Preferuje POSLEDNÍ ERROR (když máme všechny levely, poslední event může být
    INFO/recovery – ten nechceme). Bez level info je vše ERROR → poslední event.
    """
    if not timeline.events:
        return None
    errors = [e for e in timeline.events if e.level in ('ERROR', 'FATAL')]
    last = errors[-1] if errors else timeline.events[-1]
    return {
        'service': last.app,
        'error_class': last.error_class,
        'message': last.message,
        'timestamp': last.timestamp.isoformat() if last.timestamp else None,
    }


# =============================================================================
# GROUP TRACES BY SIGNATURE -> PATTERNS (known errors)
# =============================================================================

def _pick_representative(timelines: List[TraceTimeline]) -> TraceTimeline:
    """Reprezentant = nejnázornější propagace: max distinct apps, pak max eventů."""
    return max(
        timelines,
        key=lambda t: (len(t.apps_in_order), t.error_count, -len(t.trace_id)),
    )


def group_traces_by_signature(
    timelines: Dict[str, TraceTimeline],
    min_occurrences: int = 1,
) -> List[TracePattern]:
    """
    Agreguje trace se stejným průběhem do TracePattern (= known error).

    Vrací seřazené sestupně podle total_errors (dopad).
    """
    buckets: Dict[Tuple[Tuple[str, str], ...], List[TraceTimeline]] = defaultdict(list)
    for tl in timelines.values():
        if not tl.events:
            continue
        sig = _signature_strategy(tl)
        if not sig:
            continue
        buckets[sig].append(tl)

    patterns: List[TracePattern] = []
    for sig, group in buckets.items():
        if len(group) < min_occurrences:
            continue
        rep = _pick_representative(group)
        per_app: Counter = Counter()
        total = 0
        for tl in group:
            for app, cnt in tl.per_app_errors.items():
                per_app[app] += cnt
            total += tl.error_count

        patterns.append(TracePattern(
            signature=sig,
            trace_ids=[tl.trace_id for tl in group],
            representative=rep,
            per_app_errors=dict(per_app),
            total_errors=total,
            root_cause=_root_cause_strategy(rep),
            propagation_path=[app for app, _ in sig],
            outcome=_outcome(rep),
        ))

    patterns.sort(key=lambda p: (-p.total_errors, -p.occurrences))
    return patterns


# =============================================================================
# RENDER (text, pro report)
# =============================================================================

def format_pattern_behavior(pattern: TracePattern, indent: str = "  ") -> List[str]:
    """
    Vyrenderuje behavior story jednoho patternu pro rychlý debug:
      occurrences / total / avg, propagace po časové ose, root cause, outcome.
    """
    lines: List[str] = []
    lines.append(
        f"{indent}Occurrences: {pattern.occurrences:,} traces "
        f"(total {pattern.total_errors:,} errors, avg {pattern.avg_errors_per_occurrence:.1f}/trace)"
    )

    rep = pattern.representative
    if rep and rep.events:
        path = " → ".join(pattern.propagation_path[:6])
        if len(pattern.propagation_path) > 6:
            path += f" → … ({len(pattern.propagation_path)} hops)"
        lines.append(f"{indent}Propagation: {path}")
        if rep.duration_ms > 0:
            lines.append(f"{indent}  Trace span: {rep.duration_ms:,} ms (example {rep.trace_id})")
        else:
            lines.append(f"{indent}  Example trace: {rep.trace_id}")

    if pattern.per_app_errors:
        top = sorted(pattern.per_app_errors.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        apps_str = ', '.join(f"{a} ({c:,})" for a, c in top)
        lines.append(f"{indent}Errors per app: {apps_str}")

    rc = pattern.root_cause
    if rc:
        lines.append(
            f"{indent}Root cause [{rc.get('confidence', '?')}]: "
            f"{rc.get('service', '?')} — {rc.get('message', '')}"
        )
    out = pattern.outcome
    if out and (not rc or out.get('message') != rc.get('message')):
        lines.append(f"{indent}Ends at: {out.get('service', '?')} — {out.get('message', '')}")

    return lines


# =============================================================================
# #3: ENRICH REPREZENTATIVNÍHO TRACE VŠEMI LEVELY (WARN/INFO před ERROR)
# =============================================================================

def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse ES ISO timestamp; toleruje 'Z' i chybějící hodnotu."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def timeline_from_raw_events(trace_id: str, raw_events: List[Dict[str, Any]]) -> TraceTimeline:
    """Složí TraceTimeline z raw all-level eventů (fetch_trace_context).

    Event dict: message, application, namespace, timestamp, level, error_type.
    """
    events: List[TraceEvent] = []
    for e in raw_events or []:
        raw_msg = str(e.get('message', '') or '')
        useful = _extract_useful_content(raw_msg) or raw_msg
        events.append(TraceEvent(
            timestamp=_parse_ts(e.get('timestamp')),
            app=e.get('application') or '?',
            error_class=_event_error_class(e.get('error_type', '') or '', raw_msg),
            message=_smart_trim(useful) or useful[:200],
            namespace=e.get('namespace', '') or '',
            level=(e.get('level', '') or 'ERROR').upper(),
            signal=_message_signal_score(useful),
            span_id=e.get('spanId') or e.get('span_id') or None,
            parent_span_id=(
                e.get('parentId')
                or e.get('parent_span_id')
                or e.get('parent_id')
                or None
            ),
        ))
    events.sort(key=lambda x: (x.timestamp or datetime.max))
    return TraceTimeline(trace_id=trace_id, events=events)


def enrich_patterns_with_trace_context(
    patterns: List[TracePattern],
    fetch_fn: Callable[[List[str], Any, Any], Dict[str, List[Dict[str, Any]]]],
    date_from: Any,
    date_to: Any,
    top_n: int = 10,
) -> List[TracePattern]:
    """Pro top-N patternů dotáhne VŠECHNY levely reprezentativního trace a přepočítá
    root_cause/outcome/propagation z bohatší časové osy (WARN/INFO před ERROR).

    fetch_fn(trace_ids, date_from, date_to) -> dict[trace_id]->list[event dict].
    Non-blocking: při chybě ponechá původní (ERROR-only) heuristiku.
    """
    if not patterns or fetch_fn is None:
        return patterns
    targets = [p for p in patterns[:top_n] if p.representative]
    rep_ids = [p.representative.trace_id for p in targets if p.representative]
    if not rep_ids:
        return patterns
    try:
        ctx = fetch_fn(rep_ids, date_from, date_to) or {}
    except Exception:
        return patterns
    for p in targets:
        events = ctx.get(p.representative.trace_id)
        if not events:
            continue
        tl = timeline_from_raw_events(p.representative.trace_id, events)
        if not tl.events:
            continue
        p.representative = tl
        p.propagation_path = [app for app, _ in _signature_strategy(tl)]
        p.root_cause = _root_cause_strategy(tl)
        p.outcome = _outcome(tl)
    return patterns


# =============================================================================
# TRACE OWNERSHIP (r82) — každý trace patří JEDNOMU problému (řeší duplikaci)
# =============================================================================

@dataclass
class OwnershipSummary:
    """Behavior problému postavený VÝHRADNĚ z trace, které problém VLASTNÍ.

    Vlastník trace = problém s nejvíce error eventy v daném trace (dominantní /
    root-cause chyba). Tím se každý trace (a každý error event) započítá právě
    jednou → žádné duplicitní reportování téhož trace napříč problémy. Ostatní
    typy chyb ve vlastněných trace = štítky ("Other error types").
    """
    problem_key: str
    owned_trace_ids: List[str] = field(default_factory=list)
    total_errors: int = 0
    per_app_errors: Dict[str, int] = field(default_factory=dict)
    per_ns_errors: Dict[str, int] = field(default_factory=dict)
    primary_error_class: str = ''
    other_error_types: Dict[str, int] = field(default_factory=dict)
    representative: Optional[TraceTimeline] = None
    root_cause: Optional[Dict[str, Any]] = None
    propagation_path: List[str] = field(default_factory=list)

    @property
    def occurrences(self) -> int:
        """Počet vlastněných trace = počet výskytů problému."""
        return len(self.owned_trace_ids)

    @property
    def avg_errors_per_occurrence(self) -> float:
        return (self.total_errors / self.occurrences) if self.occurrences else 0.0


def assign_trace_ownership(
    problems: Dict[str, Any],
    timelines: Dict[str, TraceTimeline],
) -> Dict[str, OwnershipSummary]:
    """Přiřadí každý trace JEDNOMU vlastníkovi a postaví per-problém summary.

    Args:
        problems: dict[problem_key, ProblemAggregate] (duck-typed: .incidents,
                  každý incident má .trace_event_counts {trace_id: count}).
        timelines: dict[trace_id, TraceTimeline] z pipeline (reálné per-event data).

    Returns:
        dict[problem_key, OwnershipSummary] jen pro problémy, které něco vlastní.
    """
    # 1. Spočítej, kolik error eventů přispívá každý problém do každého trace.
    trace_problem_counts: Dict[str, Counter] = defaultdict(Counter)
    for pk, problem in problems.items():
        for inc in (getattr(problem, 'incidents', None) or []):
            for tid, cnt in (getattr(inc, 'trace_event_counts', None) or {}).items():
                if tid:
                    trace_problem_counts[tid][pk] += int(cnt or 0)

    # 2. Vlastník trace = problém s nejvíce eventy (tie-break: jméno klíče).
    owned: Dict[str, List[str]] = defaultdict(list)
    for tid, counts in trace_problem_counts.items():
        if not counts:
            continue
        owner = max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
        owned[owner].append(tid)

    # 3. Pro každý problém postav summary z VLASTNĚNÝCH trace (z timelines).
    summaries: Dict[str, OwnershipSummary] = {}
    for pk, tids in owned.items():
        tls = [timelines[t] for t in tids if t in timelines]
        per_app: Counter = Counter()
        per_ns: Counter = Counter()
        ec_counts: Counter = Counter()
        total = 0
        for tl in tls:
            for ev in tl.events:
                per_app[ev.app] += 1
                if ev.namespace:
                    per_ns[ev.namespace] += 1
                ec_counts[ev.error_class] += 1
                total += 1

        primary = ec_counts.most_common(1)[0][0] if ec_counts else ''
        other = {k: v for k, v in ec_counts.items() if k != primary}

        rep = _pick_representative(tls) if tls else None
        summaries[pk] = OwnershipSummary(
            problem_key=pk,
            owned_trace_ids=tids,
            total_errors=total,
            per_app_errors=dict(per_app),
            per_ns_errors=dict(per_ns),
            primary_error_class=primary,
            other_error_types=dict(sorted(other.items(), key=lambda kv: (-kv[1], kv[0]))),
            representative=rep,
            root_cause=_root_cause_strategy(rep) if rep else None,
            # Propagace = DISTINCTNÍ app v pořadí prvního výskytu (ne každý event –
            # mega-trace by jinak měl tisíce "hopů" téže app).
            propagation_path=rep.apps_in_order if rep else [],
        )

    return summaries


def format_ownership_behavior(summary: OwnershipSummary, indent: str = "  ") -> List[str]:
    """Vyrenderuje behavior z vlastněných trace (reálná data, jeden scope)."""
    lines: List[str] = []
    lines.append(
        f"{indent}Occurrences: {summary.occurrences:,} traces "
        f"(total {summary.total_errors:,} errors, avg {summary.avg_errors_per_occurrence:.1f}/trace)"
    )

    rep = summary.representative
    if rep and rep.events:
        path = " → ".join(summary.propagation_path[:6])
        if len(summary.propagation_path) > 6:
            path += f" → … (+{len(summary.propagation_path) - 6} apps)"
        if path:
            lines.append(f"{indent}Propagation: {path}")
        lines.append(f"{indent}  Example trace: {rep.trace_id}")

    if summary.per_app_errors:
        top = sorted(summary.per_app_errors.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        lines.append(f"{indent}Errors per app: " + ', '.join(f"{a} ({c:,})" for a, c in top))

    if summary.per_ns_errors:
        top = sorted(summary.per_ns_errors.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        lines.append(f"{indent}Namespaces: " + ', '.join(f"{n} ({c:,})" for n, c in top))

    rc = summary.root_cause
    if rc and rc.get('message'):
        lines.append(
            f"{indent}Root cause [{rc.get('confidence', '?')}]: "
            f"{rc.get('service', '?')} — {rc.get('message', '')}"
        )

    if summary.other_error_types:
        top = list(summary.other_error_types.items())[:6]
        lines.append(f"{indent}Other error types: " + ', '.join(f"{t} ({c:,})" for t, c in top))

    return lines

