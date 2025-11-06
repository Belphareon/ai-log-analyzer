"""
Feedback endpoint - collect user feedback for learning.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from app.services.learner import learner_service
from app.core.database import get_db
from app.schemas import FeedbackCreate
from app.models import Feedback, Finding
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/feedback")
async def submit_feedback(
    feedback: FeedbackCreate,
    db: Session = Depends(get_db)
):
    """
    Submit feedback on AI analysis.
    
    Used for self-learning and improving accuracy.
    """
    try:
        # Verify finding exists
        finding = db.query(Finding).filter(Finding.id == feedback.finding_id).first()
        if not finding:
            raise HTTPException(status_code=404, detail="Finding not found")
        
        # Create feedback record
        fb = Feedback(
            finding_id=feedback.finding_id,
            feedback_type=feedback.feedback_type,
            rating=feedback.rating,
            comment=feedback.comment,
            correct_root_cause=feedback.correct_root_cause,
            correct_severity=feedback.correct_severity,
            resolution_applied=feedback.resolution_applied,
            time_to_resolve=feedback.time_to_resolve,
            submitted_by=feedback.submitted_by,
            submitted_at=datetime.utcnow()
        )
        db.add(fb)
        
        # Update finding with feedback
        finding.feedback_type = feedback.feedback_type
        finding.feedback_comment = feedback.comment
        finding.feedback_timestamp = datetime.utcnow()
        
        if feedback.feedback_type == "resolved":
            finding.resolved = True
            finding.resolution_notes = feedback.resolution_applied
        
        db.commit()
        
        return {
            "status": "success",
            "feedback_id": fb.id,
            "message": "Feedback recorded, will be used for learning"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Feedback endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
