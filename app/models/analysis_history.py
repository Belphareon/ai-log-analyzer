"""Models for EWMA baseline tracking and analysis history."""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class EWMABaseline(Base):
    """
    EWMA (Exponentially Weighted Moving Average) baseline for each fingerprint.
    Used for spike detection.
    """
    __tablename__ = "ewma_baselines"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Identification
    fingerprint: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    app_name: Mapped[str] = mapped_column(String(100), index=True)
    namespace: Mapped[str] = mapped_column(String(100), index=True)
    
    # EWMA metrics
    ewma_value: Mapped[float] = mapped_column(Float, default=0.0)
    ewma_alpha: Mapped[float] = mapped_column(Float, default=0.3)  # smoothing factor
    threshold_multiplier: Mapped[float] = mapped_column(Float, default=3.0)  # spike threshold
    
    # History
    count_history: Mapped[list] = mapped_column(JSON, default=list)  # last N counts
    last_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Spike tracking
    last_spike_detected: Mapped[Optional[datetime]] = mapped_column(DateTime)
    spike_count: Mapped[int] = mapped_column(Integer, default=0)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self) -> str:
        return f"<EWMABaseline(fp={self.fingerprint[:8]}, ewma={self.ewma_value:.2f})>"
    
    def is_spike(self, current_count: int) -> bool:
        """Check if current count is a spike compared to EWMA baseline."""
        if self.ewma_value == 0:
            return False
        threshold = self.ewma_value * self.threshold_multiplier
        return current_count > threshold


class AnalysisHistory(Base):
    """
    Historical analysis data for trend analysis and reporting.
    Aggregated data per fingerprint per time window.
    """
    __tablename__ = "analysis_history"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # Identification
    fingerprint: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    app_name: Mapped[str] = mapped_column(String(100), index=True)
    namespace: Mapped[str] = mapped_column(String(100), index=True)
    
    # Time window
    window_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    
    # Metrics
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    was_spike: Mapped[bool] = mapped_column(Integer, default=False)
    ewma_at_time: Mapped[float] = mapped_column(Float)
    
    # Analysis
    analyzed: Mapped[bool] = mapped_column(Integer, default=False)
    analysis_confidence: Mapped[Optional[float]] = mapped_column(Float)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_analysis_history_fp_window', 'fingerprint', 'window_start'),
    )
    
    def __repr__(self) -> str:
        return f"<AnalysisHistory(fp={self.fingerprint[:8]}, count={self.total_count}, spike={self.was_spike})>"
