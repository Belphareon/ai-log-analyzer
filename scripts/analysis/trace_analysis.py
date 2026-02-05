#!/usr/bin/env python3
"""
Trace Analysis - Trace-based flow analýza
==========================================

Používá trace_id k sestavení flow:
1. Seskupí incidenty podle trace_id
2. Seřadí podle timestamp
3. Vytvoří flow (služba1 → služba2 → služba3)
4. Zkrátí flow pro report (2 první + 1 poslední)

Verze: 6.0
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict


# =============================================================================
# MESSAGE NORMALIZATION (V6.1)
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
# V6.1 - BEHAVIOR / TRACE FLOW ENRICHMENT
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

        # Bonus za fan-out (unique services) - tie-breaker (V6.1)
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

    # 2+1 pravidlo
    if len(flow.steps) <= 3:
        steps = flow.steps
    else:
        steps = [flow.steps[0], flow.steps[1], flow.steps[-1]]

    return [
        {
            'app': step.app,
            'message': step.message[:200],
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

    Confidence levels (V6.1):
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

    # 1. Hledej první ERROR/FATAL
    for i, step in enumerate(flow.steps):
        if step.level in ('ERROR', 'FATAL'):
            # Confidence: high pokud je ERROR na první pozici
            confidence = 'high' if i == 0 else 'medium'
            return {
                'service': step.app,
                'message': normalize_message(step.message[:300]),
                'level': step.level,
                'timestamp': step.timestamp.isoformat() if step.timestamp else None,
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

    # 3. Zkrácený flow (2+1)
    problem.trace_flow_summary = summarize_trace_flow_to_dict(flow)

    # 4. Root cause z trace
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
