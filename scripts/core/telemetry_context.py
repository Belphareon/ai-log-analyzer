#!/usr/bin/env python3
"""
Incident Telemetry Context
==========================

Jednotná normalizační vrstva která:
- Oddělí raw ES event od interního incident modelu
- Zajistí konzistentní přístup ke všem důležitým polím
- Zabrání chybnému fallbacku (např. v1 místo verze)

PRAVIDLA:
- application_version = POUZE z pole application.version (X.Y.Z formát)
- deployment_label = application.name (může obsahovat -v1, -v2)
- environment = odvozeno z namespace (prod/uat/sit/dev)
- trace_id/span_id/parent_span_id = z ES polí

ZAKÁZÁNO:
- Parsování verze z názvu služby
- Heuristiky nad build number
- Odvozování clusteru z namespace
- LLM / ML inference

Verze: 6.0
Datum: 2026-01-26
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Set, List, Dict, Any
from enum import Enum


# =============================================================================
# CONSTANTS
# =============================================================================

# Regex pro validní semantic version
VERSION_PATTERN = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:-[\w.]+)?(?:\+[\w.]+)?$')

# Environment detection patterns v namespace
ENVIRONMENT_PATTERNS = [
    (re.compile(r'-prod-|\.prod\.|_prod_|^prod-|-prod$'), 'prod'),
    (re.compile(r'-uat-|\.uat\.|_uat_|^uat-|-uat$'), 'uat'),
    (re.compile(r'-sit-|\.sit\.|_sit_|^sit-|-sit$'), 'sit'),
    (re.compile(r'-dev-|\.dev\.|_dev_|^dev-|-dev$'), 'dev'),
    (re.compile(r'-test-|\.test\.|_test_|^test-|-test$'), 'test'),
    (re.compile(r'-staging-|\.staging\.|_staging_'), 'staging'),
]


class Environment(Enum):
    """Provozní prostředí"""
    PROD = "prod"
    UAT = "uat"
    SIT = "sit"
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    UNKNOWN = "unknown"


# =============================================================================
# TELEMETRY CONTEXT
# =============================================================================

@dataclass
class IncidentTelemetryContext:
    """
    Jednotná telemetry vrstva pro jeden event.

    Tato struktura je IMMUTABLE po vytvoření - všechny hodnoty
    jsou extrahovány a validovány při konstrukci.
    """
    # Deployment info
    deployment_label: str                           # application.name (s -v1, -v2)
    application_version: Optional[str] = None       # application.version (X.Y.Z) nebo None

    # Environment
    environment: Environment = Environment.UNKNOWN
    namespace: str = "unknown"

    # Distributed tracing
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None

    # Timing
    event_timestamp: Optional[datetime] = None

    # Raw reference (for debugging)
    _raw_app_name: str = ""

    @property
    def has_trace(self) -> bool:
        """Má event trace ID?"""
        return self.trace_id is not None and len(self.trace_id) > 0

    @property
    def has_version(self) -> bool:
        """Má event validní semantic version?"""
        return self.application_version is not None

    @property
    def is_prod(self) -> bool:
        """Je event z produkce?"""
        return self.environment == Environment.PROD

    def to_dict(self) -> dict:
        return {
            'deployment_label': self.deployment_label,
            'application_version': self.application_version,
            'environment': self.environment.value,
            'namespace': self.namespace,
            'trace_id': self.trace_id,
            'span_id': self.span_id,
            'parent_span_id': self.parent_span_id,
            'event_timestamp': self.event_timestamp.isoformat() if self.event_timestamp else None,
        }


# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def extract_application_version(raw_event: dict) -> Optional[str]:
    """
    Extrahuje application version POUZE z explicitního pole.

    Zdroje (v pořadí priority):
    1. application.version (flat key)
    2. application.version (nested)
    3. app_version
    4. version (pokud je semantic)

    VRACÍ None pokud:
    - Pole neexistuje
    - Hodnota není validní semantic version (X.Y.Z)
    - Hodnota je build number, SDK version, etc.

    NIKDY neextrahuje z názvu aplikace!
    """
    version = None

    # Try flat key first (ES format)
    version = raw_event.get('application.version')

    # Try nested object
    if not version:
        app_obj = raw_event.get('application')
        if isinstance(app_obj, dict):
            version = app_obj.get('version')

    # Try other common field names
    if not version:
        version = (
            raw_event.get('app_version') or
            raw_event.get('appVersion') or
            raw_event.get('version')
        )

    if not version:
        return None

    version = str(version).strip()

    # Validate semantic version format
    if VERSION_PATTERN.match(version):
        return version

    # Try to extract version from common formats like "v3.5.0"
    if version.startswith('v') or version.startswith('V'):
        clean = version[1:]
        if VERSION_PATTERN.match(clean):
            return clean

    # Not a valid semantic version
    return None


def extract_deployment_label(raw_event: dict) -> str:
    """
    Extrahuje deployment label z application.name.

    Toto MŮŽE obsahovat -v1, -v2 suffix - to je OK,
    protože deployment_label != application_version.

    Podporuje:
    - Flat keys: {'application.name': 'my-service'}
    - Nested: {'application': {'name': 'my-service'}}
    - Simple: {'application': 'my-service'}
    """
    # Try flat key first (ES format)
    app_name = raw_event.get('application.name')

    # Try nested object
    if not app_name:
        app_obj = raw_event.get('application')
        if isinstance(app_obj, dict):
            app_name = app_obj.get('name')
        elif isinstance(app_obj, str):
            app_name = app_obj

    # Fallbacks
    if not app_name:
        app_name = (
            raw_event.get('app') or
            raw_event.get('service') or
            raw_event.get('service.name') or
            'unknown'
        )

    return str(app_name).strip() or 'unknown'


def extract_environment(namespace: str) -> Environment:
    """
    Odvozuje environment z namespace.

    Pravidla:
    - obsahuje "-prod-" → prod
    - obsahuje "-uat-" → uat
    - obsahuje "-sit-" → sit
    - obsahuje "-dev-" → dev
    - jinak → unknown

    NEZJIŠŤUJE cluster, tier, PCB, etc.
    """
    if not namespace:
        return Environment.UNKNOWN

    ns_lower = namespace.lower()

    for pattern, env_name in ENVIRONMENT_PATTERNS:
        if pattern.search(ns_lower):
            return Environment(env_name)

    return Environment.UNKNOWN


def extract_trace_id(raw_event: dict) -> Optional[str]:
    """Extrahuje trace ID z eventu."""
    trace_id = (
        raw_event.get('traceId') or
        raw_event.get('trace_id') or
        raw_event.get('traceID') or
        raw_event.get('trace.id') or
        raw_event.get('x-request-id')
    )

    if trace_id and len(str(trace_id).strip()) > 0:
        return str(trace_id).strip()

    return None


def extract_span_id(raw_event: dict) -> Optional[str]:
    """Extrahuje span ID z eventu."""
    span_id = (
        raw_event.get('spanId') or
        raw_event.get('span_id') or
        raw_event.get('spanID') or
        raw_event.get('span.id')
    )

    if span_id and len(str(span_id).strip()) > 0:
        return str(span_id).strip()

    return None


def extract_parent_span_id(raw_event: dict) -> Optional[str]:
    """Extrahuje parent span ID z eventu."""
    parent_id = (
        raw_event.get('parentId') or
        raw_event.get('parent_id') or
        raw_event.get('parentID') or
        raw_event.get('parent_span_id') or
        raw_event.get('parentSpanId')
    )

    if parent_id and len(str(parent_id).strip()) > 0:
        return str(parent_id).strip()

    return None


def extract_timestamp(raw_event: dict) -> Optional[datetime]:
    """Extrahuje a parsuje timestamp z eventu."""
    ts_str = (
        raw_event.get('@timestamp') or
        raw_event.get('timestamp') or
        raw_event.get('time') or
        raw_event.get('datetime')
    )

    if not ts_str:
        return None

    try:
        ts_str = str(ts_str).replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def extract_namespace(raw_event: dict) -> str:
    """
    Extrahuje namespace z eventu.

    Podporuje:
    - Flat keys: {'kubernetes.namespace': 'my-ns'}
    - Nested: {'kubernetes': {'namespace': 'my-ns'}}
    - Simple: {'namespace': 'my-ns'}
    """
    namespace = None

    # Try flat key first (ES format)
    namespace = raw_event.get('kubernetes.namespace')

    # Try nested object
    if not namespace:
        k8s_obj = raw_event.get('kubernetes')
        if isinstance(k8s_obj, dict):
            namespace = k8s_obj.get('namespace')

    # Fallbacks
    if not namespace:
        namespace = (
            raw_event.get('namespace') or
            raw_event.get('ns') or
            'unknown'
        )

    return str(namespace).strip() or 'unknown'


# =============================================================================
# FACTORY
# =============================================================================

def create_telemetry_context(raw_event: dict) -> IncidentTelemetryContext:
    """
    Vytvoří IncidentTelemetryContext z raw ES eventu.

    Toto je JEDINÝ způsob jak vytvořit context - zajišťuje
    konzistentní extrakci všech polí.
    """
    namespace = extract_namespace(raw_event)
    deployment_label = extract_deployment_label(raw_event)

    return IncidentTelemetryContext(
        deployment_label=deployment_label,
        application_version=extract_application_version(raw_event),
        environment=extract_environment(namespace),
        namespace=namespace,
        trace_id=extract_trace_id(raw_event),
        span_id=extract_span_id(raw_event),
        parent_span_id=extract_parent_span_id(raw_event),
        event_timestamp=extract_timestamp(raw_event),
        _raw_app_name=raw_event.get('application', {}).get('name', '') if isinstance(raw_event.get('application'), dict) else raw_event.get('application', ''),
    )


# =============================================================================
# TRACE AGGREGATION
# =============================================================================

@dataclass
class TraceContext:
    """
    Agregovaný kontext pro jeden trace (skupina eventů se stejným traceId).

    Používá se pro:
    - Detekci propagace (trace spans multiple services)
    - Určení root service (nejstarší event v trace)
    - Scope analysis
    """
    trace_id: str

    # Services in trace
    deployment_labels: Set[str] = field(default_factory=set)
    namespaces: Set[str] = field(default_factory=set)

    # Timing
    first_event_ts: Optional[datetime] = None
    last_event_ts: Optional[datetime] = None

    # Root detection
    root_deployment: Optional[str] = None
    root_timestamp: Optional[datetime] = None

    # Counts
    event_count: int = 0

    @property
    def is_propagated(self) -> bool:
        """
        Trace je propagovaný pokud obsahuje více než 1 deployment.
        """
        return len(self.deployment_labels) > 1

    @property
    def propagation_time_sec(self) -> Optional[float]:
        """Čas mezi prvním a posledním eventem v trace."""
        if self.first_event_ts and self.last_event_ts:
            return (self.last_event_ts - self.first_event_ts).total_seconds()
        return None

    @property
    def service_count(self) -> int:
        """Počet services v trace."""
        return len(self.deployment_labels)

    def to_dict(self) -> dict:
        return {
            'trace_id': self.trace_id,
            'deployment_labels': list(self.deployment_labels),
            'namespaces': list(self.namespaces),
            'first_event_ts': self.first_event_ts.isoformat() if self.first_event_ts else None,
            'last_event_ts': self.last_event_ts.isoformat() if self.last_event_ts else None,
            'root_deployment': self.root_deployment,
            'event_count': self.event_count,
            'is_propagated': self.is_propagated,
            'propagation_time_sec': self.propagation_time_sec,
        }


def aggregate_trace_contexts(telemetry_contexts: List[IncidentTelemetryContext]) -> Dict[str, TraceContext]:
    """
    Agreguje telemetry contexts podle trace_id.

    Vrací dict trace_id → TraceContext.
    Eventy bez trace_id jsou ignorovány.
    """
    traces: Dict[str, TraceContext] = {}

    for ctx in telemetry_contexts:
        if not ctx.trace_id:
            continue

        if ctx.trace_id not in traces:
            traces[ctx.trace_id] = TraceContext(trace_id=ctx.trace_id)

        trace = traces[ctx.trace_id]
        trace.deployment_labels.add(ctx.deployment_label)
        trace.namespaces.add(ctx.namespace)
        trace.event_count += 1

        # Update timing
        if ctx.event_timestamp:
            if trace.first_event_ts is None or ctx.event_timestamp < trace.first_event_ts:
                trace.first_event_ts = ctx.event_timestamp
                trace.root_deployment = ctx.deployment_label
                trace.root_timestamp = ctx.event_timestamp

            if trace.last_event_ts is None or ctx.event_timestamp > trace.last_event_ts:
                trace.last_event_ts = ctx.event_timestamp

    return traces


# =============================================================================
# PROPAGATION DETECTION
# =============================================================================

@dataclass
class PropagationInfo:
    """
    Informace o propagaci incidentu.

    Propagace = incident se šíří přes více services.
    """
    propagated: bool = False
    root_deployment: Optional[str] = None
    affected_deployments: Set[str] = field(default_factory=set)
    propagation_time_sec: Optional[float] = None
    trace_count: int = 0

    def to_dict(self) -> dict:
        return {
            'propagated': self.propagated,
            'root_deployment': self.root_deployment,
            'affected_deployments': list(self.affected_deployments),
            'propagation_time_sec': self.propagation_time_sec,
            'trace_count': self.trace_count,
        }


def detect_propagation(trace_contexts: Dict[str, TraceContext]) -> PropagationInfo:
    """
    Detekuje propagaci z agregovaných trace contexts.

    Algoritmus:
    1. Najdi traces které obsahují více než 1 deployment
    2. Urči root_deployment jako nejčastější root across propagated traces
    3. Spočítej propagation_time jako medián
    """
    if not trace_contexts:
        return PropagationInfo()

    propagated_traces = [t for t in trace_contexts.values() if t.is_propagated]

    if not propagated_traces:
        return PropagationInfo()

    # Collect all affected deployments
    affected = set()
    root_candidates: Dict[str, int] = {}
    propagation_times = []

    for trace in propagated_traces:
        affected.update(trace.deployment_labels)

        if trace.root_deployment:
            root_candidates[trace.root_deployment] = root_candidates.get(trace.root_deployment, 0) + 1

        if trace.propagation_time_sec is not None:
            propagation_times.append(trace.propagation_time_sec)

    # Determine root (most common root_deployment)
    root_deployment = None
    if root_candidates:
        root_deployment = max(root_candidates, key=root_candidates.get)

    # Median propagation time
    median_time = None
    if propagation_times:
        sorted_times = sorted(propagation_times)
        mid = len(sorted_times) // 2
        median_time = sorted_times[mid]

    return PropagationInfo(
        propagated=True,
        root_deployment=root_deployment,
        affected_deployments=affected,
        propagation_time_sec=median_time,
        trace_count=len(propagated_traces),
    )
