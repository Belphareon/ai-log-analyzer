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
# by jinak alokovala timeline pro každý trace bez limitu.
_MAX_TRACES = int(os.getenv('TRACE_TIMELINE_MAX_TRACES', '20000'))
_MAX_EVENTS_PER_TRACE = int(os.getenv('TRACE_TIMELINE_MAX_EVENTS_PER_TRACE', '500'))


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
            ))
        timelines[tid] = TraceTimeline(trace_id=tid, events=events)

    return timelines


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
