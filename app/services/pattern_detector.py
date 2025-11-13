"""Pattern detection service - ML-based error clustering"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

class PatternDetector:
    """Detect error patterns and classify as new/recurring"""
    
    def normalize_message(self, message: str) -> str:
        """Normalize error message for pattern matching
        
        ORDER MATTERS! More specific patterns must come first
        to avoid being overwritten by general {ID} pattern.
        """
        normalized = message
        
        # 1. UUIDs (before general ID pattern)
        normalized = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{UUID}', normalized, flags=re.I)
        
        # 2. Timestamps (before general ID pattern)
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?', '{TIMESTAMP}', normalized)
        
        # 3. IP addresses (before general ID pattern)
        normalized = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '{IP}', normalized)
        
        # 4. Hex addresses (before general ID pattern)
        normalized = re.sub(r'0x[0-9a-f]+', '{HEX}', normalized, flags=re.I)
        
        # 5. Port numbers after IP
        normalized = re.sub(r'\{IP\}:\d{2,5}', '{IP}:{PORT}', normalized)
        
        # 6. HTTP status codes (keep specific)
        normalized = re.sub(r'\b(HTTP|Status)\s+(\d{3})\b', r'\1 {STATUS}', normalized, flags=re.I)
        
        # 7. Durations and measurements (before general ID)
        normalized = re.sub(r'\b\d+(ms|s|sec|min|minutes|h|hours|%)\b', r'{N}\1', normalized, flags=re.I)
        
        # 8. General numbers (IDs) - 3+ digits
        # This must be LAST as it's most general
        normalized = re.sub(r'\b\d{3,}\b', '{ID}', normalized)
        
        return normalized[:200]
    
    def extract_error_code(self, message: str) -> str:
        """Extract error code (err.XXX)"""
        match = re.search(r'err\.(\d+)', message)
        return f"err.{match.group(1)}" if match else None
    
    def extract_card_id(self, message: str) -> str:
        """Extract Card ID"""
        match = re.search(r'[Cc]ard.*?id\s+(\d+)', message)
        return match.group(1) if match else None
    
    def cluster_errors(self, errors: List[Dict]) -> Dict[str, List[Dict]]:
        """Cluster errors by normalized pattern"""
        clusters = defaultdict(list)
        
        for error in errors:
            msg = error.get('message', '')
            normalized = self.normalize_message(msg)
            clusters[normalized].append(error)
        
        return dict(clusters)
    
    def detect_peaks(self, timeline: List[Tuple[datetime, int]], threshold: int = 1000) -> List[Dict]:
        """Detect error peaks in timeline"""
        peaks = []
        
        for i, (ts, count) in enumerate(timeline):
            if count > threshold:
                # Check if it's isolated spike
                prev_count = timeline[i-1][1] if i > 0 else 0
                next_count = timeline[i+1][1] if i < len(timeline)-1 else 0
                
                if count > prev_count * 5 and count > next_count * 5:
                    peaks.append({
                        'timestamp': ts,
                        'count': count,
                        'prev': prev_count,
                        'next': next_count
                    })
        
        return peaks

pattern_detector = PatternDetector()
