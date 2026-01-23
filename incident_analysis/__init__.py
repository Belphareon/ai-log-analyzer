#!/usr/bin/env python3
"""
INCIDENT ANALYSIS PACKAGE
=========================

4-vrstvá architektura:

DETECTION (fakta)
       ↓
INCIDENT ANALYSIS (kauzalita)
       ↓
KNOWLEDGE MATCHING (known vs new)
       ↓
REPORTING (human output)
"""

from .models import (
    # Enums
    IncidentStatus,
    TriggerType,
    ConfidenceLevel,
    ActionPriority,
    SeverityLevel,
    IncidentPriority,
    
    # Core models
    TimelineEvent,
    IncidentTrigger,
    IncidentScope,
    IncidentPropagation,  # v5.3: odděleno od Scope
    CausalLink,
    CausalChain,
    RecommendedAction,
    IncidentAnalysis,
    IncidentAnalysisResult,
    
    # Functions
    calculate_priority,
    
    # Rules
    ROOT_CAUSE_RULES,
    get_root_cause_rule,
    match_evidence,
)

from .analyzer import (
    IncidentAnalysisEngine,
    analyze_incidents,
)

from .timeline_builder import (
    TimelineBuilder,
)

from .causal_inference import (
    CausalInferenceEngine,
    format_causal_chain_text,
)

from .fix_recommender import (
    FixRecommender,
)

from .knowledge_base import (
    KnowledgeBase,
    KnowledgeMatch,
    KnowledgeStatus,
    MatchConfidence,
    KnownError,
    KnownPeak,
    create_knowledge_base_template,
    suggest_new_known_error,
)

from .knowledge_matcher import (
    KnowledgeMatcher,
    TriageReportGenerator,
    enrich_with_knowledge,
)

from .formatter import (
    IncidentReportFormatter,
)


__all__ = [
    # Enums
    'IncidentStatus',
    'TriggerType',
    'ConfidenceLevel',
    'ActionPriority',
    'SeverityLevel',
    'IncidentPriority',
    'KnowledgeStatus',
    'MatchConfidence',
    
    # Models
    'TimelineEvent',
    'IncidentTrigger',
    'IncidentScope',
    'IncidentPropagation',  # v5.3
    'CausalLink',
    'CausalChain',
    'RecommendedAction',
    'IncidentAnalysis',
    'IncidentAnalysisResult',
    'KnownError',
    'KnownPeak',
    'KnowledgeMatch',
    
    # Functions
    'calculate_priority',
    
    # Engine
    'IncidentAnalysisEngine',
    'analyze_incidents',
    
    # Components
    'TimelineBuilder',
    'CausalInferenceEngine',
    'FixRecommender',
    
    # Knowledge
    'KnowledgeBase',
    'KnowledgeMatcher',
    'TriageReportGenerator',
    'enrich_with_knowledge',
    'create_knowledge_base_template',
    'suggest_new_known_error',
    
    # Formatter
    'IncidentReportFormatter',
    
    # Utils
    'format_causal_chain_text',
]
