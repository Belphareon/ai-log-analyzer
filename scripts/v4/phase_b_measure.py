#!/usr/bin/env python3
"""
FÁZE B: Measure
===============

Vstup: normalized records
Výstup: statistiky (baseline, current, trend)

✅ Počty
✅ Frekvence
✅ Sliding windows
✅ EWMA baseline
✅ MAD (Median Absolute Deviation)

❌ Žádné závěry
❌ Žádné flags
❌ Žádné rozhodování
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import statistics


@dataclass
class WindowStats:
    """Statistiky pro jedno časové okno"""
    window_start: datetime
    window_end: datetime
    count: int = 0
    
    # Per-fingerprint counts
    fingerprint_counts: Dict[str, int] = field(default_factory=dict)
    
    # Per-namespace counts
    namespace_counts: Dict[str, int] = field(default_factory=dict)
    
    # Per-app counts
    app_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class BaselineStats:
    """Baseline statistiky pro fingerprint"""
    fingerprint: str
    
    # EWMA baseline
    ewma_rate: float = 0.0           # Exponential Weighted Moving Average
    
    # MAD (Median Absolute Deviation) - robustnější než stddev
    median_rate: float = 0.0
    mad: float = 0.0
    
    # Simple stats (pro porovnání)
    mean_rate: float = 0.0
    stddev_rate: float = 0.0
    
    # Samples
    sample_count: int = 0
    historical_rates: List[float] = field(default_factory=list)


@dataclass
class MeasurementResult:
    """Výstup z FÁZE B pro jeden fingerprint"""
    fingerprint: str
    
    # Current window
    current_count: int = 0
    current_rate: float = 0.0        # count per window
    
    # Baseline
    baseline_ewma: float = 0.0
    baseline_mad: float = 0.0
    baseline_median: float = 0.0
    
    # Trend
    trend_ratio: float = 1.0         # current / baseline
    trend_direction: str = "stable"  # increasing, decreasing, stable
    
    # Distribution
    namespaces: List[str] = field(default_factory=list)
    namespace_count: int = 0
    apps: List[str] = field(default_factory=list)
    app_count: int = 0
    
    # Time
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    duration_sec: int = 0


class PhaseB_Measure:
    """
    FÁZE B: Measure
    
    Počítá statistiky bez rozhodování.
    Používá EWMA pro baseline a MAD místo stddev.
    
    EWMA = exponential weighted moving average
    MAD = median absolute deviation (robustnější vůči outliers)
    """
    
    def __init__(
        self,
        window_minutes: int = 15,
        ewma_alpha: float = 0.3,      # Váha nových hodnot (0.3 = 30% nová, 70% stará)
        baseline_windows: int = 20,    # Kolik oken pro baseline
    ):
        self.window_minutes = window_minutes
        self.ewma_alpha = ewma_alpha
        self.baseline_windows = baseline_windows
        
        # Historical data per fingerprint
        self.history: Dict[str, List[float]] = defaultdict(list)
        self.baselines: Dict[str, BaselineStats] = {}
    
    def _calculate_ewma(self, values: List[float], alpha: float = None) -> float:
        """
        Exponential Weighted Moving Average.
        
        EWMA_t = alpha * value_t + (1 - alpha) * EWMA_{t-1}
        
        Dává větší váhu novějším hodnotám.
        """
        if not values:
            return 0.0
        
        if alpha is None:
            alpha = self.ewma_alpha
        
        ewma = values[0]
        for value in values[1:]:
            ewma = alpha * value + (1 - alpha) * ewma
        
        return ewma
    
    def _calculate_mad(self, values: List[float]) -> Tuple[float, float]:
        """
        Median Absolute Deviation.
        
        MAD = median(|X_i - median(X)|)
        
        Robustnější než stddev - jeden outlier nezmění MAD.
        
        Returns: (median, mad)
        """
        if not values:
            return 0.0, 0.0
        
        if len(values) == 1:
            return values[0], 0.0
        
        median = statistics.median(values)
        deviations = [abs(v - median) for v in values]
        mad = statistics.median(deviations)
        
        return median, mad
    
    def _group_into_windows(
        self,
        records: List,  # List of NormalizedRecord
        window_start: datetime,
        window_count: int,
    ) -> List[WindowStats]:
        """
        Rozdělí záznamy do časových oken.
        """
        windows = []
        
        for i in range(window_count):
            w_start = window_start + timedelta(minutes=i * self.window_minutes)
            w_end = w_start + timedelta(minutes=self.window_minutes)
            
            ws = WindowStats(window_start=w_start, window_end=w_end)
            
            for record in records:
                if record.timestamp and w_start <= record.timestamp < w_end:
                    ws.count += 1
                    
                    # Fingerprint
                    fp = record.fingerprint
                    ws.fingerprint_counts[fp] = ws.fingerprint_counts.get(fp, 0) + 1
                    
                    # Namespace
                    ns = record.namespace
                    ws.namespace_counts[ns] = ws.namespace_counts.get(ns, 0) + 1
                    
                    # App
                    app = record.app_name
                    ws.app_counts[app] = ws.app_counts.get(app, 0) + 1
            
            windows.append(ws)
        
        return windows
    
    def update_baseline(self, fingerprint: str, rate: float):
        """
        Aktualizuje baseline pro fingerprint.
        
        Přidá novou hodnotu do historie a přepočítá EWMA/MAD.
        """
        self.history[fingerprint].append(rate)
        
        # Keep only last N windows
        if len(self.history[fingerprint]) > self.baseline_windows:
            self.history[fingerprint] = self.history[fingerprint][-self.baseline_windows:]
        
        values = self.history[fingerprint]
        
        # Calculate baseline stats
        baseline = BaselineStats(fingerprint=fingerprint)
        baseline.ewma_rate = self._calculate_ewma(values)
        baseline.median_rate, baseline.mad = self._calculate_mad(values)
        baseline.mean_rate = statistics.mean(values) if values else 0
        baseline.stddev_rate = statistics.stdev(values) if len(values) > 1 else 0
        baseline.sample_count = len(values)
        baseline.historical_rates = values.copy()
        
        self.baselines[fingerprint] = baseline
    
    def get_baseline(self, fingerprint: str) -> Optional[BaselineStats]:
        """Vrátí baseline pro fingerprint"""
        return self.baselines.get(fingerprint)
    
    def measure(
        self,
        records: List,  # List of NormalizedRecord
        current_window_start: datetime = None,
    ) -> Dict[str, MeasurementResult]:
        """
        Měří statistiky pro všechny fingerprints.
        
        Vstup: normalized records
        Výstup: Dict[fingerprint] -> MeasurementResult
        """
        if not records:
            return {}
        
        # Determine time range
        timestamps = [r.timestamp for r in records if r.timestamp]
        if not timestamps:
            return {}
        
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        
        if current_window_start is None:
            # Align to window boundary
            minute = min_ts.minute
            aligned_minute = (minute // self.window_minutes) * self.window_minutes
            current_window_start = min_ts.replace(minute=aligned_minute, second=0, microsecond=0)
        
        # Calculate number of windows
        total_minutes = int((max_ts - current_window_start).total_seconds() / 60) + self.window_minutes
        window_count = max(1, total_minutes // self.window_minutes)
        
        # Group into windows
        windows = self._group_into_windows(records, current_window_start, window_count)
        
        # Aggregate per fingerprint
        results = {}
        
        # Get unique fingerprints
        fingerprints = set(r.fingerprint for r in records)
        
        for fp in fingerprints:
            # Get records for this fingerprint
            fp_records = [r for r in records if r.fingerprint == fp]
            
            # Calculate rates per window
            rates = []
            for w in windows:
                rate = w.fingerprint_counts.get(fp, 0)
                rates.append(rate)
            
            # Current (last window)
            current_rate = rates[-1] if rates else 0
            current_count = sum(1 for r in fp_records 
                               if r.timestamp and windows[-1].window_start <= r.timestamp < windows[-1].window_end)
            
            # Update baseline with historical rates (excluding current)
            if len(rates) > 1:
                for rate in rates[:-1]:
                    self.update_baseline(fp, rate)
            
            # Get baseline
            baseline = self.get_baseline(fp)
            
            # Calculate trend
            if baseline and baseline.ewma_rate > 0:
                trend_ratio = current_rate / baseline.ewma_rate
            else:
                trend_ratio = 1.0
            
            # Trend direction (jen klasifikace, žádné rozhodnutí)
            if trend_ratio > 1.2:
                trend_direction = "increasing"
            elif trend_ratio < 0.8:
                trend_direction = "decreasing"
            else:
                trend_direction = "stable"
            
            # Distribution
            namespaces = list(set(r.namespace for r in fp_records))
            apps = list(set(r.app_name for r in fp_records))
            
            # Time range
            fp_timestamps = [r.timestamp for r in fp_records if r.timestamp]
            first_seen = min(fp_timestamps) if fp_timestamps else None
            last_seen = max(fp_timestamps) if fp_timestamps else None
            duration_sec = int((last_seen - first_seen).total_seconds()) if first_seen and last_seen else 0
            
            results[fp] = MeasurementResult(
                fingerprint=fp,
                current_count=current_count,
                current_rate=current_rate,
                baseline_ewma=baseline.ewma_rate if baseline else 0,
                baseline_mad=baseline.mad if baseline else 0,
                baseline_median=baseline.median_rate if baseline else 0,
                trend_ratio=trend_ratio,
                trend_direction=trend_direction,
                namespaces=namespaces,
                namespace_count=len(namespaces),
                apps=apps,
                app_count=len(apps),
                first_seen=first_seen,
                last_seen=last_seen,
                duration_sec=duration_sec,
            )
        
        return results
    
    def load_baseline_from_db(self, conn, fingerprints: List[str] = None):
        """
        Načte baseline z DB (pro produkci).
        
        Předpokládá tabulku s historickými rates.
        """
        # TODO: Implementovat podle DB schématu
        pass
    
    def save_baseline_to_db(self, conn):
        """
        Uloží baseline do DB.
        """
        # TODO: Implementovat podle DB schématu
        pass


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    from phase_a_parse import PhaseA_Parser, NormalizedRecord
    
    # Test data - simulace 5 oken
    parser = PhaseA_Parser()
    measurer = PhaseB_Measure(window_minutes=15)
    
    # Simulace: 5 oken, baseline ~10, current spike 50
    test_errors = []
    base_time = datetime(2026, 1, 20, 10, 0, 0)
    
    # Window 1-4: baseline (~10 errors each)
    for window_idx in range(4):
        for i in range(10 + window_idx):  # 10, 11, 12, 13
            test_errors.append({
                "timestamp": (base_time + timedelta(minutes=window_idx * 15 + i)).isoformat() + "Z",
                "namespace": "pcb-sit-01-app",
                "application": "bl-pcb-v1",
                "message": "Connection to 192.168.1.100:5432 refused",
                "trace_id": f"trace-{window_idx}-{i}"
            })
    
    # Window 5: spike (50 errors)
    for i in range(50):
        test_errors.append({
            "timestamp": (base_time + timedelta(minutes=4 * 15 + i % 15)).isoformat() + "Z",
            "namespace": "pcb-sit-01-app" if i < 40 else "pcb-dev-01-app",  # Cross-namespace
            "application": "bl-pcb-v1",
            "message": "Connection to 192.168.1.100:5432 refused",
            "trace_id": f"trace-4-{i}"
        })
    
    # Parse
    records = parser.parse_batch(test_errors)
    print(f"Parsed {len(records)} records")
    
    # Measure
    results = measurer.measure(records, base_time)
    
    print("\n=== FÁZE B: Measure ===\n")
    
    for fp, result in results.items():
        print(f"Fingerprint: {fp}")
        print(f"  Current rate: {result.current_rate}")
        print(f"  Baseline EWMA: {result.baseline_ewma:.2f}")
        print(f"  Baseline MAD: {result.baseline_mad:.2f}")
        print(f"  Trend ratio: {result.trend_ratio:.2f}")
        print(f"  Trend direction: {result.trend_direction}")
        print(f"  Namespaces: {result.namespaces} ({result.namespace_count})")
        print()
