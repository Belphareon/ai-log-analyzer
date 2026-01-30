"""
Analysis Module V6 - Problem-Centric Analysis
=============================================

Nový přístup:
- Incidenty = vstupní data (ES)
- Problémy (problem_key) = primární analytická jednotka
- Trace = nástroj k pochopení co se dělo
- Report = problémový přehled + akce, ne statistický dump

Moduly:
- problem_aggregator: Agregace incidentů do problémů
- trace_analysis: Trace-based flow analýza
- root_cause: Deterministický root cause inference
- propagation: Propagace přes services
- version_analysis: Version-aware analýza
- category_refinement: Automatická reklasifikace unknown

Verze: 6.0
"""

from .problem_aggregator import (
    ProblemAggregate,
    aggregate_by_problem_key,
)
from .trace_analysis import (
    TraceStep,
    TraceFlow,
    build_trace_flow,
    summarize_trace_flow,
    group_incidents_by_trace,
    get_representative_traces,
    # V6.1 Behavior
    select_representative_trace,
    summarize_trace_flow_to_dict,
    infer_trace_root_cause,
    enrich_problem_with_trace,
    enrich_all_problems_with_traces,
    normalize_message,
)
from .root_cause import (
    RootCause,
    infer_root_cause,
)
from .propagation import (
    PropagationResult,
    analyze_propagation,
)
from .version_analysis import (
    VersionImpact,
    analyze_versions,
)
from .category_refinement import (
    refine_category,
    CATEGORY_RULES,
)
from .problem_report import (
    ProblemReportGenerator,
    generate_problem_report,
)
from .exports import (
    ProblemExporter,
    export_registry_health_csv,
    export_migration_mapping_csv,
)

__all__ = [
    # Problem Aggregator
    'ProblemAggregate',
    'aggregate_by_problem_key',
    # Trace Analysis
    'TraceStep',
    'TraceFlow',
    'build_trace_flow',
    'summarize_trace_flow',
    'group_incidents_by_trace',
    'get_representative_traces',
    # V6.1 Behavior
    'select_representative_trace',
    'summarize_trace_flow_to_dict',
    'infer_trace_root_cause',
    'enrich_problem_with_trace',
    'enrich_all_problems_with_traces',
    'normalize_message',
    # Root Cause
    'RootCause',
    'infer_root_cause',
    # Propagation
    'PropagationResult',
    'analyze_propagation',
    # Version Analysis
    'VersionImpact',
    'analyze_versions',
    # Category Refinement
    'refine_category',
    'CATEGORY_RULES',
    # Problem Report
    'ProblemReportGenerator',
    'generate_problem_report',
    # Exports
    'ProblemExporter',
    'export_registry_health_csv',
    'export_migration_mapping_csv',
]
