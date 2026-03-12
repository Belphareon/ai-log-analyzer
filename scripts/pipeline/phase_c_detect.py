#!/usr/bin/env python3
"""
FÁZE C: Detect
===============

Detekce anomálií s registry integrací.
- Správná integrace s ProblemRegistry
- Lookup přes problem_key, ne jen fingerprint
- Propagace event timestamps (ne run timestamps)
- P93/CAP namespace-level peak detection

Složitost: O(n) místo O(n × fingerprints)
"""

from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import sys
import os

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

# Import PeakDetector (P93/CAP spike detection)
try:
    from core.peak_detection import PeakDetector
    HAS_PEAK_DETECTOR = True
except ImportError:
    try:
        from peak_detection import PeakDetector
        HAS_PEAK_DETECTOR = True
    except ImportError:
        HAS_PEAK_DETECTOR = False
        PeakDetector = None


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
    FÁZE C: Detect (s Registry integrací)

    - Registry se načte při __init__ nebo přes load_registry()
    - Lookup používá BOTH fingerprint AND problem_key
    - Event timestamps se propagují do DetectionResult
    - P93/CAP namespace-level peak detection
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
        peak_detector: 'PeakDetector' = None,
        new_error_min_count: int = 50,
        min_namespace_peak_value: int = None,
    ):
        # Legacy params kept for backward compat (not used for detection when peak_detector is set)
        self.spike_threshold = spike_threshold
        self.spike_mad_threshold = spike_mad_threshold
        self.burst_threshold = burst_threshold
        self.burst_window_sec = burst_window_sec
        self.cross_ns_threshold = cross_ns_threshold

        # Legacy: direct fingerprint set
        self.known_fingerprints = known_fingerprints or set()
        self.known_fixes = known_fixes or {}

        # Registry integration
        self.registry = registry

        # P93/CAP peak detection
        self.peak_detector = peak_detector
        self.new_error_min_count = new_error_min_count
        self.min_namespace_peak_value = (
            int(os.getenv('MIN_NAMESPACE_PEAK_VALUE', '1'))
            if min_namespace_peak_value is None
            else int(min_namespace_peak_value)
        )
        self._fingerprint_peak_results = {}  # populated in detect_batch

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
        """Detekuje spike pomocí P93/CAP percentilového systému.

        Algoritmus:
        1. Zkontroluj, zda namespace fingerprintu je v peaku (precomputed v detect_batch)
        2. Pokud ano -> is_spike=True s P93/CAP evidencí
        3. Fallback: nový error typ (baseline=0, count >= threshold)
        """
        # 1. P93/CAP per-fingerprint per-namespace check (populated by detect_batch)
        peak_result = self._fingerprint_peak_results.get(measurement.fingerprint)
        if peak_result and peak_result.get('is_peak'):
            threshold_candidates = [
                t for t in [peak_result.get('p93_threshold'), peak_result.get('cap_threshold')]
                if isinstance(t, (int, float))
            ]
            threshold_value = min(threshold_candidates) if threshold_candidates else None
            result.flags.is_spike = True
            result.add_evidence(
                rule="spike_p93_cap",
                current=peak_result.get('value'),
                threshold=threshold_value,
                message=(
                    f"namespace {peak_result.get('namespace')} fingerprint_count ({peak_result.get('value', 0):.0f}) exceeds "
                    f"P93={peak_result.get('p93_threshold', 0):.0f} / "
                    f"CAP={peak_result.get('cap_threshold', 0):.0f} "
                    f"(triggered_by={peak_result.get('triggered_by')}, peak_id={peak_result.get('peak_identifier')})"
                ),
            )
            self.stats['detected_spike'] += 1
            return True

        # 2. Legacy EWMA/MAD fallback (only when no PeakDetector available)
        if not self.peak_detector:
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

        # 3. Fallback: new error type (no baseline)
        # DISABLED: Was causing false positives (e.g., connection_error with 57 occurrences)
        # Only P93/CAP baseline detection should trigger SPIKE alerts
        # if not self.peak_detector and measurement.baseline_ewma == 0 and measurement.baseline_median == 0:
        #     if measurement.current_count >= self.new_error_min_count:
        #         result.flags.is_spike = True
        #         result.add_evidence(
        #             rule="spike_new_error_type",
        #             current=measurement.current_count,
        #             threshold=self.new_error_min_count,
        #             message=f"new error type with {measurement.current_count} occurrences (no baseline)"
        #         )
        #         self.stats['detected_spike'] += 1
        #         return True

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
        
        Kontroluje BOTH fingerprint AND problem_key.
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

        Přidán record_metadata pro apps, error_type, normalized_message.
        P93/CAP namespace-level peak detection před per-fingerprint detekcí.
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

        # ==================================================================
        # P93/CAP: per-fingerprint per-namespace peak detection
        # ==================================================================
        self._fingerprint_peak_results = {}

        if self.peak_detector:
            # 1. Determine day_of_week from first record timestamp
            day_of_week = 0
            if records:
                for r in records:
                    if r.timestamp:
                        day_of_week = r.timestamp.weekday()
                        break
            elif measurements:
                for m in measurements.values():
                    if m.first_seen:
                        day_of_week = m.first_seen.weekday()
                        break

            # 2. Per-fingerprint per-namespace counts
            window_minutes = int(os.getenv('WINDOW_MINUTES', '15'))

            for fp, measurement in measurements.items():
                fp_records = records_by_fp.get(fp, [])
                if not fp_records:
                    continue

                def _bucket(ts: datetime) -> datetime:
                    minute = (ts.minute // window_minutes) * window_minutes
                    return ts.replace(minute=minute, second=0, microsecond=0)

                ns_window_counts: Dict[str, Dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
                latest_bucket = None
                for rec in fp_records:
                    if not rec.timestamp:
                        continue
                    bucket = _bucket(rec.timestamp)
                    if latest_bucket is None or bucket > latest_bucket:
                        latest_bucket = bucket
                    if rec.namespace:
                        ns_window_counts[rec.namespace][bucket] += 1

                if not ns_window_counts:
                    continue

                peak_candidate = None
                for ns, bucket_counts in ns_window_counts.items():
                    if latest_bucket is None:
                        continue

                    current_ns_count = bucket_counts.get(latest_bucket, 0)
                    if measurement.active_windows > 1:
                        non_zero_windows = [v for v in bucket_counts.values() if v > 0]
                        if non_zero_windows:
                            value_for_peak = sum(non_zero_windows) / len(non_zero_windows)
                        else:
                            value_for_peak = float(current_ns_count)
                    else:
                        value_for_peak = float(current_ns_count)

                    if value_for_peak < self.min_namespace_peak_value:
                        continue

                    try:
                        check = self.peak_detector.is_peak(value_for_peak, ns, day_of_week)
                    except Exception:
                        continue

                    if not check.get('is_peak'):
                        continue

                    trigger_score = max(
                        value_for_peak / check.get('p93_threshold', 1.0) if check.get('p93_threshold') else 0.0,
                        value_for_peak / check.get('cap_threshold', 1.0) if check.get('cap_threshold') else 0.0,
                    )
                    candidate = {
                        **check,
                        'namespace': ns,
                        'value': value_for_peak,
                        'current_ns_count': current_ns_count,
                        'peak_identifier': f"SPIKE:{fp}:{ns}:{latest_bucket.isoformat()}",
                        '_trigger_score': trigger_score,
                    }

                    if peak_candidate is None or candidate['_trigger_score'] > peak_candidate['_trigger_score']:
                        peak_candidate = candidate

                if peak_candidate:
                    peak_candidate.pop('_trigger_score', None)
                    self._fingerprint_peak_results[fp] = peak_candidate

        # ==================================================================
        # Per-fingerprint detection (O(fingerprints))
        # ==================================================================
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
    print("Phase C: Detect - with Registry integration")
