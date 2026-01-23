#!/usr/bin/env python3
"""
KNOWLEDGE BASE
==============

Human-managed knowledge base pro known errors a peaks.

ZÁSADNÍ PRINCIPY:
1. Known issues NESMÍ vznikat automaticky
2. DB = fakta, Knowledge = lidské rozhodnutí
3. Jira dnes nevzniká automaticky - musí existovat review & approval
4. MD = pro člověka, YAML = pro engine (1:1 svázané)

Struktura:
knowledge/
├─ known_errors.yaml    # Pro engine (machine readable)
├─ known_errors.md      # Pro člověka (human readable)
├─ known_peaks.yaml
└─ known_peaks.md
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from enum import Enum
import yaml
import re


# =============================================================================
# ENUMS
# =============================================================================

class KnowledgeStatus(Enum):
    """Status known issue"""
    OPEN = "OPEN"               # Aktivní, neřešený
    IN_PROGRESS = "IN_PROGRESS" # Řeší se (má Jira, někdo pracuje)
    WORKAROUND = "WORKAROUND"   # Existuje workaround
    RESOLVED = "RESOLVED"       # Vyřešeno (fix deployed)
    WONT_FIX = "WONT_FIX"       # Nebude se řešit


class MatchConfidence(Enum):
    """Confidence matchování"""
    EXACT = "EXACT"         # Přesný fingerprint match
    HIGH = "HIGH"           # Cluster match nebo category + apps
    MEDIUM = "MEDIUM"       # Category match
    LOW = "LOW"             # Jen pattern match
    NONE = "NONE"           # Žádný match


# =============================================================================
# KNOWN ERROR (datový model z YAML)
# =============================================================================

@dataclass
class KnownError:
    """
    Known error v knowledge base.
    
    TOTO NENÍ automaticky generované - je to lidské rozhodnutí!
    """
    id: str                     # "KE-001"
    fingerprint: str            # Primary fingerprint
    category: str               # DATABASE, NETWORK, TIMEOUT, etc.
    description: str            # Human readable popis
    
    # Scope
    affected_apps: List[str] = field(default_factory=list)
    affected_namespaces: List[str] = field(default_factory=list)
    
    # Timing
    first_seen: Optional[date] = None
    last_seen: Optional[date] = None
    
    # Tracking
    jira: str = ""              # "OPS-431"
    status: KnowledgeStatus = KnowledgeStatus.OPEN
    owner: str = ""             # Kdo to řeší
    
    # Solutions (klíčové!)
    workaround: List[str] = field(default_factory=list)
    permanent_fix: List[str] = field(default_factory=list)
    
    # Cluster fingerprints (pro multi-fingerprint match)
    related_fingerprints: List[str] = field(default_factory=list)
    
    # Pattern pro fuzzy match (regex)
    error_pattern: str = ""
    
    # Notes
    notes: str = ""


@dataclass
class KnownPeak:
    """Known peak pattern"""
    id: str                     # "KP-001"
    fingerprint: str
    peak_type: str              # traffic, error, latency
    description: str
    
    affected_apps: List[str] = field(default_factory=list)
    first_seen: Optional[date] = None
    typical_duration_min: int = 0
    
    jira: str = ""
    status: KnowledgeStatus = KnowledgeStatus.OPEN
    
    # Link to error (pokud peak souvisí s errorem)
    linked_error_id: str = ""   # "KE-001"
    
    mitigation: List[str] = field(default_factory=list)
    error_pattern: str = ""


# =============================================================================
# MATCH RESULT
# =============================================================================

@dataclass
class KnowledgeMatch:
    """
    Výsledek matchování incidentu proti knowledge base.
    
    Toto se zobrazuje v reportu.
    """
    status: str                 # "KNOWN" nebo "NEW"
    confidence: MatchConfidence = MatchConfidence.NONE
    
    # Pokud KNOWN
    known_error_id: str = ""
    known_peak_id: str = ""
    
    # Match details
    match_reason: str = ""      # Proč je to match
    
    # References (přetažené z known issue)
    jira: str = ""
    workaround: List[str] = field(default_factory=list)
    permanent_fix: List[str] = field(default_factory=list)
    
    @property
    def is_known(self) -> bool:
        return self.status == "KNOWN"
    
    @property
    def is_new(self) -> bool:
        return self.status == "NEW"


# =============================================================================
# KNOWLEDGE BASE
# =============================================================================

class KnowledgeBase:
    """
    Knowledge base loader a matcher.
    
    Načítá z YAML souborů, matchuje incidenty.
    """
    
    def __init__(self, knowledge_dir: str = None):
        self.knowledge_dir = Path(knowledge_dir) if knowledge_dir else None
        self.errors: Dict[str, KnownError] = {}
        self.peaks: Dict[str, KnownPeak] = {}
        
        # Indexy pro rychlé vyhledávání
        self._fp_to_error: Dict[str, str] = {}
        self._fp_to_peak: Dict[str, str] = {}
        self._app_errors: Dict[str, Set[str]] = {}
        self._category_errors: Dict[str, Set[str]] = {}
    
    def load(self, knowledge_dir: str = None) -> 'KnowledgeBase':
        """Načte knowledge base z YAML"""
        if knowledge_dir:
            self.knowledge_dir = Path(knowledge_dir)
        
        if not self.knowledge_dir or not self.knowledge_dir.exists():
            return self
        
        # Load errors
        errors_file = self.knowledge_dir / "known_errors.yaml"
        if errors_file.exists():
            self._load_errors(errors_file)
        
        # Load peaks
        peaks_file = self.knowledge_dir / "known_peaks.yaml"
        if peaks_file.exists():
            self._load_peaks(peaks_file)
        
        # Build indices
        self._build_indices()
        
        return self
    
    def _load_errors(self, filepath: Path):
        """Načte known errors"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        for item in data.get('known_errors', []):
            if not item:
                continue
            error = KnownError(
                id=item.get('id', ''),
                fingerprint=item.get('fingerprint', ''),
                category=item.get('category', 'UNKNOWN'),
                description=item.get('description', '').strip(),
                affected_apps=item.get('affected_apps', []),
                affected_namespaces=item.get('affected_namespaces', []),
                first_seen=self._parse_date(item.get('first_seen')),
                last_seen=self._parse_date(item.get('last_seen')),
                jira=item.get('jira', ''),
                status=KnowledgeStatus[item.get('status', 'OPEN')],
                owner=item.get('owner', ''),
                workaround=item.get('workaround', []) or [],
                permanent_fix=item.get('permanent_fix', []) or [],
                related_fingerprints=item.get('related_fingerprints', []) or [],
                error_pattern=item.get('error_pattern', ''),
                notes=item.get('notes', ''),
            )
            self.errors[error.id] = error
    
    def _load_peaks(self, filepath: Path):
        """Načte known peaks"""
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        for item in data.get('known_peaks', []):
            if not item:
                continue
            peak = KnownPeak(
                id=item.get('id', ''),
                fingerprint=item.get('fingerprint', ''),
                peak_type=item.get('peak_type', 'error'),
                description=item.get('description', ''),
                affected_apps=item.get('affected_apps', []),
                first_seen=self._parse_date(item.get('first_seen')),
                typical_duration_min=item.get('typical_duration_min', 0),
                jira=item.get('jira', ''),
                status=KnowledgeStatus[item.get('status', 'OPEN')],
                linked_error_id=item.get('linked_error_id', ''),
                mitigation=item.get('mitigation', []) or [],
                error_pattern=item.get('error_pattern', ''),
            )
            self.peaks[peak.id] = peak
    
    def _parse_date(self, value) -> Optional[date]:
        """Parse date"""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.strptime(value, '%Y-%m-%d').date()
            except:
                return None
        return None
    
    def _build_indices(self):
        """Staví indexy"""
        self._fp_to_error.clear()
        self._fp_to_peak.clear()
        self._app_errors.clear()
        self._category_errors.clear()
        
        for error_id, error in self.errors.items():
            # Primary fingerprint
            if error.fingerprint:
                self._fp_to_error[error.fingerprint] = error_id
            
            # Related fingerprints
            for fp in error.related_fingerprints:
                self._fp_to_error[fp] = error_id
            
            # App index
            for app in error.affected_apps:
                if app not in self._app_errors:
                    self._app_errors[app] = set()
                self._app_errors[app].add(error_id)
            
            # Category index
            cat = error.category.upper()
            if cat not in self._category_errors:
                self._category_errors[cat] = set()
            self._category_errors[cat].add(error_id)
        
        for peak_id, peak in self.peaks.items():
            if peak.fingerprint:
                self._fp_to_peak[peak.fingerprint] = peak_id
    
    def match_incident(
        self,
        fingerprint: str,
        category: str = "",
        affected_apps: List[str] = None,
        error_message: str = ""
    ) -> KnowledgeMatch:
        """
        Matchuje incident proti knowledge base.
        
        Matching pravidla (v pořadí priority):
        1. Exact fingerprint match → EXACT confidence
        2. Fingerprint ∈ cluster → HIGH confidence  
        3. Category + affected_apps match → HIGH confidence
        4. Pattern match (regex) → MEDIUM confidence
        
        Returns:
            KnowledgeMatch s status "KNOWN" nebo "NEW"
        """
        affected_apps = affected_apps or []
        
        # 1. Exact fingerprint match
        fp_base = fingerprint.rsplit('-', 1)[0]  # Remove date suffix
        
        if fp_base in self._fp_to_error:
            error_id = self._fp_to_error[fp_base]
            error = self.errors[error_id]
            return KnowledgeMatch(
                status="KNOWN",
                confidence=MatchConfidence.EXACT,
                known_error_id=error_id,
                match_reason=f"Exact fingerprint: {fp_base[:12]}...",
                jira=error.jira,
                workaround=error.workaround,
                permanent_fix=error.permanent_fix,
            )
        
        # Zkus i plný fingerprint
        if fingerprint in self._fp_to_error:
            error_id = self._fp_to_error[fingerprint]
            error = self.errors[error_id]
            return KnowledgeMatch(
                status="KNOWN",
                confidence=MatchConfidence.EXACT,
                known_error_id=error_id,
                match_reason=f"Exact fingerprint: {fingerprint[:12]}...",
                jira=error.jira,
                workaround=error.workaround,
                permanent_fix=error.permanent_fix,
            )
        
        # 2. Category + apps match
        if category and affected_apps:
            cat_upper = category.upper()
            if cat_upper in self._category_errors:
                for error_id in self._category_errors[cat_upper]:
                    error = self.errors[error_id]
                    common = set(affected_apps) & set(error.affected_apps)
                    if len(common) >= 1:
                        return KnowledgeMatch(
                            status="KNOWN",
                            confidence=MatchConfidence.HIGH,
                            known_error_id=error_id,
                            match_reason=f"Category + apps: {cat_upper}, {common}",
                            jira=error.jira,
                            workaround=error.workaround,
                            permanent_fix=error.permanent_fix,
                        )
        
        # 3. Pattern match
        if error_message:
            for error_id, error in self.errors.items():
                if error.error_pattern:
                    try:
                        if re.search(error.error_pattern, error_message, re.IGNORECASE):
                            return KnowledgeMatch(
                                status="KNOWN",
                                confidence=MatchConfidence.MEDIUM,
                                known_error_id=error_id,
                                match_reason=f"Pattern: {error.error_pattern[:30]}...",
                                jira=error.jira,
                                workaround=error.workaround,
                                permanent_fix=error.permanent_fix,
                            )
                    except re.error:
                        pass
        
        # No match = NEW
        return KnowledgeMatch(status="NEW", confidence=MatchConfidence.NONE)
    
    def match_peak(self, fingerprint: str, affected_apps: List[str] = None) -> KnowledgeMatch:
        """Matchuje peak"""
        fp_base = fingerprint.rsplit('-', 1)[0]
        
        if fp_base in self._fp_to_peak:
            peak_id = self._fp_to_peak[fp_base]
            peak = self.peaks[peak_id]
            return KnowledgeMatch(
                status="KNOWN",
                confidence=MatchConfidence.EXACT,
                known_peak_id=peak_id,
                match_reason=f"Exact fingerprint",
                jira=peak.jira,
                workaround=peak.mitigation,
            )
        
        return KnowledgeMatch(status="NEW", confidence=MatchConfidence.NONE)
    
    def get_error(self, error_id: str) -> Optional[KnownError]:
        return self.errors.get(error_id)
    
    def get_peak(self, peak_id: str) -> Optional[KnownPeak]:
        return self.peaks.get(peak_id)
    
    @property
    def error_count(self) -> int:
        return len(self.errors)
    
    @property
    def peak_count(self) -> int:
        return len(self.peaks)


# =============================================================================
# YAML/MD TEMPLATE GENERATOR
# =============================================================================

def create_knowledge_base_template(output_dir: str):
    """Vytvoří prázdnou knowledge base s templates"""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    
    # ===== known_errors.yaml =====
    errors_yaml = """# Known Errors - YAML (machine readable)
# This file is MANUALLY maintained. Do not auto-generate entries.
# Each entry MUST have corresponding entry in known_errors.md

known_errors:
  - id: KE-001
    fingerprint: abc123def456  # From incident fingerprint
    category: DATABASE
    description: >
      Order-service DB connection pool exhaustion during traffic spikes.
      Happens when incoming request rate exceeds pool capacity.
    affected_apps:
      - order-service
      - payment-service
    affected_namespaces:
      - uat
      - prod
    first_seen: 2025-11-12
    jira: OPS-431
    status: OPEN  # OPEN, IN_PROGRESS, WORKAROUND, RESOLVED, WONT_FIX
    owner: platform-team
    workaround:
      - Restart order-service pod
      - Scale up replicas temporarily
    permanent_fix:
      - Increase pool size to 25
      - Optimize slow queries
      - Add connection timeout
    related_fingerprints:
      - related_fp_001
      - related_fp_002
    error_pattern: "HikariPool.*Connection is not available"
    notes: Happens during morning traffic peak (8-9 AM)
"""
    
    with open(path / "known_errors.yaml", 'w', encoding='utf-8') as f:
        f.write(errors_yaml)
    
    # ===== known_errors.md =====
    errors_md = """# Known Errors

_Last updated: 2026-01-23_

**Total:** 1 known error

---

## KE-001 – Order-service DB pool exhaustion

**Category:** DATABASE  
**Affected apps:** order-service, payment-service  
**First seen:** 2025-11-12  
**Jira:** OPS-431  
**Status:** OPEN  
**Owner:** platform-team

### Description

Order-service DB connection pool exhaustion during traffic spikes.
Happens when incoming request rate exceeds pool capacity.

### Workaround

- Restart order-service pod
- Scale up replicas temporarily

### Permanent Fix

- Increase pool size to 25
- Optimize slow queries
- Add connection timeout

### Notes

Happens during morning traffic peak (8-9 AM)

---

"""
    
    with open(path / "known_errors.md", 'w', encoding='utf-8') as f:
        f.write(errors_md)
    
    # ===== known_peaks.yaml =====
    peaks_yaml = """# Known Peaks - YAML (machine readable)
# This file is MANUALLY maintained.

known_peaks:
  - id: KP-001
    fingerprint: peak_fp_001
    peak_type: error  # error, traffic, latency
    description: Order-service error spike during DB pool exhaustion
    affected_apps:
      - order-service
    first_seen: 2025-11-12
    typical_duration_min: 15
    jira: OPS-431
    status: OPEN
    linked_error_id: KE-001  # Links to known error
    mitigation:
      - Scale up pods
      - Restart affected service
    error_pattern: ""
"""
    
    with open(path / "known_peaks.yaml", 'w', encoding='utf-8') as f:
        f.write(peaks_yaml)
    
    # ===== known_peaks.md =====
    peaks_md = """# Known Peaks

_Last updated: 2026-01-23_

**Total:** 1 known peak

---

## KP-001 – Order-service error spike during DB pool exhaustion

**Type:** error  
**Affected apps:** order-service  
**First seen:** 2025-11-12  
**Typical duration:** 15 min  
**Jira:** OPS-431  
**Status:** OPEN  
**Linked Error:** KE-001

### Description

Error spike that occurs when order-service DB connection pool is exhausted.

### Mitigation

- Scale up pods
- Restart affected service

---

"""
    
    with open(path / "known_peaks.md", 'w', encoding='utf-8') as f:
        f.write(peaks_md)
    
    print(f"✅ Created knowledge base template in {path}")
    print(f"   - known_errors.yaml (machine readable)")
    print(f"   - known_errors.md (human readable)")
    print(f"   - known_peaks.yaml")
    print(f"   - known_peaks.md")


def suggest_new_known_error(
    incident_id: str,
    fingerprint: str,
    category: str,
    description: str,
    affected_apps: List[str],
    workaround: List[str] = None,
) -> str:
    """
    Generuje YAML návrh pro nový known error.
    
    POZOR: Toto je jen NÁVRH pro human review!
    Nesmí se automaticky přidávat do knowledge base!
    """
    workaround = workaround or []
    
    return f"""# === SUGGESTION FOR HUMAN REVIEW ===
# Incident: {incident_id}
# DO NOT add automatically! Review and modify first.

  - id: KE-XXX  # Assign next available ID
    fingerprint: {fingerprint}
    category: {category.upper()}
    description: >
      {description}
    affected_apps:
{chr(10).join(f'      - {app}' for app in affected_apps)}
    first_seen: {date.today()}
    jira: ''  # TODO: Create Jira ticket
    status: OPEN
    owner: ''  # TODO: Assign owner
    workaround:
{chr(10).join(f'      - {w}' for w in workaround) if workaround else '      - # TODO: Add workaround'}
    permanent_fix:
      - # TODO: Add permanent fix
"""
