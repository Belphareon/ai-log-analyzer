"""Finding model for storing log errors/warnings with AI analysis."""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Text, DateTime, JSON, Boolean, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Finding(Base):
    """
    Represents a log error/warning finding with AI analysis.
    
    Fingerprint is used to group similar errors together.
    """
    __tablename__ = "findings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Identification
    fingerprint: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    app_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    namespace: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    container: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Error details
    message: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[Optional[str]] = mapped_column(Text)
    level: Mapped[str] = mapped_column(String(20), index=True)
    level_value: Mapped[int] = mapped_column(Integer)
    
    # Occurrence tracking
    count: Mapped[int] = mapped_column(Integer, default=1)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # AI Analysis results
    root_cause: Mapped[Optional[str]] = mapped_column(Text)
    recommendations: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    severity: Mapped[Optional[str]] = mapped_column(String(20))
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Context
    context_data: Mapped[Optional[dict]] = mapped_column(JSON)
    
    # Feedback & Resolution
    feedback_type: Mapped[Optional[str]] = mapped_column(String(50))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    patterns: Mapped[list["Pattern"]] = relationship(
        "Pattern",
        secondary="finding_patterns",
        back_populates="findings"
    )
    
    def __repr__(self) -> str:
        return f"<Finding(id={self.id}, app={self.app_name}, fp={self.fingerprint[:8]})>"
