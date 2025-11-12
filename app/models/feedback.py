"""Feedback model for user feedback on findings and patterns."""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Feedback(Base):
    """
    User feedback on AI analysis results.
    Used to improve pattern learning and LLM responses.
    """
    __tablename__ = "feedback"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Reference
    finding_id: Mapped[int] = mapped_column(Integer, ForeignKey("findings.id"), index=True)
    pattern_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("patterns.id"))
    
    # Feedback details
    feedback_type: Mapped[str] = mapped_column(String(50), index=True)
    # Types: confirmed, false_positive, incorrect_analysis, resolved, helpful, not_helpful
    
    comment: Mapped[Optional[str]] = mapped_column(Text)
    user_id: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Resolution info
    resolution_applied: Mapped[Optional[str]] = mapped_column(Text)
    time_to_resolve: Mapped[Optional[int]] = mapped_column(Integer)  # minutes
    
    # Pattern update tracking
    pattern_updated: Mapped[bool] = mapped_column(Integer, default=0)  # 0=False, 1=True for DB compat
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self) -> str:
        return f"<Feedback(id={self.id}, type={self.feedback_type}, finding_id={self.finding_id})>"
