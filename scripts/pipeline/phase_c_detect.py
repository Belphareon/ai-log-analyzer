#!/usr/bin/env python3
"""
FÁZE C: Detect (V2 - S REGISTRY INTEGRACÍ)
==========================================

OPRAVY v2:
1. Správná integrace s ProblemRegistry
2. Lookup přes problem_key, ne jen fingerprint
3. Propagace event timestamps (ne run timestamps)

Složitost: O(n) místo O(n × fingerprints)
"""

from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import sys

# Progress
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

def progress_iter(iterable, desc="Processing", total=None, disable=False):
    if disable:
        return iterable
    if HAS_TQDM:
        return tqdm(iterable, desc=desc, total=total, file=sys.stderr, 
                    ncols=80, leave=False, mininterval=0.5)
    else:
        if total and total > 100:
            checkpoint = max(1, total // 10)
            for i, item in enumerate(iterable):
                if i % checkpoint == 0:
                    print(f"      {desc}: {i:,}/{total:,}", file=sys.stderr, flush=True)
                yield item
        else:
            yield from iterable

# Import from same package
try:
    from .phase_b_measure import MeasurementResult
    from .incident import Evidence, Flags
except ImportError:
    from phase_b_measure import MeasurementResult
    from incident import Evidence, Flags

# Import registry (optional - for backwards compatibility)
try:
    from core.problem_registry import ProblemRegistry, compute_problem_key
    HAS_REGISTRY = True
except ImportError:
    try:
        from problem_registry import ProblemRegistry, compute_problem_key
        HAS_REGISTRY = True
    except ImportError:
        HAS_REGISTRY = False
        ProblemRegistry = None


@dataclass
class DetectionResult:
    """Výstup z FÁZE C pro jeden fingerprint"""
    fingerprint: str
    flags: Flags = field(default_factory=Flags)
    evidence: List[Evidence] = field(default_factory=list)
    
    # Event timestamps (pro registry update)
    first_event_ts: Optional[datetime] = None
    last_event_ts: Optional[datetime] = None
    
    # Problem key (pro registry lookup)
    problem_key: Optional[str] = None
    
    def add_evidence(self, rule: str, **kwargs):
        self.evidence.append(Evidence(rule=rule, **kwargs))


class PhaseC_Detect:
    """
    FÁZE C: Detect (V2 s Registry)
    
    Klíčové opravy:
    1. Registry se načte při __init__ nebo přes load_registry()
    2. Lookup používá BOTH fingerprint AND problem_key
    3. Event timestamps se propagují do DetectionResult
    """
    
    def __init__(
        self,
        spike_threshold: float = 3.0,
        spike_mad_threshold: float = 3.0,
        burst_threshold: float = 5.0,
        burst_window_sec: int = 60,
        cross_ns_threshold: int = 2,
        known_fingerprints: Set[str] = None,
        known_fixes: Dict[str, str] = None,
        registry: 'ProblemRegistry' = None,
    ):
        self.spike_threshold = spike_threshold
        self.spike_mad_threshold = spike_mad_threshold
        self.burst_threshold = burst_threshold
        self.burst_window_sec = burst_window_sec
        self.cross_ns_threshold = cross_ns_threshold
        
        # Legacy: direct fingerprint set
        self.known_fingerprints = known_fingerprints or set()
        self.known_fixes = known_fixes or {}
        
        # V2: Registry integration
        self.registry = registry
        
        # Stats
        self.stats = {
            'total_processed': 0,
            'detected_new': 0,
            'detected_known': 0,
            'detected_spike': 0,
            'detected_burst': 0,
            'detected_cross_ns': 0,
        }
    
    def load_registry(self, registry_dir: str) -> bool:
        """
        Načte ProblemRegistry z adresáře.
        
        Volej PŘED spuštěním pipeline!
        """
        if not HAS_REGISTRY:
            print("⚠️ ProblemRegistry not available")
            return False
        
        try:
            self.registry = ProblemRegistry(registry_dir)
            self.registry.load()
            
            # Sync known_fingerprints from registry
            self.known_fingerprints = self.registry.get_all_known_fingerprints()
            
            print(f"✅ Loaded registry: {len(self.known_fingerprints)} known fingerprints")
            return True
            
        except Exception as e:
            print(f"⚠️ Failed to load registry: {e}")
            return False
    
    def _detect_spike(self, measurement: MeasurementResult, result: DetectionResult) -> bool:
        """Detekuje spike: current > baseline * threshold
        
        OPRAVA: Přidán fallback pro baseline=0 (nové error typy)
        """
        # Standard EWMA test
        if measurement.baseline_ewma > 0:
            ratio = measurement.current_rate / measurement.baseline_ewma
            if ratio > self.spike_threshold:
                result.flags.is_spike = True
                result.add_evidence(
                    rule="spike_ewma",
                    baseline=measurement.baseline_ewma,
                    current=measurement.current_rate,
                    threshold=self.spike_threshold,
                    message=f"ratio ({ratio:.2f}) > threshold ({self.spike_threshold})"
                )
                self.stats['detected_spike'] += 1
                return True
        
        # MAD test (robustnější na outliers)
        if measurement.baseline_mad > 0:
            mad_upper = measurement.baseline_median + (measurement.baseline_mad * self.spike_mad_threshold)
            if measurement.current_rate > mad_upper:
                result.flags.is_spike = True
                result.add_evidence(
                    rule="spike_mad",
                    baseline=measurement.baseline_median,
                    current=measurement.current_rate,
                    threshold=mad_upper,
                    message=f"current ({measurement.current_rate}) > median + {self.spike_mad_threshold}*MAD ({mad_upper:.2f})"
                )
                self.stats['detected_spike'] += 1
                return True
        
        # FALLBACK pro nové error typy (baseline=0):
        # Pokud error rate je "podstatně vyšší" než obvyklý minimální počet eventy
        # Klasifikuj jako spike aby se mohlo poslat notifikaci
        if measurement.baseline_ewma == 0 and measurement.baseline_median == 0:
            # Nový error typ - neměj historickou linii
            # Pokud máš aspoň 5 errorů v 15-min okně, to je "spike" pro nový typ
            if measurement.current_count >= 5:
                result.flags.is_spike = True
                result.add_evidence(
                    rule="spike_new_error_type",
                    current=measurement.current_count,
                    threshold=5,
                    message=f"new error type with {measurement.current_count} occurrences (no baseline)"
                )
                self.stats['detected_spike'] += 1
                return True
        
        return False
    
    def _detect_burst(
        self,
        measurement: MeasurementResult,
        fp_records: List,
        result: DetectionResult
    ) -> bool:
        """Detekuje burst: max_count / avg_count > threshold (per spec).

        Burst = náhlá LOKÁLNÍ koncentrace chyb v krátkém časovém okně.
        Pravidlo: max(window_counts) / avg(window_counts) > burst_threshold

        Nezávisí na historickém baseline (EWMA) — pouze porovnává
        distribuci eventů uvnitř aktuálního okna.
        Viz README_DETAILED.md, Phase C: Burst Detection.
        """
        if len(fp_records) < 2:
            return False

        sorted_records = sorted(
            [r for r in fp_records if r.timestamp],
            key=lambda r: r.timestamp
        )

        if len(sorted_records) < 2:
            return False

        # Capture event timestamps
        result.first_event_ts = sorted_records[0].timestamp
        result.last_event_ts = sorted_records[-1].timestamp

        # Compute sliding window counts (O(n))
        window = timedelta(seconds=self.burst_window_sec)
        window_start_idx = 0
        window_counts = []

        for i, record in enumerate(sorted_records):
            while (window_start_idx < i and
                   sorted_records[window_start_idx].timestamp < record.timestamp - window):
                window_start_idx += 1
            window_counts.append(i - window_start_idx + 1)

        max_count = max(window_counts)
        avg_count = sum(window_counts) / len(window_counts)
        ratio = max_count / avg_count if avg_count > 0 else 0

        if ratio > self.burst_threshold:
            result.flags.is_burst = True
            result.add_evidence(
                rule="burst",
                current=float(max_count),
                threshold=self.burst_threshold,
                message=f"max/avg ratio ({ratio:.2f}) > {self.burst_threshold} "
                        f"({max_count} events in {self.burst_window_sec}s window, avg {avg_count:.1f})",
            )
            self.stats['detected_burst'] += 1
            return True

        return False
    
    def _detect_new(
        self,
        measurement: MeasurementResult,
        result: DetectionResult,
        apps: List[str] = None,
        error_type: str = "",
        normalized_message: str = "",
        namespaces: List[str] = None,
    ) -> bool:
        """
        Detekuje nový fingerprint/problem.
        
        V2: Kontroluje BOTH fingerprint AND problem_key!
        """
        fp = measurement.fingerprint
        
        # 1. Check fingerprint index
        if fp in self.known_fingerprints:
            self.stats['detected_known'] += 1
            return False
        
        # 2. If registry available, check problem_key
        if self.registry and HAS_REGISTRY and apps:
            # Get category from somewhere (measurement or classification)
            category = getattr(measurement, 'category', 'unknown')
            
            problem_key = compute_problem_key(
                category=category,
                app_names=apps,
                error_type=error_type,
                normalized_message=normalized_message,
                namespaces=namespaces,
            )
            
            result.problem_key = problem_key
            
            # Even if fingerprint is new, problem might be known
            if self.registry.is_problem_key_known(problem_key):
                # Problem is known, but fingerprint is new - add to index
                # This is NOT a "new" problem, just a new variant
                result.add_evidence(
                    rule="new_fingerprint_known_problem",
                    message=f"fingerprint {fp} is new, but problem {problem_key} is known"
                )
                
                # Still mark fingerprint as known for this session
                self.known_fingerprints.add(fp)
                self.stats['detected_known'] += 1
                return False
        
        # 3. Truly new
        result.flags.is_new = True
        result.add_evidence(
            rule="new_fingerprint",
            message=f"fingerprint {fp} not seen before"
        )
        
        # Add to known (for this session)
        self.known_fingerprints.add(fp)
        self.stats['detected_new'] += 1
        
        return True
    
    def _detect_cross_namespace(self, measurement: MeasurementResult, result: DetectionResult) -> bool:
        """Detekuje cross-namespace pattern"""
        ns_count = measurement.namespace_count
        
        if ns_count >= self.cross_ns_threshold:
            result.flags.is_cross_namespace = True
            result.add_evidence(
                rule="cross_namespace",
                current=ns_count,
                threshold=self.cross_ns_threshold,
                message=f"found in {ns_count} namespaces: {measurement.namespaces}"
            )
            self.stats['detected_cross_ns'] += 1
            return True
        
        return False
    
    def _detect_silence(self, measurement: MeasurementResult, result: DetectionResult) -> bool:
        """Detekuje silence: neočekávaná absence errorů"""
        if measurement.current_rate == 0 and measurement.baseline_ewma > 5:
            result.flags.is_silence = True
            result.add_evidence(
                rule="silence",
                baseline=measurement.baseline_ewma,
                current=0,
                message=f"expected ~{measurement.baseline_ewma:.1f} errors but got 0"
            )
            return True
        
        return False
    
    def _detect_regression(
        self,
        measurement: MeasurementResult,
        current_version: str,
        result: DetectionResult
    ) -> bool:
        """Detekuje regresi"""
        fp = measurement.fingerprint
        
        if fp not in self.known_fixes:
            return False
        
        fixed_version = self.known_fixes[fp]
        
        if self._version_gte(current_version, fixed_version):
            result.flags.is_regression = True
            result.add_evidence(
                rule="regression",
                message=f"fingerprint {fp} was fixed in {fixed_version}, but appeared in {current_version}"
            )
            return True
        
        return False
    
    def _version_gte(self, v1: str, v2: str) -> bool:
        import re
        def parse_version(v):
            nums = re.findall(r'\d+', v)
            return [int(n) for n in nums] if nums else [0]
        try:
            return parse_version(v1) >= parse_version(v2)
        except:
            return False
    
    def detect(
        self,
        measurement: MeasurementResult,
        fp_records: List = None,
        current_version: str = None,
        apps: List[str] = None,
        error_type: str = "",
        normalized_message: str = "",
        namespaces: List[str] = None,
    ) -> DetectionResult:
        """Aplikuje všechna detekční pravidla"""
        result = DetectionResult(fingerprint=measurement.fingerprint)
        
        self.stats['total_processed'] += 1
        
        # Capture event timestamps from records if available
        if fp_records:
            sorted_records = sorted(
                [r for r in fp_records if r.timestamp],
                key=lambda r: r.timestamp
            )
            if sorted_records:
                result.first_event_ts = sorted_records[0].timestamp
                result.last_event_ts = sorted_records[-1].timestamp
        
        # Apply detection rules
        self._detect_spike(measurement, result)
        self._detect_new(
            measurement, result,
            apps=apps,
            error_type=error_type,
            normalized_message=normalized_message,
            namespaces=namespaces,
        )
        self._detect_cross_namespace(measurement, result)
        self._detect_silence(measurement, result)
        
        if fp_records:
            self._detect_burst(measurement, fp_records, result)
        
        if current_version:
            self._detect_regression(measurement, current_version, result)
        
        return result
    
    def detect_batch(
        self,
        measurements: Dict[str, MeasurementResult],
        records: List = None,
        versions: Dict[str, str] = None,
        record_metadata: Dict[str, dict] = None,
    ) -> Dict[str, DetectionResult]:
        """
        OPTIMALIZOVANÁ verze - předgrupuje records JEDNOU.
        
        V2: Přidán record_metadata pro apps, error_type, normalized_message.
        """
        # Pre-group records by fingerprint (O(n))
        records_by_fp: Dict[str, List] = defaultdict(list)
        if records:
            for r in records:
                records_by_fp[r.fingerprint].append(r)
        
        # Pre-extract metadata if not provided
        if record_metadata is None:
            record_metadata = {}
            for fp, fp_records in records_by_fp.items():
                if fp_records:
                    r = fp_records[0]
                    record_metadata[fp] = {
                        'apps': list(set(rec.app_name for rec in fp_records)),
                        'error_type': getattr(r, 'error_type', ''),
                        'normalized_message': getattr(r, 'normalized_message', ''),
                        'namespaces': list(set(rec.namespace for rec in fp_records)),
                    }
        
        # Detection (O(fingerprints))
        results = {}
        items = list(measurements.items())
        
        for fp, measurement in progress_iter(items, desc="Phase C: Detect", total=len(items)):
            fp_records = records_by_fp.get(fp, [])
            version = versions.get(fp) if versions else None
            meta = record_metadata.get(fp, {})
            
            results[fp] = self.detect(
                measurement,
                fp_records,
                version,
                apps=meta.get('apps', []),
                error_type=meta.get('error_type', ''),
                normalized_message=meta.get('normalized_message', ''),
                namespaces=meta.get('namespaces', []),
            )
        
        return results
    
    def get_event_timestamps(self, results: Dict[str, DetectionResult]) -> Dict[str, Tuple[datetime, datetime]]:
        """
        Vrátí event timestamps pro registry update.
        
        Returns: {fingerprint: (first_ts, last_ts)}
        """
        timestamps = {}
        for fp, result in results.items():
            if result.first_event_ts and result.last_event_ts:
                timestamps[fp] = (result.first_event_ts, result.last_event_ts)
        return timestamps
    
    def add_known_fingerprint(self, fingerprint: str):
        self.known_fingerprints.add(fingerprint)
    
    def add_known_fix(self, fingerprint: str, fixed_in_version: str):
        self.known_fixes[fingerprint] = fixed_in_version
    
    def load_known_from_db(self, conn):
        """Legacy: load from DB (use load_registry instead)"""
        cursor = conn.cursor()
        cursor.execute("SELECT signature_hash FROM ailog_peak.error_signatures")
        self.known_fingerprints = {row[0] for row in cursor.fetchall()}
        cursor.execute("""
            SELECT issue_id, fixed_in_version 
            FROM ailog_peak.known_issues 
            WHERE fixed_in_version IS NOT NULL
        """)
        self.known_fixes = {row[0]: row[1] for row in cursor.fetchall()}
    
    def print_stats(self):
        """Print detection statistics"""
        print("\n📊 Detection Stats:")
        print(f"   Total processed: {self.stats['total_processed']}")
        print(f"   New: {self.stats['detected_new']}")
        print(f"   Known: {self.stats['detected_known']}")
        print(f"   Spikes: {self.stats['detected_spike']}")
        print(f"   Bursts: {self.stats['detected_burst']}")
        print(f"   Cross-NS: {self.stats['detected_cross_ns']}")


if __name__ == "__main__":
    print("Phase C: Detect V2 - with Registry integration")
