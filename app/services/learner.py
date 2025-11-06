"""
Learner service - self-learning and auto-adjustment.
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from app.models import Finding, Pattern, Feedback, EWMABaseline

logger = logging.getLogger(__name__)


class LearnerService:
    """Self-learning service that improves over time."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def process_feedback(
        self,
        feedback: Feedback,
        db: Session
    ) -> Dict[str, Any]:
        """
        Process user feedback and learn from it.
        
        Actions:
        - Update pattern confidence
        - Adjust thresholds
        - Create new patterns
        - Mark false positives
        """
        finding = db.query(Finding).filter(Finding.id == feedback.finding_id).first()
        if not finding:
            return {"status": "error", "message": "Finding not found"}
        
        actions_taken = []
        
        # Handle false positives
        if feedback.feedback_type == "false_positive":
            actions_taken.append(self._handle_false_positive(finding, feedback, db))
        
        # Handle confirmed issues
        elif feedback.feedback_type == "confirmed":
            actions_taken.append(self._handle_confirmed(finding, feedback, db))
        
        # Handle resolved issues
        elif feedback.feedback_type == "resolved":
            actions_taken.append(self._handle_resolved(finding, feedback, db))
        
        # Update pattern confidence based on feedback
        if feedback.rating:
            actions_taken.append(self._adjust_pattern_confidence(finding, feedback, db))
        
        return {
            "status": "success",
            "actions_taken": [a for a in actions_taken if a],
            "finding_updated": True
        }
    
    def _handle_false_positive(
        self,
        finding: Finding,
        feedback: Feedback,
        db: Session
    ) -> Optional[str]:
        """Handle false positive feedback."""
        
        # Check if we should create an ignore pattern
        false_positive_count = db.query(func.count(Feedback.id)).filter(
            Feedback.feedback_type == "false_positive"
        ).join(Finding).filter(
            Finding.fingerprint == finding.fingerprint
        ).scalar()
        
        if false_positive_count >= 3:  # 3+ false positives = auto-ignore
            # Create or update pattern to auto-ignore
            pattern = db.query(Pattern).filter(
                Pattern.pattern_hash == f"fp_{finding.fingerprint}"
            ).first()
            
            if not pattern:
                pattern = Pattern(
                    pattern_hash=f"fp_{finding.fingerprint}",
                    name=f"Auto-ignore: {finding.message[:50]}",
                    description="Auto-created from false positive feedback",
                    app_filter=[finding.app_name],
                    namespace_filter=[finding.namespace],
                    keywords=[word for word in finding.message.split() if len(word) > 4][:5],
                    category="false_positive",
                    auto_ignore=True,
                    confidence=80.0,
                    created_by="learner"
                )
                db.add(pattern)
                db.commit()
                
                feedback.pattern_updated = pattern.id
                db.commit()
                
                return f"Created auto-ignore pattern (pattern_id={pattern.id})"
            else:
                pattern.confidence = min(pattern.confidence + 10, 100)
                pattern.occurrences += 1
                db.commit()
                return f"Updated auto-ignore pattern confidence to {pattern.confidence}"
        
        return None
    
    def _handle_confirmed(
        self,
        finding: Finding,
        feedback: Feedback,
        db: Session
    ) -> Optional[str]:
        """Handle confirmed issue feedback."""
        
        # If user provided correct info, update finding
        if feedback.correct_severity:
            finding.severity = feedback.correct_severity
        
        if feedback.correct_root_cause:
            finding.root_cause = feedback.correct_root_cause
        
        db.commit()
        
        # Increase confidence in matching patterns
        # (implementation depends on pattern matching logic)
        
        return "Updated finding with confirmed information"
    
    def _handle_resolved(
        self,
        finding: Finding,
        feedback: Feedback,
        db: Session
    ) -> Optional[str]:
        """Handle resolved issue feedback."""
        
        finding.resolved = True
        finding.resolution_notes = feedback.resolution_applied
        db.commit()
        
        # TODO: Extract solution pattern for similar future issues
        
        return "Marked as resolved and stored solution"
    
    def _adjust_pattern_confidence(
        self,
        finding: Finding,
        feedback: Feedback,
        db: Session
    ) -> Optional[str]:
        """Adjust pattern confidence based on rating."""
        
        # Rating: 1-5 stars
        # 5 stars = increase confidence
        # 1-2 stars = decrease confidence
        
        if feedback.rating >= 4:
            adjustment = 5.0
        elif feedback.rating <= 2:
            adjustment = -10.0
        else:
            return None
        
        # Find patterns that matched this finding
        # (simplified - in real implementation, track pattern matches)
        patterns = db.query(Pattern).filter(
            Pattern.app_filter.contains([finding.app_name])
        ).limit(3).all()
        
        for pattern in patterns:
            pattern.confidence = max(0, min(100, pattern.confidence + adjustment))
        
        db.commit()
        
        return f"Adjusted {len(patterns)} pattern confidences"


# Global instance
learner_service = LearnerService()
