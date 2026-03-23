#!/usr/bin/env python3
"""
Problem Registry - Dvouúrovňová evidence problémů
==================================================

Řeší:
1. Registry lookup nefunguje (vše je označeno jako NEW)
2. first_seen/last_seen jsou časy běhu scriptu, ne eventů
3. Peaks se neukládají
4. Duplicitní fingerprinty = explosion registru
5. v1 není verze aplikace

Architektura:
┌───────────────────────────┐
│ PROBLEM REGISTRY (LIDSKÁ) │  ← stabilní, málo záznamů
│ problem_key               │
│ first_seen / last_seen    │
│ occurrences               │
│ scope / flow              │
└─────────────▲─────────────┘
              │ 1:N
┌─────────────┴─────────────┐
│ FINGERPRINT INDEX (TECH)  │  ← hodně záznamů
│ fingerprint               │
│ problem_key (FK)          │
└───────────────────────────┘

problem_key = category:flow:error_class

Verze: 6.0
Datum: 2026-01-26
"""

import os
import re
import yaml
import tempfile
import shutil
import fcntl
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import hashlib


# =============================================================================
# CONFIGURATION LIMITS
# =============================================================================

MAX_FINGERPRINTS_PER_PROBLEM = 500  # Warning above this
MAX_SAMPLE_MESSAGES_PER_FP = 5
MAX_PROBLEMS_WARNING = 5000
MAX_FINGERPRINTS_WARNING = 100000


# =============================================================================
# DATA MODELS
# =============================================================================

@dataclass
class FingerprintEntry:
    """Technický záznam fingerprintu - mapuje na problem_key"""
    fingerprint: str
    problem_key: str
    normalized_message: str = ""
    sample_messages: List[str] = field(default_factory=list)
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    occurrence_count: int = 0


@dataclass 
class ProblemEntry:
    """Provozní záznam problému - hrubá identita"""
    id: str                          # KP-000001 (Known Problem)
    problem_key: str                 # category:flow:error_class
    category: str                    # business, database, auth, etc.
    flow: str                        # card_servicing, payments, etc.
    error_class: str                 # validation_error, connection_pool, etc.
    
    # Timing - FROM EVENT TIMESTAMPS, not script run time!
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    
    # Counts
    occurrences: int = 0

    # Track timestamps of last occurrences (max 100 for memory efficiency)
    # Used for 24h trend calculation in CSV exports
    occurrence_times: List[datetime] = field(default_factory=list)

    # Parallel list: error count per occurrence_times entry (volume tracking)
    occurrence_counts: List[int] = field(default_factory=list)

    # Linked fingerprints (1:N)
    fingerprints: List[str] = field(default_factory=list)

    # Sample error messages - CRITICAL for understanding what the problem is!
    sample_messages: List[str] = field(default_factory=list)
    description: str = ""  # Human-readable description / root cause
    root_cause: str = ""
    behavior: str = ""

    # Scope
    affected_apps: Set[str] = field(default_factory=set)
    affected_namespaces: Set[str] = field(default_factory=set)
    deployments_seen: Set[str] = field(default_factory=set)  # app-v1, app-v2
    app_versions_seen: Set[str] = field(default_factory=set)  # 4.65.2, 4.65.3

    # Scope classification
    scope: str = "LOCAL"  # LOCAL, CROSS_NS, SYSTEMIC

    # Status
    status: str = "OPEN"  # OPEN, ACKNOWLEDGED, RESOLVED, WONT_FIX
    jira: Optional[str] = None
    notes: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Serializace pro YAML"""
        return {
            'id': self.id,
            'problem_key': self.problem_key,
            'category': self.category,
            'flow': self.flow,
            'error_class': self.error_class,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'occurrences': self.occurrences,
            'occurrence_times': [ts.isoformat() if isinstance(ts, datetime) else ts for ts in self.occurrence_times],
            'occurrence_counts': list(self.occurrence_counts),
            'fingerprints': self.fingerprints,
            'sample_messages': self.sample_messages[:MAX_SAMPLE_MESSAGES_PER_FP],  # Limit samples
            'description': self.description,
            'affected_apps': sorted(self.affected_apps),
            'affected_namespaces': sorted(self.affected_namespaces),
            'deployments_seen': sorted(self.deployments_seen),
            'app_versions_seen': sorted(self.app_versions_seen),
            'scope': self.scope,
            'status': self.status,
            'jira': self.jira,
            'notes': self.notes,
            'root_cause': self.root_cause,
            'behavior': self.behavior,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ProblemEntry':
        """Deserializace z YAML"""
        entry = cls(
            id=data.get('id', ''),
            problem_key=data.get('problem_key', ''),
            category=data.get('category', 'unknown'),
            flow=data.get('flow', 'unknown'),
            error_class=data.get('error_class', 'unknown'),
        )
        
        if data.get('first_seen'):
            entry.first_seen = datetime.fromisoformat(data['first_seen'])
        if data.get('last_seen'):
            entry.last_seen = datetime.fromisoformat(data['last_seen'])
        
        entry.occurrences = data.get('occurrences', 0)
        
        # Load occurrence_times (deserialize from ISO strings)
        occurrence_times_data = data.get('occurrence_times', [])
        entry.occurrence_times = []
        for ts_str in occurrence_times_data:
            if isinstance(ts_str, str):
                try:
                    entry.occurrence_times.append(datetime.fromisoformat(ts_str))
                except (ValueError, TypeError):
                    pass
            elif isinstance(ts_str, datetime):
                entry.occurrence_times.append(ts_str)
        
        # Load occurrence_counts (parallel to occurrence_times).
        # Migration: old YAML entries lack this field — default each slot to 1.
        raw_counts = data.get('occurrence_counts', [])
        if raw_counts and len(raw_counts) == len(entry.occurrence_times):
            entry.occurrence_counts = [int(c) for c in raw_counts]
        else:
            entry.occurrence_counts = [1] * len(entry.occurrence_times)
        
        entry.fingerprints = data.get('fingerprints', [])
        entry.sample_messages = data.get('sample_messages', [])
        entry.description = data.get('description', '')
        entry.root_cause = data.get('root_cause', '') or entry.description or ''
        entry.behavior = data.get('behavior', '')
        if not entry.behavior and entry.sample_messages:
            entry.behavior = entry.sample_messages[0]
        entry.affected_apps = set(data.get('affected_apps', []))
        entry.affected_namespaces = set(data.get('affected_namespaces', []))
        entry.deployments_seen = set(data.get('deployments_seen', []))
        entry.app_versions_seen = set(data.get('app_versions_seen', []))
        entry.scope = data.get('scope', 'LOCAL')
        entry.status = data.get('status', 'OPEN')
        entry.jira = data.get('jira')
        entry.notes = data.get('notes')
        
        return entry


@dataclass
class PeakEntry:
    """Záznam detekovaného peaku"""
    id: str                          # PK-000001 (Peak Known)
    problem_key: str                 # category:flow:peak_type
    peak_type: str                   # SPIKE, BURST, TRAFFIC_SPIKE
    
    # Timing - FROM EVENT TIMESTAMPS!
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    
    # Counts
    occurrences: int = 0
    raw_error_count: int = 0
    
    # Linked fingerprints
    fingerprints: List[str] = field(default_factory=list)
    
    # Scope
    affected_apps: Set[str] = field(default_factory=set)
    affected_namespaces: Set[str] = field(default_factory=set)
    
    # Peak-specific
    max_value: float = 0.0
    max_ratio: float = 0.0
    
    # Status
    status: str = "OPEN"
    jira: Optional[str] = None
    notes: Optional[str] = None
    root_cause: str = ""
    behavior: str = ""
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'problem_key': self.problem_key,
            'peak_type': self.peak_type,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'occurrences': self.occurrences,
            'raw_error_count': self.raw_error_count,
            'fingerprints': self.fingerprints,
            'affected_apps': sorted(self.affected_apps),
            'affected_namespaces': sorted(self.affected_namespaces),
            'max_value': self.max_value,
            'max_ratio': self.max_ratio,
            'status': self.status,
            'jira': self.jira,
            'notes': self.notes,
            'root_cause': self.root_cause,
            'behavior': self.behavior,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'PeakEntry':
        entry = cls(
            id=data.get('id', ''),
            problem_key=data.get('problem_key', ''),
            peak_type=data.get('peak_type', 'UNKNOWN'),
        )
        
        if data.get('first_seen'):
            entry.first_seen = datetime.fromisoformat(data['first_seen'])
        if data.get('last_seen'):
            entry.last_seen = datetime.fromisoformat(data['last_seen'])
        
        entry.occurrences = data.get('occurrences', 0)
        entry.raw_error_count = data.get('raw_error_count', entry.occurrences)
        entry.fingerprints = data.get('fingerprints', [])
        entry.affected_apps = set(data.get('affected_apps', []))
        entry.affected_namespaces = set(data.get('affected_namespaces', []))
        entry.max_value = data.get('max_value', 0.0)
        entry.max_ratio = data.get('max_ratio', 0.0)
        entry.status = data.get('status', 'OPEN')
        entry.jira = data.get('jira')
        entry.notes = data.get('notes')
        entry.root_cause = data.get('root_cause', '')
        entry.behavior = data.get('behavior', '')
        
        return entry
    
    @property
    def category(self) -> str:
        """Extract category from problem_key (format: category:flow:peak_type)."""
        if ':' in self.problem_key:
            return self.problem_key.split(':')[0]
        return 'UNKNOWN'
    
    @property
    def flow(self) -> str:
        """Extract flow from problem_key (format: category:flow:peak_type)."""
        parts = self.problem_key.split(':')
        if len(parts) >= 2:
            return parts[1]
        return 'UNKNOWN'


# =============================================================================
# PROBLEM KEY COMPUTATION
# =============================================================================

# Flow detection patterns
FLOW_PATTERNS = {
    # App name patterns → flow
    r'card-servicing': 'card_servicing',
    r'card-opening': 'card_opening',
    r'card-validation': 'card_validation',
    r'click2pay': 'click2pay',
    r'billing': 'billing',
    r'document-signing': 'document_signing',
    r'batch-processor': 'batch_processing',
    r'event-processor': 'event_processing',
    r'rainbow-status': 'client_status',
    r'codelist': 'codelist',
    r'client-segment': 'client_segment',
    r'design-lifecycle': 'design_lifecycle',
    r'georisk': 'georisk',
}

# Error class patterns
ERROR_CLASS_PATTERNS = {
    # Exception types → error class
    r'ServiceBusinessException': 'business_exception',
    r'ValidationException': 'validation_error',
    r'ConstraintViolationException': 'constraint_violation',
    r'AccessDeniedException': 'access_denied',
    r'AuthenticationException': 'authentication_error',
    r'TimeoutException': 'timeout',
    r'ConnectionException': 'connection_error',
    r'SQLException': 'database_error',
    r'OutOfMemoryError': 'memory_error',
    r'NullPointerException': 'null_pointer',
    r'IllegalArgumentException': 'invalid_argument',
    r'IOException': 'io_error',
    r'ResourceNotFoundException': 'not_found',
    r'not found': 'not_found',
    r'404': 'not_found',
    r'401': 'unauthorized',
    r'403': 'forbidden',
    r'500': 'internal_error',
    r'502|503|504': 'gateway_error',
}


def extract_flow(app_names: List[str], namespaces: List[str] = None) -> str:
    """
    Extrahuje business flow z názvů aplikací.
    
    DEFENSIVE: Zvládá None, prázdné seznamy, None položky v seznamu.
    
    Příklady:
        ['bff-pcb-ch-card-servicing-v1'] → 'card_servicing'
        ['bl-pcb-billing-v1'] → 'billing'
        ['feapi-pca-v1'] → 'pca'
        [None, 'bff-app'] → 'app'
        None → 'unknown'
    """
    # DEFENSIVE: Sanitize input - remove None and empty strings
    safe_apps = []
    if app_names:
        safe_apps = [
            a for a in app_names 
            if isinstance(a, str) and a.strip()
        ]
    
    # If no valid apps, try namespaces as fallback
    if not safe_apps:
        if namespaces:
            safe_ns = [n for n in namespaces if isinstance(n, str) and n.strip()]
            if safe_ns:
                # Extract flow hint from namespace (e.g., pcb-dev-01-app → pcb)
                for ns in safe_ns:
                    parts = ns.lower().replace('_', '-').split('-')
                    if parts:
                        return parts[0]
        return 'unknown'
    
    # Try pattern matching first
    combined = ' '.join(safe_apps).lower()
    
    for pattern, flow in FLOW_PATTERNS.items():
        if re.search(pattern, combined):
            return flow
    
    # Fallback: extract from app name structure
    for app in safe_apps:
        # bff-pcb-ch-card-servicing-v1 → card-servicing
        parts = app.lower().replace('_', '-').split('-')
        # Skip prefixes: bff, bl, feapi, pcb, pca, ch
        skip_prefixes = {'bff', 'bl', 'feapi', 'pcb', 'pca', 'ch', 'v1', 'v2', 'v3'}
        meaningful = [p for p in parts if p not in skip_prefixes and not p.isdigit()]
        if meaningful:
            return '_'.join(meaningful[:2])
    
    return 'unknown'


def extract_error_class(error_type: str, normalized_message: str) -> str:
    """
    Extrahuje error class z typu erroru a zprávy.
    
    Příklady:
        'ServiceBusinessException', '...' → 'business_exception'
        'UnknownError', 'Connection refused...' → 'connection_error'
    """
    combined = f"{error_type} {normalized_message}"
    
    for pattern, error_class in ERROR_CLASS_PATTERNS.items():
        if re.search(pattern, combined, re.IGNORECASE):
            return error_class
    
    # Fallback: use error type directly
    if error_type and error_type != 'UnknownError':
        # Convert CamelCase to snake_case
        snake = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', error_type)
        snake = re.sub('([a-z0-9])([A-Z])', r'\1_\2', snake)
        return snake.lower()
    
    return 'unclassified'


def compute_problem_key(
    category: str,
    app_names: List[str],
    error_type: str = "",
    normalized_message: str = "",
    namespaces: List[str] = None,
) -> str:
    """
    Vytvoří stabilní problem_key.
    
    DEFENSIVE: Zvládá None vstupy, nikdy nepadne.
    
    Format: CATEGORY:flow:error_class
    
    Příklady:
        BUSINESS:card_servicing:validation_error
        DATABASE:batch_processing:connection_pool
        AUTH:card_opening:access_denied
    """
    # DEFENSIVE: Sanitize all inputs
    safe_apps = []
    if app_names:
        safe_apps = [a for a in app_names if isinstance(a, str) and a.strip()]
    
    safe_ns = []
    if namespaces:
        safe_ns = [n for n in namespaces if isinstance(n, str) and n.strip()]
    
    flow = extract_flow(safe_apps, safe_ns)
    error_class = extract_error_class(error_type or "", normalized_message or "")
    
    # Normalize category
    cat = category.upper() if category else 'UNKNOWN'
    
    return f"{cat}:{flow}:{error_class}"


def extract_deployment_label(app_name: str) -> str:
    """
    Extrahuje deployment label (ne verzi aplikace!).
    
    bff-pcb-ch-card-servicing-v1 → bff-pcb-ch-card-servicing-v1
    
    To NENÍ verze aplikace (4.65.2), to je deployment generation!
    """
    return app_name


def extract_app_version(raw_record: dict) -> Optional[str]:
    """
    Extrahuje skutečnou verzi aplikace z ES záznamu.
    
    Hledá pole jako:
    - application.version
    - app.version  
    - version
    - @version
    
    Vrací None pokud není nalezena verze.
    """
    # Prioritized fields
    version_fields = [
        'application.version',
        'app.version',
        'service.version',
        'version',
        '@version',
    ]
    
    for field in version_fields:
        # Handle nested fields
        value = raw_record
        for part in field.split('.'):
            if isinstance(value, dict):
                value = value.get(part)
            else:
                value = None
                break
        
        if value and isinstance(value, str):
            # Validate it looks like a version (not "v1")
            if re.match(r'^\d+\.\d+', value):
                return value
    
    return None


# =============================================================================
# PROBLEM REGISTRY CLASS
# =============================================================================

class ProblemRegistry:
    """
    Centrální registry pro známé problémy a peaky.
    
    Použití:
        registry = ProblemRegistry('/path/to/registry')
        registry.load()
        
        # Lookup
        if registry.is_fingerprint_known(fp):
            problem = registry.get_problem_for_fingerprint(fp)
        
        # Update po pipeline
        registry.update_from_incidents(incidents)
        registry.save()
    """
    
    def __init__(self, registry_dir: str):
        self.registry_dir = Path(registry_dir)
        
        # Problem registry (problem_key → ProblemEntry)
        self.problems: Dict[str, ProblemEntry] = {}
        
        # Peak registry (problem_key → PeakEntry)
        self.peaks: Dict[str, PeakEntry] = {}
        
        # Fingerprint index (fingerprint → problem_key)
        self.fingerprint_index: Dict[str, str] = {}
        
        # Counters for ID generation
        self._problem_counter = 0
        self._peak_counter = 0
        
        # Stats
        self.stats = {
            'problems_loaded': 0,
            'peaks_loaded': 0,
            'fingerprints_indexed': 0,
            'new_problems_added': 0,
            'problems_updated': 0,
            'new_peaks_added': 0,
            'peaks_updated': 0,
        }
    
    # =========================================================================
    # LOAD / SAVE
    # =========================================================================
    
    def load(self) -> bool:
        """Načte registry z YAML souborů."""
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        
        # Load problems
        problems_file = self.registry_dir / 'known_problems.yaml'
        if problems_file.exists():
            try:
                with open(problems_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or []
                
                for item in data:
                    problem = ProblemEntry.from_dict(item)
                    self.problems[problem.problem_key] = problem
                    
                    # Build fingerprint index
                    for fp in problem.fingerprints:
                        self.fingerprint_index[fp] = problem.problem_key
                    
                    # Track max ID
                    if problem.id.startswith('KP-'):
                        try:
                            num = int(problem.id.split('-')[1])
                            self._problem_counter = max(self._problem_counter, num)
                        except ValueError:
                            pass
                
                self.stats['problems_loaded'] = len(self.problems)
                self.stats['fingerprints_indexed'] = len(self.fingerprint_index)
                
            except Exception as e:
                print(f"⚠️ Error loading problems: {e}")
                return False
        
        # Load peaks
        peaks_file = self.registry_dir / 'known_peaks.yaml'
        if peaks_file.exists():
            try:
                with open(peaks_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or []
                
                for item in data:
                    peak = PeakEntry.from_dict(item)
                    self.peaks[peak.problem_key] = peak

                    # Index peak fingerprints so is_fingerprint_known() finds them
                    # This ensures recurring peaks are not marked as NEW
                    for fp in peak.fingerprints:
                        if fp not in self.fingerprint_index:
                            self.fingerprint_index[fp] = peak.problem_key

                    # Track max ID
                    if peak.id.startswith('PK-'):
                        try:
                            num = int(peak.id.split('-')[1])
                            self._peak_counter = max(self._peak_counter, num)
                        except ValueError:
                            pass

                self.stats['peaks_loaded'] = len(self.peaks)
                
            except Exception as e:
                print(f"⚠️ Error loading peaks: {e}")
        
        return True
    
    def save(self) -> bool:
        """
        Uloží registry do YAML a MD souborů.
        
        ATOMIC WRITE: Používá tmp + rename pro bezpečnost.
        FILE LOCKING: Chrání před concurrent writes.
        """
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        
        lock_file = self.registry_dir / '.registry.lock'
        
        try:
            # Acquire file lock
            lock_fd = open(lock_file, 'w')
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            
            try:
                # Save problems YAML (atomic)
                problems_yaml = self.registry_dir / 'known_problems.yaml'
                sorted_problems = sorted(
                    self.problems.values(),
                    key=lambda p: p.last_seen or datetime.min,
                    reverse=True
                )
                
                self._atomic_write_yaml(
                    problems_yaml,
                    [p.to_dict() for p in sorted_problems]
                )
                
                # Save problems MD
                self._write_problems_md(sorted_problems)
                
                # Save peaks YAML (atomic)
                peaks_yaml = self.registry_dir / 'known_peaks.yaml'
                sorted_peaks = sorted(
                    self.peaks.values(),
                    key=lambda p: p.last_seen or datetime.min,
                    reverse=True
                )
                
                self._atomic_write_yaml(
                    peaks_yaml,
                    [p.to_dict() for p in sorted_peaks]
                )
                
                # Save peaks MD
                self._write_peaks_md(sorted_peaks)
                
                # Save fingerprint index (atomic)
                self._save_fingerprint_index()
                
                # Check health warnings
                self._check_health_warnings()
                
                return True
                
            finally:
                # Release lock
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                lock_fd.close()
            
        except Exception as e:
            print(f"⚠️ Error saving registry: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _atomic_write_yaml(self, filepath: Path, data: Any):
        """
        Atomic write: zapisuje do tmp souboru, pak rename.
        
        Tím se zabrání corrupted registry při crash uprostřed zápisu.
        """
        tmp_path = filepath.with_suffix('.yaml.tmp')
        
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False
                )
            
            # Atomic rename
            shutil.move(str(tmp_path), str(filepath))
            
        except Exception as e:
            # Cleanup tmp if exists
            if tmp_path.exists():
                tmp_path.unlink()
            raise
    
    def _write_problems_md(self, problems: List[ProblemEntry]):
        """Zapíše MD verzi problem registry."""
        filepath = self.registry_dir / 'known_problems.md'
        
        lines = [
            "# Known Problems Registry",
            "",
            f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
            f"_Total problems: {len(problems)}_",
            f"_Total fingerprints: {len(self.fingerprint_index)}_",
            "",
            "---",
            "",
        ]
        
        # Group by category
        by_category = defaultdict(list)
        for p in problems:
            by_category[p.category].append(p)
        
        for category in sorted(by_category.keys()):
            cat_problems = by_category[category]
            lines.append(f"## {category.upper()} ({len(cat_problems)} problems)")
            lines.append("")
            
            for p in cat_problems:
                scope_icon = {'LOCAL': '📍', 'CROSS_NS': '🔀', 'SYSTEMIC': '🌐'}.get(p.scope, '❓')
                status_icon = {'OPEN': '🔴', 'ACKNOWLEDGED': '🟡', 'RESOLVED': '🟢', 'WONT_FIX': '⚪'}.get(p.status, '❓')
                
                lines.extend([
                    f"### {p.id} – {p.flow}/{p.error_class} {scope_icon} {status_icon}",
                    "",
                    f"**Problem Key:** `{p.problem_key}`",
                    f"**First seen:** {p.first_seen.strftime('%Y-%m-%d %H:%M') if p.first_seen else 'N/A'}",
                    f"**Last seen:** {p.last_seen.strftime('%Y-%m-%d %H:%M') if p.last_seen else 'N/A'}",
                    f"**Occurrences:** {p.occurrences:,}",
                    f"**Fingerprints:** {len(p.fingerprints)}",
                    "",
                    f"**Apps:** {', '.join(sorted(p.affected_apps)[:5])}{'...' if len(p.affected_apps) > 5 else ''}",
                    f"**Namespaces:** {', '.join(sorted(p.affected_namespaces))}",
                    "",
                ])

                if p.root_cause:
                    lines.append(f"**Root cause:** {p.root_cause}")
                if p.behavior:
                    lines.append(f"**Behavior:** {p.behavior}")
                if p.root_cause or p.behavior:
                    lines.append("")
                
                if p.jira:
                    lines.append(f"**JIRA:** [{p.jira}](https://jira.kb.cz/browse/{p.jira})")
                if p.notes:
                    lines.append(f"**Notes:** {p.notes}")
                
                lines.extend(["", "---", ""])
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    def _write_peaks_md(self, peaks: List[PeakEntry]):
        """Zapíše MD verzi peak registry."""
        filepath = self.registry_dir / 'known_peaks.md'
        
        lines = [
            "# Known Peaks Registry",
            "",
            f"_Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
            f"_Total peaks: {len(peaks)}_",
            "",
            "---",
            "",
        ]
        
        if not peaks:
            lines.extend([
                "_No peaks recorded yet. Registry will be automatically populated when peaks are detected._",
                "",
            ])
        else:
            # Group by peak type
            by_type = defaultdict(list)
            for p in peaks:
                by_type[p.peak_type].append(p)
            
            for peak_type in sorted(by_type.keys()):
                type_peaks = by_type[peak_type]
                lines.append(f"## {peak_type} ({len(type_peaks)} peaks)")
                lines.append("")
                
                for p in type_peaks:
                    lines.extend([
                        f"### {p.id}",
                        "",
                        f"**Problem Key:** `{p.problem_key}`",
                        f"**First seen:** {p.first_seen.strftime('%Y-%m-%d %H:%M') if p.first_seen else 'N/A'}",
                        f"**Last seen:** {p.last_seen.strftime('%Y-%m-%d %H:%M') if p.last_seen else 'N/A'}",
                        f"**Occurrence count (peak windows):** {p.occurrences}",
                        f"**Peak count (raw errors):** {p.raw_error_count}",
                        f"**Max value:** {p.max_value:.2f}",
                        f"**Max ratio:** {p.max_ratio:.2f}x",
                        "",
                        f"**Apps:** {', '.join(sorted(p.affected_apps)[:5])}",
                        f"**Namespaces:** {', '.join(sorted(p.affected_namespaces))}",
                        "",
                    ])

                    if p.root_cause:
                        lines.append(f"**Root cause:** {p.root_cause}")
                    if p.behavior:
                        lines.append(f"**Behavior:** {p.behavior}")

                    lines.extend([
                        "",
                        "---",
                        "",
                    ])
        
        # Add usage guide
        lines.extend([
            "## How to use this registry",
            "",
            "1. **Automatic updates**: This file is updated automatically by the pipeline on each run.",
            "2. **Never deleted**: Entries are never removed, only updated with new `last_seen` timestamps.",
            "3. **Manual fields**: You can fill in `jira` and `notes` fields manually.",
            "4. **Sorting**: Entries are sorted by `last_seen` (newest first).",
            "",
            "## Peak types",
            "",
            "- **SPIKE**: EWMA ratio > threshold (sustained increase)",
            "- **BURST**: Sudden burst in short time window",
            "- **TRAFFIC_SPIKE**: Abnormal increase in traffic/requests",
            "",
        ])
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    def _save_fingerprint_index(self):
        """Uloží fingerprint index jako YAML (atomic)."""
        filepath = self.registry_dir / 'fingerprint_index.yaml'
        
        # Group by problem_key for readability
        by_problem = defaultdict(list)
        for fp, pk in self.fingerprint_index.items():
            by_problem[pk].append(fp)
        
        # Atomic write
        self._atomic_write_yaml(filepath, dict(by_problem))
    
    def _check_health_warnings(self):
        """Kontroluje zdraví registry a vypisuje varování."""
        warnings = []
        
        # Check total counts
        if len(self.problems) > MAX_PROBLEMS_WARNING:
            warnings.append(
                f"⚠️ High problem count: {len(self.problems)} (threshold: {MAX_PROBLEMS_WARNING})"
            )
        
        if len(self.fingerprint_index) > MAX_FINGERPRINTS_WARNING:
            warnings.append(
                f"⚠️ High fingerprint count: {len(self.fingerprint_index)} (threshold: {MAX_FINGERPRINTS_WARNING})"
            )
        
        # Check problems with too many fingerprints
        for pk, problem in self.problems.items():
            if len(problem.fingerprints) > MAX_FINGERPRINTS_PER_PROBLEM:
                warnings.append(
                    f"⚠️ Problem {problem.id} has {len(problem.fingerprints)} fingerprints "
                    f"(threshold: {MAX_FINGERPRINTS_PER_PROBLEM})"
                )
        
        if warnings:
            print("\n🏥 REGISTRY HEALTH WARNINGS:")
            for w in warnings[:10]:  # Max 10 warnings
                print(f"   {w}")
            if len(warnings) > 10:
                print(f"   ... and {len(warnings) - 10} more warnings")
    
    # =========================================================================
    # LOOKUP
    # =========================================================================
    
    def is_fingerprint_known(self, fingerprint: str) -> bool:
        """Zjistí zda je fingerprint známý."""
        return fingerprint in self.fingerprint_index
    
    def is_problem_key_known(self, problem_key: str) -> bool:
        """Zjistí zda je problem_key známý (v problems NEBO peaks)."""
        if problem_key in self.problems:
            return True
        # Also check peaks (peak keys have format PEAK:category:flow:peak_type)
        if problem_key in self.peaks:
            return True
        # Cross-check: try matching as peak key variant
        # Detection generates CATEGORY:flow:error_class, peaks use PEAK:category:flow:peak_type
        # Check if any peak matches the category+flow portion
        parts = problem_key.split(':')
        if len(parts) >= 2:
            category = parts[0].lower()
            flow = parts[1]
            for peak_key in self.peaks:
                peak_parts = peak_key.split(':')
                # PEAK:category:flow:peak_type
                if len(peak_parts) >= 3 and peak_parts[1] == category and peak_parts[2] == flow:
                    return True
        return False
    
    def get_problem_for_fingerprint(self, fingerprint: str) -> Optional[ProblemEntry]:
        """Vrátí ProblemEntry pro fingerprint."""
        pk = self.fingerprint_index.get(fingerprint)
        if pk:
            return self.problems.get(pk)
        return None
    
    def get_all_known_fingerprints(self) -> Set[str]:
        """Vrátí množinu všech známých fingerprintů."""
        return set(self.fingerprint_index.keys())
    
    # =========================================================================
    # UPDATE FROM INCIDENTS
    # =========================================================================
    
    def update_from_incidents(
        self,
        incidents: List[Any],
        event_timestamps: Dict[str, Tuple[datetime, datetime]] = None
    ):
        """
        Aktualizuje registry z incidentů.
        
        KRITICKÉ: event_timestamps obsahuje skutečné časy eventů:
        {fingerprint: (first_event_ts, last_event_ts)}
        
        Ne čas běhu scriptu!
        """
        event_timestamps = event_timestamps or {}
        
        for incident in incidents:
            # Extract data from incident
            fingerprint = incident.fingerprint
            category = incident.category.value if hasattr(incident.category, 'value') else str(incident.category)
            apps = incident.apps
            namespaces = incident.namespaces
            error_type = incident.error_type
            normalized_message = incident.normalized_message
            count = incident.stats.current_count if hasattr(incident.stats, 'current_count') else 1
            
            # Get event timestamps (CRITICAL!)
            if fingerprint in event_timestamps:
                first_ts, last_ts = event_timestamps[fingerprint]
            elif hasattr(incident.time, 'first_seen') and incident.time.first_seen:
                first_ts = incident.time.first_seen
                last_ts = incident.time.last_seen or first_ts
            else:
                # Fallback - but this is NOT ideal
                first_ts = datetime.utcnow()
                last_ts = first_ts
            
            # Compute problem_key
            problem_key = compute_problem_key(
                category=category,
                app_names=apps,
                error_type=error_type,
                normalized_message=normalized_message,
                namespaces=namespaces,
            )
            
            # Update or create problem
            if problem_key in self.problems:
                self._update_problem(
                    problem_key, fingerprint, apps, namespaces,
                    error_type, normalized_message, first_ts, last_ts, count
                )
            else:
                self._create_problem(
                    problem_key, fingerprint, category, apps, namespaces,
                    error_type, normalized_message, first_ts, last_ts, count
                )
            
            # Update fingerprint index
            if fingerprint not in self.fingerprint_index:
                self.fingerprint_index[fingerprint] = problem_key
            
            # Handle peaks
            if hasattr(incident, 'flags'):
                if incident.flags.is_spike:
                    self._update_peak(
                        incident, 'SPIKE', first_ts, last_ts
                    )
                if incident.flags.is_burst:
                    self._update_peak(
                        incident, 'BURST', first_ts, last_ts
                    )
    
    def _update_problem(
        self,
        problem_key: str,
        fingerprint: str,
        apps: List[str],
        namespaces: List[str],
        error_type: str,
        normalized_message: str,
        first_ts: datetime,
        last_ts: datetime,
        count: int
    ):
        """Aktualizuje existující problem."""
        problem = self.problems[problem_key]
        
        # Update timestamps (CRITICAL: use min/max!)
        if problem.first_seen is None or first_ts < problem.first_seen:
            problem.first_seen = first_ts
        if problem.last_seen is None or last_ts > problem.last_seen:
            problem.last_seen = last_ts
        
        # Update counts — deduplicate by truncating last_ts to minute precision.
        # Without this, repeated backfill runs (--force) for the same window
        # would accumulate occurrences and duplicate timestamps each run.
        if last_ts:
            ts_bucket = last_ts.replace(second=0, microsecond=0)
            existing_buckets = {
                t.replace(second=0, microsecond=0) if hasattr(t, "replace") else t
                for t in problem.occurrence_times
            }
            if ts_bucket not in existing_buckets:
                # Genuinely new window — count it
                problem.occurrences += count
                problem.occurrence_times.append(last_ts)
                problem.occurrence_counts.append(count)
            # else: same minute already recorded -> idempotent re-run, skip
        else:
            # No timestamp -> always count (e.g. regular phase rows)
            problem.occurrences += count
        
        # Add fingerprint if new (with limit)
        if fingerprint not in problem.fingerprints:
            if len(problem.fingerprints) < MAX_FINGERPRINTS_PER_PROBLEM:
                problem.fingerprints.append(fingerprint)
            # else: silently skip - fingerprint index still tracks it
        
        # Add sample message if unique and within limit
        if normalized_message and normalized_message.strip():
            msg = normalized_message.strip()[:500]
            if msg not in problem.sample_messages and len(problem.sample_messages) < MAX_SAMPLE_MESSAGES_PER_FP:
                problem.sample_messages.append(msg)
            if not problem.behavior:
                problem.behavior = msg

        if not problem.root_cause:
            if error_type and error_type != 'UnknownError':
                problem.root_cause = error_type
            else:
                problem.root_cause = problem.description or ''
        
        # Update affected entities (defensive: filter None)
        safe_apps = [a for a in apps if a] if apps else []
        safe_ns = [n for n in namespaces if n] if namespaces else []
        
        problem.affected_apps.update(safe_apps)
        problem.affected_namespaces.update(safe_ns)
        
        # Extract deployment labels vs app versions
        for app in safe_apps:
            problem.deployments_seen.add(extract_deployment_label(app))
        
        # Update scope
        problem.scope = self._compute_scope(problem)
        
        self.stats['problems_updated'] += 1
    
    def _create_problem(
        self,
        problem_key: str,
        fingerprint: str,
        category: str,
        apps: List[str],
        namespaces: List[str],
        error_type: str,
        normalized_message: str,
        first_ts: datetime,
        last_ts: datetime,
        count: int
    ):
        """Vytvoří nový problem."""
        self._problem_counter += 1
        
        # Parse problem_key parts
        parts = problem_key.split(':')
        cat = parts[0] if len(parts) > 0 else 'unknown'
        flow = parts[1] if len(parts) > 1 else 'unknown'
        error_class = parts[2] if len(parts) > 2 else 'unknown'
        
        # DEFENSIVE: filter None values
        safe_apps = [a for a in apps if a] if apps else []
        safe_ns = [n for n in namespaces if n] if namespaces else []
        
        # Create sample_messages from normalized_message
        sample_messages = []
        if normalized_message and normalized_message.strip():
            sample_messages = [normalized_message.strip()[:500]]  # Limit message length
        
        problem = ProblemEntry(
            id=f"KP-{self._problem_counter:06d}",
            problem_key=problem_key,
            category=cat.lower(),
            flow=flow,
            error_class=error_class,
            first_seen=first_ts,
            last_seen=last_ts,
            occurrences=count,
            occurrence_times=[last_ts] if last_ts else [],
            occurrence_counts=[count] if last_ts else [],
            fingerprints=[fingerprint],
            sample_messages=sample_messages,
            description=f"{error_type}: {normalized_message[:200] if normalized_message else 'N/A'}",
            root_cause=(error_type if error_type and error_type != 'UnknownError' else ''),
            behavior=(sample_messages[0] if sample_messages else ''),
            affected_apps=set(safe_apps),
            affected_namespaces=set(safe_ns),
            deployments_seen={extract_deployment_label(app) for app in safe_apps},
        )
        
        problem.scope = self._compute_scope(problem)
        
        self.problems[problem_key] = problem
        self.stats['new_problems_added'] += 1
    
    def _update_peak(
        self,
        incident: Any,
        peak_type: str,
        first_ts: datetime,
        last_ts: datetime
    ):
        """Aktualizuje nebo vytvoří peak."""
        # Compute peak problem_key (defensive: apps may contain None)
        category = incident.category.value if hasattr(incident.category, 'value') else 'unknown'
        safe_apps = [a for a in (incident.apps or []) if a]
        flow = extract_flow(safe_apps)
        peak_key = f"PEAK:{category}:{flow}:{peak_type.lower()}"
        
        # Get peak metrics
        ratio = 1.0
        value = 0.0
        if hasattr(incident, 'stats'):
            value = incident.stats.current_rate
            if incident.stats.baseline_rate > 0:
                ratio = value / incident.stats.baseline_rate

        count = 1
        if hasattr(incident, 'stats') and hasattr(incident.stats, 'current_count'):
            try:
                count = max(1, int(incident.stats.current_count))
            except (TypeError, ValueError):
                count = 1

        def _window_bucket(ts: Optional[datetime]) -> Optional[datetime]:
            if ts is None:
                return None
            return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
        
        if peak_key in self.peaks:
            peak = self.peaks[peak_key]
            previous_last_seen = peak.last_seen
            
            # Update timestamps
            if peak.first_seen is None or first_ts < peak.first_seen:
                peak.first_seen = first_ts
            if peak.last_seen is None or last_ts > peak.last_seen:
                peak.last_seen = last_ts

            previous_bucket = _window_bucket(previous_last_seen)
            current_bucket = _window_bucket(last_ts)
            if previous_bucket != current_bucket:
                peak.occurrences += 1

            peak.raw_error_count += count
            peak.max_value = max(peak.max_value, value)
            peak.max_ratio = max(peak.max_ratio, ratio)
            peak.affected_apps.update(incident.apps or [])
            peak.affected_namespaces.update(incident.namespaces or [])
            if not peak.root_cause and getattr(incident, 'error_type', None) and incident.error_type != 'UnknownError':
                peak.root_cause = str(incident.error_type)
            if not peak.behavior and getattr(incident, 'normalized_message', None):
                peak.behavior = str(incident.normalized_message)[:300]
            
            if incident.fingerprint not in peak.fingerprints:
                peak.fingerprints.append(incident.fingerprint)
            
            self.stats['peaks_updated'] += 1
        else:
            self._peak_counter += 1
            
            peak = PeakEntry(
                id=f"PK-{self._peak_counter:06d}",
                problem_key=peak_key,
                peak_type=peak_type,
                first_seen=first_ts,
                last_seen=last_ts,
                occurrences=1,
                raw_error_count=count,
                fingerprints=[incident.fingerprint],
                affected_apps=set(incident.apps or []),
                affected_namespaces=set(incident.namespaces or []),
                max_value=value,
                max_ratio=ratio,
                root_cause=(str(incident.error_type) if getattr(incident, 'error_type', None) and incident.error_type != 'UnknownError' else ''),
                behavior=(str(getattr(incident, 'normalized_message', ''))[:300] if getattr(incident, 'normalized_message', None) else ''),
            )
            
            self.peaks[peak_key] = peak
            self.stats['new_peaks_added'] += 1
    
    def _compute_scope(self, problem: ProblemEntry) -> str:
        """Určí scope problému."""
        ns_count = len(problem.affected_namespaces)
        app_count = len(problem.affected_apps)
        
        if ns_count >= 4 or app_count >= 8:
            return 'SYSTEMIC'
        elif ns_count >= 2:
            return 'CROSS_NS'
        else:
            return 'LOCAL'
    
    # =========================================================================
    # STATS & HEALTH METRICS
    # =========================================================================
    
    def get_stats(self) -> dict:
        """Vrátí statistiky registry."""
        return {
            **self.stats,
            'total_problems': len(self.problems),
            'total_peaks': len(self.peaks),
            'total_fingerprints': len(self.fingerprint_index),
            'problems_by_category': self._count_by_category(),
            'problems_by_scope': self._count_by_scope(),
        }
    
    def get_health_metrics(self) -> dict:
        """
        Vrátí kompletní health metriky pro monitoring.
        
        Použití:
            metrics = registry.get_health_metrics()
            if metrics['health_score'] < 80:
                alert("Registry health degraded")
        """
        metrics = {
            'timestamp': datetime.now().isoformat(),
            
            # Counts
            'total_problems': len(self.problems),
            'total_peaks': len(self.peaks),
            'total_fingerprints': len(self.fingerprint_index),
            
            # Thresholds status
            'problems_threshold': MAX_PROBLEMS_WARNING,
            'fingerprints_threshold': MAX_FINGERPRINTS_WARNING,
            'fps_per_problem_threshold': MAX_FINGERPRINTS_PER_PROBLEM,
            
            # Health indicators
            'problems_over_threshold': len(self.problems) > MAX_PROBLEMS_WARNING,
            'fingerprints_over_threshold': len(self.fingerprint_index) > MAX_FINGERPRINTS_WARNING,
            
            # Distribution
            'by_category': self._count_by_category(),
            'by_scope': self._count_by_scope(),
            
            # Fingerprint distribution
            'fingerprints_per_problem': {},
            'problems_with_many_fps': 0,
            
            # Age analysis
            'oldest_problem_date': None,
            'newest_problem_date': None,
            'problems_last_24h': 0,
            'problems_last_7d': 0,
            
            # Session stats
            'session_new_problems': self.stats['new_problems_added'],
            'session_updated_problems': self.stats['problems_updated'],
            'session_new_peaks': self.stats['new_peaks_added'],
            
            # Health score (0-100)
            'health_score': 100,
            'health_issues': [],
        }
        
        # Calculate fingerprint distribution
        fp_counts = []
        for pk, problem in self.problems.items():
            fp_count = len(problem.fingerprints)
            fp_counts.append(fp_count)
            
            if fp_count > MAX_FINGERPRINTS_PER_PROBLEM:
                metrics['problems_with_many_fps'] += 1
        
        if fp_counts:
            metrics['fingerprints_per_problem'] = {
                'min': min(fp_counts),
                'max': max(fp_counts),
                'avg': sum(fp_counts) / len(fp_counts),
                'median': sorted(fp_counts)[len(fp_counts) // 2],
            }
        
        # Age analysis
        now = datetime.now()
        last_24h = now.replace(hour=0, minute=0, second=0, microsecond=0)
        last_7d = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        
        oldest = None
        newest = None
        
        for problem in self.problems.values():
            if problem.first_seen:
                if oldest is None or problem.first_seen < oldest:
                    oldest = problem.first_seen
                if newest is None or problem.first_seen > newest:
                    newest = problem.first_seen
                
                if problem.first_seen >= last_24h:
                    metrics['problems_last_24h'] += 1
                if problem.first_seen >= last_7d:
                    metrics['problems_last_7d'] += 1
        
        metrics['oldest_problem_date'] = oldest.isoformat() if oldest else None
        metrics['newest_problem_date'] = newest.isoformat() if newest else None
        
        # Calculate health score
        issues = []
        score = 100
        
        if metrics['problems_over_threshold']:
            score -= 20
            issues.append(f"Too many problems: {len(self.problems)} > {MAX_PROBLEMS_WARNING}")
        
        if metrics['fingerprints_over_threshold']:
            score -= 20
            issues.append(f"Too many fingerprints: {len(self.fingerprint_index)} > {MAX_FINGERPRINTS_WARNING}")
        
        if metrics['problems_with_many_fps'] > 0:
            penalty = min(30, metrics['problems_with_many_fps'] * 5)
            score -= penalty
            issues.append(f"{metrics['problems_with_many_fps']} problems with >500 fingerprints")
        
        # Check for unknown category dominance
        unknown_count = metrics['by_category'].get('unknown', 0)
        if len(self.problems) > 0 and unknown_count / len(self.problems) > 0.5:
            score -= 10
            issues.append(f"High unknown category ratio: {100 * unknown_count / len(self.problems):.1f}%")
        
        metrics['health_score'] = max(0, score)
        metrics['health_issues'] = issues
        
        return metrics
    
    def _count_by_category(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for p in self.problems.values():
            counts[p.category] += 1
        return dict(counts)
    
    def _count_by_scope(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for p in self.problems.values():
            counts[p.scope] += 1
        return dict(counts)
    
    def print_summary(self):
        """Vytiskne shrnutí registry."""
        stats = self.get_stats()
        
        print("\n" + "=" * 60)
        print("📋 PROBLEM REGISTRY SUMMARY")
        print("=" * 60)
        print(f"   Problems: {stats['total_problems']}")
        print(f"   Peaks: {stats['total_peaks']}")
        print(f"   Fingerprints indexed: {stats['total_fingerprints']}")
        print(f"\n   By category: {stats['problems_by_category']}")
        print(f"   By scope: {stats['problems_by_scope']}")
        print(f"\n   Session stats:")
        print(f"     New problems: {stats['new_problems_added']}")
        print(f"     Updated problems: {stats['problems_updated']}")
        print(f"     New peaks: {stats['new_peaks_added']}")
        print(f"     Updated peaks: {stats['peaks_updated']}")
    
    def print_health_report(self):
        """Vytiskne kompletní health report."""
        metrics = self.get_health_metrics()
        
        # Health score color
        score = metrics['health_score']
        if score >= 80:
            score_icon = "🟢"
        elif score >= 60:
            score_icon = "🟡"
        else:
            score_icon = "🔴"
        
        print("\n" + "=" * 70)
        print("🏥 REGISTRY HEALTH REPORT")
        print("=" * 70)
        
        print(f"\n{score_icon} Health Score: {score}/100")
        
        if metrics['health_issues']:
            print("\n⚠️  Issues:")
            for issue in metrics['health_issues']:
                print(f"   • {issue}")
        
        print(f"\n📊 Counts:")
        print(f"   Problems: {metrics['total_problems']:,} (threshold: {metrics['problems_threshold']:,})")
        print(f"   Peaks: {metrics['total_peaks']:,}")
        print(f"   Fingerprints: {metrics['total_fingerprints']:,} (threshold: {metrics['fingerprints_threshold']:,})")
        
        print(f"\n📈 Fingerprints per problem:")
        fp_stats = metrics['fingerprints_per_problem']
        if fp_stats:
            print(f"   Min: {fp_stats['min']}, Max: {fp_stats['max']}, Avg: {fp_stats['avg']:.1f}, Median: {fp_stats['median']}")
        
        print(f"\n📅 Activity:")
        print(f"   New problems (24h): {metrics['problems_last_24h']}")
        print(f"   New problems (7d): {metrics['problems_last_7d']}")
        
        print(f"\n📂 Distribution:")
        print(f"   By category: {metrics['by_category']}")
        print(f"   By scope: {metrics['by_scope']}")
        
        print(f"\n🕐 Session stats:")
        print(f"   New problems: {metrics['session_new_problems']}")
        print(f"   Updated problems: {metrics['session_updated_problems']}")
        print(f"   New peaks: {metrics['session_new_peaks']}")
        
        return metrics


# =============================================================================
# UTILITY: MIGRATION FROM OLD FORMAT
# =============================================================================

def migrate_old_registry(old_dir: str, new_dir: str) -> int:
    """
    Migruje starý formát registry (1:1 fingerprint) na nový (problem_key).
    
    DEFENSIVE: Zvládá None, prázdné seznamy, None položky v seznamech.
    
    Returns: počet zmigrovaných záznamů
    """
    old_path = Path(old_dir)
    new_registry = ProblemRegistry(new_dir)
    
    # Load old known_errors.yaml
    old_errors = old_path / 'known_errors.yaml'
    if not old_errors.exists():
        print(f"⚠️ Old registry not found: {old_errors}")
        return 0
    
    with open(old_errors, 'r', encoding='utf-8') as f:
        old_data = yaml.safe_load(f) or []
    
    migrated = 0
    skipped = 0
    
    for item in old_data:
        fingerprint = item.get('fingerprint')
        if not fingerprint:
            skipped += 1
            continue
        
        category = item.get('category', 'unknown') or 'unknown'
        
        # DEFENSIVE: affected_apps může být None, [], nebo obsahovat None
        raw_apps = item.get('affected_apps')
        apps = [a for a in (raw_apps or []) if isinstance(a, str) and a.strip()]
        
        raw_ns = item.get('affected_namespaces')
        namespaces = [n for n in (raw_ns or []) if isinstance(n, str) and n.strip()]
        
        # Parse timestamps
        first_seen = None
        last_seen = None
        if item.get('first_seen'):
            try:
                ts_str = item['first_seen'].replace('Z', '+00:00').replace('+00:00', '')
                first_seen = datetime.fromisoformat(ts_str)
            except:
                pass
        if item.get('last_seen'):
            try:
                ts_str = item['last_seen'].replace('Z', '+00:00').replace('+00:00', '')
                last_seen = datetime.fromisoformat(ts_str)
            except:
                pass
        
        # Compute problem_key (defensivní funkce)
        problem_key = compute_problem_key(
            category=category,
            app_names=apps,
            namespaces=namespaces,
        )
        
        # Occurrences - defensive
        occurrences = item.get('occurrences', 1)
        if not isinstance(occurrences, (int, float)) or occurrences < 1:
            occurrences = 1
        
        # Update or create
        if problem_key in new_registry.problems:
            problem = new_registry.problems[problem_key]
            if fingerprint not in problem.fingerprints:
                if len(problem.fingerprints) < MAX_FINGERPRINTS_PER_PROBLEM:
                    problem.fingerprints.append(fingerprint)
            if first_seen and (problem.first_seen is None or first_seen < problem.first_seen):
                problem.first_seen = first_seen
            if last_seen and (problem.last_seen is None or last_seen > problem.last_seen):
                problem.last_seen = last_seen
            problem.occurrences += int(occurrences)
            problem.affected_apps.update(apps)  # apps is already sanitized
            problem.affected_namespaces.update(namespaces)  # namespaces is already sanitized
        else:
            new_registry._problem_counter += 1
            parts = problem_key.split(':')
            
            problem = ProblemEntry(
                id=f"KP-{new_registry._problem_counter:06d}",
                problem_key=problem_key,
                category=parts[0].lower() if parts else 'unknown',
                flow=parts[1] if len(parts) > 1 else 'unknown',
                error_class=parts[2] if len(parts) > 2 else 'unknown',
                first_seen=first_seen,
                last_seen=last_seen,
                occurrences=int(occurrences),
                fingerprints=[fingerprint],
                affected_apps=set(apps),  # apps is already sanitized
                affected_namespaces=set(namespaces),  # namespaces is already sanitized
                status=item.get('status', 'OPEN'),
                jira=item.get('jira'),
                notes=item.get('notes'),
            )
            problem.scope = new_registry._compute_scope(problem)
            new_registry.problems[problem_key] = problem
        
        # Index fingerprint
        new_registry.fingerprint_index[fingerprint] = problem_key
        migrated += 1
    
    # Save new registry
    new_registry.save()
    
    print(f"✅ Migrated {migrated:,} fingerprints into {len(new_registry.problems):,} problems")
    if skipped > 0:
        print(f"⚠️  Skipped {skipped:,} entries (missing fingerprint)")
    return migrated


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Problem Registry Management')
    parser.add_argument('--registry-dir', default='./registry', help='Registry directory')
    parser.add_argument('--migrate-from', help='Migrate from old registry directory')
    parser.add_argument('--stats', action='store_true', help='Show registry stats')
    
    args = parser.parse_args()
    
    if args.migrate_from:
        migrate_old_registry(args.migrate_from, args.registry_dir)
    else:
        registry = ProblemRegistry(args.registry_dir)
        registry.load()
        
        if args.stats:
            registry.print_summary()
        else:
            print(f"Loaded registry from {args.registry_dir}")
            print(f"  Problems: {len(registry.problems)}")
            print(f"  Peaks: {len(registry.peaks)}")
            print(f"  Fingerprints: {len(registry.fingerprint_index)}")
