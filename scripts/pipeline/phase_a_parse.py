#!/usr/bin/env python3
"""
FÁZE A: Parse & Normalize
=========================

Vstup: raw log/error
Výstup: normalized_line + fingerprint

❌ Žádná logika
❌ Žádné prahy
❌ Žádné rozhodování

Pouze:
✅ Extrakce polí
✅ Normalizace message
✅ Generování fingerprint
"""

import re
import hashlib
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass

# Add core to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'core'))

try:
    from telemetry_context import (
        extract_application_version,
        extract_environment,
        extract_trace_id,
        extract_span_id,
        extract_parent_span_id,
        Environment,
    )
    HAS_TELEMETRY = True
except ImportError:
    HAS_TELEMETRY = False


@dataclass
class NormalizedRecord:
    """Výstup z FÁZE A"""
    # Original
    raw_message: str
    raw_timestamp: str

    # Extracted
    timestamp: Optional[datetime]
    namespace: str
    app_name: str                           # deployment_label (může obsahovat -v1)
    app_version: Optional[str]              # application.version (X.Y.Z) nebo None
    trace_id: Optional[str]
    span_id: Optional[str] = None           # NEW: span v rámci trace
    parent_span_id: Optional[str] = None    # NEW: parent span
    environment: str = "unknown"            # NEW: prod/uat/sit/dev

    # Normalized
    normalized_message: str = ""
    error_type: str = ""
    fingerprint: str = ""


class PhaseA_Parser:
    """
    FÁZE A: Parse & Normalize
    
    Pravidla:
    - Žádná logika
    - Žádné prahy
    - Jen transformace dat
    """
    
    # Patterns pro normalizaci (odstranění variabilních částí)
    NORMALIZE_PATTERNS = [
        # UUIDs
        (r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<UUID>'),
        # Long numbers (IDs)
        (r'\b\d{10,}\b', '<ID>'),
        # Short IDs in context
        (r'(?:id|Id|ID)[=:\s]+\d+', 'id=<ID>'),
        # IP addresses
        (r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '<IP>'),
        # Timestamps in message
        (r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?', '<TS>'),
        # Hex strings
        (r'0x[0-9a-fA-F]+', '<HEX>'),
        # Port numbers
        (r':(\d{4,5})\b', ':<PORT>'),
        # Memory addresses
        (r'@[0-9a-f]{6,}', '@<ADDR>'),
        # File paths with numbers
        (r'/\d+/', '/<NUM>/'),
        # Query parameters
        (r'\?\S+', '?<PARAMS>'),
    ]
    
    # Patterns pro extrakci error type
    ERROR_TYPE_PATTERNS = [
        r'(\w+Exception)',
        r'(\w+Error)',
        r'(\w+Failure)',
        r'(\w+Fault)',
    ]
    
    def __init__(self):
        # Compile patterns for performance
        self._normalize_compiled = [
            (re.compile(p), r) for p, r in self.NORMALIZE_PATTERNS
        ]
        self._error_type_compiled = [
            re.compile(p) for p in self.ERROR_TYPE_PATTERNS
        ]
    
    def normalize_message(self, msg: str) -> str:
        """
        Normalizuje message - odstraní variabilní části.
        
        Vstup: "Connection to 192.168.1.1:5432 failed for user 12345"
        Výstup: "Connection to <IP>:<PORT> failed for user <ID>"
        """
        result = msg
        for pattern, replacement in self._normalize_compiled:
            result = pattern.sub(replacement, result)
        
        # Limit length
        return result[:500]
    
    def extract_error_type(self, msg: str) -> str:
        """
        Extrahuje error type z message.
        
        Vstup: "java.lang.NullPointerException: ..."
        Výstup: "NullPointerException"
        """
        for pattern in self._error_type_compiled:
            match = pattern.search(msg)
            if match:
                return match.group(1)
        
        # Fallback: HTTP codes
        if '404' in msg:
            return 'NotFoundError'
        if '500' in msg or '503' in msg:
            return 'ServerError'
        if '401' in msg:
            return 'UnauthorizedError'
        if '403' in msg:
            return 'ForbiddenError'
        if 'timeout' in msg.lower():
            return 'TimeoutError'
        if 'connection' in msg.lower() and ('refused' in msg.lower() or 'failed' in msg.lower()):
            return 'ConnectionError'
        
        return 'UnknownError'
    
    def generate_fingerprint(self, normalized_message: str, error_type: str) -> str:
        """
        Generuje fingerprint pro deduplikaci.
        
        Fingerprint = MD5(error_type + normalized_message)[:16]
        """
        combined = f"{error_type}:{normalized_message}"
        return hashlib.md5(combined.encode()).hexdigest()[:16]
    
    def extract_app_version(self, app_name: str, error: dict) -> Optional[str]:
        """
        Extrahuje verzi aplikace POUZE z explicitního pole.

        POVOLENO:
        - application.version
        - app_version
        - version (pokud je semantic X.Y.Z)

        ZAKÁZÁNO:
        - Extrakce z názvu aplikace (-v1, -v2)
        - Build number
        - SDK version
        """
        if HAS_TELEMETRY:
            return extract_application_version(error)

        # Fallback bez telemetry modulu
        version = (
            error.get('application.version') or
            error.get('app_version') or
            error.get('appVersion')
        )

        if not version:
            return None

        version = str(version).strip()

        # Validace semantic version
        if re.match(r'^\d+\.\d+\.\d+', version):
            return version

        return None
    
    def parse_timestamp(self, ts_str: str) -> Optional[datetime]:
        """Parse timestamp string to datetime"""
        if not ts_str:
            return None
        
        try:
            # Handle various formats
            ts_str = ts_str.replace('Z', '+00:00')
            return datetime.fromisoformat(ts_str)
        except:
            return None
    
    def parse(self, error: dict) -> NormalizedRecord:
        """
        Parsuje jeden error záznam.

        Vstup: raw error dict z ES/JSON
        Výstup: NormalizedRecord

        Nová pole v V6:
        - span_id, parent_span_id (pro trace propagation)
        - environment (odvozeno z namespace)
        - app_version = POUZE z application.version (ne z názvu!)
        """
        # Extract raw values
        raw_message = error.get('message', '')
        raw_timestamp = error.get('@timestamp') or error.get('timestamp', '')
        namespace = error.get('kubernetes.namespace') or error.get('namespace', 'unknown')
        app_name = error.get('application.name') or error.get('application') or error.get('app') or 'unknown'

        # Handle nested application object
        if isinstance(error.get('application'), dict):
            app_name = error['application'].get('name', app_name)

        # Parse timestamp
        timestamp = self.parse_timestamp(raw_timestamp)

        # Extract app version (ONLY from explicit field, never from name!)
        app_version = self.extract_app_version(app_name, error)

        # Extract trace info
        if HAS_TELEMETRY:
            trace_id = extract_trace_id(error)
            span_id = extract_span_id(error)
            parent_span_id = extract_parent_span_id(error)
            environment = extract_environment(namespace).value
        else:
            trace_id = error.get('traceId') or error.get('trace_id')
            span_id = error.get('spanId') or error.get('span_id')
            parent_span_id = error.get('parentId') or error.get('parent_id')
            environment = self._derive_environment(namespace)

        # Normalize message
        normalized_message = self.normalize_message(raw_message)

        # Extract error type
        error_type = self.extract_error_type(raw_message)

        # Generate fingerprint
        fingerprint = self.generate_fingerprint(normalized_message, error_type)

        return NormalizedRecord(
            raw_message=raw_message[:1000],  # Keep sample
            raw_timestamp=raw_timestamp,
            timestamp=timestamp,
            namespace=namespace,
            app_name=app_name,
            app_version=app_version,
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            environment=environment,
            normalized_message=normalized_message,
            error_type=error_type,
            fingerprint=fingerprint,
        )

    def _derive_environment(self, namespace: str) -> str:
        """Fallback environment detection bez telemetry modulu."""
        ns_lower = namespace.lower()
        if '-prod-' in ns_lower or ns_lower.endswith('-prod'):
            return 'prod'
        if '-uat-' in ns_lower or ns_lower.endswith('-uat'):
            return 'uat'
        if '-sit-' in ns_lower or ns_lower.endswith('-sit'):
            return 'sit'
        if '-dev-' in ns_lower or ns_lower.endswith('-dev'):
            return 'dev'
        return 'unknown'
    
    def parse_batch(self, errors: List[dict]) -> List[NormalizedRecord]:
        """Parsuje batch errorů"""
        return [self.parse(e) for e in errors]


# ============================================================================
# GROUP BY FINGERPRINT
# ============================================================================

def group_by_fingerprint(records: List[NormalizedRecord]) -> Dict[str, List[NormalizedRecord]]:
    """
    Seskupí záznamy podle fingerprint.
    
    Toto je čistá transformace, žádná logika.
    """
    groups = {}
    for record in records:
        fp = record.fingerprint
        if fp not in groups:
            groups[fp] = []
        groups[fp].append(record)
    return groups


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    # Test
    parser = PhaseA_Parser()
    
    test_errors = [
        {
            "timestamp": "2026-01-20T10:30:00Z",
            "namespace": "pcb-sit-01-app",
            "application": "bl-pcb-v1",
            "message": "Connection to 192.168.1.100:5432 refused for user 1234567890",
            "trace_id": "abc-123-def"
        },
        {
            "timestamp": "2026-01-20T10:30:05Z",
            "namespace": "pcb-sit-01-app",
            "application": "bl-pcb-v1",
            "message": "Connection to 192.168.1.101:5432 refused for user 9876543210",
            "trace_id": "xyz-456-ghi"
        },
    ]
    
    records = parser.parse_batch(test_errors)
    
    print("=== FÁZE A: Parse & Normalize ===\n")
    
    for r in records:
        print(f"Raw: {r.raw_message[:60]}...")
        print(f"Normalized: {r.normalized_message}")
        print(f"Error Type: {r.error_type}")
        print(f"Fingerprint: {r.fingerprint}")
        print()
    
    # Group
    groups = group_by_fingerprint(records)
    print(f"Unique fingerprints: {len(groups)}")
    for fp, recs in groups.items():
        print(f"  {fp}: {len(recs)} records")
