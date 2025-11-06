"""
Health and metrics endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy import func
import logging
import time
from datetime import datetime, timedelta

from app.core.database import get_db
from app.schemas import HealthResponse, MetricsResponse
from app.services import llm_service as ollama_service
from app.models import Finding, Pattern, Feedback

router = APIRouter()
logger = logging.getLogger(__name__)

# Track startup time
start_time = time.time()


@router.get("/health", response_model=HealthResponse)
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint."""
    
    # Check database
    db_healthy = False
    try:
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception as e:
        logger.error(f"DB health check failed: {e}")
    
    # Check Ollama
    ollama_healthy = await ollama_service.health_check()
    
    status = "healthy" if (db_healthy and ollama_healthy) else "degraded"
    
    return HealthResponse(
        status=status,
        database=db_healthy,
        ollama=ollama_healthy,
        version="0.1.0",
        uptime_seconds=time.time() - start_time
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(db: Session = Depends(get_db)):
    """Get system metrics."""
    
    # Total findings
    total = db.query(func.count(Finding.id)).scalar() or 0
    
    # Last 24h
    yesterday = datetime.utcnow() - timedelta(days=1)
    last_24h = db.query(func.count(Finding.id)).filter(
        Finding.created_at >= yesterday
    ).scalar() or 0
    
    # Average confidence
    avg_conf = db.query(func.avg(Finding.confidence)).filter(
        Finding.confidence.isnot(None)
    ).scalar()
    
    # Patterns learned
    patterns = db.query(func.count(Pattern.id)).scalar() or 0
    
    # Feedback count
    feedback = db.query(func.count(Feedback.id)).scalar() or 0
    
    # Top errors (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    top_errors = db.query(
        Finding.fingerprint,
        Finding.message,
        func.sum(Finding.count).label("total_count")
    ).filter(
        Finding.last_seen >= week_ago
    ).group_by(
        Finding.fingerprint, Finding.message
    ).order_by(
        func.sum(Finding.count).desc()
    ).limit(10).all()
    
    # Top apps
    top_apps = db.query(
        Finding.app_name,
        func.count(Finding.id).label("finding_count"),
        func.sum(Finding.count).label("total_errors")
    ).filter(
        Finding.last_seen >= week_ago
    ).group_by(
        Finding.app_name
    ).order_by(
        func.sum(Finding.count).desc()
    ).limit(10).all()
    
    return MetricsResponse(
        total_findings=total,
        findings_last_24h=last_24h,
        avg_confidence=float(avg_conf) if avg_conf else None,
        patterns_learned=patterns,
        feedback_count=feedback,
        top_errors=[
            {
                "fingerprint": e.fingerprint,
                "message": e.message[:100],
                "count": int(e.total_count)
            }
            for e in top_errors
        ],
        top_apps=[
            {
                "app": a.app_name,
                "findings": int(a.finding_count),
                "total_errors": int(a.total_errors)
            }
            for a in top_apps
        ]
    )
