#!/usr/bin/env python3
"""
FÁZE C: Detect (OPTIMALIZOVANÁ VERZE)
=====================================

OPRAVA: Předgrupování records v detect_batch místo filtrování v každém volání.
Složitost: O(n) místo O(n × fingerprints)
"""

from typing import Dict, List, Set, Optional
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


@dataclass
class DetectionResult:
    """Výstup z FÁZE C pro jeden fingerprint"""
    fingerprint: str
    flags: Flags = field(default_factory=Flags)
    evidence: List[Evidence] = field(default_factory=list)
    
    def add_evidence(self, rule: str, **kwargs):
        self.evidence.append(Evidence(rule=rule, **kwargs))


class PhaseC_Detect:
    """
    FÁZE C: Detect (OPTIMALIZOVANÁ)
    
    Klíčová optimalizace: records se předgrupují JEDNOU v detect_batch,
    ne pro každý fingerprint zvlášť.
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
    ):
        self.spike_threshold = spike_threshold
        self.spike_mad_threshold = spike_mad_threshold
        self.burst_threshold = burst_threshold
        self.burst_window_sec = burst_window_sec
        self.cross_ns_threshold = cross_ns_threshold
        self.known_fingerprints = known_fingerprints or set()
        self.known_fixes = known_fixes or {}
    
    def _detect_spike(self, measurement: MeasurementResult, result: DetectionResult) -> bool:
        """Detekuje spike: current > baseline * threshold"""
        # EWMA test
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
                return True
        
        # MAD test
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
                return True
        
        return False
    
    def _detect_burst(
        self,
        measurement: MeasurementResult,
        fp_records: List,  # PŘEDFILTROVANÉ records pro tento fingerprint
        result: DetectionResult
    ) -> bool:
        """Detekuje burst - přijímá UŽ FILTROVANÉ records"""
        if len(fp_records) < 2:
            return False
        
        # Sort by timestamp
        sorted_records = sorted(
            [r for r in fp_records if r.timestamp],
            key=lambda r: r.timestamp
        )
        
        if len(sorted_records) < 2:
            return False
        
        # Optimalizace: použij sliding window s O(n) complexity
        window = timedelta(seconds=self.burst_window_sec)
        window_start_idx = 0
        
        for i, record in enumerate(sorted_records):
            # Move window start forward
            while (window_start_idx < i and 
                   sorted_records[window_start_idx].timestamp < record.timestamp - window):
                window_start_idx += 1
            
            # Count in window = i - window_start_idx + 1
            count_in_window = i - window_start_idx + 1
            
            if count_in_window < 3:  # Minimum pro burst
                continue
            
            # Calculate rate
            rate_per_min = count_in_window / (self.burst_window_sec / 60)
            
            if measurement.baseline_ewma > 0:
                rate_change = rate_per_min / measurement.baseline_ewma
                
                if rate_change > self.burst_threshold:
                    result.flags.is_burst = True
                    result.add_evidence(
                        rule="burst",
                        baseline=measurement.baseline_ewma,
                        current=rate_per_min,
                        threshold=self.burst_threshold,
                        message=f"rate_change ({rate_change:.2f}) > {self.burst_threshold}",
                        timestamp=record.timestamp
                    )
                    return True
        
        return False
    
    def _detect_new(self, measurement: MeasurementResult, result: DetectionResult) -> bool:
        """Detekuje nový fingerprint"""
        fp = measurement.fingerprint
        
        if fp not in self.known_fingerprints:
            result.flags.is_new = True
            result.add_evidence(
                rule="new_fingerprint",
                message=f"fingerprint {fp} not seen before"
            )
            self.known_fingerprints.add(fp)
            return True
        
        return False
    
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
    ) -> DetectionResult:
        """Aplikuje všechna detekční pravidla"""
        result = DetectionResult(fingerprint=measurement.fingerprint)
        
        self._detect_spike(measurement, result)
        self._detect_new(measurement, result)
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
    ) -> Dict[str, DetectionResult]:
        """
        OPTIMALIZOVANÁ verze - předgrupuje records JEDNOU.
        """
        # Předgrupuj records (O(n))
        records_by_fp: Dict[str, List] = defaultdict(list)
        if records:
            for r in records:
                records_by_fp[r.fingerprint].append(r)
        
        # Detekce (O(fingerprints))
        results = {}
        items = list(measurements.items())
        for fp, measurement in progress_iter(items, desc="Phase C: Detect", total=len(items)):
            fp_records = records_by_fp.get(fp, [])
            version = versions.get(fp) if versions else None
            results[fp] = self.detect(measurement, fp_records, version)
        
        return results
    
    def add_known_fingerprint(self, fingerprint: str):
        self.known_fingerprints.add(fingerprint)
    
    def add_known_fix(self, fingerprint: str, fixed_in_version: str):
        self.known_fixes[fingerprint] = fixed_in_version
    
    def load_known_from_db(self, conn):
        cursor = conn.cursor()
        cursor.execute("SELECT signature_hash FROM ailog_peak.error_signatures")
        self.known_fingerprints = {row[0] for row in cursor.fetchall()}
        cursor.execute("""
            SELECT issue_id, fixed_in_version 
            FROM ailog_peak.known_issues 
            WHERE fixed_in_version IS NOT NULL
        """)
        self.known_fixes = {row[0]: row[1] for row in cursor.fetchall()}


if __name__ == "__main__":
    print("Phase C: Detect - optimized version")
