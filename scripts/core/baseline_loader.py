#!/usr/bin/env python3
"""Load dense fingerprint baselines from authoritative complete-run facts."""

import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from typing import Dict, List
from collections import defaultdict


class BaselineLoader:
    """Načítá historické baseline data z DB"""
    
    def __init__(self, db_conn):
        """
        Args:
            db_conn: psycopg2 connection (musí mít SELECT na peak_investigation)
        """
        self.db_conn = db_conn
    
    def load_fingerprint_rates(
        self,
        fingerprints: List[str],
        analysis_window_start: datetime,
        lookback_days: int = 7,
        window_minutes: int = 15,
        min_samples: int = 3
    ) -> Dict[str, List[float]]:
        """Return one zero-inclusive rate per authoritative complete bucket."""
        if not fingerprints:
            return {}

        if analysis_window_start is None:
            raise ValueError('analysis_window_start is required for as-of baseline loading')
        if analysis_window_start.tzinfo is None or analysis_window_start.utcoffset() is None:
            raise ValueError('analysis_window_start must be timezone-aware')
        if window_minutes != 15:
            raise ValueError('authoritative facts currently use fixed 15-minute buckets')

        fingerprints = sorted(set(fingerprints))
        cutoff_time = analysis_window_start - timedelta(days=lookback_days)
        try:
            cursor = self.db_conn.cursor()
            query = """
            WITH complete_windows AS (
                SELECT DISTINCT window_start
                FROM ailog_peak.v_authoritative_run_windows
                WHERE window_start >= %s
                  AND window_start < %s
            ),
            requested_fingerprints AS (
                SELECT UNNEST(%s::TEXT[]) AS fingerprint
            ),
            fingerprint_counts AS (
                SELECT fingerprint, window_start, SUM(error_count)::BIGINT AS error_count
                FROM ailog_peak.v_complete_error_kind_counts
                WHERE fingerprint = ANY(%s)
                  AND window_start >= %s
                  AND window_start < %s
                GROUP BY fingerprint, window_start
            )
            SELECT
                requested.fingerprint,
                complete.window_start,
                COALESCE(counts.error_count, 0)::BIGINT AS error_count
            FROM requested_fingerprints requested
            CROSS JOIN complete_windows complete
            LEFT JOIN fingerprint_counts counts
              ON counts.fingerprint = requested.fingerprint
             AND counts.window_start = complete.window_start
            ORDER BY requested.fingerprint, complete.window_start
            """
            cursor.execute(query, (
                cutoff_time,
                analysis_window_start,
                fingerprints,
                fingerprints,
                cutoff_time,
                analysis_window_start,
            ))
            rows = cursor.fetchall()
            cursor.close()

            if not rows:
                return {}

            rates_by_fingerprint: Dict[str, List[float]] = defaultdict(list)
            for fingerprint, _, error_count in rows:
                rates_by_fingerprint[fingerprint].append(float(error_count))

            result = {
                fingerprint: rates
                for fingerprint, rates in rates_by_fingerprint.items()
                if len(rates) >= min_samples
            }
            for fingerprint, rates in result.items():
                print(f"✓ {fingerprint}: {len(rates)} dense historical rates")
            return result

        except Exception as e:
            print(f"❌ BaselineLoader error: {e}")
            raise

    def load_historical_rates(
        self,
        fingerprints: List[str],
        analysis_window_start: datetime,
        lookback_days: int = 7,
        window_minutes: int = 15,
        min_samples: int = 3,
    ) -> Dict[str, List[float]]:
        """Compatibility alias for the fingerprint-grain loader."""
        return self.load_fingerprint_rates(
            fingerprints,
            analysis_window_start,
            lookback_days,
            window_minutes,
            min_samples,
        )

    def load_baseline_for_fingerprint(
        self,
        fingerprint: str,
        analysis_window_start: datetime,
        lookback_days: int = 7,
        min_samples: int = 3
    ) -> List[float]:
        return self.load_fingerprint_rates(
            [fingerprint],
            analysis_window_start,
            lookback_days=lookback_days,
            min_samples=min_samples,
        ).get(fingerprint, [])

    def get_baseline_stats(
        self,
        fingerprints: List[str],
        analysis_window_start: datetime,
        lookback_days: int = 7
    ) -> Dict[str, Dict]:
        """
        Vrátí statistiku baseline - min, max, avg pro každý error_type.
        
        Returns:
            {
              'NullPointerException': {
                'min': 0.5,
                'max': 45.2,
                'avg': 12.3,
                'median': 10.0,
                'count': 126
              },
              ...
            }
        """
        rates = self.load_fingerprint_rates(
            fingerprints,
            analysis_window_start,
            lookback_days=lookback_days,
        )
        
        if not rates:
            return {}
        
        result = {}
        for error_type, rate_list in rates.items():
            if not rate_list:
                continue
            
            sorted_rates = sorted(rate_list)
            count = len(sorted_rates)
            median_idx = count // 2
            
            result[error_type] = {
                'min': min(rate_list),
                'max': max(rate_list),
                'avg': sum(rate_list) / count,
                'median': sorted_rates[median_idx],
                'count': count,
            }
        
        return result


# CLI pro testování
if __name__ == '__main__':
    import argparse
    import os
    from dotenv import load_dotenv
    from pathlib import Path
    
    load_dotenv()
    load_dotenv(Path(__file__).parent.parent.parent / '.env')
    
    parser = argparse.ArgumentParser(description='Baseline Loader - Debug tool')
    parser.add_argument('--error-types', nargs='+', help='Error types k testování')
    parser.add_argument('--days', type=int, default=7, help='Lookback days')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    
    args = parser.parse_args()
    
    # Connect to DB
    try:
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST'),
            port=int(os.getenv('DB_PORT', 5432)),
            database=os.getenv('DB_NAME'),
            user=os.getenv('DB_DDL_USER', os.getenv('DB_USER')),
            password=os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD')),
        )
        ddl_role = os.getenv('DB_DDL_ROLE', 'role_ailog_analyzer_ddl')
        cur = conn.cursor()
        cur.execute(f"SET ROLE {ddl_role}")
        conn.commit()
        cur.close()
    except Exception as e:
        print(f"❌ DB connection failed: {e}")
        exit(1)
    
    loader = BaselineLoader(conn)
    
    if args.error_types:
        if args.stats:
            stats = loader.get_baseline_stats(args.error_types, args.days)
            print(f"\n📊 Baseline Statistics ({args.days} days):\n")
            for et, stat in stats.items():
                print(f"{et}:")
                print(f"  Count: {stat['count']}")
                print(f"  Avg:   {stat['avg']:.2f}")
                print(f"  Min:   {stat['min']:.2f}")
                print(f"  Max:   {stat['max']:.2f}")
        else:
            rates = loader.load_historical_rates(args.error_types, args.days)
            print(f"\n📈 Historical Rates ({args.days} days):\n")
            for et, rate_list in rates.items():
                print(f"{et}: {len(rate_list)} samples")
                print(f"  First 10: {rate_list[:10]}")
                if len(rate_list) > 10:
                    print(f"  Last 10:  {rate_list[-10:]}")
    else:
        print("Usage: python baseline_loader.py --error-types NullPointerException TimeoutException [--stats]")
    
    conn.close()
