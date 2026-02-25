#!/usr/bin/env python3
"""
Incident Object - Canonical Data Model
======================================

Jednotná datová struktura která prochází celým pipeline.
Každá fáze POUZE PŘIDÁVÁ pole, nikdy nemaže ani nepřepisuje.

Verze: 4.0
Datum: 2026-01-20
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import hashlib
import json


class IncidentCategory(Enum):
    """Taxonomy kategorií incidentů"""
    MEMORY = "memory"
    NETWORK = "network"
    DATABASE = "database"
    TIMEOUT = "timeout"
    AUTH = "auth"
    BUSINESS = "business"
    EXTERNAL = "external"
    UNKNOWN = "unknown"


class IncidentSeverity(Enum):
    """Severity levels - odvozeno ze score, ne magicky"""
    CRITICAL = "critical"  # score >= 80
    HIGH = "high"          # score >= 60
    MEDIUM = "medium"      # score >= 40
    LOW = "low"            # score >= 20
    INFO = "info"          # score < 20


@dataclass
class TimeInfo:
    """Časové informace o incidentu"""
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    duration_sec: int = 0
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


@dataclass
class Stats:
    """Měřené statistiky (FÁZE B)"""
    # Baseline
    baseline_rate: float = 0.0       # EWMA baseline
    baseline_median: float = 0.0     # Median baseline value
    baseline_mad: float = 0.0        # Median Absolute Deviation
    
    # Current
    current_rate: float = 0.0
    current_count: int = 0
    
    # Hosts/Services
    hosts: int = 0
    services: int = 0
    namespaces: int = 0
    
    # Trend
    trend_direction: str = "stable"  # increasing, decreasing, stable
    trend_ratio: float = 1.0


@dataclass
class Evidence:
    """Důkaz pro flag (FÁZE C)"""
    rule: str                        # Název pravidla
    baseline: Optional[float] = None
    current: Optional[float] = None
    threshold: Optional[float] = None
    message: str = ""
    timestamp: Optional[datetime] = None
    
    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "baseline": self.baseline,
            "current": self.current,
            "threshold": self.threshold,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class Flags:
    """Boolean flags z detekce (FÁZE C)"""
    is_new: bool = False             # Nikdy předtím neviděno
    is_spike: bool = False           # current > baseline * threshold
    is_burst: bool = False           # Náhlý nárůst v krátkém čase
    is_silence: bool = False         # Neočekávaná absence errorů
    is_regression: bool = False      # Vrátil se opravený bug
    is_cascade: bool = False         # Součást cascade failure
    is_cross_namespace: bool = False # Objevuje se ve více namespaces


@dataclass
class ScoreBreakdown:
    """Rozklad skóre (FÁZE D)"""
    base_score: float = 0.0
    spike_bonus: float = 0.0
    burst_bonus: float = 0.0
    new_bonus: float = 0.0
    regression_bonus: float = 0.0
    cascade_bonus: float = 0.0
    cross_ns_bonus: float = 0.0
    propagation_bonus: float = 0.0  # NEW: bonus pro propagované incidenty

    @property
    def total(self) -> float:
        return min(100, max(0,
            self.base_score +
            self.spike_bonus +
            self.burst_bonus +
            self.new_bonus +
            self.regression_bonus +
            self.cascade_bonus +
            self.cross_ns_bonus +
            self.propagation_bonus
        ))


@dataclass
class PropagationInfo:
    """
    Informace o propagaci incidentu (V6).

    Propagace = incident se šíří přes více services (detekováno přes traceId).
    """
    propagated: bool = False                        # Incident se šíří přes více services
    root_deployment: Optional[str] = None           # Deployment kde incident začal
    affected_deployments: List[str] = field(default_factory=list)  # Všechny affected deployments
    propagation_time_sec: Optional[float] = None    # Čas propagace
    trace_count: int = 0                            # Počet trace s propagací

    def to_dict(self) -> dict:
        return {
            'propagated': self.propagated,
            'root_deployment': self.root_deployment,
            'affected_deployments': self.affected_deployments,
            'propagation_time_sec': self.propagation_time_sec,
            'trace_count': self.trace_count,
        }


@dataclass
class TraceInfo:
    """
    Agregované trace informace pro incident (V6).
    """
    trace_ids: List[str] = field(default_factory=list)    # Všechny trace IDs
    trace_count: int = 0                                  # Počet unikátních traces
    trace_services: List[str] = field(default_factory=list)  # Services v traces
    trace_first_seen: Optional[datetime] = None           # První event v trace
    trace_last_seen: Optional[datetime] = None            # Poslední event v trace

    def to_dict(self) -> dict:
        return {
            'trace_ids': self.trace_ids[:10],  # Limit pro export
            'trace_count': self.trace_count,
            'trace_services': self.trace_services,
            'trace_first_seen': self.trace_first_seen.isoformat() if self.trace_first_seen else None,
            'trace_last_seen': self.trace_last_seen.isoformat() if self.trace_last_seen else None,
        }


@dataclass 
class Incident:
    """
    Hlavní Incident Object - prochází celým pipeline.
    
    Pravidla:
    - Každá fáze POUZE PŘIDÁVÁ pole
    - Nikdy nic nemazat
    - Nikdy nepřepisovat význam
    """
    
    # === IDENTIFIKACE (nastaveno při vytvoření) ===
    id: str = ""                     # inc-YYYYMMDD-NNN
    fingerprint: str = ""            # Hash pro deduplikaci
    
    # === FÁZE A: Parse & Normalize ===
    normalized_message: str = ""     # Normalizovaná message
    error_type: str = ""             # Extrahovaný error type
    raw_samples: List[str] = field(default_factory=list)  # Max 3 raw samples
    
    # === FÁZE B: Measure ===
    time: TimeInfo = field(default_factory=TimeInfo)
    stats: Stats = field(default_factory=Stats)
    
    # Affected entities
    apps: List[str] = field(default_factory=list)           # deployment_labels (mohou obsahovat -v1)
    namespaces: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)   # V6: prod/uat/sit/dev

    # V6: Oddělené verze a deploymenty
    deployment_labels: List[str] = field(default_factory=list)  # V6: explicitní deployment labels
    app_versions: List[str] = field(default_factory=list)       # V6: POUZE semantic versions (X.Y.Z)
    versions: List[str] = field(default_factory=list)           # DEPRECATED: pro zpětnou kompatibilitu

    # V6: Trace info
    trace_ids: List[str] = field(default_factory=list)
    trace_info: TraceInfo = field(default_factory=TraceInfo)

    # V6: Propagation
    propagation: PropagationInfo = field(default_factory=PropagationInfo)
    
    # === FÁZE C: Detect ===
    flags: Flags = field(default_factory=Flags)
    evidence: List[Evidence] = field(default_factory=list)
    
    # === FÁZE D: Score ===
    score: float = 0.0
    score_breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    severity: IncidentSeverity = IncidentSeverity.INFO
    
    # === FÁZE E: Classify ===
    category: IncidentCategory = IncidentCategory.UNKNOWN
    subcategory: str = ""
    
    # === FÁZE F: Report ===
    # (není v objektu - report jen renderuje)
    
    # === METADATA ===
    created_at: datetime = field(default_factory=datetime.utcnow)
    pipeline_version: str = "4.0"
    
    # === LINKAGE ===
    known_issue_id: Optional[str] = None
    cascade_root_id: Optional[str] = None  # ID root cause incidentu
    related_incidents: List[str] = field(default_factory=list)
    
    def add_evidence(self, rule: str, **kwargs):
        """Přidá důkaz pro flag"""
        self.evidence.append(Evidence(rule=rule, **kwargs))
    
    def calculate_severity(self):
        """Odvození severity ze score (ne magicky!)"""
        if self.score >= 80:
            self.severity = IncidentSeverity.CRITICAL
        elif self.score >= 60:
            self.severity = IncidentSeverity.HIGH
        elif self.score >= 40:
            self.severity = IncidentSeverity.MEDIUM
        elif self.score >= 20:
            self.severity = IncidentSeverity.LOW
        else:
            self.severity = IncidentSeverity.INFO
    
    def to_dict(self) -> Dict[str, Any]:
        """Serializace do dict"""
        return {
            "id": self.id,
            "fingerprint": self.fingerprint,
            "normalized_message": self.normalized_message,
            "error_type": self.error_type,
            "raw_samples": self.raw_samples[:3],
            
            "time": {
                "first_seen": self.time.first_seen.isoformat() if self.time.first_seen else None,
                "last_seen": self.time.last_seen.isoformat() if self.time.last_seen else None,
                "duration_sec": self.time.duration_sec,
            },
            
            "stats": {
                "baseline_rate": self.stats.baseline_rate,
                "baseline_mad": self.stats.baseline_mad,
                "current_rate": self.stats.current_rate,
                "current_count": self.stats.current_count,
                "hosts": self.stats.hosts,
                "namespaces": self.stats.namespaces,
                "trend_direction": self.stats.trend_direction,
                "trend_ratio": self.stats.trend_ratio,
            },
            
            "apps": self.apps,
            "namespaces": self.namespaces,
            "environments": self.environments,
            "deployment_labels": self.deployment_labels,
            "app_versions": self.app_versions,
            "versions": self.versions,  # DEPRECATED

            # V6: Trace & Propagation
            "trace_info": self.trace_info.to_dict(),
            "propagation": self.propagation.to_dict(),
            
            "flags": {
                "new": self.flags.is_new,
                "spike": self.flags.is_spike,
                "burst": self.flags.is_burst,
                "silence": self.flags.is_silence,
                "regression": self.flags.is_regression,
                "cascade": self.flags.is_cascade,
                "cross_namespace": self.flags.is_cross_namespace,
            },
            
            "evidence": [e.to_dict() for e in self.evidence],
            
            "score": self.score,
            "score_breakdown": {
                "base": self.score_breakdown.base_score,
                "spike": self.score_breakdown.spike_bonus,
                "burst": self.score_breakdown.burst_bonus,
                "new": self.score_breakdown.new_bonus,
                "regression": self.score_breakdown.regression_bonus,
                "cascade": self.score_breakdown.cascade_bonus,
                "cross_ns": self.score_breakdown.cross_ns_bonus,
                "total": self.score_breakdown.total,
            },
            
            "severity": self.severity.value,
            "category": self.category.value,
            "subcategory": self.subcategory,
            
            "known_issue_id": self.known_issue_id,
            "cascade_root_id": self.cascade_root_id,
            "related_incidents": self.related_incidents,
            
            "created_at": self.created_at.isoformat(),
            "pipeline_version": self.pipeline_version,
        }
    
    def to_json(self, indent: int = 2) -> str:
        """Serializace do JSON"""
        return json.dumps(self.to_dict(), indent=indent, default=str)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Incident':
        """Deserializace z dict"""
        inc = cls()
        inc.id = data.get("id", "")
        inc.fingerprint = data.get("fingerprint", "")
        inc.normalized_message = data.get("normalized_message", "")
        inc.error_type = data.get("error_type", "")
        inc.raw_samples = data.get("raw_samples", [])
        
        # Time
        time_data = data.get("time", {})
        if time_data.get("first_seen"):
            inc.time.first_seen = datetime.fromisoformat(time_data["first_seen"])
        if time_data.get("last_seen"):
            inc.time.last_seen = datetime.fromisoformat(time_data["last_seen"])
        inc.time.duration_sec = time_data.get("duration_sec", 0)
        
        # Stats
        stats_data = data.get("stats", {})
        inc.stats.baseline_rate = stats_data.get("baseline_rate", 0)
        inc.stats.baseline_mad = stats_data.get("baseline_mad", 0)
        inc.stats.current_rate = stats_data.get("current_rate", 0)
        inc.stats.current_count = stats_data.get("current_count", 0)
        inc.stats.hosts = stats_data.get("hosts", 0)
        inc.stats.namespaces = stats_data.get("namespaces", 0)
        
        # Lists
        inc.apps = data.get("apps", [])
        inc.namespaces = data.get("namespaces", [])
        inc.versions = data.get("versions", [])
        
        # Flags
        flags_data = data.get("flags", {})
        inc.flags.is_new = flags_data.get("new", False)
        inc.flags.is_spike = flags_data.get("spike", False)
        inc.flags.is_burst = flags_data.get("burst", False)
        inc.flags.is_silence = flags_data.get("silence", False)
        inc.flags.is_regression = flags_data.get("regression", False)
        inc.flags.is_cascade = flags_data.get("cascade", False)
        inc.flags.is_cross_namespace = flags_data.get("cross_namespace", False)
        
        # Score
        inc.score = data.get("score", 0)
        inc.severity = IncidentSeverity(data.get("severity", "info"))
        inc.category = IncidentCategory(data.get("category", "unknown"))
        
        return inc


# ============================================================================
# INCIDENT COLLECTION
# ============================================================================

@dataclass
class IncidentCollection:
    """Kolekce incidentů z jednoho běhu pipeline"""
    
    run_id: str = ""
    run_timestamp: datetime = field(default_factory=datetime.utcnow)
    pipeline_version: str = "4.0"
    
    # Input info
    input_file: str = ""
    input_records: int = 0
    time_range_start: Optional[datetime] = None
    time_range_end: Optional[datetime] = None
    
    # Incidents
    incidents: List[Incident] = field(default_factory=list)
    
    # Summary
    total_incidents: int = 0
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_category: Dict[str, int] = field(default_factory=dict)
    
    def add_incident(self, incident: Incident):
        """Přidá incident a aktualizuje summary"""
        self.incidents.append(incident)
        self.total_incidents = len(self.incidents)
        
        # Update by_severity
        sev = incident.severity.value
        self.by_severity[sev] = self.by_severity.get(sev, 0) + 1
        
        # Update by_category
        cat = incident.category.value
        self.by_category[cat] = self.by_category.get(cat, 0) + 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_timestamp": self.run_timestamp.isoformat(),
            "pipeline_version": self.pipeline_version,
            "input_file": self.input_file,
            "input_records": self.input_records,
            "time_range": {
                "start": self.time_range_start.isoformat() if self.time_range_start else None,
                "end": self.time_range_end.isoformat() if self.time_range_end else None,
            },
            "summary": {
                "total_incidents": self.total_incidents,
                "by_severity": self.by_severity,
                "by_category": self.by_category,
            },
            "incidents": [inc.to_dict() for inc in self.incidents],
        }
    
    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)
    
    def save(self, filepath: str):
        """Uloží kolekci do JSON souboru"""
        with open(filepath, 'w') as f:
            f.write(self.to_json())
    
    @classmethod
    def load(cls, filepath: str) -> 'IncidentCollection':
        """Načte kolekci z JSON souboru"""
        with open(filepath) as f:
            data = json.load(f)
        
        collection = cls()
        collection.run_id = data.get("run_id", "")
        collection.pipeline_version = data.get("pipeline_version", "")
        collection.input_file = data.get("input_file", "")
        collection.input_records = data.get("input_records", 0)
        
        for inc_data in data.get("incidents", []):
            collection.add_incident(Incident.from_dict(inc_data))
        
        return collection


# ============================================================================
# HELPER: Generate IDs
# ============================================================================

def generate_incident_id(date: datetime = None, sequence: int = 1) -> str:
    """Generuje ID incidentu: inc-YYYYMMDD-NNN"""
    if date is None:
        date = datetime.utcnow()
    return f"inc-{date.strftime('%Y%m%d')}-{sequence:03d}"


def generate_fingerprint(normalized_message: str, error_type: str = "") -> str:
    """Generuje fingerprint pro deduplikaci"""
    combined = f"{error_type}:{normalized_message}"
    return hashlib.md5(combined.encode()).hexdigest()[:16]


# ============================================================================
# EXAMPLE
# ============================================================================

if __name__ == "__main__":
    # Příklad vytvoření incidentu
    inc = Incident(
        id=generate_incident_id(sequence=1),
        fingerprint=generate_fingerprint("Connection to <IP>:<PORT> refused", "ConnectionError"),
        normalized_message="Connection to <IP>:<PORT> refused",
        error_type="ConnectionError",
    )
    
    # FÁZE B: Measure
    inc.stats.baseline_rate = 1.2
    inc.stats.current_rate = 18.4
    inc.stats.current_count = 150
    inc.stats.namespaces = 3
    
    # FÁZE C: Detect
    inc.flags.is_spike = True
    inc.flags.is_cross_namespace = True
    inc.add_evidence(
        rule="rate_spike",
        baseline=1.2,
        current=18.4,
        threshold=3.0,
        message="current > baseline * 3.0"
    )
    
    # FÁZE D: Score
    inc.score_breakdown.base_score = 30
    inc.score_breakdown.spike_bonus = 25
    inc.score_breakdown.cross_ns_bonus = 15
    inc.score = inc.score_breakdown.total
    inc.calculate_severity()
    
    # FÁZE E: Classify
    inc.category = IncidentCategory.NETWORK
    
    # Print
    print(inc.to_json())
