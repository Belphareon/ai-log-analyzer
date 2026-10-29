#!/usr/bin/env python3
"""Train independent UTC weekly-slot percentile/MAD profiles from completed DB facts."""

import os
import sys
import argparse
import uuid
import statistics
from datetime import datetime, timedelta, timezone
from collections import defaultdict

try:
    import psycopg2
    from psycopg2.extras import execute_batch
except ImportError:
    print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from .namespace_contract import load_monitored_namespaces as _load_namespace_contract
except ImportError:  # pragma: no cover - direct script execution
    from namespace_contract import load_monitored_namespaces as _load_namespace_contract

# Database configuration (uses DDL user for INSERT/DELETE operations)
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_DDL_USER', os.getenv('DB_USER', 'ailog_analyzer_user_d1')),
    'password': os.getenv('DB_DDL_PASSWORD', os.getenv('DB_PASSWORD'))
}

# Day names for display
DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

POPULATION_GRAIN = 'namespace/utc_weekday/hour/quarter/observed'
PERCENTILE_METHOD = 'configured_percentile_capped_by_median_plus_6_scaled_mad'
CALCULATION_VERSION = '5.0'
DEFAULT_THRESHOLD_WEEKS = 12
MAD_SCALE_FACTOR = 1.4826
ROBUST_MAD_MULTIPLIER = 6.0


def load_monitored_namespaces() -> list[str]:
    strict = os.getenv('NAMESPACE_CONTRACT_STRICT', '').strip().lower() in {
        '1', 'true', 'yes', 'on'
    }
    return _load_namespace_contract(strict=strict)


def percentile(values: list, p: float) -> float:
    """Calculate percentile from list of values"""
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(len(s) * p)
    idx = min(idx, len(s) - 1)  # Ensure we don't go out of bounds
    return float(s[idx])


def robust_upper_bound(values: list) -> float:
    """Return an outlier-resistant upper bound for one observed slot population."""
    if not values:
        return 0.0
    median_value = float(statistics.median(values))
    mad = float(statistics.median(abs(value - median_value) for value in values))
    if mad == 0:
        return float(max(values))
    return median_value + (ROBUST_MAD_MULTIPLIER * MAD_SCALE_FACTOR * mad)


def fetch_raw_data(conn, weeks: int = DEFAULT_THRESHOLD_WEEKS, as_of: datetime = None) -> dict:
    """Read completed facts only; missing windows are never filled with zeros."""
    cur = conn.cursor()
    
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    if weeks is not None and weeks < 10:
        raise ValueError('threshold history must request at least 10 weeks')

    monitored_namespaces = load_monitored_namespaces()
    if not monitored_namespaces:
        raise ValueError('MONITORED_NAMESPACES is required for threshold training')

    query = """
        SELECT
            namespace,
            error_count,
            window_start
        FROM ailog_peak.v_complete_namespace_error_counts
        WHERE window_start < %s
          AND namespace = ANY(%s)
    """
    params = [as_of, monitored_namespaces]
    
    if weeks:
        start_date = as_of - timedelta(weeks=weeks)
        query += " AND window_start >= %s"
        params.append(start_date)
    
    query += " ORDER BY namespace, window_start"
    
    print(f"📊 Fetching dense data from v_complete_namespace_error_counts...")
    cur.execute(query, params)
    rows = cur.fetchall()
    
    print(f"   Found {len(rows):,} rows")
    
    data = defaultdict(list)
    date_range = {'min': None, 'max': None}
    
    for ns, value, ts in rows:
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise ValueError('fact window_start must be timezone-aware')
        ts = ts.astimezone(timezone.utc)
        if ts.minute % 15 or ts.second or ts.microsecond:
            raise ValueError('fact window_start must align to a UTC quarter hour')
        data[(ns, ts.weekday(), ts.hour, ts.minute // 15)].append(float(value))
        if date_range['min'] is None or ts < date_range['min']:
            date_range['min'] = ts
        if date_range['max'] is None or ts > date_range['max']:
            date_range['max'] = ts
    
    print(f"   Observed UTC weekly slots: {len(data)}")
    if date_range['min'] and date_range['max']:
        print(f"   Date range: {date_range['min'].strftime('%Y-%m-%d')} to {date_range['max'].strftime('%Y-%m-%d')}")
    
    return data, date_range


def calculate_p93_thresholds(data: dict, percentile_level: float = 0.95) -> dict:
    """Calculate an independent percentile/MAD profile for each observed UTC slot."""
    if not 0 < percentile_level < 1:
        raise ValueError('percentile must be between zero and one')
    minimum_samples = int(os.getenv('MIN_SAMPLES_FOR_THRESHOLD', '10'))
    if minimum_samples < 10:
        raise ValueError('mature profiles require at least 10 samples')
    thresholds = {}

    for slot, values in data.items():
        namespace, weekday, hour, quarter = slot
        if not namespace or not 0 <= weekday <= 6 or not 0 <= hour <= 23 or not 0 <= quarter <= 3:
            raise ValueError('invalid UTC weekly slot')
        if any(value < 0 for value in values):
            raise ValueError('observed counts cannot be negative')
        if not values:
            continue

        sample_count = len(values)
        raw_percentile = percentile(values, percentile_level)
        robust_limit = robust_upper_bound(values)
        thresholds[slot] = {
            'p93': min(raw_percentile, robust_limit),
            'raw_percentile': raw_percentile,
            'robust_upper_bound': robust_limit,
            'count': sample_count,
            'profile_status': 'mature' if sample_count >= minimum_samples else 'init',
            'median': float(statistics.median(values)),
            'mean': sum(values) / sample_count,
            'max': max(values),
        }
    
    return thresholds


def save_thresholds_to_db(
    conn,
    thresholds: dict,
    date_range: dict,
    percentile_level: float = 0.95,
    dry_run: bool = False,
    as_of: datetime = None,
):
    """
    Save calculated thresholds to database
    """
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')
    training_start = date_range['min']
    training_end = as_of
    sample_count = sum(stats['count'] for stats in thresholds.values())
    monitored_namespaces = sorted(load_monitored_namespaces())
    if not monitored_namespaces:
        raise ValueError('MONITORED_NAMESPACES is required for threshold snapshot metadata')
    
    if dry_run:
        print("\n🔍 DRY RUN - would save:")
        print(f"\n   Percentile thresholds: {len(thresholds)} rows")
        return None

    if not training_start or training_end <= training_start:
        raise ValueError('threshold training interval is empty')

    snapshot_id = str(uuid.uuid4())
    snapshot_rows = [
        (
            snapshot_id,
            ns,
            dow,
            hour,
            quarter,
            stats['p93'],
            stats['count'],
            stats['profile_status'],
            stats['median'],
            stats['mean'],
            stats['max'],
        )
        for (ns, dow, hour, quarter), stats in thresholds.items()
    ]
    cur = conn.cursor()
    running_committed = False
    try:
        cur.execute("""
            INSERT INTO ailog_peak.threshold_snapshot_runs
                (snapshot_id, percentile_level, population_grain,
                 training_start, training_end, sample_count,
                 percentile_method, calculation_version,
                 monitored_namespaces, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'running')
        """, (
            snapshot_id,
            percentile_level,
            POPULATION_GRAIN,
            training_start,
            training_end,
            sample_count,
            PERCENTILE_METHOD,
            CALCULATION_VERSION,
            monitored_namespaces,
        ))
        conn.commit()
        running_committed = True

        execute_batch(cur, """
            INSERT INTO ailog_peak.threshold_slot_values
                (snapshot_id, namespace, day_of_week, hour_of_day, quarter_hour,
                 percentile_value, sample_count, profile_status,
                 median_value, mean_value, max_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, snapshot_rows)
        cur.execute("""
            UPDATE ailog_peak.threshold_snapshot_runs
            SET status = 'complete', completed_at = NOW()
            WHERE snapshot_id = %s AND status = 'running'
        """, (snapshot_id,))
        if cur.rowcount != 1:
            raise RuntimeError('threshold snapshot was not completed exactly once')
        conn.commit()
        print(f"   ✅ Stored complete threshold snapshot {snapshot_id}")
        return snapshot_id
    except Exception:
        conn.rollback()
        if running_committed:
            cur.execute("""
                UPDATE ailog_peak.threshold_snapshot_runs
                SET status = 'failed', completed_at = NOW()
                WHERE snapshot_id = %s AND status = 'running'
            """, (snapshot_id,))
            conn.commit()
        raise
    finally:
        cur.close()


def print_summary(thresholds: dict, percentile_level: float = 0.95):
    """Print every observed slot, including its sample count and maturity."""
    print(f"\nUTC weekly slot P{int(percentile_level * 100)}/MAD; global CAP disabled")
    for (namespace, weekday, hour, quarter), stats in sorted(thresholds.items()):
        print(
            f"{namespace:<25} {DAYS[weekday]} {hour:02d}:{quarter * 15:02d}Z "
            f"limit={stats['p93']:.4f} samples={stats['count']} "
            f"profile={stats['profile_status']}"
        )


def main():
    default_percentile = float(os.getenv('PERCENTILE_LEVEL', '0.95'))

    parser = argparse.ArgumentParser(description='Calculate Peak Thresholds from complete namespace facts')
    parser.add_argument('--weeks', type=int, default=DEFAULT_THRESHOLD_WEEKS,
                        help='History horizon in weeks (minimum 10; default 12)')
    parser.add_argument('--percentile', type=float, default=default_percentile,
                        help=f'Percentile level (default: {default_percentile} from env PERCENTILE_LEVEL)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be calculated without saving')
    parser.add_argument('--verbose', action='store_true', help='Show detailed output')
    parser.add_argument(
        '--as-of',
        help='Exclusive UTC training cutoff (ISO-8601); defaults to current UTC time',
    )

    args = parser.parse_args()
    
    print("=" * 80)
    print("📊 Calculate Peak Thresholds")
    print("=" * 80)
    print(f"   Percentile: P{int(args.percentile * 100)}")
    if args.weeks:
        print(f"   Data range: last {args.weeks} weeks")
    else:
        print(f"   Data range: all available data")
    if args.dry_run:
        print(f"   Mode: DRY RUN")
    
    # Connect to DB
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print(f"\n✅ Connected to {DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}")

        # SET ROLE for schema access (same pattern as backfill/regular_phase)
        ddl_role = os.getenv('DB_DDL_ROLE', 'role_ailog_analyzer_ddl')
        cur = conn.cursor()
        cur.execute(f"SET ROLE {ddl_role}")
        conn.commit()
        cur.close()
        print(f"   SET ROLE {ddl_role}")
    except Exception as e:
        print(f"\n❌ Database connection failed: {e}")
        return 1

    try:
        as_of = (
            datetime.fromisoformat(args.as_of.replace('Z', '+00:00'))
            if args.as_of else datetime.now(timezone.utc)
        )
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError('--as-of must include a timezone')

        data, date_range = fetch_raw_data(conn, args.weeks, as_of=as_of)
        
        if not data:
            print("\n⚠️  No complete namespace facts found!")
            return 1
        
        # Calculate P93 thresholds
        print(f"\n📈 Calculating P{int(args.percentile * 100)} thresholds...")
        thresholds = calculate_p93_thresholds(data, args.percentile)
        
        # Print summary
        print_summary(thresholds, args.percentile)
        
        # Save to DB
        save_thresholds_to_db(
            conn,
            thresholds,
            date_range,
            args.percentile,
            args.dry_run,
            as_of=as_of,
        )
        
        print("\n" + "=" * 80)
        print("✅ Peak thresholds calculation complete!")
        print("=" * 80)
        
        conn.close()
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        return 1


if __name__ == '__main__':
    sys.exit(main())
