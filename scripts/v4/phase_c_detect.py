#!/usr/bin/env python3
"""
FÁZE C: Detect
==============

Vstup: measurement results
Výstup: boolean flags + evidence

✅ Spike detection
✅ New fingerprint detection
✅ Burst detection
✅ Silence detection
✅ Cross-namespace detection
✅ Evidence pro každý flag

❌ Žádná interpretace
❌ Žádné skóre
❌ Žádná severity
"""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

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
    
    # Boolean flags
    flags: Flags = field(default_factory=Flags)
    
    # Evidence - důvod pro každý flag
    evidence: List[Evidence] = field(default_factory=list)
    
    def add_evidence(self, rule: str, **kwargs):
        self.evidence.append(Evidence(rule=rule, **kwargs))


class PhaseC_Detect:
    """
    FÁZE C: Detect
    
    Aplikuje detekční pravidla a generuje boolean flags.
    Každý flag má přiložený evidence log s důvodem.
    
    Pravidla:
    - Deterministická (žádné ML)
    - Každý flag má threshold
    - Každý flag má evidence
    """
    
    def __init__(
        self,
        # Spike detection
        spike_threshold: float = 3.0,      # current > baseline * threshold
        spike_mad_threshold: float = 3.0,  # current > median + MAD * threshold
        
        # Burst detection (náhlý nárůst v krátkém čase)
        burst_threshold: float = 5.0,      # rate change > threshold
        burst_window_sec: int = 60,        # Časové okno pro burst
        
        # Cross-namespace threshold
        cross_ns_threshold: int = 2,       # Minimálně N namespaces
        
        # Known fingerprints (pro new detection)
        known_fingerprints: Set[str] = None,
        
        # Known fixed versions (pro regression detection)
        known_fixes: Dict[str, str] = None,  # fingerprint -> fixed_in_version
    ):
        self.spike_threshold = spike_threshold
        self.spike_mad_threshold = spike_mad_threshold
        self.burst_threshold = burst_threshold
        self.burst_window_sec = burst_window_sec
        self.cross_ns_threshold = cross_ns_threshold
        
        self.known_fingerprints = known_fingerprints or set()
        self.known_fixes = known_fixes or {}
    
    def _detect_spike(
        self,
        measurement: MeasurementResult,
        result: DetectionResult
    ) -> bool:
        """
        Detekuje spike: current > baseline * threshold
        
        Používá dva testy:
        1. EWMA: current > ewma * spike_threshold
        2. MAD: current > median + MAD * spike_mad_threshold
        
        Spike = alespoň jeden z testů projde
        """
        current = measurement.current_rate
        ewma = measurement.baseline_ewma
        median = measurement.baseline_median
        mad = measurement.baseline_mad
        
        # Test 1: EWMA threshold
        ewma_triggered = False
        if ewma > 0 and current > ewma * self.spike_threshold:
            ewma_triggered = True
            result.add_evidence(
                rule="spike_ewma",
                baseline=ewma,
                current=current,
                threshold=self.spike_threshold,
                message=f"current ({current}) > ewma ({ewma:.2f}) * {self.spike_threshold}"
            )
        
        # Test 2: MAD threshold (robustnější)
        mad_triggered = False
        mad_limit = median + mad * self.spike_mad_threshold
        if mad > 0 and current > mad_limit:
            mad_triggered = True
            result.add_evidence(
                rule="spike_mad",
                baseline=median,
                current=current,
                threshold=mad_limit,
                message=f"current ({current}) > median ({median:.2f}) + MAD ({mad:.2f}) * {self.spike_mad_threshold}"
            )
        
        # Spike pokud alespoň jeden test prošel
        is_spike = ewma_triggered or mad_triggered
        result.flags.is_spike = is_spike
        
        return is_spike
    
    def _detect_burst(
        self,
        measurement: MeasurementResult,
        records: List,  # NormalizedRecord
        result: DetectionResult
    ) -> bool:
        """
        Detekuje burst: náhlý nárůst v krátkém čase.
        
        Burst = rate_change > burst_threshold během burst_window_sec
        """
        # Get records for this fingerprint
        fp_records = [r for r in records if r.fingerprint == measurement.fingerprint]
        
        if len(fp_records) < 2:
            return False
        
        # Sort by timestamp
        sorted_records = sorted(
            [r for r in fp_records if r.timestamp],
            key=lambda r: r.timestamp
        )
        
        if len(sorted_records) < 2:
            return False
        
        # Check for burst in any window
        window = timedelta(seconds=self.burst_window_sec)
        
        for i in range(len(sorted_records)):
            start_time = sorted_records[i].timestamp
            end_time = start_time + window
            
            # Count in window
            count_in_window = sum(
                1 for r in sorted_records
                if r.timestamp and start_time <= r.timestamp < end_time
            )
            
            # Calculate rate per minute
            rate_per_min = count_in_window / (self.burst_window_sec / 60)
            
            # Compare to baseline
            if measurement.baseline_ewma > 0:
                rate_change = rate_per_min / measurement.baseline_ewma
                
                if rate_change > self.burst_threshold:
                    result.flags.is_burst = True
                    result.add_evidence(
                        rule="burst",
                        baseline=measurement.baseline_ewma,
                        current=rate_per_min,
                        threshold=self.burst_threshold,
                        message=f"rate_change ({rate_change:.2f}) > {self.burst_threshold} in {self.burst_window_sec}s window",
                        timestamp=start_time
                    )
                    return True
        
        return False
    
    def _detect_new(
        self,
        measurement: MeasurementResult,
        result: DetectionResult
    ) -> bool:
        """
        Detekuje nový fingerprint: nikdy předtím neviděný.
        """
        fp = measurement.fingerprint
        
        if fp not in self.known_fingerprints:
            result.flags.is_new = True
            result.add_evidence(
                rule="new_fingerprint",
                message=f"fingerprint {fp} not in known set ({len(self.known_fingerprints)} known)"
            )
            return True
        
        return False
    
    def _detect_regression(
        self,
        measurement: MeasurementResult,
        current_version: str,
        result: DetectionResult
    ) -> bool:
        """
        Detekuje regresi: bug který měl být opravený se vrátil.
        
        Regression = fingerprint má fixed_in_version a current_version >= fixed_in_version
        """
        fp = measurement.fingerprint
        
        if fp not in self.known_fixes:
            return False
        
        fixed_version = self.known_fixes[fp]
        
        # Simple version comparison
        if self._version_gte(current_version, fixed_version):
            result.flags.is_regression = True
            result.add_evidence(
                rule="regression",
                message=f"fingerprint {fp} was fixed in {fixed_version}, but appeared in {current_version}"
            )
            return True
        
        return False
    
    def _version_gte(self, v1: str, v2: str) -> bool:
        """Check if v1 >= v2"""
        import re
        
        def parse_version(v):
            nums = re.findall(r'\d+', v)
            return [int(n) for n in nums] if nums else [0]
        
        try:
            return parse_version(v1) >= parse_version(v2)
        except:
            return False
    
    def _detect_cross_namespace(
        self,
        measurement: MeasurementResult,
        result: DetectionResult
    ) -> bool:
        """
        Detekuje cross-namespace pattern: stejný error ve více namespaces.
        """
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
    
    def _detect_silence(
        self,
        measurement: MeasurementResult,
        result: DetectionResult
    ) -> bool:
        """
        Detekuje silence: neočekávaná absence errorů.
        
        Silence = current == 0 AND baseline > threshold
        """
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
    
    def detect(
        self,
        measurement: MeasurementResult,
        records: List = None,
        current_version: str = None,
    ) -> DetectionResult:
        """
        Aplikuje všechna detekční pravidla na jeden fingerprint.
        
        Vstup: MeasurementResult
        Výstup: DetectionResult s flags a evidence
        """
        result = DetectionResult(fingerprint=measurement.fingerprint)
        
        # Run all detectors
        self._detect_spike(measurement, result)
        self._detect_new(measurement, result)
        self._detect_cross_namespace(measurement, result)
        self._detect_silence(measurement, result)
        
        if records:
            self._detect_burst(measurement, records, result)
        
        if current_version:
            self._detect_regression(measurement, current_version, result)
        
        return result
    
    def detect_batch(
        self,
        measurements: Dict[str, MeasurementResult],
        records: List = None,
        versions: Dict[str, str] = None,  # fingerprint -> version
    ) -> Dict[str, DetectionResult]:
        """
        Aplikuje detekci na batch measurementů.
        """
        results = {}
        
        for fp, measurement in measurements.items():
            version = versions.get(fp) if versions else None
            results[fp] = self.detect(measurement, records, version)
        
        return results
    
    def add_known_fingerprint(self, fingerprint: str):
        """Přidá fingerprint do known setu"""
        self.known_fingerprints.add(fingerprint)
    
    def add_known_fix(self, fingerprint: str, fixed_in_version: str):
        """Přidá známý fix"""
        self.known_fixes[fingerprint] = fixed_in_version
    
    def load_known_from_db(self, conn):
        """
        Načte known fingerprints a fixes z DB.
        """
        cursor = conn.cursor()
        
        # Load known signatures
        cursor.execute("SELECT signature_hash FROM ailog_peak.error_signatures")
        self.known_fingerprints = {row[0] for row in cursor.fetchall()}
        
        # Load known fixes
        cursor.execute("""
            SELECT issue_id, fixed_in_version 
            FROM ailog_peak.known_issues 
            WHERE fixed_in_version IS NOT NULL
        """)
        self.known_fixes = {row[0]: row[1] for row in cursor.fetchall()}


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    from phase_a_parse import PhaseA_Parser
    from phase_b_measure import PhaseB_Measure, MeasurementResult
    
    # Create test measurement
    measurement = MeasurementResult(
        fingerprint="abc123",
        current_count=50,
        current_rate=50,
        baseline_ewma=10,
        baseline_mad=2,
        baseline_median=10,
        trend_ratio=5.0,
        trend_direction="increasing",
        namespaces=["pcb-sit-01-app", "pcb-dev-01-app", "pcb-uat-01-app"],
        namespace_count=3,
        apps=["bl-pcb-v1"],
        app_count=1,
    )
    
    # Create detector
    detector = PhaseC_Detect(
        spike_threshold=3.0,
        cross_ns_threshold=2,
        known_fingerprints=set(),  # Empty = all are new
    )
    
    # Detect
    result = detector.detect(measurement)
    
    print("=== FÁZE C: Detect ===\n")
    
    print(f"Fingerprint: {result.fingerprint}")
    print(f"\nFlags:")
    print(f"  is_new: {result.flags.is_new}")
    print(f"  is_spike: {result.flags.is_spike}")
    print(f"  is_burst: {result.flags.is_burst}")
    print(f"  is_cross_namespace: {result.flags.is_cross_namespace}")
    print(f"  is_silence: {result.flags.is_silence}")
    print(f"  is_regression: {result.flags.is_regression}")
    
    print(f"\nEvidence ({len(result.evidence)} items):")
    for ev in result.evidence:
        print(f"  [{ev.rule}] {ev.message}")
        if ev.baseline is not None:
            print(f"    baseline={ev.baseline}, current={ev.current}, threshold={ev.threshold}")
