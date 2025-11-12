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
            comment=feedback.comment,
            resolution_applied=feedback.resolution_applied,
            time_to_resolve=feedback.time_to_resolve,
            user_id=feedback.submitted_by,  # Map to existing column
            # created_at is set automatically by default
        )
        db.add(fb)
        
        # Update finding with feedback
        finding.feedback_type = feedback.feedback_type
        
        if feedback.feedback_type == "resolved":
            finding.resolved = True
            finding.resolved_at = datetime.utcnow()
        
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
