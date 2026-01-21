#!/usr/bin/env python3
"""
FÁZE D: Score
=============

Vstup: detection results (flags + evidence)
Výstup: numeric score (0-100)

✅ Deterministická váhová funkce
✅ Každý flag má váhu
✅ Transparentní breakdown
✅ Žádné if/else v logice

Score = base_score + sum(flag_bonuses)
"""

from typing import Dict, Optional
from dataclasses import dataclass, field

# Import from same package
try:
    from .phase_c_detect import DetectionResult
    from .phase_b_measure import MeasurementResult
    from .incident import ScoreBreakdown
except ImportError:
    from phase_c_detect import DetectionResult
    from phase_b_measure import MeasurementResult
    from incident import ScoreBreakdown


@dataclass
class ScoreWeights:
    """
    Váhy pro výpočet skóre.
    
    Všechny váhy jsou explicitní - žádná magie.
    """
    # Base score calculation
    base_multiplier: float = 10.0       # Základ = count / multiplier (capped at 30)
    base_max: float = 30.0
    
    # Flag bonuses
    spike_weight: float = 25.0          # Spike = +25
    burst_weight: float = 20.0          # Burst = +20
    new_weight: float = 15.0            # New = +15
    regression_weight: float = 35.0     # Regression = +35 (velmi důležité!)
    cascade_weight: float = 20.0        # Cascade = +20
    cross_ns_weight: float = 15.0       # Cross-namespace = +15
    
    # Scaling bonuses (based on magnitude)
    trend_ratio_weight: float = 2.0     # Per 1.0 ratio above 2.0
    namespace_count_weight: float = 3.0 # Per namespace above 2
    
    # Cap
    max_score: float = 100.0


@dataclass
class ScoreResult:
    """Výstup z FÁZE D"""
    fingerprint: str
    score: float
    breakdown: ScoreBreakdown


class PhaseD_Score:
    """
    FÁZE D: Score
    
    Deterministická váhová funkce.
    
    Score = base + spike_bonus + burst_bonus + new_bonus + ...
    
    Pravidla:
    - Žádné if/else v hlavní logice
    - Váhy jsou explicitní parametry
    - Breakdown je vždy transparentní
    """
    
    def __init__(self, weights: ScoreWeights = None):
        self.weights = weights or ScoreWeights()
    
    def _calculate_base_score(
        self,
        measurement: MeasurementResult,
    ) -> float:
        """
        Základní skóre z počtu errorů.
        
        base = min(max_base, count / multiplier)
        """
        count = measurement.current_count
        score = min(
            self.weights.base_max,
            count / self.weights.base_multiplier
        )
        return score
    
    def _calculate_flag_bonuses(
        self,
        detection: DetectionResult,
        measurement: MeasurementResult,
    ) -> ScoreBreakdown:
        """
        Bonusy za detekované flags.
        
        Používá násobení místo if/else:
        bonus = flag * weight
        """
        breakdown = ScoreBreakdown()
        
        # Base score
        breakdown.base_score = self._calculate_base_score(measurement)
        
        # Flag bonuses (bool * weight = weight if True, 0 if False)
        breakdown.spike_bonus = int(detection.flags.is_spike) * self.weights.spike_weight
        breakdown.burst_bonus = int(detection.flags.is_burst) * self.weights.burst_weight
        breakdown.new_bonus = int(detection.flags.is_new) * self.weights.new_weight
        breakdown.regression_bonus = int(detection.flags.is_regression) * self.weights.regression_weight
        breakdown.cascade_bonus = int(detection.flags.is_cascade) * self.weights.cascade_weight
        breakdown.cross_ns_bonus = int(detection.flags.is_cross_namespace) * self.weights.cross_ns_weight
        
        # Scaling bonuses (based on magnitude)
        # Trend ratio bonus: extra points for extreme spikes
        if measurement.trend_ratio > 2.0:
            extra_ratio = min(5.0, measurement.trend_ratio - 2.0)  # Cap at 5.0 extra
            breakdown.spike_bonus += extra_ratio * self.weights.trend_ratio_weight
        
        # Namespace count bonus: extra points for widespread issues
        if measurement.namespace_count > 2:
            extra_ns = min(5, measurement.namespace_count - 2)  # Cap at 5 extra
            breakdown.cross_ns_bonus += extra_ns * self.weights.namespace_count_weight
        
        return breakdown
    
    def score(
        self,
        detection: DetectionResult,
        measurement: MeasurementResult,
    ) -> ScoreResult:
        """
        Počítá skóre pro jeden fingerprint.
        
        Vstup: DetectionResult + MeasurementResult
        Výstup: ScoreResult
        """
        breakdown = self._calculate_flag_bonuses(detection, measurement)
        
        # Total score (capped at max)
        total = min(self.weights.max_score, breakdown.total)
        
        return ScoreResult(
            fingerprint=detection.fingerprint,
            score=total,
            breakdown=breakdown,
        )
    
    def score_batch(
        self,
        detections: Dict[str, DetectionResult],
        measurements: Dict[str, MeasurementResult],
    ) -> Dict[str, ScoreResult]:
        """
        Počítá skóre pro batch.
        """
        results = {}
        
        for fp, detection in detections.items():
            if fp in measurements:
                results[fp] = self.score(detection, measurements[fp])
        
        return results


# ============================================================================
# SEVERITY MAPPING
# ============================================================================

def score_to_severity(score: float) -> str:
    """
    Mapuje skóre na severity.
    
    Toto je jediné místo s if/else - a je to explicitní mapping.
    """
    if score >= 80:
        return "critical"
    elif score >= 60:
        return "high"
    elif score >= 40:
        return "medium"
    elif score >= 20:
        return "low"
    else:
        return "info"


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    from phase_b_measure import MeasurementResult
    from phase_c_detect import DetectionResult
    from incident import Flags
    
    # Test measurement
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
    
    # Test detection
    detection = DetectionResult(
        fingerprint="abc123",
        flags=Flags(
            is_new=True,
            is_spike=True,
            is_burst=False,
            is_cross_namespace=True,
            is_regression=False,
        )
    )
    
    # Score
    scorer = PhaseD_Score()
    result = scorer.score(detection, measurement)
    
    print("=== FÁZE D: Score ===\n")
    
    print(f"Fingerprint: {result.fingerprint}")
    print(f"\nBreakdown:")
    print(f"  Base score: {result.breakdown.base_score:.1f}")
    print(f"  Spike bonus: {result.breakdown.spike_bonus:.1f}")
    print(f"  Burst bonus: {result.breakdown.burst_bonus:.1f}")
    print(f"  New bonus: {result.breakdown.new_bonus:.1f}")
    print(f"  Regression bonus: {result.breakdown.regression_bonus:.1f}")
    print(f"  Cascade bonus: {result.breakdown.cascade_bonus:.1f}")
    print(f"  Cross-NS bonus: {result.breakdown.cross_ns_bonus:.1f}")
    print(f"\nTotal score: {result.score:.1f}")
    print(f"Severity: {score_to_severity(result.score)}")
