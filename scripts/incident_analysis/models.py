#!/usr/bin/env python3
"""
INCIDENT ANALYSIS MODELS
========================

Per-problém objekty (ne per-day agregáty).

IncidentAnalysis reprezentuje jeden problém:
- Co ho spustilo (trigger)
- Kde se projevil (scope)
- Jak se šířil (timeline)
- Proč → důsledek (causal_chain)
- Co s tím dělat (recommended_actions)
"""

from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class IncidentStatus(Enum):
    """Status incidentu"""
    ACTIVE = "active"          # Právě probíhá
    RESOLVED = "resolved"      # Vyřešeno
    INVESTIGATING = "investigating"  # Vyšetřuje se


class TriggerType(Enum):
    """Typ triggeru"""
    NEW_ERROR = "new_error"           # Nový error fingerprint
    SPIKE = "spike"                   # Spike nad prahem
    BURST = "burst"                   # Burst pattern
    CROSS_NAMESPACE = "cross_namespace"  # Cross-namespace peak
    CASCADING = "cascading"           # Error → peak v krátkém čase


class ConfidenceLevel(Enum):
    """Confidence pro inference"""
    HIGH = "high"      # >80% - jasný pattern
    MEDIUM = "medium"  # 50-80% - pravděpodobný
    LOW = "low"        # <50% - jen odhad


class ActionPriority(Enum):
    """Priorita akce"""
    IMMEDIATE = "immediate"  # Do 1 hodiny
    TODAY = "today"          # Do konce dne
    THIS_WEEK = "this_week"  # Do konce týdne
    BACKLOG = "backlog"      # Někdy


class SeverityLevel(Enum):
    """Severity = DOPAD (jak moc to bolí)"""
    CRITICAL = "critical"   # Výpadek služby
    HIGH = "high"           # Degradace
    MEDIUM = "medium"       # Opakující se problém
    LOW = "low"             # Informativní


class IncidentPriority(Enum):
    """
    Priority = AKČNOST (mám to řešit hned?)
    
    Pravidla:
    - P1: NEW AND (CRITICAL OR cross-app) → řeš HNED
    - P2: KNOWN AND worsening → řeš dnes  
    - P3: KNOWN AND stable → sleduj
    - P4: ostatní → backlog
    """
    P1 = "P1"  # Řeš HNED (3 AM call)
    P2 = "P2"  # Řeš dnes
    P3 = "P3"  # Sleduj, naplánuj
    P4 = "P4"  # Backlog


def calculate_priority(
    knowledge_status: str,
    severity: SeverityLevel,
    blast_radius: int,
    is_worsening: bool = False,
) -> Tuple['IncidentPriority', List[str]]:
    """
    Vypočítá prioritu incidentu.
    
    Returns:
        (priority, reasons)
    """
    reasons = []
    
    # P1: NEW AND (CRITICAL OR cross-app ≥3)
    if knowledge_status == "NEW":
        if severity == SeverityLevel.CRITICAL:
            reasons.append("new_incident")
            reasons.append("critical_severity")
            return IncidentPriority.P1, reasons
        if blast_radius >= 3:
            reasons.append("new_incident")
            reasons.append("cross_app_impact")
            return IncidentPriority.P1, reasons
    
    # P2: KNOWN AND worsening
    if knowledge_status == "KNOWN" and is_worsening:
        reasons.append("known_worsening")
        return IncidentPriority.P2, reasons
    
    # P3: KNOWN AND stable
    if knowledge_status == "KNOWN":
        reasons.append("known_stable")
        return IncidentPriority.P3, reasons
    
    # P2: NEW but not critical/cross-app
    if knowledge_status == "NEW":
        reasons.append("new_incident")
        return IncidentPriority.P2, reasons
    
    # P4: default
    return IncidentPriority.P4, ["low_priority"]


# =============================================================================
# TIMELINE EVENT
# =============================================================================

@dataclass
class TimelineEvent:
    """Jedna událost v timeline incidentu"""
    timestamp: datetime
    event_type: str         # error, spike, peak, downstream_error, recovery
    
    app: str
    namespace: str = ""
    version: str = ""
    
    description: str = ""
    fingerprint: str = ""
    
    # Metrics
    error_count: int = 0
    ratio: float = 1.0      # Pro spike/peak
    
    # Linkování
    is_trigger: bool = False
    is_effect: bool = False
    caused_by: str = ""     # Fingerprint triggeru


# =============================================================================
# TRIGGER
# =============================================================================

@dataclass
class IncidentTrigger:
    """Co spustilo incident"""
    trigger_type: TriggerType
    
    # Kde to začalo
    app: str
    namespace: str
    
    # Co to bylo
    fingerprint: str
    error_type: str
    message: str
    
    # Kdy
    timestamp: datetime
    
    # Optional fields
    version: str = ""
    
    # Kontext
    preceding_errors: List[str] = field(default_factory=list)  # Fingerprints
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


# =============================================================================
# SCOPE
# =============================================================================

@dataclass
class IncidentScope:
    """Kde všude se incident projevil (blast radius)"""
    
    # Affected apps
    apps: List[str] = field(default_factory=list)
    app_versions: Dict[str, List[str]] = field(default_factory=dict)  # app -> versions
    
    # Namespaces
    namespaces: List[str] = field(default_factory=list)
    
    # Fingerprints
    fingerprints: List[str] = field(default_factory=list)
    fingerprint_count: int = 0
    
    # Metrics
    total_errors: int = 0
    affected_pods: int = 0
    
    # Relationships
    upstream_apps: List[str] = field(default_factory=list)
    downstream_apps: List[str] = field(default_factory=list)
    
    @property
    def blast_radius(self) -> int:
        """Kolik apps zasaženo"""
        return len(self.apps)


# =============================================================================
# CAUSAL CHAIN
# =============================================================================

@dataclass
class CausalLink:
    """Jeden link v kauzálním řetězci"""
    cause_fingerprint: str
    effect_fingerprint: str
    
    cause_app: str
    effect_app: str
    
    cause_type: str   # error, spike, timeout, etc.
    effect_type: str
    
    time_delta_sec: int   # Jak dlouho mezi cause a effect
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


@dataclass
class CausalChain:
    """Kauzální řetězec: proč → důsledek"""
    
    # Root cause
    root_cause_fingerprint: str
    root_cause_app: str
    root_cause_type: str      # database, network, external, etc.
    root_cause_description: str
    
    # Chain of effects
    links: List[CausalLink] = field(default_factory=list)
    
    # Summary
    effects: List[str] = field(default_factory=list)  # Human-readable effects
    
    # Confidence
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    
    # Evidence
    evidence: List[str] = field(default_factory=list)


# =============================================================================
# RECOMMENDED ACTION
# =============================================================================

@dataclass
class RecommendedAction:
    """Doporučená akce"""
    title: str
    description: str
    priority: ActionPriority
    
    # Target
    target_app: str = ""
    target_config: str = ""
    
    # Details
    steps: List[str] = field(default_factory=list)
    config_change: str = ""
    code_change: str = ""
    
    # Metadata
    category: str = ""      # database, network, scaling, etc.
    estimated_effort: str = ""  # "5 min", "1 hour", etc.
    
    # Linkování
    runbook_url: str = ""
    similar_jira: str = ""
    
    # Confidence
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM


# =============================================================================
# INCIDENT ANALYSIS (hlavní objekt)
# =============================================================================

@dataclass
class IncidentAnalysis:
    """
    Kompletní analýza jednoho incidentu.
    
    TOTO JE ABSOLUTNÍ ZDROJ PRAVDY.
    Report je jen renderer - nesmí nic přepočítávat!
    
    Struktura:
    - incident_id
    - trigger (co to spustilo)
    - time (kdy)
    - scope (kde)
    - timeline (jak se to šířilo) - FACTS
    - causal_chain (proč) - HYPOTHESIS
    - confidence
    - recommended_actions
    - knowledge (known vs new) - vyplňuje KnowledgeMatcher
    """
    
    # ===== IDENTITY =====
    incident_id: str
    
    # ===== STATUS =====
    status: IncidentStatus = IncidentStatus.ACTIVE
    severity: SeverityLevel = SeverityLevel.MEDIUM
    
    # ===== PRIORITY (klíčové pro operační použití!) =====
    priority: IncidentPriority = IncidentPriority.P4
    priority_reasons: List[str] = field(default_factory=list)
    
    # ===== IMMEDIATE ACTIONS (1-3 kroky pro SRE ve 3 ráno) =====
    immediate_actions: List[str] = field(default_factory=list)
    
    # ===== TRIGGER (co to spustilo) =====
    trigger: Optional[IncidentTrigger] = None
    
    # ===== SCOPE (kde) =====
    scope: IncidentScope = field(default_factory=IncidentScope)
    
    # ===== TIMELINE (FACTS - detekované události) =====
    timeline: List[TimelineEvent] = field(default_factory=list)
    
    # ===== CAUSAL CHAIN (HYPOTHESIS - odvozený root cause) =====
    causal_chain: Optional[CausalChain] = None
    
    # ===== RECOMMENDED ACTIONS =====
    recommended_actions: List[RecommendedAction] = field(default_factory=list)
    
    # ===== TIMING =====
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_sec: int = 0
    
    # ===== METRICS (FACTS) =====
    total_errors: int = 0
    peak_error_rate: float = 0.0
    
    # ===== LINKOVÁNÍ =====
    linked_errors: List[str] = field(default_factory=list)
    linked_peaks: List[str] = field(default_factory=list)
    related_incidents: List[str] = field(default_factory=list)
    
    # ===== CONFIDENCE =====
    overall_confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    
    # ===== KNOWLEDGE MATCHING (vyplňuje KnowledgeMatcher, ne engine!) =====
    knowledge_status: str = "NEW"           # "KNOWN" nebo "NEW"
    knowledge_id: str = ""                  # "KE-001" nebo "KP-001"
    knowledge_confidence: Optional[ConfidenceLevel] = None
    knowledge_match_reason: str = ""
    knowledge_jira: str = ""
    knowledge_workaround: List[str] = field(default_factory=list)
    knowledge_permanent_fix: List[str] = field(default_factory=list)
    
    # ===== METADATA =====
    detected_at: datetime = field(default_factory=lambda: datetime.now())
    last_updated: datetime = field(default_factory=lambda: datetime.now())
    
    # ===== HUMAN-READABLE =====
    title: str = ""
    summary: str = ""
    
    def get_primary_app(self) -> str:
        """Hlavní zasažená aplikace"""
        if self.trigger:
            return self.trigger.app
        if self.scope.apps:
            return self.scope.apps[0]
        return "unknown"
    
    def get_root_cause_summary(self) -> str:
        """Shrnutí root cause"""
        if self.causal_chain:
            return self.causal_chain.root_cause_description
        return "Unknown root cause"
    
    def get_top_action(self) -> Optional[RecommendedAction]:
        """Nejdůležitější akce"""
        if self.recommended_actions:
            return self.recommended_actions[0]
        return None


# =============================================================================
# INCIDENT ANALYSIS RESULT (výstup enginu)
# =============================================================================

@dataclass
class IncidentAnalysisResult:
    """Výsledek analýzy - kolekce incidentů"""
    
    # Časový rozsah
    analysis_start: datetime
    analysis_end: datetime
    
    # Incidenty
    incidents: List[IncidentAnalysis] = field(default_factory=list)
    
    # Statistiky
    total_incidents: int = 0
    active_incidents: int = 0
    resolved_incidents: int = 0
    
    # By severity
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    
    # Metadata
    analysis_duration_ms: int = 0
    
    def get_active_incidents(self) -> List[IncidentAnalysis]:
        """Aktivní incidenty"""
        return [i for i in self.incidents if i.status == IncidentStatus.ACTIVE]
    
    def get_critical_incidents(self) -> List[IncidentAnalysis]:
        """Kritické incidenty"""
        return [i for i in self.incidents if i.severity == SeverityLevel.CRITICAL]
    
    def get_by_app(self, app: str) -> List[IncidentAnalysis]:
        """Incidenty pro konkrétní app"""
        return [i for i in self.incidents if app in i.scope.apps]


# =============================================================================
# ROOT CAUSE RULES (statické, bez AI)
# =============================================================================

ROOT_CAUSE_RULES = {
    'database': {
        'connection_pool': {
            'description': 'Database connection pool exhausted',
            'evidence': ['HikariPool', 'connection pool', 'no available connection', 'pool exhausted'],
            'actions': [
                {
                    'title': 'Increase connection pool size',
                    'priority': ActionPriority.IMMEDIATE,
                    'config_change': 'spring.datasource.hikari.maximum-pool-size: 25',
                    'estimated_effort': '5 min',
                },
                {
                    'title': 'Check slow queries',
                    'priority': ActionPriority.TODAY,
                    'steps': ['Review slow query log', 'Check for missing indexes', 'Optimize N+1 queries'],
                    'estimated_effort': '2 hours',
                },
            ],
        },
        'deadlock': {
            'description': 'Database deadlock between transactions',
            'evidence': ['deadlock', 'lock wait timeout', 'could not serialize'],
            'actions': [
                {
                    'title': 'Use SELECT FOR UPDATE NOWAIT',
                    'priority': ActionPriority.TODAY,
                    'code_change': 'Add NOWAIT to prevent blocking',
                    'estimated_effort': '2 hours',
                },
            ],
        },
        'constraint': {
            'description': 'Database constraint violation',
            'evidence': ['duplicate key', 'unique constraint', 'foreign key'],
            'actions': [
                {
                    'title': 'Implement upsert logic',
                    'priority': ActionPriority.TODAY,
                    'code_change': 'INSERT ... ON CONFLICT DO UPDATE',
                    'estimated_effort': '1 hour',
                },
            ],
        },
    },
    'network': {
        'connection_refused': {
            'description': 'Target service down or port blocked',
            'evidence': ['connection refused', 'ECONNREFUSED', 'connect failed'],
            'actions': [
                {
                    'title': 'Check target service health',
                    'priority': ActionPriority.IMMEDIATE,
                    'steps': ['kubectl get pods', 'Check service logs', 'Verify network policy'],
                    'estimated_effort': '15 min',
                },
            ],
        },
        'connection_reset': {
            'description': 'Network connection reset by peer',
            'evidence': ['connection reset', 'ECONNRESET', 'broken pipe'],
            'actions': [
                {
                    'title': 'Add retry with backoff',
                    'priority': ActionPriority.TODAY,
                    'code_change': 'Add @Retryable annotation',
                    'estimated_effort': '1 hour',
                },
            ],
        },
    },
    'timeout': {
        'read': {
            'description': 'Downstream service responding slowly',
            'evidence': ['read timed out', 'SocketTimeoutException', 'read timeout'],
            'actions': [
                {
                    'title': 'Increase read timeout',
                    'priority': ActionPriority.IMMEDIATE,
                    'config_change': 'client.read-timeout: 30s',
                    'estimated_effort': '5 min',
                },
                {
                    'title': 'Add circuit breaker',
                    'priority': ActionPriority.THIS_WEEK,
                    'code_change': 'Add @CircuitBreaker with Resilience4j',
                    'estimated_effort': '4 hours',
                },
            ],
        },
        'connect': {
            'description': 'Cannot establish connection to target',
            'evidence': ['connect timed out', 'connection timeout'],
            'actions': [
                {
                    'title': 'Check target service capacity',
                    'priority': ActionPriority.IMMEDIATE,
                    'estimated_effort': '15 min',
                },
            ],
        },
    },
    'external': {
        'rate_limit': {
            'description': 'External API rate limit exceeded',
            'evidence': ['429', 'rate limit', 'too many requests'],
            'actions': [
                {
                    'title': 'Implement client-side rate limiting',
                    'priority': ActionPriority.TODAY,
                    'estimated_effort': '2 hours',
                },
                {
                    'title': 'Add response caching',
                    'priority': ActionPriority.THIS_WEEK,
                    'estimated_effort': '4 hours',
                },
            ],
        },
        'unavailable': {
            'description': 'External service unavailable',
            'evidence': ['503', 'service unavailable', 'upstream'],
            'actions': [
                {
                    'title': 'Add circuit breaker with fallback',
                    'priority': ActionPriority.THIS_WEEK,
                    'estimated_effort': '4 hours',
                },
            ],
        },
    },
    'memory': {
        'oom': {
            'description': 'Out of memory - heap exhausted',
            'evidence': ['OutOfMemoryError', 'heap space', 'GC overhead'],
            'actions': [
                {
                    'title': 'Increase heap size',
                    'priority': ActionPriority.IMMEDIATE,
                    'config_change': '-Xmx4g',
                    'estimated_effort': '5 min',
                },
                {
                    'title': 'Analyze heap dump',
                    'priority': ActionPriority.TODAY,
                    'steps': ['Generate heap dump', 'Analyze with MAT', 'Find memory leak'],
                    'estimated_effort': '2 hours',
                },
            ],
        },
    },
    'business': {
        'not_found': {
            'description': 'Referenced entity does not exist',
            'evidence': ['not found', 'does not exist', '404'],
            'actions': [
                {
                    'title': 'Add existence check',
                    'priority': ActionPriority.TODAY,
                    'estimated_effort': '1 hour',
                },
            ],
        },
        'validation': {
            'description': 'Input validation failure',
            'evidence': ['validation', 'invalid', 'constraint violation'],
            'actions': [
                {
                    'title': 'Add API gateway validation',
                    'priority': ActionPriority.THIS_WEEK,
                    'estimated_effort': '2 hours',
                },
            ],
        },
    },
}


def get_root_cause_rule(category: str, subcategory: str) -> Optional[Dict]:
    """Najde pravidlo pro root cause"""
    if category in ROOT_CAUSE_RULES:
        if subcategory in ROOT_CAUSE_RULES[category]:
            return ROOT_CAUSE_RULES[category][subcategory]
    return None


def match_evidence(message: str, evidence_patterns: List[str]) -> List[str]:
    """Najde matching evidence v message"""
    found = []
    message_lower = message.lower()
    for pattern in evidence_patterns:
        if pattern.lower() in message_lower:
            found.append(pattern)
    return found
