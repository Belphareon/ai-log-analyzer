"""Pattern model for learned patterns from findings."""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Text, DateTime, JSON, Boolean, Float, Table, Column, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


# Association table for many-to-many relationship
finding_patterns = Table(
    "finding_patterns",
    Base.metadata,
    Column("finding_id", Integer, ForeignKey("findings.id"), primary_key=True),
    Column("pattern_id", Integer, ForeignKey("patterns.id"), primary_key=True),
    Column("match_confidence", Float, default=1.0),
    Column("matched_at", DateTime, default=datetime.utcnow),
)


class Pattern(Base):
    """
    Learned pattern from historical findings.
    Used for automatic classification and response suggestions.
    """
    __tablename__ = "patterns"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Pattern identification
    pattern_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    pattern_type: Mapped[str] = mapped_column(String(50), index=True)  # error_type, stack_pattern, etc.
    
    # Pattern matching rules
    regex_pattern: Mapped[Optional[str]] = mapped_column(Text)
    keywords: Mapped[Optional[list]] = mapped_column(JSON)
    app_filter: Mapped[Optional[list]] = mapped_column(JSON)
    namespace_filter: Mapped[Optional[list]] = mapped_column(JSON)
    
    # Auto-response
    auto_ignore: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_action: Mapped[Optional[str]] = mapped_column(String(50))
    suggested_root_cause: Mapped[Optional[str]] = mapped_column(Text)
    suggested_recommendations: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Learning metrics
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    true_positives: Mapped[int] = mapped_column(Integer, default=0)
    false_positives: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    
    # Metadata
    created_by: Mapped[str] = mapped_column(String(50), default="system")  # system, user, llm
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_matched: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Status
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    
    # Relationships
    findings: Mapped[list["Finding"]] = relationship(
        "Finding",
        secondary="finding_patterns",
        back_populates="patterns"
    )
    
    def __repr__(self) -> str:
        return f"<Pattern(id={self.id}, name={self.pattern_name}, confidence={self.confidence:.2f})>"
    
    @property
    def accuracy(self) -> float:
        """Calculate pattern accuracy."""
        total = self.true_positives + self.false_positives
        return self.true_positives / total if total > 0 else 0.0
