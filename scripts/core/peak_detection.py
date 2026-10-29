#!/usr/bin/env python3
"""Peak detection using only the matching UTC weekly-slot percentile/MAD profile."""

import os
import yaml
from datetime import datetime
from typing import Dict, Tuple, Optional, Any

try:
    from .calculate_peak_thresholds import (
        CALCULATION_VERSION,
        PERCENTILE_METHOD,
        POPULATION_GRAIN,
    )
except ImportError:  # pragma: no cover - direct script execution
    from calculate_peak_thresholds import (
        CALCULATION_VERSION,
        PERCENTILE_METHOD,
        POPULATION_GRAIN,
    )


class PeakDetector:
    """
    Load versioned UTC slot profiles; never fall back to another slot or a global CAP.
    """
    
    def __init__(self, conn=None, config_path: str = None):
        """
        Initialize detector

        Configuration priority: env vars (from K8s values.yaml) > config file > defaults.

        Env vars (set by K8s CronJob from k8s/values.yaml):
            PERCENTILE_LEVEL          - percentile level (default: 0.95)
            MIN_SAMPLES_FOR_THRESHOLD - mature profile sample count (default: 10)

        Args:
            conn: psycopg2 database connection (optional, can be set later)
            config_path: path to values.yaml for default settings (legacy)
        """
        self._conn = conn
        self._thresholds_cache = None
        self._threshold_snapshot_id = None
        self._cache_loaded_at = None
        self._cache_ttl_seconds = 300  # 5 minutes cache

        # Load config: env vars take priority over file config
        self._config = self._load_config(config_path)
        self._percentile_level = float(os.getenv(
            'PERCENTILE_LEVEL', self._config.get('percentile_level', 0.95)))
        self._min_samples = int(float(os.getenv(
            'MIN_SAMPLES_FOR_THRESHOLD', self._config.get('min_samples_for_threshold', 10))))
        if self._min_samples < 10:
            raise ValueError('mature profiles require at least 10 samples')

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
    
    def load_thresholds_direct(
        self,
        thresholds: Dict[tuple, dict],
        snapshot_id: str = None,
    ):
        """Load exact-slot profiles for standalone replay or testing."""
        for key, profile in thresholds.items():
            namespace, weekday, hour, quarter = key
            if not namespace or not 0 <= weekday <= 6 or not 0 <= hour <= 23 or not 0 <= quarter <= 3:
                raise ValueError('invalid UTC weekly slot')
            if profile['samples'] <= 0 or profile['value'] < 0:
                raise ValueError('invalid UTC slot profile')
        self._thresholds_cache = {key: dict(profile) for key, profile in thresholds.items()}
        self._threshold_snapshot_id = snapshot_id
        self._cache_loaded_at = datetime.now()

    def _invalidate_cache(self):
        """Invalidate threshold cache"""
        self._thresholds_cache = None
        self._threshold_snapshot_id = None
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
        try:
            cur.execute("""
                SELECT threshold_row.snapshot_id, threshold_row.namespace,
                      threshold_row.day_of_week, threshold_row.hour_of_day,
                      threshold_row.quarter_hour, threshold_row.percentile_value,
                      threshold_row.sample_count, threshold_row.profile_status,
                      threshold_row.percentile_level, threshold_row.population_grain,
                       threshold_row.percentile_method,
                       threshold_row.calculation_version
                  FROM ailog_peak.v_latest_threshold_slots threshold_row
            """)
            rows = cur.fetchall()
        finally:
            cur.close()

        if not rows:
            raise RuntimeError('no complete threshold snapshot values available')

        snapshot_ids = {str(row[0]) for row in rows}
        if len(snapshot_ids) != 1:
            raise RuntimeError(f'latest threshold view mixed snapshots: {sorted(snapshot_ids)}')

        metadata = {
            (float(row[8]), str(row[9]), str(row[10]), str(row[11]))
            for row in rows
        }
        if len(metadata) != 1:
            raise RuntimeError('latest threshold snapshot has inconsistent metadata')
        percentile_level, population_grain, percentile_method, calculation_version = metadata.pop()
        mismatches = []
        if abs(percentile_level - self._percentile_level) >= 1e-9:
            mismatches.append(
                f'percentile_level={percentile_level} expected={self._percentile_level}'
            )
        if population_grain != POPULATION_GRAIN:
            mismatches.append(
                f'population_grain={population_grain} expected={POPULATION_GRAIN}'
            )
        if percentile_method != PERCENTILE_METHOD:
            mismatches.append(
                f'percentile_method={percentile_method} expected={PERCENTILE_METHOD}'
            )
        if calculation_version != CALCULATION_VERSION:
            mismatches.append(
                f'calculation_version={calculation_version} expected={CALCULATION_VERSION}'
            )
        if mismatches:
            raise RuntimeError('incompatible threshold snapshot: ' + '; '.join(mismatches))

        thresholds = {}
        for snapshot_id, ns, dow, hour, quarter, value, samples, status, *_metadata in rows:
            thresholds[(ns, dow, hour, quarter)] = {
                'value': float(value),
                'samples': samples,
                'profile_status': status,
            }
        self.load_thresholds_direct(thresholds, snapshot_id=next(iter(snapshot_ids)))
    
    def _ensure_cache_loaded(self):
        """Ensure threshold cache is loaded and valid"""
        if not self._is_cache_valid():
            self._load_thresholds_from_db()
    
    def get_threshold(self, namespace: str, day_of_week: int, hour: int, quarter: int) -> Optional[float]:
        """Return this slot's limit, including init profiles, or None when untrained."""
        self._ensure_cache_loaded()
        profile = self._thresholds_cache.get((namespace, day_of_week, hour, quarter))
        return profile['value'] if profile else None

    def is_peak(self, value: float, namespace: str, day_of_week: int, hour: int, quarter: int) -> Dict[str, Any]:
        """Compare only with the exact UTC slot; missing profiles remain unevaluated."""
        if not 0 <= day_of_week <= 6 or not 0 <= hour <= 23 or not 0 <= quarter <= 3:
            raise ValueError('invalid UTC weekly slot')
        threshold = self.get_threshold(namespace, day_of_week, hour, quarter)
        profile = self._thresholds_cache.get((namespace, day_of_week, hour, quarter)) or {}
        samples = profile.get('samples', 0)
        status = 'missing' if not samples else ('mature' if samples >= self._min_samples else 'init')
        peak_detected = threshold is not None and value > threshold
        return {
            'is_peak': peak_detected,
            'is_evaluated': threshold is not None,
            'value': value,
            'p93_threshold': threshold,
            'percentile_level': self._percentile_level,
            'percentile_threshold': threshold,
            'cap_threshold': None,
            'triggered_by': 'p93' if peak_detected else None,
            'profile_status': status,
            'threshold_samples': samples,
            'namespace': namespace,
            'day_of_week': day_of_week,
            'hour_of_day': hour,
            'quarter_hour': quarter,
            'threshold_snapshot_id': self._threshold_snapshot_id,
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
        result = self.is_peak(value, namespace, day, hour, quarter)
        
        # For replacement, use aggregation_mean if provided, otherwise use threshold
        if result['is_peak']:
            if aggregation_mean is not None:
                replacement = aggregation_mean
            else:
                replacement = result['percentile_threshold']
        else:
            replacement = value
        
        percentile_label = f"P{int(self._percentile_level * 100)}"
        reason = f"{percentile_label}={result['percentile_threshold']}, profile={result['profile_status']}"
        if not result['is_evaluated']:
            reason = 'UNEVALUATED: missing UTC slot profile'
        elif result['is_peak']:
            reason = f"PEAK ({result['triggered_by']}): value={value:.0f} > {reason}"
        else:
            reason = f"OK: value={value:.0f} <= {reason}"
        
        return {
            **result,
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
            'caps': {},
            'percentile_level': self._percentile_level,
            'cache_loaded_at': self._cache_loaded_at,
        }
    
    def print_thresholds_summary(self):
        """Print summary of all thresholds"""
        self._ensure_cache_loaded()
        
        print(f"UTC slot P{int(self._percentile_level * 100)}/MAD; global CAP disabled")
        for (namespace, weekday, hour, quarter), profile in sorted(self._thresholds_cache.items()):
            status = 'mature' if profile['samples'] >= self._min_samples else 'init'
            print(f"{namespace} DOW={weekday} {hour:02d}:{quarter * 15:02d}Z {profile} status={status}")
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


def is_peak(value: float, namespace: str, day_of_week: int, hour: int, quarter: int, conn=None) -> Dict[str, Any]:
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
    return detector.is_peak(value, namespace, day_of_week, hour, quarter)


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
    
    parser = argparse.ArgumentParser(description='Peak Detection - exact UTC weekly slots')
    parser.add_argument('--show-thresholds', action='store_true', help='Show all thresholds from DB')
    parser.add_argument('--check', nargs=5, metavar=('VALUE', 'NAMESPACE', 'DOW', 'HOUR', 'QUARTER'),
                        help='Check a UTC slot (quarter 0..3)')
    
    args = parser.parse_args()
    
    # Connect to DB (use DDL user for schema access)
    DB_CONFIG = {
        'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
        'port': int(os.getenv('DB_PORT', 5432)),
        'database': os.getenv('DB_NAME', 'ailog_analyzer'),
        'user': os.getenv('DB_DDL_USER', os.getenv('DB_USER', 'ailog_analyzer_user_d1')),
        'password': os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD'))
    }

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print(f"✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")

        # SET ROLE for schema access
        ddl_role = os.getenv('DB_DDL_ROLE', 'role_ailog_analyzer_ddl')
        cur = conn.cursor()
        cur.execute(f"SET ROLE {ddl_role}")
        conn.commit()
        cur.close()
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
        
        result = detector.is_peak(value, namespace, dow, int(args.check[3]), int(args.check[4]))
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
