"""
AI Log Analyzer - Pipeline V4
=============================

Striktně oddělené fáze pro incident detection.

Fáze:
- A: Parse & Normalize
- B: Measure (EWMA, MAD)
- C: Detect (boolean flags)
- D: Score (váhová funkce)
- E: Classify (taxonomy)
- F: Report (render)

Použití:
    from v4.pipeline_v4 import PipelineV4
    
    pipeline = PipelineV4()
    collection = pipeline.run(errors)
"""

from .incident import (
    Incident,
    IncidentCollection,
    IncidentCategory,
    IncidentSeverity,
    TimeInfo,
    Stats,
    Flags,
    ScoreBreakdown,
    Evidence,
    generate_incident_id,
    generate_fingerprint,
)

from .phase_a_parse import PhaseA_Parser, NormalizedRecord, group_by_fingerprint
from .phase_b_measure import PhaseB_Measure, MeasurementResult, BaselineStats
from .phase_c_detect import PhaseC_Detect, DetectionResult
from .phase_d_score import PhaseD_Score, ScoreResult, ScoreWeights, score_to_severity
from .phase_e_classify import PhaseE_Classify, ClassificationRule, ClassificationResult
from .phase_f_report import PhaseF_Report
from .pipeline_v4 import PipelineV4, load_batch_files

__version__ = "4.0"
__all__ = [
    # Incident
    "Incident",
    "IncidentCollection", 
    "IncidentCategory",
    "IncidentSeverity",
    "TimeInfo",
    "Stats",
    "Flags",
    "ScoreBreakdown",
    "Evidence",
    "generate_incident_id",
    "generate_fingerprint",
    
    # Phases
    "PhaseA_Parser",
    "PhaseB_Measure",
    "PhaseC_Detect",
    "PhaseD_Score",
    "PhaseE_Classify",
    "PhaseF_Report",
    
    # Pipeline
    "PipelineV4",
    "load_batch_files",
]
