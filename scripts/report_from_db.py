#!/usr/bin/env python3
"""
Report from DB - Usar existující registry a exportovat CSV

KRITICKÉ: 
- Jen ČTE existing registry (vytvořenou backfill nebo regular phází)
- Exportuje CSV do /app/scripts/exports/latest/
- NEMODIFIKUJE registry

Použití:
    python3 report_from_db.py --from "2026-02-01" --to "2026-02-06"
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))

# Imports
try:
    from core.problem_registry import ProblemRegistry
    from exports import TableExporter
    HAS_EXPORTS = True
except ImportError:
    HAS_EXPORTS = False


def safe_print(msg):
    """Thread-safe print."""
    print(msg, flush=True)


def main():
    parser = argparse.ArgumentParser(
        description='Export registry to CSV (read-only)'
    )
    parser.add_argument('--from', dest='date_from', help='Start date (unused)')
    parser.add_argument('--to', dest='date_to', help='End date (unused)')
    parser.add_argument('--output', type=str, help='Output directory')
    
    args = parser.parse_args()
    
    safe_print("=" * 70)
    safe_print("📊 REPORT FROM REGISTRY")
    safe_print("=" * 70)
    
    if args.date_from or args.date_to:
        safe_print(f"\n📅 Date range: {args.date_from or '?'} to {args.date_to or '?'}")
        safe_print("   (Dates are informational only - using full registry)")
    
    # Load registry (READ-ONLY)
    # IMPORTANT: Registry MUST be on persistence volume!
    registry_base = os.getenv('REGISTRY_DIR') or '/app/data/registry'
    registry_dir = Path(registry_base)
    try:
        registry = ProblemRegistry(str(registry_dir))
        registry.load()
        safe_print(f"\n📋 Registry loaded (READ-ONLY):")
        safe_print(f"   ✅ Problems: {len(registry.problems)}")
        safe_print(f"   ✅ Peaks: {len(registry.peaks)}")
        safe_print(f"   ✅ Known fingerprints: {len(registry.fingerprint_index)}")
        
        if len(registry.problems) == 0:
            safe_print("\n⚠️  Registry je prázdná! Spusť nejdřív backfill.")
            return 1
            
    except Exception as e:
        safe_print(f"\n❌ Registry load error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Export CSV
    if not HAS_EXPORTS:
        safe_print("   ⚠️  Exports module not available")
        return 1
    
    # CRITICAL: Always export to SCRIPT_DIR/exports
    exports_dir = SCRIPT_DIR / 'exports'
    safe_print(f"\n📊 Exporting tables to {exports_dir}...")
    
    try:
        exporter = TableExporter(registry)
        export_files = exporter.export_all(str(exports_dir))
        safe_print(f"   ✅ errors_table.csv/md/json")
        safe_print(f"   ✅ peaks_table.csv/md/json")
        
        # Verify files exist
        latest_dir = exports_dir / 'latest'
        if latest_dir.exists():
            errors_csv = latest_dir / 'errors_table.csv'
            peaks_csv = latest_dir / 'peaks_table.csv'
            
            if errors_csv.exists():
                size = errors_csv.stat().st_size
                safe_print(f"\n   📍 errors_table.csv: {size} bytes")
            else:
                safe_print(f"\n   ⚠️  errors_table.csv not found!")
                
            if peaks_csv.exists():
                size = peaks_csv.stat().st_size
                safe_print(f"   📍 peaks_table.csv: {size} bytes")
            else:
                safe_print(f"   ⚠️  peaks_table.csv not found!")
        
    except Exception as e:
        safe_print(f"   ❌ Export error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    safe_print("\n" + "=" * 70)
    safe_print("✅ REPORT FROM REGISTRY COMPLETE")
    safe_print("=" * 70)
    safe_print("\n📝 NOTE: Registry is READ-ONLY.")
    safe_print("   Data prepared for Confluence upload.")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
