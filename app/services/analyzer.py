"""
Analyzer service - core AI analysis logic.
"""
import logging
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from app.models import Finding, Pattern, EWMABaseline
from app.services.llm import ollama_service
from app.services.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class AnalyzerService:
    """Core analysis service with pattern matching and AI."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    async def match_patterns(
        self,
        finding: Finding,
        db: Session
    ) -> List[Pattern]:
        """
        Match finding against known patterns.
        
        Returns list of matching patterns ordered by confidence.
        """
        matched = []
        
        # Get all active patterns
        patterns = db.query(Pattern).all()
        
        for pattern in patterns:
            match_score = self._calculate_pattern_match(finding, pattern)
            
            if match_score > 0.5:  # 50% confidence threshold
                matched.append({
                    "pattern": pattern,
                    "confidence": match_score
                })
        
        # Sort by confidence
        matched.sort(key=lambda x: x["confidence"], reverse=True)
        
        return [m["pattern"] for m in matched]
    
    def _calculate_pattern_match(
        self,
        finding: Finding,
        pattern: Pattern
    ) -> float:
        """Calculate how well a finding matches a pattern (0.0 - 1.0)."""
        score = 0.0
        checks = 0
        
        # Check app filter
        if pattern.app_filter:
            checks += 1
            if finding.app_name in pattern.app_filter:
                score += 1.0
            else:
                return 0.0  # App doesn't match, skip pattern
        
        # Check namespace filter
        if pattern.namespace_filter:
            checks += 1
            if finding.namespace in pattern.namespace_filter:
                score += 1.0
            else:
                return 0.0  # Namespace doesn't match
        
        # Check regex pattern
        if pattern.regex_pattern:
            checks += 1
            try:
                if re.search(pattern.regex_pattern, finding.message, re.IGNORECASE):
                    score += 1.0
            except re.error as e:
                self.logger.warning(f"Invalid regex in pattern {pattern.id}: {e}")
        
        # Check keywords
        if pattern.keywords:
            checks += 1
            message_lower = finding.message.lower()
            matched_keywords = sum(
                1 for kw in pattern.keywords
                if kw.lower() in message_lower
            )
            if matched_keywords > 0:
                # Partial score based on keyword match ratio
                score += matched_keywords / len(pattern.keywords)
        
        # Check severity match
        if pattern.severity and finding.severity:
            checks += 1
            if pattern.severity == finding.severity:
                score += 0.5  # Bonus for severity match
        
        # Calculate final score
        if checks == 0:
            return 0.0
        
        return min(score / checks, 1.0)


# Global instance
analyzer_service = AnalyzerService()


