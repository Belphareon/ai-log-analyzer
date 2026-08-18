#!/usr/bin/env python3
"""
Calculate Peak Thresholds from peak_raw_data
=============================================
Purpose: Calculate P93 and CAP thresholds dynamically from collected data

Algorithm:
1. Read all data from peak_raw_data (or last N weeks)
2. For each (namespace, day_of_week):
   - Calculate P93 (93rd percentile) from raw values
   - Store in peak_thresholds table
3. For each namespace:
   - Calculate CAP = (median_P93 + avg_P93) / 2 across all DOWs
   - Store in peak_threshold_caps table

Usage:
    python calculate_peak_thresholds.py                    # Calculate from all data
    python calculate_peak_thresholds.py --weeks 4          # Last 4 weeks only
    python calculate_peak_thresholds.py --percentile 0.92  # Use P92 instead of P93
    python calculate_peak_thresholds.py --dry-run          # Show what would be calculated
"""

import os
import sys
import argparse
import uuid
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

def load_monitored_namespaces() -> list[str]:
    return [
        namespace.strip()
        for namespace in os.getenv('MONITORED_NAMESPACES', '').split(',')
        if namespace.strip()
    ]



def percentile(values: list, p: float) -> float:
    """Calculate percentile from list of values"""
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(len(s) * p)
    idx = min(idx, len(s) - 1)  # Ensure we don't go out of bounds
    return float(s[idx])


def fetch_raw_data(conn, weeks: int = None, as_of: datetime = None) -> dict:
    """
    Fetch dense authoritative namespace facts, grouped by (namespace, weekday).
    
    Args:
        conn: database connection
        weeks: if specified, only fetch last N weeks
    
    Returns:
        dict: {(namespace, day_of_week): [values]}
    """
    cur = conn.cursor()
    
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('as_of must be timezone-aware')

    monitored_namespaces = load_monitored_namespaces()
    if not monitored_namespaces:
        raise ValueError('MONITORED_NAMESPACES is required for threshold training')

    query = """
        SELECT
            namespace,
            EXTRACT(ISODOW FROM window_start)::INTEGER - 1 AS day_of_week,
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
    
    query += " ORDER BY namespace, day_of_week"
    
    print(f"📊 Fetching dense data from v_complete_namespace_error_counts...")
    cur.execute(query, params)
    rows = cur.fetchall()
    
    print(f"   Found {len(rows):,} rows")
    
    # Group by (namespace, day_of_week)
    data = defaultdict(list)
    date_range = {'min': None, 'max': None}
    
    for ns, dow, value, ts in rows:
        data[(ns, dow)].append(float(value))
        if date_range['min'] is None or ts < date_range['min']:
            date_range['min'] = ts
        if date_range['max'] is None or ts > date_range['max']:
            date_range['max'] = ts
    
    print(f"   Unique (namespace, dow) combinations: {len(data)}")
    if date_range['min'] and date_range['max']:
        print(f"   Date range: {date_range['min'].strftime('%Y-%m-%d')} to {date_range['max'].strftime('%Y-%m-%d')}")
    
    return data, date_range


def calculate_p93_thresholds(data: dict, percentile_level: float = 0.93) -> dict:
    """
    Calculate P93 (or other percentile) for each (namespace, day_of_week)
    
    Returns:
        dict: {(namespace, day_of_week): {'p93': value, 'count': n, 'median': m, 'mean': avg, 'max': max_val}}
    """
    thresholds = {}
    
    for (ns, dow), values in data.items():
        if not values:
            continue
        
        s = sorted(values)
        n = len(s)
        
        thresholds[(ns, dow)] = {
            'p93': percentile(values, percentile_level),
            'count': n,
            'median': s[n // 2],
            'mean': sum(values) / n,
            'max': max(values),
        }
    
    return thresholds


def calculate_cap_values(thresholds: dict) -> dict:
    """
    Calculate CAP for each namespace
    CAP = (median_P93 + avg_P93) / 2 across all DOWs
    
    Returns:
        dict: {namespace: {'cap': value, 'median_p93': m, 'avg_p93': avg, 'min_p93': min, 'max_p93': max, 'total_samples': n}}
    """
    # Group P93 values by namespace
    p93_by_ns = defaultdict(list)
    samples_by_ns = defaultdict(int)
    
    for (ns, dow), stats in thresholds.items():
        p93_by_ns[ns].append(stats['p93'])
        samples_by_ns[ns] += stats['count']
    
    caps = {}
    
    for ns, p93_values in p93_by_ns.items():
        if not p93_values:
            continue
        
        s = sorted(p93_values)
        median_p93 = s[len(s) // 2]
        avg_p93 = sum(p93_values) / len(p93_values)
        
        caps[ns] = {
            'cap': (median_p93 + avg_p93) / 2,
            'median_p93': median_p93,
            'avg_p93': avg_p93,
            'min_p93': min(p93_values),
            'max_p93': max(p93_values),
            'total_samples': samples_by_ns[ns],
        }
    
    return caps


def save_thresholds_to_db(
    conn,
    thresholds: dict,
    caps: dict,
    date_range: dict,
    percentile_level: float = 0.93,
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
    start_date = training_start.date() if training_start else None
    end_date = date_range['max'].date() if date_range['max'] else None
    sample_count = sum(stats['count'] for stats in thresholds.values())
    
    if dry_run:
        print("\n🔍 DRY RUN - would save:")
        print(f"\n   Percentile thresholds: {len(thresholds)} rows")
        print(f"   CAP values: {len(caps)} rows")
        return None

    if not training_start or training_end <= training_start:
        raise ValueError('threshold training interval is empty')

    snapshot_id = str(uuid.uuid4())
    p93_rows = []
    for (ns, dow), stats in thresholds.items():
        p93_rows.append((
            ns, dow, stats['p93'], percentile_level, stats['count'], 
            stats['median'], stats['mean'], stats['max'],
            start_date, end_date
        ))
    cap_rows = []
    for ns, stats in caps.items():
        cap_rows.append((
            ns, stats['cap'], stats['median_p93'], stats['avg_p93'],
            stats['min_p93'], stats['max_p93'], percentile_level, stats['total_samples']
        ))

    snapshot_rows = [
        (
            snapshot_id,
            ns,
            dow,
            stats['p93'],
            caps[ns]['cap'],
            stats['count'],
            stats['median'],
            stats['mean'],
            stats['max'],
        )
        for (ns, dow), stats in thresholds.items()
    ]
    cur = conn.cursor()
    running_committed = False
    try:
        cur.execute("""
            INSERT INTO ailog_peak.threshold_snapshot_runs
                (snapshot_id, percentile_level, population_grain,
                 training_start, training_end, sample_count,
                 percentile_method, calculation_version, status)
            VALUES (%s, %s, 'namespace/15m/day_of_week', %s, %s, %s,
                    'sorted_floor_n_times_p', '2.0', 'running')
        """, (
            snapshot_id,
            percentile_level,
            training_start,
            training_end,
            sample_count,
        ))
        conn.commit()
        running_committed = True

        execute_batch(cur, """
            INSERT INTO ailog_peak.threshold_snapshot_values
                (snapshot_id, namespace, day_of_week, percentile_value,
                 cap_value, sample_count, median_value, mean_value, max_value)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, snapshot_rows)

        cur.execute("DELETE FROM ailog_peak.peak_thresholds")
        cur.execute("DELETE FROM ailog_peak.peak_threshold_caps")
        execute_batch(cur, """
            INSERT INTO ailog_peak.peak_thresholds
                (namespace, day_of_week, percentile_value, percentile_level,
                 sample_count, median_value, mean_value, max_value,
                 calculated_at, data_start_date, data_end_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, %s)
        """, p93_rows)
        execute_batch(cur, """
            INSERT INTO ailog_peak.peak_threshold_caps
                (namespace, cap_value, median_percentile, avg_percentile,
                 min_percentile, max_percentile, percentile_level,
                 total_samples, calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        """, cap_rows)
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


def print_summary(thresholds: dict, caps: dict, percentile_level: float = 0.93):
    """Print summary of calculated thresholds"""
    percentile_label = f"P{int(percentile_level * 100)}"
    
    # Get all namespaces
    namespaces = sorted(set(ns for (ns, dow) in thresholds.keys()))
    
    print("\n" + "=" * 120)
    print(f"{percentile_label} THRESHOLDS per NS per DOW")
    print("=" * 120)
    
    print(f"\n{'NS':<25} {'CAP':>7} | {'Mon':>7} {'Tue':>7} {'Wed':>7} {'Thu':>7} {'Fri':>7} {'Sat':>7} {'Sun':>7} | {'Samples':>8}")
    print("-" * 120)
    
    for ns in namespaces:
        cap = caps.get(ns, {}).get('cap', 0)
        row = f"{ns:<25} {cap:>7.0f} |"
        
        total_samples = 0
        for dow in range(7):
            stats = thresholds.get((ns, dow))
            if stats:
                row += f" {stats['p93']:>7.0f}"
                total_samples += stats['count']
            else:
                row += f" {'--':>7}"
        
        row += f" | {total_samples:>8}"
        print(row)
    
    print("\n" + "=" * 120)
    print("CAP VALUES per NS")
    print("=" * 120)
    
    print(f"\n{'NS':<25} {'CAP':>8} | {f'Median_{percentile_label}':>11} {f'Avg_{percentile_label}':>10} {f'Min_{percentile_label}':>9} {f'Max_{percentile_label}':>9} | {'Samples':>8}")
    print("-" * 100)
    
    for ns in namespaces:
        c = caps.get(ns, {})
        if c:
            print(f"{ns:<25} {c['cap']:>8.0f} | {c['median_p93']:>11.0f} {c['avg_p93']:>10.0f} {c['min_p93']:>9.0f} {c['max_p93']:>9.0f} | {c['total_samples']:>8}")


def main():
    # Percentile default: env var PERCENTILE_LEVEL (from K8s values.yaml) > hardcoded 0.93
    default_percentile = float(os.getenv('PERCENTILE_LEVEL', '0.93'))

    parser = argparse.ArgumentParser(description='Calculate Peak Thresholds from complete namespace facts')
    parser.add_argument('--weeks', type=int, help='Only use last N weeks of data')
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
        
        # Calculate CAP values
        print(f"📊 Calculating CAP values...")
        caps = calculate_cap_values(thresholds)
        
        # Print summary
        print_summary(thresholds, caps, args.percentile)
        
        # Save to DB
        save_thresholds_to_db(
            conn,
            thresholds,
            caps,
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
