"""Pattern detection service - ML-based error clustering"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

class PatternDetector:
    """Detect error patterns and classify as new/recurring"""
    
    def normalize_message(self, message: str) -> str:
        """Normalize error message for pattern matching"""
        # Remove numbers (IDs) - všechna čísla 3+ digits
        normalized = re.sub(r'\d{3,}', '{ID}', message)
        # Remove UUIDs
        normalized = re.sub(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '{UUID}', normalized, flags=re.I)
        # Remove timestamps
        normalized = re.sub(r'\d{4}-\d{2}-\d{2}T[\d:\.]+Z?', '{TIMESTAMP}', normalized)
        # Remove IPs
        normalized = re.sub(r'\d+\.\d+\.\d+\.\d+', '{IP}', normalized)
        # Remove hex addresses
        normalized = re.sub(r'0x[0-9a-f]+', '{HEX}', normalized, flags=re.I)
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
