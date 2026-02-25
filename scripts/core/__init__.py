"""
AI Log Analyzer - Core Components
=================================

Základní komponenty pro sběr a zpracování dat.
"""

from .fetch_unlimited import fetch_unlimited
from .problem_registry import (
    ProblemRegistry,
    ProblemEntry,
    PeakEntry,
    FingerprintEntry,
    compute_problem_key,
    extract_flow,
    extract_error_class,
    extract_deployment_label,
    extract_app_version,
    migrate_old_registry,
)
from .telemetry_context import (
    IncidentTelemetryContext,
    TraceContext,
    PropagationInfo,
    Environment,
    create_telemetry_context,
    extract_application_version,
    extract_environment,
    extract_trace_id,
    extract_span_id,
    extract_parent_span_id,
    aggregate_trace_contexts,
    detect_propagation,
)

__all__ = [
    'fetch_unlimited',
    'ProblemRegistry',
    'ProblemEntry',
    'PeakEntry',
    'FingerprintEntry',
    'compute_problem_key',
    'extract_flow',
    'extract_error_class',
    'extract_deployment_label',
    'extract_app_version',
    'migrate_old_registry',
    # Telemetry
    'IncidentTelemetryContext',
    'TraceContext',
    'PropagationInfo',
    'Environment',
    'create_telemetry_context',
    'extract_application_version',
    'extract_environment',
    'extract_trace_id',
    'extract_span_id',
    'extract_parent_span_id',
    'aggregate_trace_contexts',
    'detect_propagation',
]
