#!/usr/bin/env python3
"""
Root Cause Inference - Deterministické odvození root cause
==========================================================

Pravidla:
1. Žádné LLM
2. Žádná heuristická magie
3. První ERROR v trace = root

Logika:
- Projdi trace flow chronologicky
- První ERROR/WARN = pravděpodobný root cause
- Pokud není trace, použij nejvyšší score incident

Verze: 6.0
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any, List

from .trace_analysis import TraceFlow, TraceStep


@dataclass
class RootCause:
    """Inferred root cause problému."""

    # Identifikace
    service: str                         # App/deployment kde problém začal
    message: str                         # Error message
    error_type: str = ""                 # Typ chyby

    # Kontext
    timestamp: Optional[datetime] = None
    namespace: str = ""
    level: str = "ERROR"                 # ERROR, WARN, etc.

    # Confidence
    confidence: str = "high"             # high, medium, low
    inference_method: str = "trace"      # trace, score, heuristic

    # Evidence
    trace_id: Optional[str] = None
    fingerprint: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'service': self.service,
            'message': self.message[:500],
            'error_type': self.error_type,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'namespace': self.namespace,
            'level': self.level,
            'confidence': self.confidence,
            'inference_method': self.inference_method,
            'trace_id': self.trace_id,
            'fingerprint': self.fingerprint,
        }

    def to_short_string(self) -> str:
        """Krátký popis pro report."""
        return f"{self.service}: {self.message[:60]}"

    def __str__(self) -> str:
        return f"[{self.confidence.upper()}] {self.service}: {self.error_type or 'error'} - {self.message[:80]}"


def infer_root_cause(trace_flow: TraceFlow) -> Optional[RootCause]:
    """
    Odvodí root cause z trace flow.

    Algoritmus:
    1. Projdi kroky chronologicky
    2. První ERROR nebo FATAL = root cause
    3. Pokud žádný ERROR, vezmi první WARN
    4. Pokud nic, vrať None

    Args:
        trace_flow: TraceFlow k analýze

    Returns:
        RootCause nebo None
    """
    if not trace_flow.steps:
        return None

    # 1. Hledej první ERROR/FATAL
    for step in trace_flow.steps:
        if step.level in ('ERROR', 'FATAL'):
            return RootCause(
                service=step.app,
                message=step.message,
                error_type=step.error_type,
                timestamp=step.timestamp,
                namespace=step.namespace,
                level=step.level,
                confidence='high',
                inference_method='trace_error',
                trace_id=trace_flow.trace_id,
            )

    # 2. Fallback na první WARN
    for step in trace_flow.steps:
        if step.level == 'WARN':
            return RootCause(
                service=step.app,
                message=step.message,
                error_type=step.error_type,
                timestamp=step.timestamp,
                namespace=step.namespace,
                level=step.level,
                confidence='medium',
                inference_method='trace_warn',
                trace_id=trace_flow.trace_id,
            )

    # 3. Fallback na první krok
    step = trace_flow.steps[0]
    return RootCause(
        service=step.app,
        message=step.message,
        error_type=step.error_type,
        timestamp=step.timestamp,
        namespace=step.namespace,
        level=step.level,
        confidence='low',
        inference_method='trace_first',
        trace_id=trace_flow.trace_id,
    )


def infer_root_cause_from_problem(problem: Any) -> Optional[RootCause]:
    """
    Odvodí root cause z ProblemAggregate (bez trace).

    Algoritmus:
    1. Vezmi incident s nejvyšším score
    2. Použij jeho app a message

    Args:
        problem: ProblemAggregate

    Returns:
        RootCause nebo None
    """
    if not problem.incidents:
        return None

    # Najdi incident s nejvyšším score
    best_incident = max(problem.incidents, key=lambda i: i.score)

    return RootCause(
        service=best_incident.apps[0] if best_incident.apps else 'unknown',
        message=best_incident.normalized_message or '',
        error_type=best_incident.error_type or '',
        timestamp=best_incident.time.first_seen,
        namespace=best_incident.namespaces[0] if best_incident.namespaces else '',
        level='ERROR' if best_incident.score >= 60 else 'WARN',
        confidence='medium',
        inference_method='score',
        fingerprint=best_incident.fingerprint,
    )


def infer_root_cause_combined(
    problem: Any,
    trace_flows: List[TraceFlow] = None
) -> Optional[RootCause]:
    """
    Kombinovaná inference - preferuje trace, fallback na score.

    Args:
        problem: ProblemAggregate
        trace_flows: Volitelné trace flows pro problém

    Returns:
        RootCause nebo None
    """
    # 1. Pokus o trace-based inference
    if trace_flows:
        for flow in trace_flows:
            if flow.error_count > 0:
                root = infer_root_cause(flow)
                if root and root.confidence == 'high':
                    return root

    # 2. Fallback na score-based
    return infer_root_cause_from_problem(problem)


def enrich_problems_with_root_cause(
    problems: dict,
    trace_flows: dict = None
) -> dict:
    """
    Obohatí problémy o root cause.

    Args:
        problems: Dict[problem_key, ProblemAggregate]
        trace_flows: Dict[problem_key, List[TraceFlow]]

    Returns:
        Stejný dict, problémy mají nový atribut 'root_cause'
    """
    for key, problem in problems.items():
        flows = trace_flows.get(key, []) if trace_flows else []
        root = infer_root_cause_combined(problem, flows)

        # Přidej jako atribut (dynamicky)
        problem.root_cause = root

    return problems
