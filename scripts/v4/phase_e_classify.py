#!/usr/bin/env python3
"""
FÁZE E: Classify
================

Vstup: normalized message, error type
Výstup: category + subcategory

✅ Taxonomy-based classification
✅ Pattern matching
✅ Deterministické (žádné ML)

❌ Žádné heuristiky typu "když text obsahuje X, tak asi Y"
❌ Žádné fuzzy matching
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from enum import Enum
import re

# Import from same package
try:
    from .incident import IncidentCategory
except ImportError:
    from incident import IncidentCategory


@dataclass
class ClassificationRule:
    """Pravidlo pro klasifikaci"""
    category: IncidentCategory
    subcategory: str
    patterns: List[str]              # Regex patterns
    priority: int = 0                # Vyšší = důležitější


@dataclass
class ClassificationResult:
    """Výstup z FÁZE E"""
    fingerprint: str
    category: IncidentCategory
    subcategory: str
    matched_rule: Optional[str] = None
    confidence: float = 1.0          # Pro pattern match vždy 1.0


class PhaseE_Classify:
    """
    FÁZE E: Classify
    
    Klasifikuje incidenty do taxonomy kategorií.
    
    Používá explicitní pravidla, žádné heuristiky.
    """
    
    # Výchozí pravidla - seřazená podle priority (nejvyšší první)
    DEFAULT_RULES: List[ClassificationRule] = [
        # MEMORY
        ClassificationRule(
            category=IncidentCategory.MEMORY,
            subcategory="out_of_memory",
            patterns=[r'OutOfMemory', r'OOM', r'heap space', r'GC overhead'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.MEMORY,
            subcategory="memory_leak",
            patterns=[r'memory leak', r'MemoryLeak'],
            priority=90,
        ),
        
        # DATABASE
        ClassificationRule(
            category=IncidentCategory.DATABASE,
            subcategory="connection",
            patterns=[r'database.*connection', r'DB.*connection', r'JDBC.*connection', r'PostgreSQL.*connection'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.DATABASE,
            subcategory="deadlock",
            patterns=[r'deadlock', r'Deadlock'],
            priority=95,
        ),
        ClassificationRule(
            category=IncidentCategory.DATABASE,
            subcategory="constraint_violation",
            patterns=[r'constraint violation', r'unique constraint', r'foreign key'],
            priority=80,
        ),
        ClassificationRule(
            category=IncidentCategory.DATABASE,
            subcategory="query_error",
            patterns=[r'SQL.*error', r'query.*failed', r'syntax error.*SQL'],
            priority=70,
        ),
        
        # NETWORK
        ClassificationRule(
            category=IncidentCategory.NETWORK,
            subcategory="connection_refused",
            patterns=[r'connection refused', r'Connection refused', r'ECONNREFUSED'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.NETWORK,
            subcategory="connection_reset",
            patterns=[r'connection reset', r'ECONNRESET'],
            priority=95,
        ),
        ClassificationRule(
            category=IncidentCategory.NETWORK,
            subcategory="dns",
            patterns=[r'DNS.*failed', r'UnknownHostException', r'ENOTFOUND'],
            priority=90,
        ),
        ClassificationRule(
            category=IncidentCategory.NETWORK,
            subcategory="ssl",
            patterns=[r'SSL.*error', r'TLS.*error', r'certificate', r'CERT_'],
            priority=85,
        ),
        
        # TIMEOUT
        ClassificationRule(
            category=IncidentCategory.TIMEOUT,
            subcategory="read_timeout",
            patterns=[r'read timeout', r'ReadTimeout', r'socket timeout'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.TIMEOUT,
            subcategory="connect_timeout",
            patterns=[r'connect timeout', r'ConnectTimeout', r'connection timed out'],
            priority=95,
        ),
        ClassificationRule(
            category=IncidentCategory.TIMEOUT,
            subcategory="request_timeout",
            patterns=[r'request timeout', r'RequestTimeout', r'ETIMEDOUT'],
            priority=90,
        ),
        ClassificationRule(
            category=IncidentCategory.TIMEOUT,
            subcategory="generic",
            patterns=[r'[Tt]imeout', r'timed out'],
            priority=50,
        ),
        
        # AUTH
        ClassificationRule(
            category=IncidentCategory.AUTH,
            subcategory="unauthorized",
            patterns=[r'401', r'[Uu]nauthorized', r'authentication failed'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.AUTH,
            subcategory="forbidden",
            patterns=[r'403', r'[Ff]orbidden', r'access denied', r'permission denied'],
            priority=95,
        ),
        ClassificationRule(
            category=IncidentCategory.AUTH,
            subcategory="token_expired",
            patterns=[r'token expired', r'TokenExpired', r'JWT expired'],
            priority=90,
        ),
        
        # BUSINESS
        ClassificationRule(
            category=IncidentCategory.BUSINESS,
            subcategory="not_found",
            patterns=[r'404', r'[Nn]ot [Ff]ound', r'NotFoundException', r'does not exist'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.BUSINESS,
            subcategory="validation",
            patterns=[r'[Vv]alidation.*failed', r'[Ii]nvalid.*parameter', r'IllegalArgument'],
            priority=90,
        ),
        ClassificationRule(
            category=IncidentCategory.BUSINESS,
            subcategory="business_exception",
            patterns=[r'BusinessException', r'ServiceBusinessException'],
            priority=80,
        ),
        
        # EXTERNAL
        ClassificationRule(
            category=IncidentCategory.EXTERNAL,
            subcategory="api_error",
            patterns=[r'external.*API', r'third.*party', r'upstream.*error'],
            priority=100,
        ),
        ClassificationRule(
            category=IncidentCategory.EXTERNAL,
            subcategory="service_unavailable",
            patterns=[r'503', r'[Ss]ervice [Uu]navailable'],
            priority=95,
        ),
        ClassificationRule(
            category=IncidentCategory.EXTERNAL,
            subcategory="server_error",
            patterns=[r'500', r'[Ii]nternal [Ss]erver [Ee]rror'],
            priority=80,
        ),
    ]
    
    def __init__(self, rules: List[ClassificationRule] = None):
        self.rules = rules or self.DEFAULT_RULES.copy()
        # Sort by priority (highest first)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        
        # Compile patterns
        self._compiled_rules = []
        for rule in self.rules:
            compiled_patterns = [re.compile(p, re.IGNORECASE) for p in rule.patterns]
            self._compiled_rules.append((rule, compiled_patterns))
    
    def classify(
        self,
        normalized_message: str,
        error_type: str,
        fingerprint: str = "",
    ) -> ClassificationResult:
        """
        Klasifikuje incident na základě message a error type.
        
        Prochází pravidla podle priority, první match vyhrává.
        """
        text_to_match = f"{error_type} {normalized_message}"
        
        for rule, compiled_patterns in self._compiled_rules:
            for pattern in compiled_patterns:
                if pattern.search(text_to_match):
                    return ClassificationResult(
                        fingerprint=fingerprint,
                        category=rule.category,
                        subcategory=rule.subcategory,
                        matched_rule=f"{rule.category.value}/{rule.subcategory}",
                        confidence=1.0,
                    )
        
        # No match - unknown
        return ClassificationResult(
            fingerprint=fingerprint,
            category=IncidentCategory.UNKNOWN,
            subcategory="unclassified",
            matched_rule=None,
            confidence=0.5,
        )
    
    def classify_batch(
        self,
        items: List[Tuple[str, str, str]],  # (fingerprint, normalized_message, error_type)
    ) -> Dict[str, ClassificationResult]:
        """
        Klasifikuje batch incidentů.
        """
        results = {}
        for fingerprint, normalized_message, error_type in items:
            results[fingerprint] = self.classify(normalized_message, error_type, fingerprint)
        return results
    
    def add_rule(self, rule: ClassificationRule):
        """Přidá pravidlo a znovu seřadí"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        
        # Recompile
        compiled_patterns = [re.compile(p, re.IGNORECASE) for p in rule.patterns]
        self._compiled_rules.append((rule, compiled_patterns))
        self._compiled_rules.sort(key=lambda x: x[0].priority, reverse=True)


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    classifier = PhaseE_Classify()
    
    test_cases = [
        ("fp1", "Connection to <IP>:<PORT> refused", "ConnectionError"),
        ("fp2", "java.lang.OutOfMemoryError: Java heap space", "OutOfMemoryError"),
        ("fp3", "Request timeout after 30000ms", "TimeoutError"),
        ("fp4", "User <UUID> not found in database", "NotFoundException"),
        ("fp5", "Database connection pool exhausted", "DatabaseException"),
        ("fp6", "401 Unauthorized: Invalid token", "UnauthorizedError"),
        ("fp7", "Something weird happened", "UnknownError"),
    ]
    
    print("=== FÁZE E: Classify ===\n")
    
    for fp, msg, err_type in test_cases:
        result = classifier.classify(msg, err_type, fp)
        print(f"{fp}: {result.category.value}/{result.subcategory}")
        print(f"   Matched: {result.matched_rule}")
        print(f"   Message: {msg[:50]}...")
        print()
