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
import statistics
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
        fingerprint_spike_min_count: int = None,
        fingerprint_spike_mad_multiplier: float = None,
        monitored_namespaces: Optional[List[str]] = None,
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
        self.fingerprint_spike_min_count = (
            int(os.getenv('FINGERPRINT_SPIKE_MIN_COUNT', '20'))
            if fingerprint_spike_min_count is None
            else int(fingerprint_spike_min_count)
        )
        self.fingerprint_spike_mad_multiplier = (
            float(os.getenv('FINGERPRINT_SPIKE_MAD_MULTIPLIER', '6'))
            if fingerprint_spike_mad_multiplier is None
            else float(fingerprint_spike_mad_multiplier)
        )
        self.namespace_fingerprint_baselines = {}
        self.namespace_fingerprint_baseline_available = False
        self.monitored_namespaces = tuple(sorted({
            str(namespace).strip()
            for namespace in (monitored_namespaces or ())
            if str(namespace).strip()
        }))
        self._fingerprint_peak_results = {}  # populated in detect_batch
        self.namespace_peak_audit = []

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
        if isinstance(peak_result, list):
            peak_result = max(
                peak_result,
                key=lambda item: (
                    float(item.get('_trigger_score', 0) or 0),
                    int(item.get('fingerprint_contribution', 0) or 0),
                ),
                default=None,
            )
        if peak_result and peak_result.get('is_peak'):
            threshold_candidates = [
                t for t in [peak_result.get('p93_threshold'), peak_result.get('cap_threshold')]
                if isinstance(t, (int, float))
            ]
            threshold_value = min(threshold_candidates) if threshold_candidates else None
            diagnosis_status = str(peak_result.get('diagnosis_status') or 'diagnosed')
            diagnosis_suffix = ' [UNDIAGNOSED]' if diagnosis_status == 'undiagnosed' else ''
            result.flags.is_spike = True
            result.add_evidence(
                rule="spike_p93_cap",
                current=peak_result.get('value'),
                threshold=threshold_value,
                message=(
                    f"namespace {peak_result.get('namespace')} total ({peak_result.get('value', 0):.0f}) exceeds "
                    f"P93={peak_result.get('p93_threshold', 0):.0f} / "
                    f"CAP={peak_result.get('cap_threshold', 0):.0f} "
                    f"(triggered_by={peak_result.get('triggered_by')}, peak_id={peak_result.get('peak_identifier')})"
                    f"{diagnosis_suffix}"
                ),
                details={
                    'namespace': peak_result.get('namespace'),
                    'diagnosis_status': diagnosis_status,
                    'owner_fingerprint': peak_result.get('owner_fingerprint'),
                    'anomalous_contributors': peak_result.get('anomalous_contributors', []),
                    'fingerprint_contribution': peak_result.get('fingerprint_contribution'),
                    'contributing_fingerprints': peak_result.get('contributing_fingerprints'),
                    'fingerprint_threshold': peak_result.get('fingerprint_threshold'),
                    'fingerprint_baseline': peak_result.get('fingerprint_baseline'),
                    'fingerprint_anomaly_score': peak_result.get('fingerprint_anomaly_score'),
                    'fingerprint_gate_method': peak_result.get('fingerprint_gate_method'),
                    'p93_threshold': peak_result.get('p93_threshold'),
                    'percentile_level': peak_result.get('percentile_level'),
                    'percentile_threshold': peak_result.get('percentile_threshold'),
                    'cap_threshold': peak_result.get('cap_threshold'),
                    'triggered_by': peak_result.get('triggered_by'),
                    'peak_identifier': peak_result.get('peak_identifier'),
                    'threshold_snapshot_id': peak_result.get('threshold_snapshot_id'),
                    'detector_version': 'namespace_pxx_cap_fingerprint_v3',
                },
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
        except (ValueError, TypeError):
            return False

    @staticmethod
    def latest_version(versions) -> Optional[str]:
        """Return the highest observed numeric application version."""
        import re

        parsed_versions = []
        for version in versions:
            if not version:
                continue
            numbers = tuple(int(number) for number in re.findall(r'\d+', str(version)))
            if numbers:
                parsed_versions.append((numbers, str(version)))
        return max(parsed_versions)[1] if parsed_versions else None

    def prepare_namespace_peak_results(
        self,
        fingerprint_namespace_windows: Dict[str, Dict[str, Dict[datetime, int]]],
        measurements: Dict[str, MeasurementResult] = None,
    ) -> None:
        """Evaluate namespace volume and assign it to an anomalous contributor."""
        self._fingerprint_peak_results = {}
        self.namespace_peak_audit = []
        if not self.peak_detector:
            return
        measurements = measurements or {}

        namespace_totals: Dict[str, Dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
        contributors: Dict[Tuple[str, datetime], Dict[str, int]] = defaultdict(dict)
        for fingerprint, namespace_windows in fingerprint_namespace_windows.items():
            for namespace, bucket_counts in namespace_windows.items():
                if not namespace:
                    continue
                for bucket, count in bucket_counts.items():
                    namespace_totals[namespace][bucket] += count
                    contributors[(namespace, bucket)][fingerprint] = count

        for namespace, bucket_counts in namespace_totals.items():
            for bucket, namespace_total in bucket_counts.items():
                if namespace_total < self.min_namespace_peak_value:
                    self.namespace_peak_audit.append({
                        'window_start': bucket.isoformat(),
                        'namespace': namespace,
                        'namespace_total': namespace_total,
                        'is_namespace_peak': False,
                        'p93_threshold': None,
                        'percentile_level': None,
                        'percentile_threshold': None,
                        'cap_threshold': None,
                        'triggered_by': None,
                        'threshold_snapshot_id': None,
                        'family_baseline_available': self.namespace_fingerprint_baseline_available,
                        'family_decisions': [],
                        'owner_fingerprint': None,
                        'suppressed_reason': None,
                        'verdict_reason': 'below_min_volume',
                        'diagnosis_status': 'undiagnosed',
                    })
                    continue
                check = self.peak_detector.is_peak(
                    float(namespace_total), namespace, bucket.weekday()
                )
                audit_entry = {
                    'window_start': bucket.isoformat(),
                    'namespace': namespace,
                    'namespace_total': namespace_total,
                    'is_namespace_peak': bool(check.get('is_peak')),
                    'p93_threshold': check.get('p93_threshold'),
                    'percentile_level': check.get('percentile_level'),
                    'percentile_threshold': check.get('percentile_threshold'),
                    'cap_threshold': check.get('cap_threshold'),
                    'triggered_by': check.get('triggered_by'),
                    'threshold_snapshot_id': check.get('threshold_snapshot_id'),
                    'family_baseline_available': self.namespace_fingerprint_baseline_available,
                    'family_decisions': [],
                    'owner_fingerprint': None,
                    'suppressed_reason': None,
                    'verdict_reason': 'below_threshold',
                    'diagnosis_status': 'undiagnosed',
                    'peak_identifier': (
                        f"SPIKE:NS:{namespace}:{bucket.isoformat()}"
                        if check.get('is_peak') else None
                    ),
                }
                if not check.get('is_peak'):
                    self.namespace_peak_audit.append(audit_entry)
                    continue

                bucket_contributors = contributors[(namespace, bucket)]
                qualified_contributors = []
                family_decisions = []
                for fingerprint, contribution in bucket_contributors.items():
                    namespace_rates = self.namespace_fingerprint_baselines.get(
                        (namespace, fingerprint)
                    )
                    if not self.namespace_fingerprint_baseline_available:
                        family_decisions.append({
                            'fingerprint': fingerprint,
                            'contribution': contribution,
                            'is_anomalous': False,
                            'method': 'baseline_unavailable',
                        })
                        continue
                    gate = self._fingerprint_peak_gate(
                        contribution,
                        measurements.get(fingerprint),
                        namespace_rates,
                    )
                    family_decisions.append({
                        'fingerprint': fingerprint,
                        'contribution': contribution,
                        **gate,
                    })
                    if gate['is_anomalous']:
                        qualified_contributors.append((fingerprint, contribution, gate))
                family_decisions.sort(
                    key=lambda decision: (
                        not decision.get('is_anomalous', False),
                        -decision['contribution'],
                        decision['fingerprint'],
                    )
                )
                audit_entry['family_decisions'] = family_decisions
                if qualified_contributors:
                    owner, owner_contribution, owner_gate = min(
                        qualified_contributors,
                        key=lambda item: (-item[2]['anomaly_score'], -item[1], item[0]),
                    )
                    candidate_fingerprints = {
                        item[0]: (item[1], item[2])
                        for item in qualified_contributors
                    }
                    audit_entry['owner_fingerprint'] = owner
                    audit_entry['verdict_reason'] = 'peak_diagnosed'
                    audit_entry['diagnosis_status'] = 'diagnosed'
                else:
                    audit_entry['suppressed_reason'] = (
                        'family_baseline_unavailable'
                        if not self.namespace_fingerprint_baseline_available
                        else 'no_anomalous_family'
                    )
                    audit_entry['verdict_reason'] = 'peak_undiagnosed'
                    owner = None
                    owner_contribution, owner_gate = None, {}
                    anchor = min(
                        bucket_contributors.items(),
                        key=lambda item: (-item[1], item[0]),
                    ) if bucket_contributors else None
                    candidate_fingerprints = {
                        anchor[0]: (anchor[1], {})
                    } if anchor else {}
                self.namespace_peak_audit.append(audit_entry)
                trigger_score = max(
                    namespace_total / check.get('p93_threshold', 1.0)
                    if check.get('p93_threshold') else 0.0,
                    namespace_total / check.get('cap_threshold', 1.0)
                    if check.get('cap_threshold') else 0.0,
                )
                candidate = {
                    **check,
                    'namespace': namespace,
                    'value': float(namespace_total),
                    'fingerprint_contribution': owner_contribution,
                    'contributing_fingerprints': len(bucket_contributors),
                    'fingerprint_threshold': owner_gate.get('threshold'),
                    'fingerprint_baseline': owner_gate.get('baseline'),
                    'fingerprint_anomaly_score': owner_gate.get('anomaly_score'),
                    'fingerprint_gate_method': owner_gate.get('method'),
                    'owner_fingerprint': owner,
                    'diagnosis_status': audit_entry['diagnosis_status'],
                    'anomalous_contributors': [
                        {
                            'fingerprint': fingerprint,
                            'contribution': contribution,
                            **gate,
                        }
                        for fingerprint, contribution, gate in qualified_contributors
                    ],
                    'peak_identifier': f"SPIKE:NS:{namespace}:{bucket.isoformat()}",
                    '_trigger_score': trigger_score,
                }
                for fingerprint, (contribution, gate) in candidate_fingerprints.items():
                    fingerprint_candidate = candidate.copy()
                    fingerprint_candidate.update({
                        'fingerprint_contribution': contribution,
                        'fingerprint_threshold': gate.get('threshold'),
                        'fingerprint_baseline': gate.get('baseline'),
                        'fingerprint_anomaly_score': gate.get('anomaly_score'),
                        'fingerprint_gate_method': gate.get('method'),
                    })
                    self._fingerprint_peak_results.setdefault(fingerprint, []).append(
                        fingerprint_candidate
                    )

        for candidates in self._fingerprint_peak_results.values():
            for candidate in candidates:
                candidate.pop('_trigger_score', None)

    def _fingerprint_peak_gate(
        self,
        contribution: int,
        measurement: Optional[MeasurementResult],
        namespace_rates: Optional[List[float]] = None,
    ) -> dict:
        if namespace_rates is not None:
            ordered_rates = sorted(namespace_rates)
            baseline_median = float(statistics.median(ordered_rates))
            baseline_mad = float(statistics.median(
                abs(rate - baseline_median) for rate in ordered_rates
            ))
            has_history = True
            method = 'namespace_fingerprint_median_mad'
        else:
            baseline_median = 0.0
            baseline_mad = 0.0
            has_history = False
            method = 'new_namespace_fingerprint_volume'

        if has_history:
            threshold = max(
                float(self.fingerprint_spike_min_count),
                baseline_median + (
                    self.fingerprint_spike_mad_multiplier * 1.4826 * baseline_mad
                ),
            )
            is_anomalous = contribution > threshold
        else:
            threshold = float(max(
                self.fingerprint_spike_min_count,
                self.new_error_min_count,
            ))
            method = 'new_fingerprint_volume'
            is_anomalous = contribution >= threshold

        return {
            'is_anomalous': is_anomalous,
            'threshold': threshold,
            'baseline': baseline_median,
            'anomaly_score': contribution / threshold if threshold > 0 else 0.0,
            'method': method,
        }
    
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
                        'current_version': self.latest_version(
                            getattr(rec, 'app_version', None) for rec in fp_records
                        ),
                    }

        window_minutes = int(os.getenv('WINDOW_MINUTES', '15'))
        fingerprint_namespace_windows = {}
        for fingerprint, fp_records in records_by_fp.items():
            namespace_windows: Dict[str, Dict[datetime, int]] = defaultdict(lambda: defaultdict(int))
            for record in fp_records:
                if not record.timestamp or not record.namespace:
                    continue
                minute = (record.timestamp.minute // window_minutes) * window_minutes
                bucket = record.timestamp.replace(minute=minute, second=0, microsecond=0)
                namespace_windows[record.namespace][bucket] += 1
            fingerprint_namespace_windows[fingerprint] = namespace_windows
        self.prepare_namespace_peak_results(fingerprint_namespace_windows, measurements)
        for audit_entry in self.namespace_peak_audit:
            for decision in audit_entry['family_decisions']:
                metadata = record_metadata.get(decision['fingerprint'], {})
                decision['error_type'] = str(metadata.get('error_type') or '')
                decision['normalized_message'] = str(
                    metadata.get('normalized_message') or ''
                )[:500]
                decision['apps'] = sorted(metadata.get('apps') or [])

        # ==================================================================
        # Per-fingerprint detection (O(fingerprints))
        # ==================================================================
        results = {}
        items = list(measurements.items())

        for fp, measurement in progress_iter(items, desc="Phase C: Detect", total=len(items)):
            fp_records = records_by_fp.get(fp, [])
            meta = record_metadata.get(fp, {})
            version = versions.get(fp) if versions else meta.get('current_version')

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
