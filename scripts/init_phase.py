#!/usr/bin/env python3
"""
INIT PHASE - Sběr baseline dat
==============================

Spouští se jednou na začátku pro sběr baseline dat (21+ dní).
BEZ peak detection, jen sběr a uložení raw dat do DB.

Použití:
    python init_phase.py --days 21
    python init_phase.py --from "2025-12-01T00:00:00Z" --to "2025-12-21T23:59:59Z"
    python init_phase.py --days 21 --dry-run
"""

import os
import sys
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))

from core.fetch_unlimited import fetch_unlimited

# DB
try:
    import psycopg2
    HAS_DB = True
except ImportError:
    HAS_DB = False

# Config
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from dotenv import load_dotenv
load_dotenv()
load_dotenv(SCRIPT_DIR.parent / 'config' / '.env')


def get_db_connection():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT', 5432)),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )


def load_namespaces():
    """Load namespaces from config"""
    config_path = SCRIPT_DIR.parent / 'config' / 'namespaces.yaml'
    
    if config_path.exists() and HAS_YAML:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            return config.get('namespaces', [])
    
    # Default namespaces
    return [
        'pcb-dev-01-app',
        'pcb-sit-01-app',
        'pcb-uat-01-app',
        'pcb-prd-01-app',
    ]


def group_into_windows(errors: list, namespaces: list) -> dict:
    """
    Group errors into 15-minute windows per namespace.
    
    Returns: dict[(window_start, namespace)] = count
    """
    window_counts = defaultdict(int)
    discovered_ns = set()
    
    for error in errors:
        # Parse timestamp
        ts_str = error.get('timestamp', '')
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        except:
            continue
        
        # Align to 15-min boundary
        minute = (ts.minute // 15) * 15
        window_start = ts.replace(minute=minute, second=0, microsecond=0)
        
        # Get namespace
        ns = error.get('namespace', 'unknown')
        discovered_ns.add(ns)
        
        # Filter by configured namespaces
        if namespaces and ns not in namespaces:
            continue
        
        key = (window_start.isoformat(), ns)
        window_counts[key] += 1
    
    return window_counts, discovered_ns


def collect_day(date: datetime, namespaces: list, dry_run: bool = False) -> dict:
    """
    Sbírá data za jeden den.
    """
    date_from = date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_to = date.replace(hour=23, minute=59, second=59, microsecond=0)
    
    date_from_str = date_from.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_to_str = date_to.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    print(f"\n📅 {date.strftime('%Y-%m-%d')} | {date_from_str} → {date_to_str}")
    
    # Fetch from ES
    errors = fetch_unlimited(date_from_str, date_to_str)
    
    if errors is None:
        print(f"   ❌ Fetch failed")
        return {'status': 'error', 'date': date.strftime('%Y-%m-%d')}
    
    print(f"   📥 Fetched {len(errors):,} errors")
    
    if len(errors) == 0:
        return {
            'status': 'no_data',
            'date': date.strftime('%Y-%m-%d'),
            'error_count': 0
        }
    
    # Group into windows
    window_counts, discovered_ns = group_into_windows(errors, namespaces)
    print(f"   📊 {len(window_counts)} window records, {len(discovered_ns)} namespaces")
    
    if dry_run:
        print(f"   ⏭️  DRY RUN - not saving to DB")
        return {
            'status': 'dry_run',
            'date': date.strftime('%Y-%m-%d'),
            'error_count': len(errors),
            'window_count': len(window_counts)
        }
    
    # Save to DB
    conn = get_db_connection()
    cursor = conn.cursor()
    
    inserted = 0
    for (window_start, namespace), count in window_counts.items():
        ts = datetime.fromisoformat(window_start)
        
        try:
            cursor.execute("""
                INSERT INTO ailog_peak.peak_raw_data
                (timestamp, day_of_week, hour_of_day, quarter_hour, namespace, 
                 error_count, original_value, is_peak)
                VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
                ON CONFLICT (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
                DO UPDATE SET
                    error_count = EXCLUDED.error_count,
                    original_value = EXCLUDED.original_value
            """, (
                ts,
                ts.weekday(),
                ts.hour,
                ts.minute // 15,
                namespace,
                count,
                count
            ))
            inserted += 1
        except Exception as e:
            print(f"   ⚠️  Insert error: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"   💾 Saved {inserted} records")
    
    return {
        'status': 'success',
        'date': date.strftime('%Y-%m-%d'),
        'error_count': len(errors),
        'records_inserted': inserted
    }


def run_init_phase(
    days: int = 21,
    date_from: str = None,
    date_to: str = None,
    dry_run: bool = False
) -> dict:
    """
    Spustí INIT fázi - sběr baseline dat.
    """
    print("=" * 70)
    print("🚀 INIT PHASE - Baseline Data Collection")
    print("=" * 70)
    
    # Load namespaces
    namespaces = load_namespaces()
    print(f"\n📋 Configured namespaces: {len(namespaces)}")
    for ns in namespaces[:5]:
        print(f"   - {ns}")
    if len(namespaces) > 5:
        print(f"   - ... and {len(namespaces) - 5} more")
    
    # Determine date range
    if date_from and date_to:
        start_date = datetime.fromisoformat(date_from.replace('Z', '+00:00'))
        end_date = datetime.fromisoformat(date_to.replace('Z', '+00:00'))
    else:
        end_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        start_date = end_date - timedelta(days=days - 1)
    
    print(f"\n📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"   Total days: {(end_date - start_date).days + 1}")
    
    if dry_run:
        print("   Mode: DRY RUN (no DB writes)")
    
    # Collect each day
    results = []
    current_date = start_date
    
    while current_date <= end_date:
        result = collect_day(current_date, namespaces, dry_run)
        results.append(result)
        current_date += timedelta(days=1)
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 INIT PHASE SUMMARY")
    print("=" * 70)
    
    success_count = sum(1 for r in results if r['status'] in ['success', 'dry_run'])
    error_count = sum(1 for r in results if r['status'] == 'error')
    no_data_count = sum(1 for r in results if r['status'] == 'no_data')
    total_errors = sum(r.get('error_count', 0) for r in results)
    total_records = sum(r.get('records_inserted', r.get('window_count', 0)) for r in results)
    
    print(f"\n   Days processed: {len(results)}")
    print(f"   ✅ Successful: {success_count}")
    print(f"   ⚪ No data: {no_data_count}")
    print(f"   ❌ Failed: {error_count}")
    print(f"\n   Total errors collected: {total_errors:,}")
    print(f"   Total DB records: {total_records:,}")
    
    print("\n" + "=" * 70)
    print("✅ INIT PHASE COMPLETE")
    print("=" * 70)
    
    if not dry_run:
        print("\n📝 Next steps:")
        print("   1. Calculate thresholds:")
        print("      python scripts/core/calculate_peak_thresholds.py")
        print("\n   2. Run backfill (last 14 days with detection):")
        print("      ./run_backfill.sh --days 14")
        print("\n   3. Setup cron for regular phase:")
        print("      */15 * * * * /path/to/run_regular.sh --quiet")
    
    return {
        'phase': 'init',
        'days_processed': len(results),
        'success_count': success_count,
        'error_count': error_count,
        'total_errors': total_errors,
        'total_records': total_records,
    }


def main():
    parser = argparse.ArgumentParser(description='INIT Phase - Baseline Data Collection')
    parser.add_argument('--days', type=int, default=21, help='Number of days to collect (default: 21)')
    parser.add_argument('--from', dest='date_from', help='Start date (ISO format)')
    parser.add_argument('--to', dest='date_to', help='End date (ISO format)')
    parser.add_argument('--dry-run', action='store_true', help='Dry run - no DB writes')
    
    args = parser.parse_args()
    
    if not HAS_DB and not args.dry_run:
        print("❌ psycopg2 not installed. Use --dry-run or: pip install psycopg2-binary")
        return 1
    
    result = run_init_phase(
        days=args.days,
        date_from=args.date_from,
        date_to=args.date_to,
        dry_run=args.dry_run
    )
    
    return 0 if result['error_count'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
