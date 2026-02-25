#!/usr/bin/env python3
"""
Problem Aggregator - Agregace incidentů do problémů
===================================================

KLÍČOVÁ ZMĚNA: Incidenty už nikdy nejdou přímo do reportu!

Tok:
1. Incidenty přijdou z pipeline
2. aggregate_by_problem_key() je seskupí podle problem_key
3. Každý ProblemAggregate obsahuje všechna data pro analýzu
4. Report iteruje přes problémy, ne incidenty

Změny:
- Robustní výpočet occurrences z více zdrojů (ne jen stats.current_count)
- Vylepšené priority scoring s log-scale occurrences a fan-out bonus
- Lepší diferenciace mezi MEDIUM problémy
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Set, Optional, Any
from collections import defaultdict


@dataclass
class ProblemAggregate:
    """
    Agregovaný problém - primární analytická jednotka.

    Jeden problém může mít N incidentů (různé fingerprinty, časy, atd.)
    """

    # Identifikace
    problem_key: str                     # category:flow:error_class
    category: str = "unknown"
    flow: str = "unknown"
    error_class: str = "unknown"

    # Počty
    incident_count: int = 0              # Počet incidentů
    total_occurrences: int = 0           # Součet všech occurrence_counts

    # Časové rozmezí (z event timestamps)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None

    # Fingerprinty (unikátní)
    fingerprints: Set[str] = field(default_factory=set)

    # Entity (agregované přes všechny incidenty)
    apps: Set[str] = field(default_factory=set)
    namespaces: Set[str] = field(default_factory=set)
    app_versions: Set[str] = field(default_factory=set)
    deployment_labels: Set[str] = field(default_factory=set)
    environments: Set[str] = field(default_factory=set)

    # Trace IDs (jen unikátní, pro další analýzu)
    trace_ids: Set[str] = field(default_factory=set)
    trace_count: int = 0

    # === BEHAVIOR / TRACE FLOW ===
    # Reprezentativní trace pro "příběh" problému
    representative_trace_id: Optional[str] = None
    trace_flow_summary: List[Dict[str, Any]] = field(default_factory=list)  # 2+1 kroky
    trace_root_cause: Optional[Dict[str, Any]] = None  # {service, message, level}

    # Flags (OR přes všechny incidenty)
    has_spike: bool = False
    has_burst: bool = False
    has_new: bool = False
    has_regression: bool = False
    has_cascade: bool = False
    is_cross_namespace: bool = False

    # Nejvyšší score z incidentů
    max_score: float = 0.0
    max_severity: str = "info"

    # Raw samples (max 5)
    sample_messages: List[str] = field(default_factory=list)
    normalized_message: str = ""         # Reprezentativní message
    error_type: str = ""

    # Incidenty (pro detailní analýzu)
    _incidents: List[Any] = field(default_factory=list, repr=False)

    def add_incident(self, incident: Any):
        """
        Přidá incident do agregace.

        Args:
            incident: Incident object z pipeline
        """
        self._incidents.append(incident)
        self.incident_count += 1

        # Počty - robustní výpočet z více zdrojů
        count = _get_incident_occurrence_count(incident)
        self.total_occurrences += count

        # Fingerprint
        self.fingerprints.add(incident.fingerprint)

        # Časové rozmezí
        if incident.time.first_seen:
            if self.first_seen is None or incident.time.first_seen < self.first_seen:
                self.first_seen = incident.time.first_seen
        if incident.time.last_seen:
            if self.last_seen is None or incident.time.last_seen > self.last_seen:
                self.last_seen = incident.time.last_seen

        # Entity
        self.apps.update(incident.apps)
        self.namespaces.update(incident.namespaces)
        self.app_versions.update(incident.app_versions)
        self.deployment_labels.update(incident.deployment_labels)
        self.environments.update(incident.environments)

        # Trace IDs
        if hasattr(incident, 'trace_ids'):
            self.trace_ids.update(incident.trace_ids)
        if hasattr(incident, 'trace_info') and incident.trace_info:
            self.trace_ids.update(incident.trace_info.trace_ids)
        self.trace_count = len(self.trace_ids)

        # Flags (OR)
        self.has_spike = self.has_spike or incident.flags.is_spike
        self.has_burst = self.has_burst or incident.flags.is_burst
        self.has_new = self.has_new or incident.flags.is_new
        self.has_regression = self.has_regression or incident.flags.is_regression
        self.has_cascade = self.has_cascade or incident.flags.is_cascade
        self.is_cross_namespace = self.is_cross_namespace or incident.flags.is_cross_namespace

        # Score (max)
        if incident.score > self.max_score:
            self.max_score = incident.score
            self.max_severity = incident.severity.value

        # Samples
        if len(self.sample_messages) < 5 and incident.raw_samples:
            for sample in incident.raw_samples:
                if sample not in self.sample_messages and len(self.sample_messages) < 5:
                    self.sample_messages.append(sample)

        # Reprezentativní message (první)
        if not self.normalized_message and incident.normalized_message:
            self.normalized_message = incident.normalized_message
        if not self.error_type and incident.error_type:
            self.error_type = incident.error_type

    @property
    def incidents(self) -> List[Any]:
        """Vrátí seznam incidentů pro detailní analýzu."""
        return self._incidents

    @property
    def duration_sec(self) -> int:
        """Celková doba trvání problému v sekundách."""
        if self.first_seen and self.last_seen:
            return int((self.last_seen - self.first_seen).total_seconds())
        return 0

    @property
    def namespace_count(self) -> int:
        """Počet affected namespaces."""
        return len(self.namespaces)

    @property
    def app_count(self) -> int:
        """Počet affected apps."""
        return len(self.apps)

    @property
    def flag_summary(self) -> str:
        """Shrnutí aktivních flagů."""
        flags = []
        if self.has_new:
            flags.append("NEW")
        if self.has_spike:
            flags.append("SPIKE")
        if self.has_burst:
            flags.append("BURST")
        if self.has_regression:
            flags.append("REGRESSION")
        if self.has_cascade:
            flags.append("CASCADE")
        if self.is_cross_namespace:
            flags.append("CROSS_NS")
        return " | ".join(flags) if flags else "-"

    def to_dict(self) -> dict:
        """Serializace pro export."""
        return {
            'problem_key': self.problem_key,
            'category': self.category,
            'flow': self.flow,
            'error_class': self.error_class,
            'incident_count': self.incident_count,
            'total_occurrences': self.total_occurrences,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'duration_sec': self.duration_sec,
            'fingerprints': list(self.fingerprints),
            'fingerprint_count': len(self.fingerprints),
            'apps': sorted(self.apps),
            'namespaces': sorted(self.namespaces),
            'app_versions': sorted(self.app_versions),
            'deployment_labels': sorted(self.deployment_labels),
            'environments': sorted(self.environments),
            'trace_count': self.trace_count,
            # Behavior / Trace Flow
            'trace': {
                'representative_trace_id': self.representative_trace_id,
                'flow_summary': self.trace_flow_summary,
                'root_cause': self.trace_root_cause,
            } if self.representative_trace_id else None,
            'flags': {
                'has_spike': self.has_spike,
                'has_burst': self.has_burst,
                'has_new': self.has_new,
                'has_regression': self.has_regression,
                'has_cascade': self.has_cascade,
                'is_cross_namespace': self.is_cross_namespace,
            },
            'max_score': self.max_score,
            'max_severity': self.max_severity,
            'normalized_message': self.normalized_message,
            'error_type': self.error_type,
            'sample_messages': self.sample_messages[:3],
        }


def aggregate_by_problem_key(incidents: List[Any]) -> Dict[str, ProblemAggregate]:
    """
    Agreguje incidenty do problémů podle problem_key.

    CRITICAL: Toto je hlavní vstupní bod pro problem-centric analýzu.

    Args:
        incidents: Seznam Incident objektů z pipeline

    Returns:
        Dict[problem_key, ProblemAggregate]
    """
    problems: Dict[str, ProblemAggregate] = {}

    for incident in incidents:
        # Získej problem_key z incidentu (nebo ho vypočítej)
        problem_key = _get_problem_key(incident)

        if problem_key not in problems:
            # Parsuj problem_key
            parts = problem_key.split(":", 2)
            category = parts[0] if len(parts) > 0 else "unknown"
            flow = parts[1] if len(parts) > 1 else "unknown"
            error_class = parts[2] if len(parts) > 2 else "unknown"

            problems[problem_key] = ProblemAggregate(
                problem_key=problem_key,
                category=category,
                flow=flow,
                error_class=error_class,
            )

        problems[problem_key].add_incident(incident)

    return problems


def _get_incident_occurrence_count(incident: Any, debug: bool = False) -> int:
    """
    Získá počet occurrences z incidentu (robustní).

    Hierarchie zdrojů:
    1. incident.stats.current_count (pokud > 0)
    2. incident.trace_info.trace_count (pokud > 0)
    3. len(incident.raw_samples) (pokud > 0)
    4. Fallback: 1 (každý incident = minimálně 1 occurrence)

    Args:
        incident: Incident objekt
        debug: Pokud True, loguje zdroj hodnoty

    Returns:
        int: Počet occurrences (vždy >= 1)
    """
    source = "fallback"
    count = 1

    # 1. Primary source: stats.current_count
    if hasattr(incident, 'stats') and incident.stats:
        stats_count = getattr(incident.stats, 'current_count', 0)
        if stats_count and stats_count > 0:
            count = stats_count
            source = "stats.current_count"
            if debug:
                _log_occurrence_source(incident, count, source)
            return count

    # 2. Fallback: trace count
    if hasattr(incident, 'trace_info') and incident.trace_info:
        trace_count = getattr(incident.trace_info, 'trace_count', 0)
        if trace_count and trace_count > 0:
            count = trace_count
            source = "trace_info.trace_count"
            if debug:
                _log_occurrence_source(incident, count, source)
            return count

    # 3. Fallback: raw samples count (pokud není 0)
    if hasattr(incident, 'raw_samples') and incident.raw_samples:
        sample_count = len(incident.raw_samples)
        if sample_count > 0:
            count = sample_count
            source = "raw_samples.length"
            if debug:
                _log_occurrence_source(incident, count, source)
            return count

    # 4. Ultimate fallback: každý incident = 1 occurrence
    if debug:
        _log_occurrence_source(incident, count, source)
    return count


def _log_occurrence_source(incident: Any, count: int, source: str):
    """Loguje zdroj occurrence count (pro debug/audit)."""
    import logging
    logger = logging.getLogger('problem_aggregator')
    fingerprint = getattr(incident, 'fingerprint', 'unknown')[:16]
    logger.debug(f"Occurrence count: {count} from {source} (incident: {fingerprint}...)")


def _get_problem_key(incident: Any) -> str:
    """
    Získá nebo vypočítá problem_key pro incident.

    Hierarchie:
    1. incident.problem_key (pokud existuje)
    2. Vypočítat z category + flow + error_class
    3. Fallback na fingerprint
    """
    # 1. Přímý problem_key
    if hasattr(incident, 'problem_key') and incident.problem_key:
        return incident.problem_key

    # 2. Vypočítat z komponent
    category = incident.category.value if hasattr(incident.category, 'value') else str(incident.category)

    # Flow z apps
    flow = _extract_flow(incident.apps)

    # Error class z error_type nebo normalized_message
    error_class = _extract_error_class(incident.error_type, incident.normalized_message)

    return f"{category}:{flow}:{error_class}"


def _extract_flow(apps: List[str]) -> str:
    """Extrahuje flow z názvů aplikací."""
    if not apps:
        return "unknown"

    # Známé flow patterny
    flow_patterns = {
        'card': 'card_servicing',
        'payment': 'payments',
        'auth': 'authentication',
        'user': 'user_management',
        'notification': 'notifications',
        'report': 'reporting',
        'batch': 'batch_processing',
        'api': 'api_gateway',
        'gateway': 'api_gateway',
        'queue': 'messaging',
        'kafka': 'messaging',
        'rabbit': 'messaging',
        'redis': 'caching',
        'cache': 'caching',
        'db': 'database',
        'postgres': 'database',
        'mysql': 'database',
        'mongo': 'database',
    }

    for app in apps:
        app_lower = app.lower()
        for pattern, flow in flow_patterns.items():
            if pattern in app_lower:
                return flow

    # Default: první app bez verze
    base_app = apps[0].split('-v')[0].split('-')[0] if apps else "unknown"
    return base_app


def _extract_error_class(error_type: str, normalized_message: str) -> str:
    """Extrahuje error class z error_type nebo message."""
    if error_type:
        # Normalize error type
        et = error_type.lower()

        # Známé error classes
        if 'connection' in et or 'connect' in et:
            return 'connection_error'
        if 'timeout' in et:
            return 'timeout_error'
        if 'validation' in et or 'invalid' in et:
            return 'validation_error'
        if 'auth' in et or 'unauthorized' in et or 'forbidden' in et:
            return 'auth_error'
        if 'null' in et or 'npe' in et:
            return 'null_pointer'
        if 'outofmemory' in et or 'oom' in et:
            return 'memory_error'
        if 'sql' in et or 'database' in et or 'db' in et:
            return 'database_error'

        # Použij error type přímo (normalizovaný)
        return error_type.replace(' ', '_').lower()[:50]

    if normalized_message:
        # Extrahuj z message
        msg_lower = normalized_message.lower()

        if 'connection refused' in msg_lower or 'connection reset' in msg_lower:
            return 'connection_error'
        if 'timeout' in msg_lower or 'timed out' in msg_lower:
            return 'timeout_error'
        if 'validation' in msg_lower or 'invalid' in msg_lower:
            return 'validation_error'
        if 'unauthorized' in msg_lower or '401' in msg_lower:
            return 'auth_error'
        if 'not found' in msg_lower or '404' in msg_lower:
            return 'not_found'
        if '500' in msg_lower or 'internal server' in msg_lower:
            return 'server_error'

    return 'unknown_error'


def sort_problems_by_priority(
    problems: Dict[str, ProblemAggregate]
) -> List[ProblemAggregate]:
    """
    Seřadí problémy podle priority pro report.

    Vylepšený composite scoring pro lepší diferenciaci.
    Upper cap + stabilní tie-breaker.

    Kritéria (vážená kombinace):
    1. max_score (základ)
    2. occurrences bonus (log scale - masivní problémy mají přednost)
    3. fan_out bonus (propagace přes více služeb)
    4. confidence bonus (high confidence root cause)
    5. new problem bonus
    6. cross_namespace bonus

    Stabilita:
    - Upper cap 150 - extrémní outlier nerozbije TOP list
    - Deterministický tie-breaker přes problem_key
    """
    import math

    # Upper cap pro score - extrémní outlier nesmí odsunout všechno ostatní
    SCORE_CAP = 150.0

    def compute_priority_score(p: ProblemAggregate) -> float:
        """Vypočítá composite priority score."""
        score = p.max_score  # Základ: 0-100

        # Occurrences bonus (log scale, max +20)
        if p.total_occurrences > 0:
            occ_bonus = min(20, math.log10(p.total_occurrences + 1) * 6)
            score += occ_bonus

        # Fan-out bonus (počet affected apps, max +10)
        fan_out = len(p.apps) - 1 if len(p.apps) > 1 else 0
        score += min(10, fan_out * 2)

        # Confidence bonus (from trace_root_cause)
        if hasattr(p, 'trace_root_cause') and p.trace_root_cause:
            confidence = p.trace_root_cause.get('confidence', '')
            if confidence == 'high':
                score += 10
            elif confidence == 'medium':
                score += 5

        # New problem bonus
        if p.has_new:
            score += 8

        # Cross-namespace bonus
        if p.is_cross_namespace:
            score += 5

        # Spike/Burst bonus
        if p.has_spike:
            score += 5
        if p.has_burst:
            score += 3

        # Apply upper cap
        return min(score, SCORE_CAP)

    return sorted(
        problems.values(),
        key=lambda p: (
            -compute_priority_score(p),
            -p.total_occurrences,  # Tie-breaker 1: volume
            -p.incident_count,     # Tie-breaker 2: incident count
            p.problem_key,         # Tie-breaker 3: deterministic (alphabetical)
        )
    )


def filter_problems(
    problems: Dict[str, ProblemAggregate],
    min_score: float = 0,
    min_occurrences: int = 0,
    categories: List[str] = None,
    only_new: bool = False,
    only_spike: bool = False,
) -> Dict[str, ProblemAggregate]:
    """
    Filtruje problémy podle kritérií.
    """
    result = {}

    for key, problem in problems.items():
        if problem.max_score < min_score:
            continue
        if problem.total_occurrences < min_occurrences:
            continue
        if categories and problem.category not in categories:
            continue
        if only_new and not problem.has_new:
            continue
        if only_spike and not problem.has_spike:
            continue

        result[key] = problem

    return result
