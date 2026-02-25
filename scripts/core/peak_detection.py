#!/usr/bin/env python3
"""
Peak Detection - P93 OR CAP Methodology (DATABASE VERSION)
==============================================================
Thresholds se načítají DYNAMICKY z databáze (tabulky peak_thresholds a peak_threshold_caps).
Žádné hardcoded hodnoty!

ALGORITMUS:
-----------
is_peak = (value > P93_per_DOW) OR (value > CAP)

P93_per_DOW = percentil pro daný (namespace, den_týdne) - z DB tabulky peak_thresholds
CAP = (median_P93 + avg_P93) / 2 per namespace - z DB tabulky peak_threshold_caps

DATABÁZOVÉ TABULKY:
-------------------
- ailog_peak.peak_thresholds: percentil per (namespace, day_of_week)
- ailog_peak.peak_threshold_caps: CAP per namespace

POUŽITÍ:
--------
from peak_detection import PeakDetector

# S DB connection
detector = PeakDetector(conn=db_connection)

# Nebo lazy load (načte při prvním použití)
detector = PeakDetector()
detector.set_connection(conn)

# Detekuj peak
result = detector.is_peak(value=500, namespace='pcb-sit-01-app', day_of_week=0)
"""

import os
import yaml
from datetime import datetime
from typing import Dict, Tuple, Optional, Any


class PeakDetector:
    """
    Peak Detection using P93 OR CAP methodology
    Loads thresholds from database tables
    """
    
    def __init__(self, conn=None, config_path: str = None):
        """
        Initialize detector

        Configuration priority: env vars (from K8s values.yaml) > config file > defaults.

        Env vars (set by K8s CronJob from k8s/values.yaml):
            PERCENTILE_LEVEL          - percentile level (default: 0.93)
            DEFAULT_THRESHOLD         - fallback threshold (default: 100)
            MIN_SAMPLES_FOR_THRESHOLD - min samples for reliable P93 (default: 10)

        Args:
            conn: psycopg2 database connection (optional, can be set later)
            config_path: path to values.yaml for default settings (legacy)
        """
        self._conn = conn
        self._thresholds_cache = None
        self._caps_cache = None
        self._cache_loaded_at = None
        self._cache_ttl_seconds = 300  # 5 minutes cache

        # Load config: env vars take priority over file config
        self._config = self._load_config(config_path)
        self._default_threshold = float(os.getenv(
            'DEFAULT_THRESHOLD', self._config.get('default_threshold', 100)))
        self._percentile_level = float(os.getenv(
            'PERCENTILE_LEVEL', self._config.get('percentile_level', 0.93)))
        self._min_samples = int(float(os.getenv(
            'MIN_SAMPLES_FOR_THRESHOLD', self._config.get('min_samples_for_threshold', 10))))

    def _load_config(self, config_path: str = None) -> dict:
        """Load configuration from values.yaml (legacy fallback)"""
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), '..', 'values.yaml')

        if not os.path.exists(config_path):
            return {}

        try:
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f)
            return data.get('peak_detection', {})
        except Exception:
            return {}
    
    def set_connection(self, conn):
        """Set database connection"""
        self._conn = conn
        self._invalidate_cache()
    
    def load_thresholds_direct(self, thresholds: Dict[tuple, dict], caps: Dict[str, dict]):
        """
        Load thresholds directly from dicts (for standalone/testing without DB).

        Args:
            thresholds: {(namespace, day_of_week): {'value': float, 'samples': int}}
            caps: {namespace: {'value': float, 'samples': int}}
        """
        self._thresholds_cache = thresholds
        self._caps_cache = caps
        self._cache_loaded_at = datetime.now()

    def _invalidate_cache(self):
        """Invalidate threshold cache"""
        self._thresholds_cache = None
        self._caps_cache = None
        self._cache_loaded_at = None
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if self._cache_loaded_at is None:
            return False
        age = (datetime.now() - self._cache_loaded_at).total_seconds()
        return age < self._cache_ttl_seconds
    
    def _load_thresholds_from_db(self):
        """Load thresholds from database"""
        if self._conn is None:
            raise RuntimeError("Database connection not set. Call set_connection() first.")
        
        cur = self._conn.cursor()
        
        # Load percentile thresholds
        cur.execute("""
            SELECT namespace, day_of_week, percentile_value, sample_count
            FROM ailog_peak.peak_thresholds
        """)
        
        self._thresholds_cache = {}
        for ns, dow, value, samples in cur.fetchall():
            self._thresholds_cache[(ns, dow)] = {
                'value': float(value),
                'samples': samples
            }
        
        # Load CAP values
        cur.execute("""
            SELECT namespace, cap_value, total_samples
            FROM ailog_peak.peak_threshold_caps
        """)
        
        self._caps_cache = {}
        for ns, cap, samples in cur.fetchall():
            self._caps_cache[ns] = {
                'value': float(cap),
                'samples': samples
            }
        
        self._cache_loaded_at = datetime.now()
    
    def _ensure_cache_loaded(self):
        """Ensure threshold cache is loaded and valid"""
        if not self._is_cache_valid():
            self._load_thresholds_from_db()
    
    def get_threshold(self, namespace: str, day_of_week: int) -> Tuple[float, float]:
        """
        Get P93 and CAP thresholds for given namespace and day of week
        
        Args:
            namespace: e.g. 'pcb-dev-01-app'
            day_of_week: 0=Monday, 6=Sunday
        
        Returns:
            tuple (p93_threshold, cap_threshold)
        """
        self._ensure_cache_loaded()
        
        # Get P93 for this (namespace, dow)
        p93_data = self._thresholds_cache.get((namespace, day_of_week))
        if p93_data and p93_data['samples'] >= self._min_samples:
            p93 = p93_data['value']
        else:
            p93 = None  # Will use CAP or default
        
        # Get CAP for this namespace
        cap_data = self._caps_cache.get(namespace)
        cap = cap_data['value'] if cap_data else self._default_threshold
        
        # If P93 not available, use CAP
        if p93 is None:
            p93 = cap
        
        return p93, cap
    
    def is_peak(self, value: float, namespace: str, day_of_week: int) -> Dict[str, Any]:
        """
        Detect if value is a peak using P93 OR CAP methodology
        
        Algorithm:
            is_peak = (value > P93_per_DOW) OR (value > CAP)
        
        Args:
            value: the value to check
            namespace: e.g. 'pcb-dev-01-app'
            day_of_week: 0=Monday, 6=Sunday
        
        Returns:
            dict with:
                'is_peak': bool
                'value': float
                'p93_threshold': float
                'cap_threshold': float
                'triggered_by': 'p93' | 'cap' | 'both' | None
                'namespace': str
                'day_of_week': int
        """
        p93_thr, cap_thr = self.get_threshold(namespace, day_of_week)
        
        exceeds_p93 = value > p93_thr
        exceeds_cap = value > cap_thr
        
        peak_detected = exceeds_p93 or exceeds_cap
        
        if exceeds_p93 and exceeds_cap:
            triggered_by = 'both'
        elif exceeds_p93:
            triggered_by = 'p93'
        elif exceeds_cap:
            triggered_by = 'cap'
        else:
            triggered_by = None
        
        return {
            'is_peak': peak_detected,
            'value': value,
            'p93_threshold': p93_thr,
            'cap_threshold': cap_thr,
            'triggered_by': triggered_by,
            'namespace': namespace,
            'day_of_week': day_of_week,
        }
    
    def detect_peak_for_row(self, day: int, hour: int, quarter: int, namespace: str, 
                           value: float, aggregation_mean: float = None) -> Dict[str, Any]:
        """
        Peak detection for a single data row (compatible with ingest scripts)
        
        Args:
            day: day of week (0=Monday)
            hour: hour (0-23)
            quarter: quarter (0-3)
            namespace: namespace string
            value: the value to check
            aggregation_mean: optional baseline mean for replacement value
        
        Returns:
            dict compatible with existing ingest scripts
        """
        result = self.is_peak(value, namespace, day)
        
        # For replacement, use aggregation_mean if provided, otherwise use threshold
        if result['is_peak']:
            if aggregation_mean is not None:
                replacement = aggregation_mean
            else:
                replacement = min(result['p93_threshold'], result['cap_threshold'])
        else:
            replacement = value
        
        reason = f"P93={result['p93_threshold']:.0f}, CAP={result['cap_threshold']:.0f}"
        if result['is_peak']:
            reason = f"PEAK ({result['triggered_by']}): value={value:.0f} > {reason}"
        else:
            reason = f"OK: value={value:.0f} <= {reason}"
        
        return {
            'is_peak': result['is_peak'],
            'original_value': value,
            'replacement_value': replacement,
            'p93_threshold': result['p93_threshold'],
            'cap_threshold': result['cap_threshold'],
            'triggered_by': result['triggered_by'],
            'reason': reason,
        }
    
    def get_all_thresholds(self) -> Dict[str, Any]:
        """
        Get all thresholds for reporting
        
        Returns:
            dict with 'thresholds' and 'caps'
        """
        self._ensure_cache_loaded()
        
        return {
            'thresholds': self._thresholds_cache.copy(),
            'caps': self._caps_cache.copy(),
            'default_threshold': self._default_threshold,
            'percentile_level': self._percentile_level,
            'cache_loaded_at': self._cache_loaded_at,
        }
    
    def print_thresholds_summary(self):
        """Print summary of all thresholds"""
        self._ensure_cache_loaded()
        
        # Get all namespaces
        namespaces = sorted(set(ns for (ns, dow) in self._thresholds_cache.keys()))
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        print("\n" + "=" * 120)
        print(f"Peak Thresholds (P{int(self._percentile_level * 100)} OR CAP)")
        print("=" * 120)
        
        print(f"\n{'NS':<25} {'CAP':>7} | {'Mon':>7} {'Tue':>7} {'Wed':>7} {'Thu':>7} {'Fri':>7} {'Sat':>7} {'Sun':>7}")
        print("-" * 100)
        
        for ns in namespaces:
            cap = self._caps_cache.get(ns, {}).get('value', self._default_threshold)
            row = f"{ns:<25} {cap:>7.0f} |"
            
            for dow in range(7):
                data = self._thresholds_cache.get((ns, dow))
                if data:
                    row += f" {data['value']:>7.0f}"
                else:
                    row += f" {'--':>7}"
            
            print(row)
        
        print(f"\nDefault threshold: {self._default_threshold}")
        print(f"Cache loaded at: {self._cache_loaded_at}")


# ============================================================================
# STANDALONE FUNCTIONS (for backwards compatibility)
# ============================================================================

_global_detector = None


def get_detector(conn=None) -> PeakDetector:
    """Get or create global detector instance"""
    global _global_detector
    if _global_detector is None:
        _global_detector = PeakDetector()
    if conn is not None:
        _global_detector.set_connection(conn)
    return _global_detector


def is_peak(value: float, namespace: str, day_of_week: int, conn=None) -> Dict[str, Any]:
    """
    Detect if value is a peak (standalone function)
    
    Args:
        value: the value to check
        namespace: e.g. 'pcb-dev-01-app'
        day_of_week: 0=Monday, 6=Sunday
        conn: optional database connection
    
    Returns:
        dict with is_peak, thresholds, etc.
    """
    detector = get_detector(conn)
    return detector.is_peak(value, namespace, day_of_week)


def detect_peak_for_row(day: int, hour: int, quarter: int, namespace: str, 
                        value: float, conn=None, aggregation_mean: float = None) -> Dict[str, Any]:
    """
    Peak detection for a single data row (standalone function)
    """
    detector = get_detector(conn)
    return detector.detect_peak_for_row(day, hour, quarter, namespace, value, aggregation_mean)


# ============================================================================
# CLI
# ============================================================================

if __name__ == '__main__':
    import argparse
    import sys
    
    try:
        import psycopg2
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("❌ Required: pip install psycopg2-binary python-dotenv")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description='Peak Detection - P93 OR CAP (DB thresholds)')
    parser.add_argument('--show-thresholds', action='store_true', help='Show all thresholds from DB')
    parser.add_argument('--check', nargs=3, metavar=('VALUE', 'NAMESPACE', 'DOW'), 
                        help='Check if value is peak (e.g. --check 500 pcb-sit-01-app 0)')
    
    args = parser.parse_args()
    
    # Connect to DB
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
        'port': int(os.getenv('DB_PORT', 5432)),
        'database': os.getenv('DB_NAME', 'ailog_analyzer'),
        'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
        'password': os.getenv('DB_PASSWORD')
    }
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)
    
    detector = PeakDetector(conn=conn)
    
    if args.show_thresholds:
        detector.print_thresholds_summary()
    
    elif args.check:
        value = float(args.check[0])
        namespace = args.check[1]
        dow = int(args.check[2])
        
        result = detector.is_peak(value, namespace, dow)
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        
        print(f"\n{'=' * 60}")
        print(f"Peak Detection Check")
        print(f"{'=' * 60}")
        print(f"Value:      {value}")
        print(f"Namespace:  {namespace}")
        print(f"Day:        {days[dow]}")
        print(f"P93:        {result['p93_threshold']}")
        print(f"CAP:        {result['cap_threshold']}")
        print(f"{'=' * 60}")
        print(f"IS PEAK:    {'✅ YES' if result['is_peak'] else '❌ NO'}")
        if result['triggered_by']:
            print(f"Triggered:  {result['triggered_by']}")
        print(f"{'=' * 60}")
    
    else:
        parser.print_help()
    
    conn.close()
