"""Schemas for trends analysis"""
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

class ErrorPattern(BaseModel):
    """Single error pattern"""
    fingerprint: str
    error_code: Optional[str] = None
    message_sample: str
    count: int
    first_seen: datetime
    last_seen: datetime
    affected_apps: List[str]
    affected_namespaces: Dict[str, int] = Field(description="Namespace -> count")
    status: str = Field(description="new, recurring, or resolved")
    
class KnownIssue(BaseModel):
    """Known issue that should be fixed"""
    fingerprint: str
    error_code: Optional[str]
    description: str
    occurrences_total: int
    occurrences_today: int
    first_seen: datetime
    last_seen: datetime
    affected_apps: List[str]
    affected_namespaces: Dict[str, int] = Field(description="Namespace -> count")
    sample_trace_id: Optional[str] = None
    sample_timestamp: Optional[datetime] = None
    recommendation: str
    priority: str = Field(description="low, medium, high, critical")

class PeakEvent(BaseModel):
    """Detected error peak"""
    timestamp: datetime
    duration_minutes: int
    error_count: int
    primary_cause: str
    affected_apps: List[str]
    severity: str

class WeeklyTrendsResponse(BaseModel):
    """Weekly trends analysis response"""
    period_start: datetime
    period_end: datetime
    total_errors: int
    sample_size: int = Field(description="Počet analyzovaných errorů")
    coverage_percent: float = Field(description="Pokrytí vzorku v %")
    
    # Patterns
    recurring_issues: List[ErrorPattern] = Field(description="Opakující se problémy")
    new_issues: List[ErrorPattern] = Field(description="Nové problémy")
    
    # Known issues to fix
    known_issues: List[KnownIssue] = Field(description="Známé problémy k řešení")
    
    # Peaks detected
    peaks: List[PeakEvent] = Field(description="Detekované peaky")
    
    # Summary
    recommendations: List[str] = Field(description="Doporučení pro snížení errorů")
