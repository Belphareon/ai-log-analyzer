#!/usr/bin/env python3
"""
FÁZE B: Measure (OPTIMALIZOVANÁ VERZE)
======================================

Vstup: normalized records
Výstup: statistiky (baseline, current, trend)

OPTIMALIZACE:
- Předgrupování records podle fingerprint a window (O(n))
- Žádné opakované průchody přes všechny records

Složitost: O(n) místo O(n²)
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import statistics
import sys

# Progress bar - tqdm if available, else simple fallback
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

def progress_iter(iterable, desc="Processing", total=None, disable=False):
    """Progress wrapper - uses tqdm if available"""
    if disable:
        return iterable
    
    if HAS_TQDM:
        return tqdm(iterable, desc=desc, total=total, file=sys.stderr, 
                    ncols=80, leave=False, mininterval=0.5)
    else:
        # Simple fallback - print every 10%
        if total is None:
            total = len(iterable) if hasattr(iterable, '__len__') else None
        
        if total and total > 100:
            checkpoint = max(1, total // 10)
            for i, item in enumerate(iterable):
                if i % checkpoint == 0:
                    pct = (i / total) * 100
                    print(f" {desc}: {pct:.0f}% ({i:,}/{total:,})", file=sys.stderr, flush=True)
                yield item
        else:
            yield from iterable
import sys

# Progress bar - tqdm nebo fallback
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

def progress_iter(iterable, desc="Processing", total=None):
    """Progress iterator - uses tqdm if available, else simple counter"""
    if HAS_TQDM:
        return tqdm(iterable, desc=desc, total=total, file=sys.stderr)
    else:
        # Simple fallback
        if total is None:
            try:
                total = len(iterable)
            except:
                total = None
        
        count = 0
        last_pct = -1
        for item in iterable:
            count += 1
            if total:
                pct = (count * 100) // total
                if pct >= last_pct + 10: # Print every 10%
                    print(f" {desc}: {pct}% ({count:,}/{total:,})", file=sys.stderr, flush=True)
                    last_pct = pct
            yield item
        
        if total and last_pct < 100:
            print(f" {desc}: 100% ({count:,}/{total:,})", file=sys.stderr, flush=True)


@dataclass
class MeasurementResult:
    """Výstup z FÁZE B pro jeden fingerprint"""
    fingerprint: str
    
    # Current window
    current_count: int = 0
    current_rate: float = 0.0
    
    # Baseline
    baseline_ewma: float = 0.0
    baseline_mad: float = 0.0
    baseline_median: float = 0.0
    
    # Trend
    trend_ratio: float = 1.0
    trend_direction: str = "stable"
    
    # Distribution
    namespaces: List[str] = field(default_factory=list)
    namespace_count: int = 0
    apps: List[str] = field(default_factory=list)
    app_count: int = 0
    
    # Time
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    duration_sec: int = 0


@dataclass
class BaselineStats:
    """Baseline statistiky pro fingerprint"""
    fingerprint: str
    ewma_rate: float = 0.0
    median_rate: float = 0.0
    mad: float = 0.0
    mean_rate: float = 0.0
    stddev_rate: float = 0.0
    sample_count: int = 0
    historical_rates: List[float] = field(default_factory=list)


class PhaseB_Measure:
    """
    FÁZE B: Measure (OPTIMALIZOVANÁ)
    
    Složitost: O(n) - jeden průchod pro groupování, pak O(fingerprints)
    """
    
    def __init__(
        self,
        window_minutes: int = 15,
        ewma_alpha: float = 0.3,
        baseline_windows: int = 20,
        historical_baseline: Dict[str, List[float]] = None,
    ):
        self.window_minutes = window_minutes
        self.ewma_alpha = ewma_alpha
        self.baseline_windows = baseline_windows
        self.historical_baseline = historical_baseline or {}  # ← Historické baseline z DB
        
        self.history: Dict[str, List[float]] = defaultdict(list)
        self.baselines: Dict[str, BaselineStats] = {}
    
    def _get_window_key(self, ts: datetime, base: datetime) -> int:
        """Vrátí index okna pro timestamp"""
        delta_minutes = int((ts - base).total_seconds() / 60)
        return delta_minutes // self.window_minutes
    
    def _calculate_ewma(self, values: List[float]) -> float:
        """EWMA - O(n)"""
        if not values:
            return 0.0
        
        ewma = values[0]
        for value in values[1:]:
            ewma = self.ewma_alpha * value + (1 - self.ewma_alpha) * ewma
        return ewma
    
    def _calculate_mad(self, values: List[float]) -> Tuple[float, float]:
        """MAD - O(n log n) kvůli medianu"""
        if not values:
            return 0.0, 0.0
        if len(values) == 1:
            return values[0], 0.0
        
        median = statistics.median(values)
        deviations = [abs(v - median) for v in values]
        mad = statistics.median(deviations)
        return median, mad
    
    def update_baseline(self, fingerprint: str, rate: float):
        """Aktualizuje baseline"""
        self.history[fingerprint].append(rate)
        
        if len(self.history[fingerprint]) > self.baseline_windows:
            self.history[fingerprint] = self.history[fingerprint][-self.baseline_windows:]
        
        values = self.history[fingerprint]
        
        baseline = BaselineStats(fingerprint=fingerprint)
        baseline.ewma_rate = self._calculate_ewma(values)
        baseline.median_rate, baseline.mad = self._calculate_mad(values)
        baseline.mean_rate = statistics.mean(values) if values else 0
        baseline.stddev_rate = statistics.stdev(values) if len(values) > 1 else 0
        baseline.sample_count = len(values)
        baseline.historical_rates = values.copy()
        
        self.baselines[fingerprint] = baseline
    
    def get_baseline(self, fingerprint: str) -> Optional[BaselineStats]:
        return self.baselines.get(fingerprint)
    
    def measure(
        self,
        records: List,
        current_window_start: datetime = None,
    ) -> Dict[str, MeasurementResult]:
        """
        OPTIMALIZOVANÁ verze - O(n) místo O(n²)
        
        1. Jeden průchod: grupuj records podle (fingerprint, window_idx)
        2. Pro každý fingerprint: spočítej statistiky z předgrupovaných dat
        """
        if not records:
            return {}
        
        # ============================================================
        # KROK 1: Najdi časový rozsah (O(n))
        # ============================================================
        min_ts = None
        max_ts = None
        
        for r in records:
            if r.timestamp:
                if min_ts is None or r.timestamp < min_ts:
                    min_ts = r.timestamp
                if max_ts is None or r.timestamp > max_ts:
                    max_ts = r.timestamp
        
        if not min_ts:
            return {}
        
        # Align to window boundary
        if current_window_start is None:
            minute = min_ts.minute
            aligned_minute = (minute // self.window_minutes) * self.window_minutes
            current_window_start = min_ts.replace(minute=aligned_minute, second=0, microsecond=0)
        
        # ============================================================
        # KROK 2: Jeden průchod - grupuj vše najednou (O(n))
        # ============================================================
        # fp_window_counts[fingerprint][window_idx] = count
        fp_window_counts: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        
        # fp_namespaces[fingerprint] = set of namespaces
        fp_namespaces: Dict[str, set] = defaultdict(set)
        
        # fp_apps[fingerprint] = set of apps
        fp_apps: Dict[str, set] = defaultdict(set)
        
        # fp_timestamps[fingerprint] = (min_ts, max_ts)
        fp_first_seen: Dict[str, datetime] = {}
        fp_last_seen: Dict[str, datetime] = {}
        
        max_window_idx = 0
        
        for r in progress_iter(records, desc="Phase B: Grouping", total=len(records)):
            if not r.timestamp:
                continue
            
            fp = r.fingerprint
            window_idx = self._get_window_key(r.timestamp, current_window_start)
            
            # Count per window
            fp_window_counts[fp][window_idx] += 1
            
            # Track max window
            if window_idx > max_window_idx:
                max_window_idx = window_idx
            
            # Namespaces & Apps
            fp_namespaces[fp].add(r.namespace)
            fp_apps[fp].add(r.app_name)
            
            # Time range
            if fp not in fp_first_seen or r.timestamp < fp_first_seen[fp]:
                fp_first_seen[fp] = r.timestamp
            if fp not in fp_last_seen or r.timestamp > fp_last_seen[fp]:
                fp_last_seen[fp] = r.timestamp
        
        # ============================================================
        # KROK 3: Pro každý fingerprint spočítej výsledek (O(fingerprints * windows))
        # ============================================================
        results = {}
        
        fp_items = list(fp_window_counts.items())
        for fp, window_counts in progress_iter(fp_items, desc="Phase B: Stats", total=len(fp_items)):
            # Build rates array (sparse -> dense)
            rates = []
            for w_idx in range(max_window_idx + 1):
                rates.append(window_counts.get(w_idx, 0))
            
            # Current = last window
            current_rate = rates[-1] if rates else 0
            current_count = window_counts.get(max_window_idx, 0)
            
            # Calculate baseline ONCE from historical rates (exclude current)
            current_window_historical = rates[:-1] if len(rates) > 1 else []
            
            # ← NOVÉ: Kombinuj s DB historical baseline
            historical_rates = current_window_historical
            if fp in self.historical_baseline:
                # Přidej DB historii před aktuální okno
                historical_rates = self.historical_baseline[fp] + historical_rates
            
            if historical_rates:
                ewma_rate = self._calculate_ewma(historical_rates)
                median_rate, mad = self._calculate_mad(historical_rates)
                baseline = BaselineStats(
                    fingerprint=fp,
                    ewma_rate=ewma_rate,
                    median_rate=median_rate,
                    mad=mad,
                    mean_rate=sum(historical_rates) / len(historical_rates),
                    sample_count=len(historical_rates)
                )
            else:
                baseline = None
            
            # Trend
            if baseline and baseline.ewma_rate > 0:
                trend_ratio = current_rate / baseline.ewma_rate
            else:
                trend_ratio = 1.0
            
            if trend_ratio > 1.2:
                trend_direction = "increasing"
            elif trend_ratio < 0.8:
                trend_direction = "decreasing"
            else:
                trend_direction = "stable"
            
            # Time
            first_seen = fp_first_seen.get(fp)
            last_seen = fp_last_seen.get(fp)
            duration_sec = int((last_seen - first_seen).total_seconds()) if first_seen and last_seen else 0
            
            # Result
            namespaces = list(fp_namespaces[fp])
            apps = list(fp_apps[fp])
            
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
        """Načte baseline z DB"""
        pass
    
    def save_baseline_to_db(self, conn):
        """Uloží baseline do DB"""
        pass


# ============================================================================
# CLI TEST
# ============================================================================

if __name__ == "__main__":
    import time
    from phase_a_parse import PhaseA_Parser
    
    parser = PhaseA_Parser()
    measurer = PhaseB_Measure(window_minutes=15)
    
    # Generate test data
    print("Generating test data...")
    test_errors = []
    base_time = datetime(2026, 1, 20, 0, 0, 0)
    
    # Simulate 100k records across 24h
    import random
    for i in range(100000):
        offset_minutes = random.randint(0, 24 * 60 - 1)
        test_errors.append({
            "timestamp": (base_time + timedelta(minutes=offset_minutes)).isoformat() + "Z",
            "namespace": f"ns-{i % 100}",
            "application": f"app-{i % 50}",
            "message": f"Error type {i % 1000}: Something went wrong",
            "trace_id": f"trace-{i}"
        })
    
    print(f"Generated {len(test_errors)} test errors")
    
    # Parse
    print("Parsing...")
    start = time.time()
    records = parser.parse_batch(test_errors)
    print(f"Parsed {len(records)} records in {time.time() - start:.2f}s")
    
    # Measure
    print("Measuring...")
    start = time.time()
    results = measurer.measure(records, base_time)
    elapsed = time.time() - start
    
    print(f"\n=== RESULTS ===")
    print(f"Fingerprints: {len(results)}")
    print(f"Time: {elapsed:.2f}s")
    print(f"Rate: {len(records) / elapsed:.0f} records/sec")