#!/usr/bin/env python3
"""
RESET AND RERUN - Čistý restart s novým registry systémem
=========================================================

Provede:
1. Backup stávajících dat
2. Vyčištění DB (volitelně)
3. Migrace registry na nový formát
4. Spuštění backfill s novým systémem

Použití:
    python reset_and_rerun.py --days 20              # Dry-run (preview)
    python reset_and_rerun.py --days 20 --execute    # Skutečné spuštění
    python reset_and_rerun.py --days 20 --execute --keep-db  # Bez mazání DB
"""

import os
import sys
import argparse
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))

# DB
try:
    import psycopg2
    HAS_DB = True
except ImportError:
    HAS_DB = False

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
        password=os.getenv('DB_PASSWORD'),
        connect_timeout=30,
    )


def set_db_role(cursor) -> None:
    """Set DDL role after login (if configured)."""
    ddl_role = os.getenv('DB_DDL_ROLE') or os.getenv('DB_DDL_USER') or 'role_ailog_analyzer_ddl'
    if ddl_role:
        cursor.execute(f"SET ROLE {ddl_role}")


def count_db_records(start_date: datetime, end_date: datetime) -> int:
    """Počet záznamů v DB pro dané období."""
    if not HAS_DB:
        return 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        set_db_role(cursor)
        
        cursor.execute("""
            SELECT COUNT(*) FROM ailog_peak.peak_investigation
            WHERE timestamp >= %s AND timestamp <= %s
        """, (start_date, end_date))
        
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return count
    except Exception as e:
        print(f"⚠️ DB error: {e}")
        return 0


def delete_db_records(start_date: datetime, end_date: datetime, dry_run: bool = True) -> int:
    """Smaže záznamy z DB pro dané období."""
    if not HAS_DB:
        print("⚠️ No DB driver")
        return 0
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        set_db_role(cursor)
        
        if dry_run:
            cursor.execute("""
                SELECT COUNT(*) FROM ailog_peak.peak_investigation
                WHERE timestamp >= %s AND timestamp <= %s
            """, (start_date, end_date))
            count = cursor.fetchone()[0]
            cursor.close()
            conn.close()
            return count
        else:
            cursor.execute("""
                DELETE FROM ailog_peak.peak_investigation
                WHERE timestamp >= %s AND timestamp <= %s
            """, (start_date, end_date))
            count = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            return count
    except Exception as e:
        print(f"⚠️ DB error: {e}")
        return 0


def backup_registry(registry_dir: Path) -> Path:
    """Vytvoří backup registry."""
    if not registry_dir.exists():
        return None
    
    backup_name = f"backup_pre_reset_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_path = registry_dir / backup_name
    backup_path.mkdir(parents=True, exist_ok=True)
    
    for f in registry_dir.glob('*.yaml'):
        if 'backup' not in str(f):
            shutil.copy(f, backup_path / f.name)
    
    for f in registry_dir.glob('*.md'):
        if 'backup' not in str(f):
            shutil.copy(f, backup_path / f.name)
    
    return backup_path


def clear_registry(registry_dir: Path, dry_run: bool = True) -> bool:
    """Vymaže starou registry (připraví pro migraci)."""
    if dry_run:
        return True
    
    # Backup first
    backup_path = backup_registry(registry_dir)
    if backup_path:
        print(f"   📦 Backup: {backup_path}")
    
    # Remove old files (keep backups)
    for f in registry_dir.glob('known_errors.*'):
        f.unlink()
        print(f"   🗑️ Deleted: {f.name}")
    
    for f in registry_dir.glob('known_peaks.*'):
        if 'backup' not in str(f):
            f.unlink()
            print(f"   🗑️ Deleted: {f.name}")
    
    return True


def run_migration(registry_dir: Path, dry_run: bool = True) -> bool:
    """Spustí migraci registry."""
    from migrate_registry import run_migration as migrate, analyze_old_registry
    
    old_errors = registry_dir / 'known_errors.yaml'
    
    if old_errors.exists():
        if dry_run:
            print("\n📊 Analyzing old registry...")
            analyze_old_registry(str(registry_dir))
        else:
            print("\n🔄 Running migration...")
            result = migrate(str(registry_dir), str(registry_dir), backup=True)
            return result.get('success', False)
    else:
        print("   ℹ️ No old registry to migrate (starting fresh)")
    
    return True


def run_backfill(days: int, workers: int, dry_run: bool = True) -> dict:
    """Spustí backfill."""
    from backfill_v6 import run_backfill as backfill
    
    if dry_run:
        print(f"\n   Would run: backfill_v6.py --days {days} --workers {workers}")
        return {'dry_run': True}
    else:
        return backfill(
            days=days,
            workers=workers,
            skip_processed=False,  # Force reprocess
        )


def main():
    parser = argparse.ArgumentParser(
        description='Reset and Rerun - Clean restart with new registry system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --days 20                     Preview what would happen
  %(prog)s --days 20 --execute           Full reset and rerun
  %(prog)s --days 20 --execute --keep-db Keep DB data, only reset registry
  %(prog)s --days 20 --execute --keep-registry  Keep registry, only clear DB
        """
    )
    
    parser.add_argument('--days', type=int, default=20, help='Days to backfill')
    parser.add_argument('--workers', type=int, default=4, help='Parallel workers')
    parser.add_argument('--execute', action='store_true', help='Actually execute (not dry-run)')
    parser.add_argument('--keep-db', action='store_true', help='Keep DB data')
    parser.add_argument('--keep-registry', action='store_true', help='Keep registry')
    parser.add_argument('--registry-dir', type=str, default=None, help='Registry directory')
    
    args = parser.parse_args()
    
    dry_run = not args.execute
    registry_dir = Path(args.registry_dir) if args.registry_dir else SCRIPT_DIR.parent / 'registry'
    
    # Calculate date range
    now = datetime.now(timezone.utc)
    end_date = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    start_date = (now - timedelta(days=args.days)).replace(hour=0, minute=0, second=0, microsecond=0)
    
    print("=" * 70)
    print("🔄 RESET AND RERUN" + (" (DRY-RUN)" if dry_run else ""))
    print("=" * 70)
    
    print(f"\n📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    print(f"📁 Registry: {registry_dir}")
    print(f"👷 Workers: {args.workers}")
    
    # ==========================================================================
    # STEP 1: Check current state
    # ==========================================================================
    print("\n" + "-" * 70)
    print("📊 STEP 1: Current state")
    print("-" * 70)
    
    db_count = count_db_records(start_date, end_date)
    print(f"   DB records in range: {db_count:,}")
    
    old_errors = registry_dir / 'known_errors.yaml'
    if old_errors.exists():
        import yaml
        with open(old_errors, 'r') as f:
            old_data = yaml.safe_load(f) or []
        print(f"   Old registry entries: {len(old_data):,}")
    else:
        print("   Old registry: not found")
    
    new_problems = registry_dir / 'known_problems.yaml'
    if new_problems.exists():
        import yaml
        with open(new_problems, 'r') as f:
            new_data = yaml.safe_load(f) or []
        print(f"   New registry problems: {len(new_data):,}")
    else:
        print("   New registry: not found")
    
    # ==========================================================================
    # STEP 2: Clear DB (optional)
    # ==========================================================================
    if not args.keep_db:
        print("\n" + "-" * 70)
        print("🗑️ STEP 2: Clear DB records")
        print("-" * 70)
        
        if db_count > 0:
            if dry_run:
                print(f"   Would delete: {db_count:,} records")
            else:
                deleted = delete_db_records(start_date, end_date, dry_run=False)
                print(f"   ✅ Deleted: {deleted:,} records")
        else:
            print("   ℹ️ No records to delete")
    else:
        print("\n   ⏭️ Skipping DB cleanup (--keep-db)")
    
    # ==========================================================================
    # STEP 3: Migrate/Clear registry
    # ==========================================================================
    if not args.keep_registry:
        print("\n" + "-" * 70)
        print("📋 STEP 3: Migrate registry")
        print("-" * 70)
        
        if old_errors.exists() and not new_problems.exists():
            # Need migration
            run_migration(registry_dir, dry_run=dry_run)
        elif old_errors.exists() and new_problems.exists():
            # Both exist - probably already migrated
            print("   ℹ️ Both old and new registry exist")
            if not dry_run:
                # Clear old format
                backup_path = backup_registry(registry_dir)
                print(f"   📦 Backup: {backup_path}")
                old_errors.unlink()
                print("   🗑️ Removed old known_errors.yaml")
        else:
            print("   ℹ️ Registry ready (or starting fresh)")
    else:
        print("\n   ⏭️ Skipping registry reset (--keep-registry)")
    
    # ==========================================================================
    # STEP 4: Run backfill
    # ==========================================================================
    print("\n" + "-" * 70)
    print("🚀 STEP 4: Run backfill")
    print("-" * 70)
    
    if dry_run:
        print(f"\n   Would execute:")
        print(f"   python backfill_v6.py --days {args.days} --workers {args.workers} --force")
        print("\n   ⚠️  This is a DRY-RUN. Use --execute to actually run.")
    else:
        print(f"\n   Running backfill with {args.days} days, {args.workers} workers...")
        result = run_backfill(args.days, args.workers, dry_run=False)
        
        print("\n" + "=" * 70)
        print("✅ RESET AND RERUN COMPLETE")
        print("=" * 70)
        
        if result and not result.get('dry_run'):
            print(f"   Days processed: {result.get('days_processed', 'N/A')}")
            print(f"   Total incidents: {result.get('total_incidents', 'N/A')}")
            print(f"   Saved to DB: {result.get('total_saved', 'N/A')}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
