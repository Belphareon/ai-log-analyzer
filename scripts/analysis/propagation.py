#!/usr/bin/env python3
"""
Propagation Analysis - Analýza šíření problémů
==============================================

ZMĚNA oproti V5:
- TEĎ: boolean CROSS_NS + neurčitý text
- NOVĚ: seznam služeb, root service, propagation path

Logika:
- Použij trace flow k určení směru propagace
- root = první služba v trace
- affected = všechny další služby

V6.3 změny:
- propagation_time_ms se počítá POUZE z trace dat
- Pokud nemáme trace, duration = 0 (N/A)
- Opraveny nesmyslné hodnoty jako 47176523ms (13 hodin)

Verze: 6.3
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any, Dict, Set

from .trace_analysis import TraceFlow


@dataclass
class PropagationResult:
    """Výsledek propagation analýzy."""

    # Root
    root_service: str = ""               # Služba kde problém začal
    root_namespace: str = ""             # Namespace root služby

    # Affected
    affected_services: List[str] = field(default_factory=list)  # Seznam všech služeb
    affected_namespaces: List[str] = field(default_factory=list)

    # Propagation path
    propagation_path: List[str] = field(default_factory=list)  # Cesta šíření

    # Metrics
    service_count: int = 0               # Počet služeb
    namespace_count: int = 0             # Počet namespaces
    fan_out: int = 0                     # Počet služeb zasažených z root

    # Časové info
    propagation_time_ms: int = 0         # Čas od root k poslední službě
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    # Classification
    is_cross_namespace: bool = False     # Šíří se přes namespaces?
    is_cascading: bool = False           # Kaskádové selhání?
    propagation_type: str = "none"       # none, single, linear, fan_out, cascade

    def to_dict(self) -> dict:
        return {
            'root_service': self.root_service,
            'root_namespace': self.root_namespace,
            'affected_services': self.affected_services,
            'affected_namespaces': self.affected_namespaces,
            'propagation_path': self.propagation_path,
            'service_count': self.service_count,
            'namespace_count': self.namespace_count,
            'fan_out': self.fan_out,
            'propagation_time_ms': self.propagation_time_ms,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'is_cross_namespace': self.is_cross_namespace,
            'is_cascading': self.is_cascading,
            'propagation_type': self.propagation_type,
        }

    def to_short_string(self) -> str:
        """Krátký popis pro report."""
        if not self.affected_services:
            return "No propagation"

        path = " → ".join(self.propagation_path[:4])
        if len(self.propagation_path) > 4:
            path += f" → ... ({len(self.propagation_path)} total)"

        return path

    def __str__(self) -> str:
        if self.service_count <= 1:
            return f"[{self.propagation_type.upper()}] Single service: {self.root_service}"

        return f"[{self.propagation_type.upper()}] {self.root_service} → {self.service_count} services ({self.propagation_time_ms}ms)"


def analyze_propagation(trace_flow: TraceFlow) -> PropagationResult:
    """
    Analyzuje propagaci z trace flow.

    Args:
        trace_flow: TraceFlow k analýze

    Returns:
        PropagationResult
    """
    result = PropagationResult()

    if not trace_flow.steps:
        result.propagation_type = "none"
        return result

    # Extrahuj služby (unique, v pořadí)
    services = []
    namespaces = set()
    seen_services = set()

    for step in trace_flow.steps:
        if step.app not in seen_services:
            seen_services.add(step.app)
            services.append(step.app)
        namespaces.add(step.namespace)

    # Root = první služba
    result.root_service = services[0] if services else ""
    result.root_namespace = trace_flow.steps[0].namespace if trace_flow.steps else ""

    # Affected = všechny služby
    result.affected_services = services
    result.affected_namespaces = sorted(namespaces)
    result.propagation_path = services

    # Metrics
    result.service_count = len(services)
    result.namespace_count = len(namespaces)
    result.fan_out = result.service_count - 1  # Služby mimo root

    # Časové info
    if trace_flow.steps:
        result.first_seen = trace_flow.steps[0].timestamp
        result.last_seen = trace_flow.steps[-1].timestamp
        result.propagation_time_ms = trace_flow.duration_ms

    # Classification
    result.is_cross_namespace = result.namespace_count > 1
    result.is_cascading = result.service_count >= 3 and trace_flow.error_count >= 2

    # Propagation type
    if result.service_count <= 1:
        result.propagation_type = "single"
    elif result.is_cascading:
        result.propagation_type = "cascade"
    elif result.service_count == 2:
        result.propagation_type = "linear"
    else:
        result.propagation_type = "fan_out"

    return result


def analyze_propagation_from_problem(problem: Any) -> PropagationResult:
    """
    Analyzuje propagaci přímo z ProblemAggregate (bez trace).

    V6.3: Duration se NEPOČÍTÁ z problem.first_seen/last_seen (to je celý den),
    ale pouze z trace dat. Pokud nemáme trace, duration = 0 (N/A).

    Args:
        problem: ProblemAggregate

    Returns:
        PropagationResult
    """
    result = PropagationResult()

    # Služby z problému
    services = sorted(problem.apps) if hasattr(problem, 'apps') else []
    namespaces = sorted(problem.namespaces) if hasattr(problem, 'namespaces') else []

    if not services:
        result.propagation_type = "none"
        return result

    # Root = první app (abecedně, nemáme lepší info)
    result.root_service = services[0]
    result.root_namespace = namespaces[0] if namespaces else ""

    # Affected
    result.affected_services = services
    result.affected_namespaces = namespaces
    result.propagation_path = services

    # Metrics
    result.service_count = len(services)
    result.namespace_count = len(namespaces)
    result.fan_out = max(0, result.service_count - 1)

    # V6.3: Časové info - BEZ DURATION (ta je smysluplná pouze z trace)
    # problem.first_seen/last_seen reprezentuje časový rozsah problému, ne propagace
    if hasattr(problem, 'first_seen'):
        result.first_seen = problem.first_seen
    if hasattr(problem, 'last_seen'):
        result.last_seen = problem.last_seen
    # V6.3: propagation_time_ms = 0 (N/A) pokud nemáme trace data
    # Nesmyslné hodnoty jako 47176523ms (13 hodin) byly způsobeny použitím
    # časového rozsahu celého problému místo jednoho trace
    result.propagation_time_ms = 0

    # Classification
    result.is_cross_namespace = result.namespace_count > 1

    # Propagation type
    if result.service_count <= 1:
        result.propagation_type = "single"
    elif result.service_count == 2:
        result.propagation_type = "linear"
    else:
        result.propagation_type = "fan_out"

    return result


def analyze_propagation_combined(
    problem: Any,
    trace_flows: List[TraceFlow] = None
) -> PropagationResult:
    """
    Kombinovaná analýza - preferuje trace, fallback na problem data.

    Args:
        problem: ProblemAggregate
        trace_flows: Volitelné trace flows

    Returns:
        PropagationResult
    """
    # 1. Pokus o trace-based analýzu
    if trace_flows:
        # Vyber trace s nejvíce službami
        best_flow = max(trace_flows, key=lambda f: f.service_count, default=None)
        if best_flow and best_flow.service_count > 1:
            return analyze_propagation(best_flow)

    # 2. Fallback na problem-based
    return analyze_propagation_from_problem(problem)


def enrich_problems_with_propagation(
    problems: dict,
    trace_flows: dict = None
) -> dict:
    """
    Obohatí problémy o propagation info.

    Args:
        problems: Dict[problem_key, ProblemAggregate]
        trace_flows: Dict[problem_key, List[TraceFlow]]

    Returns:
        Stejný dict, problémy mají nový atribut 'propagation_result'
    """
    for key, problem in problems.items():
        flows = trace_flows.get(key, []) if trace_flows else []
        prop = analyze_propagation_combined(problem, flows)

        # Přidej jako atribut (dynamicky)
        problem.propagation_result = prop

    return problems


def get_propagation_summary(problems: dict) -> dict:
    """
    Vytvoří summary propagace přes všechny problémy.

    Returns:
        {
            'total_cascades': int,
            'cross_namespace_count': int,
            'avg_fan_out': float,
            'most_affected_services': List[str],
        }
    """
    cascades = 0
    cross_ns = 0
    fan_outs = []
    service_hits: Dict[str, int] = {}

    for problem in problems.values():
        if not hasattr(problem, 'propagation_result'):
            continue

        prop = problem.propagation_result

        if prop.is_cascading:
            cascades += 1
        if prop.is_cross_namespace:
            cross_ns += 1
        if prop.fan_out > 0:
            fan_outs.append(prop.fan_out)

        for svc in prop.affected_services:
            service_hits[svc] = service_hits.get(svc, 0) + 1

    # Top services
    top_services = sorted(service_hits.items(), key=lambda x: -x[1])[:10]

    return {
        'total_cascades': cascades,
        'cross_namespace_count': cross_ns,
        'avg_fan_out': sum(fan_outs) / len(fan_outs) if fan_outs else 0,
        'max_fan_out': max(fan_outs) if fan_outs else 0,
        'most_affected_services': [s[0] for s in top_services],
        'service_hit_counts': dict(top_services),
    }
