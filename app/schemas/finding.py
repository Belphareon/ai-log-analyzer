"""
Pydantic schemas for Finding API.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class FindingBase(BaseModel):
    """Base finding schema."""
    app_name: str
    namespace: str
    container: Optional[str] = None
    message: str
    level: str
    count: int = 1
    stack_trace: Optional[str] = None


class FindingCreate(FindingBase):
    """Schema for creating a finding."""
    fingerprint: str
    normalized_message: Optional[str] = None
    level_value: Optional[int] = None
    context_data: Optional[Dict[str, Any]] = None


class FindingAnalysisRequest(BaseModel):
    """Request for AI analysis."""
    findings: List[FindingCreate]
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)
    include_similar: bool = True
    auto_learn: bool = True


class FindingAnalysisResponse(BaseModel):
    """AI analysis response."""
    fingerprint: str
    app_name: str
    namespace: str
    message: str
    count: int
    
    # AI Analysis
    root_cause: Optional[str] = None
    recommendations: Optional[List[str]] = None
    confidence: Optional[float] = None
    severity: Optional[str] = None
    trace_analysis: Optional[str] = None  # Analysis of trace and related logs
    
    # Context
    similar_incidents: Optional[List[Dict[str, Any]]] = None
    matched_patterns: Optional[List[str]] = None
    context_data: Optional[Dict[str, Any]] = None  # Original context (traceId, spanId, pod, etc.)
    
    # Metadata
    analysis_timestamp: datetime
    finding_id: Optional[int] = None


class FeedbackCreate(BaseModel):
    """Submit feedback on analysis."""
    finding_id: int
    feedback_type: str  # confirmed, false_positive, partially_correct, resolved
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None
    correct_root_cause: Optional[str] = None
    correct_severity: Optional[str] = None
    resolution_applied: Optional[str] = None
    time_to_resolve: Optional[int] = None  # minutes
    submitted_by: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    database: bool
    ollama: bool
    version: str
    uptime_seconds: float


class MetricsResponse(BaseModel):
    """Metrics response."""
    total_findings: int
    findings_last_24h: int
    avg_confidence: Optional[float]
    patterns_learned: int
    feedback_count: int
    top_errors: List[Dict[str, Any]]
    top_apps: List[Dict[str, Any]]
