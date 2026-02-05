#!/usr/bin/env python3
"""
DAILY ANALYSIS REPORT - Datové struktury
=========================================

Implementace podle návrhu:
- Primární osa = DEN
- Report = interpretace, ne dump
- Vše deterministické, bez AI
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum


class DayStatus(Enum):
    """Status dne"""
    IMPROVING = "IMPROVING"
    STABLE = "STABLE"
    DEGRADING = "DEGRADING"
    CRITICAL = "CRITICAL"


@dataclass
class DailyStatistics:
    """Statistiky za den"""
    total_errors: int = 0
    total_incidents: int = 0
    
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_category: Dict[str, int] = field(default_factory=dict)
    by_namespace: Dict[str, int] = field(default_factory=dict)
    by_app: Dict[str, int] = field(default_factory=dict)


@dataclass
class AppErrorSummary:
    """Souhrn errorů pro jednu aplikaci za den"""
    app_name: str
    total_errors: int = 0
    unique_fingerprints: int = 0
    versions: List[str] = field(default_factory=list)
    namespaces: List[str] = field(default_factory=list)
    
    # Top errors: [{fingerprint, message, count, severity, flags}]
    top_errors: List[Dict] = field(default_factory=list)
    
    # Propojené aplikace (sdílejí stejné errory)
    related_apps: List[str] = field(default_factory=list)


@dataclass
class ErrorCluster:
    """Skupina souvisejících errorů - pravděpodobně stejný root cause"""
    cluster_id: str
    category: str  # database/connection, network/timeout, etc.
    
    fingerprints: List[str] = field(default_factory=list)
    affected_apps: List[str] = field(default_factory=list)
    affected_namespaces: List[str] = field(default_factory=list)
    
    total_occurrences: int = 0
    sample_messages: List[str] = field(default_factory=list)
    
    # Inference
    hypothesis: str = ""
    suggested_fixes: List[str] = field(default_factory=list)
    
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None


@dataclass
class TimelineEvent:
    """Událost v timeline"""
    timestamp: datetime
    event_type: str  # first_error, spike, cross_app, stabilized
    description: str
    fingerprints: List[str] = field(default_factory=list)
    apps: List[str] = field(default_factory=list)


@dataclass
class PeakDetail:
    """Detail jednoho peaku"""
    fingerprint: str
    peak_type: str  # SPIKE, BURST
    
    apps: List[str] = field(default_factory=list)
    namespaces: List[str] = field(default_factory=list)
    
    baseline_rate: float = 0.0
    peak_rate: float = 0.0
    ratio: float = 1.0
    
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    duration_sec: int = 0
    
    likely_cause: str = ""
    linked_errors: List[str] = field(default_factory=list)
    message: str = ""


@dataclass
class KnownVsNew:
    """Porovnání známých vs nových issues"""
    new_errors: int = 0
    known_errors: int = 0
    new_error_fingerprints: List[str] = field(default_factory=list)
    
    new_peaks: int = 0
    known_peaks: int = 0
    new_peak_fingerprints: List[str] = field(default_factory=list)


@dataclass
class TrendVsPreviousDay:
    """Trend oproti předchozímu dni"""
    errors_change_pct: float = 0.0
    incidents_change_pct: float = 0.0
    new_errors_change: int = 0
    peaks_change: int = 0
    status: DayStatus = DayStatus.STABLE


@dataclass
class DailyConclusion:
    """Denní závěr - pravidlově generovaný"""
    summary_points: List[str] = field(default_factory=list)
    action_items: List[str] = field(default_factory=list)
    status: DayStatus = DayStatus.STABLE


@dataclass
class DailyReport:
    """Kompletní report za jeden den"""
    date: date
    
    # Sekce
    statistics: DailyStatistics = field(default_factory=DailyStatistics)
    
    # Errors
    errors_per_app: List[AppErrorSummary] = field(default_factory=list)
    error_clusters: List[ErrorCluster] = field(default_factory=list)
    error_timeline: List[TimelineEvent] = field(default_factory=list)
    
    # Peaks
    peaks: List[PeakDetail] = field(default_factory=list)
    peak_error_links: Dict[str, List[str]] = field(default_factory=dict)
    
    # Known vs New
    known_vs_new: KnownVsNew = field(default_factory=KnownVsNew)
    
    # Trend
    trend: TrendVsPreviousDay = field(default_factory=TrendVsPreviousDay)
    
    # Conclusion
    conclusion: DailyConclusion = field(default_factory=DailyConclusion)


@dataclass
class CrossDayTrends:
    """Týdenní/období trendy"""
    period_start: date
    period_end: date
    
    top_growing: List[Tuple[str, str, float]] = field(default_factory=list)  # (fp, message, change%)
    top_new_issues: List[Tuple[str, str, int]] = field(default_factory=list)  # (fp, message, count)
    persistent_issues: List[Tuple[str, str, int]] = field(default_factory=list)  # (fp, message, days)
    
    overall_errors_trend: float = 0.0
    overall_incidents_trend: float = 0.0
    overall_status: DayStatus = DayStatus.STABLE


@dataclass
class ReportMetadata:
    """Metadata reportu"""
    generated_at: datetime
    date_range_from: date
    date_range_to: date
    input_records: int
    total_incidents: int
    pipeline_version: str
    report_version: str = "2.0"


@dataclass
class DailyReportBundle:
    """Kompletní report bundle"""
    metadata: ReportMetadata
    daily_reports: List[DailyReport] = field(default_factory=list)
    cross_day_trends: Optional[CrossDayTrends] = None


# ============================================================================
# KNOWN ISSUES REGISTRY
# ============================================================================

@dataclass
class KnownIssue:
    """Známý issue v registru"""
    fingerprint: str
    description: str
    first_seen: date
    category: str = "unknown"
    status: str = "open"  # open, investigating, workaround, fixed
    workaround: str = ""
    jira_ticket: str = ""


@dataclass
class KnownIssuesRegistry:
    """Registry známých issues"""
    errors: Dict[str, KnownIssue] = field(default_factory=dict)
    peaks: Dict[str, KnownIssue] = field(default_factory=dict)
    
    def is_known_error(self, fp: str) -> bool:
        return fp in self.errors
    
    def is_known_peak(self, fp: str) -> bool:
        return fp in self.peaks
    
    @classmethod
    def load_yaml(cls, filepath: str) -> 'KnownIssuesRegistry':
        """Načte z YAML"""
        import yaml
        registry = cls()
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f) or {}
            for fp, info in data.get('errors', {}).items():
                registry.errors[fp] = KnownIssue(
                    fingerprint=fp,
                    description=info.get('description', ''),
                    first_seen=info.get('first_seen', date.today()),
                    category=info.get('category', 'unknown'),
                    status=info.get('status', 'open'),
                    workaround=info.get('workaround', ''),
                    jira_ticket=info.get('jira_ticket', ''),
                )
            for fp, info in data.get('peaks', {}).items():
                registry.peaks[fp] = KnownIssue(
                    fingerprint=fp,
                    description=info.get('description', ''),
                    first_seen=info.get('first_seen', date.today()),
                    category=info.get('category', 'unknown'),
                    status=info.get('status', 'open'),
                )
        except FileNotFoundError:
            pass
        return registry
    
    def save_yaml(self, filepath: str):
        """Uloží do YAML"""
        import yaml
        data = {'errors': {}, 'peaks': {}}
        for fp, issue in self.errors.items():
            data['errors'][fp] = {
                'description': issue.description,
                'first_seen': str(issue.first_seen),
                'category': issue.category,
                'status': issue.status,
                'workaround': issue.workaround,
                'jira_ticket': issue.jira_ticket,
            }
        for fp, issue in self.peaks.items():
            data['peaks'][fp] = {
                'description': issue.description,
                'first_seen': str(issue.first_seen),
                'category': issue.category,
                'status': issue.status,
            }
        with open(filepath, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


# ============================================================================
# ROOT CAUSE INFERENCE RULES
# ============================================================================

ROOT_CAUSE_RULES = {
    'database/connection': {
        'hypothesis': 'Database connection pool exhausted or DB server overloaded',
        'fixes': ['Increase connection pool size', 'Add connection timeout', 'Check DB server resources'],
    },
    'database/deadlock': {
        'hypothesis': 'Concurrent transactions causing deadlocks',
        'fixes': ['Review transaction isolation', 'Use SELECT FOR UPDATE NOWAIT', 'Reduce transaction scope'],
    },
    'database/constraint_violation': {
        'hypothesis': 'Data integrity issue - duplicate keys or missing FK references',
        'fixes': ['Add upsert logic', 'Verify FK references before insert', 'Check race conditions'],
    },
    'network/connection_refused': {
        'hypothesis': 'Target service down or port blocked',
        'fixes': ['Check target service health', 'Verify firewall rules', 'Check service discovery'],
    },
    'network/connection_reset': {
        'hypothesis': 'Network instability or load balancer issues',
        'fixes': ['Check network infrastructure', 'Review load balancer config', 'Add retry logic'],
    },
    'timeout/read_timeout': {
        'hypothesis': 'Slow downstream service or network congestion',
        'fixes': ['Increase timeout', 'Add circuit breaker', 'Optimize downstream service'],
    },
    'timeout/connect_timeout': {
        'hypothesis': 'Target service overloaded or network routing issues',
        'fixes': ['Check target service health', 'Verify network routing', 'Check proxy/mesh'],
    },
    'auth/unauthorized': {
        'hypothesis': 'Invalid or expired credentials',
        'fixes': ['Check token expiration', 'Implement token refresh', 'Verify credentials config'],
    },
    'auth/forbidden': {
        'hypothesis': 'Missing permissions or RBAC misconfiguration',
        'fixes': ['Review RBAC configuration', 'Check service account permissions'],
    },
    'business/not_found': {
        'hypothesis': 'Missing data - possible sync issue between services',
        'fixes': ['Add existence check', 'Implement fallback', 'Check data synchronization'],
    },
    'external/service_unavailable': {
        'hypothesis': 'Third-party service outage or rate limiting',
        'fixes': ['Add circuit breaker', 'Implement fallback/cache', 'Check rate limits'],
    },
}


def get_root_cause(category: str) -> Tuple[str, List[str]]:
    """Vrátí hypothesis a fixes pro kategorii"""
    rule = ROOT_CAUSE_RULES.get(category, {})
    if rule:
        return rule['hypothesis'], rule['fixes']
    
    # Zkus partial match
    cat_prefix = category.split('/')[0] if '/' in category else category
    for key, rule in ROOT_CAUSE_RULES.items():
        if key.startswith(cat_prefix):
            return rule['hypothesis'], rule['fixes']
    
    return f'Unknown root cause for {category}', ['Review logs', 'Add monitoring']


def infer_day_status(errors_change: float, incidents_change: float, critical: int) -> DayStatus:
    """Pravidlové odvození statusu dne"""
    if critical > 0:
        return DayStatus.CRITICAL
    if errors_change > 50 or incidents_change > 50:
        return DayStatus.CRITICAL
    if errors_change > 10 and incidents_change > 10:
        return DayStatus.DEGRADING
    if errors_change < -10 and incidents_change < -10:
        return DayStatus.IMPROVING
    return DayStatus.STABLE
