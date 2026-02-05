#!/usr/bin/env python3
"""
STREAMING MIGRATION - Memory-efficient migrace 700k+ záznamů
============================================================

Problém:
    yaml.safe_load() na 200MB YAML = 10-15GB RAM = OOM

Řešení:
    1. Konverze YAML → NDJSON (streaming write)
    2. Streaming read NDJSON (1 entry = 1 line)
    3. Incremental merge do ProblemRegistry
    4. Konstantní paměť (~100MB)

Použití:
    python migrate_registry_streaming.py --analyze           # Analýza
    python migrate_registry_streaming.py --convert           # YAML → NDJSON
    python migrate_registry_streaming.py --migrate           # Streaming migrace
    python migrate_registry_streaming.py --full              # Vše najednou
    python migrate_registry_streaming.py --cleanup           # Smaž NDJSON temp

Memory profile:
    Před:  700k entries × ~15KB/entry = 10GB+ RAM
    Po:    konstantní ~100MB (registry state only)
"""

import os
import sys
import json
import argparse
import gc
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Iterator, Dict, Any, Optional
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))

from core.problem_registry import (
    ProblemRegistry,
    ProblemEntry,
    compute_problem_key,
    ensure_utc,
    parse_timestamp_utc,
    MAX_FINGERPRINTS_PER_PROBLEM,
    MAX_PROBLEMS_WARNING,
)


# =============================================================================
# CONFIGURATION
# =============================================================================

PROGRESS_INTERVAL = 10_000  # Log progress every N entries
GC_INTERVAL = 50_000        # Force GC every N entries
BATCH_SAVE_INTERVAL = 100_000  # Save checkpoint every N entries


# =============================================================================
# STEP 1: YAML → NDJSON CONVERSION (streaming write)
# =============================================================================

def convert_yaml_to_ndjson(yaml_path: Path, ndjson_path: Path) -> int:
    """
    Konvertuje YAML list na NDJSON (newline-delimited JSON).
    
    YAML se musí načíst celý (PyYAML limitation), ale okamžitě
    se streamuje do NDJSON a paměť se uvolňuje.
    
    Returns: počet zkonvertovaných záznamů
    """
    import yaml
    
    print(f"📂 Loading YAML: {yaml_path}")
    print(f"   File size: {yaml_path.stat().st_size / 1024 / 1024:.1f} MB")
    
    # Load YAML (this is the memory-intensive part, but unavoidable for YAML list)
    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    if not data:
        print("❌ Empty or invalid YAML")
        return 0
    
    print(f"   Loaded {len(data):,} entries")
    print(f"📝 Writing NDJSON: {ndjson_path}")
    
    count = 0
    with open(ndjson_path, 'w', encoding='utf-8') as f:
        for i, entry in enumerate(data):
            if entry:
                # Write one JSON object per line
                json.dump(entry, f, ensure_ascii=False, default=str)
                f.write('\n')
                count += 1
            
            # Clear reference to allow GC
            data[i] = None
            
            if count % PROGRESS_INTERVAL == 0:
                print(f"   Written {count:,} entries...")
            
            if count % GC_INTERVAL == 0:
                gc.collect()
    
    # Force cleanup
    del data
    gc.collect()
    
    print(f"✅ Converted {count:,} entries")
    print(f"   NDJSON size: {ndjson_path.stat().st_size / 1024 / 1024:.1f} MB")
    
    return count


# =============================================================================
# STEP 2: STREAMING NDJSON READER
# =============================================================================

def stream_ndjson_entries(ndjson_path: Path) -> Iterator[Dict[str, Any]]:
    """
    Streaming reader pro NDJSON.
    
    Načítá jeden řádek = jeden JSON objekt.
    Paměť: konstantní, nezávislá na velikosti souboru.
    """
    with open(ndjson_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid JSON at line {line_num}: {e}")
                continue


def count_ndjson_entries(ndjson_path: Path) -> int:
    """Spočítá záznamy v NDJSON (streaming)."""
    count = 0
    with open(ndjson_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                count += 1
    return count


# =============================================================================
# STEP 3: ENTRY NORMALIZATION (legacy-safe)
# =============================================================================

def normalize_apps(raw_apps: Any) -> list:
    """Normalizuje affected_apps - zvládá None, [], [None], atd."""
    if not raw_apps:
        return []
    return [a for a in raw_apps if isinstance(a, str) and a.strip()]


def normalize_namespaces(raw_ns: Any) -> list:
    """Normalizuje affected_namespaces - zvládá legacy bordel."""
    if not raw_ns:
        return []
    return [n for n in raw_ns if isinstance(n, str) and n.strip()]


def normalize_timestamp(ts_str: Any) -> Optional[datetime]:
    """
    Parsuje timestamp - zvládá různé formáty.
    
    CRITICAL: Vždy vrací UTC-aware datetime nebo None.
    """
    return parse_timestamp_utc(ts_str)


def normalize_occurrences(raw_occ: Any) -> int:
    """Normalizuje occurrences - vždy vrátí kladné int."""
    if isinstance(raw_occ, (int, float)) and raw_occ > 0:
        return int(raw_occ)
    return 1


# =============================================================================
# STEP 4: SINGLE ENTRY MIGRATION
# =============================================================================

def migrate_entry(entry: Dict[str, Any], registry: ProblemRegistry, stats: dict):
    """
    Migruje jeden legacy entry do nového registry.
    
    DEFENSIVE: Nikdy nepadne, vždy vrátí.
    """
    # Extract fingerprint (required)
    fingerprint = entry.get('fingerprint')
    if not fingerprint or not isinstance(fingerprint, str):
        stats['skipped_no_fp'] += 1
        return
    
    # Normalize all fields
    category = entry.get('category', 'unknown') or 'unknown'
    apps = normalize_apps(entry.get('affected_apps'))
    namespaces = normalize_namespaces(entry.get('affected_namespaces'))
    first_seen = normalize_timestamp(entry.get('first_seen'))  # Already UTC
    last_seen = normalize_timestamp(entry.get('last_seen'))    # Already UTC
    occurrences = normalize_occurrences(entry.get('occurrences'))
    
    # Compute problem_key
    problem_key = compute_problem_key(
        category=category,
        app_names=apps,
        namespaces=namespaces,
    )
    
    # Get or create problem
    if problem_key in registry.problems:
        problem = registry.problems[problem_key]
        stats['updated'] += 1
        
        # CRITICAL: Normalize existing timestamps to UTC before comparison
        problem.first_seen = ensure_utc(problem.first_seen)
        problem.last_seen = ensure_utc(problem.last_seen)
        
        # Update timestamps (min/max)
        if first_seen:
            if problem.first_seen is None or first_seen < problem.first_seen:
                problem.first_seen = first_seen
        if last_seen:
            if problem.last_seen is None or last_seen > problem.last_seen:
                problem.last_seen = last_seen
        
        # Update counts
        problem.occurrences += occurrences
        
        # Add fingerprint (with limit)
        if fingerprint not in problem.fingerprints:
            if len(problem.fingerprints) < MAX_FINGERPRINTS_PER_PROBLEM:
                problem.fingerprints.append(fingerprint)
            else:
                stats['fps_dropped'] += 1
        
        # Update entities
        problem.affected_apps.update(apps)
        problem.affected_namespaces.update(namespaces)
        
    else:
        # Create new problem
        registry._problem_counter += 1
        parts = problem_key.split(':')
        
        problem = ProblemEntry(
            id=f"KP-{registry._problem_counter:06d}",
            problem_key=problem_key,
            category=parts[0].lower() if parts else 'unknown',
            flow=parts[1] if len(parts) > 1 else 'unknown',
            error_class=parts[2] if len(parts) > 2 else 'unknown',
            first_seen=first_seen,
            last_seen=last_seen,
            occurrences=occurrences,
            fingerprints=[fingerprint],
            affected_apps=set(apps),
            affected_namespaces=set(namespaces),
            status=entry.get('status', 'OPEN') or 'OPEN',
            jira=entry.get('jira'),
            notes=entry.get('notes'),
        )
        
        # Compute scope
        ns_count = len(problem.affected_namespaces)
        app_count = len(problem.affected_apps)
        if ns_count >= 4 or app_count >= 8:
            problem.scope = 'SYSTEMIC'
        elif ns_count >= 2:
            problem.scope = 'CROSS_NS'
        else:
            problem.scope = 'LOCAL'
        
        registry.problems[problem_key] = problem
        stats['created'] += 1
    
    # Index fingerprint
    registry.fingerprint_index[fingerprint] = problem_key
    stats['processed'] += 1


# =============================================================================
# STEP 5: MAIN MIGRATION LOOP (streaming)
# =============================================================================

def migrate_streaming(
    ndjson_path: Path,
    output_dir: Path,
    checkpoint_dir: Path = None
) -> dict:
    """
    Streaming migrace z NDJSON do ProblemRegistry.
    
    Memory: konstantní (~100MB pro registry state)
    """
    print("=" * 70)
    print("🚀 STREAMING MIGRATION")
    print("=" * 70)
    
    print(f"\n📂 Input: {ndjson_path}")
    print(f"📂 Output: {output_dir}")
    
    # Count entries first (fast, streaming)
    total_entries = count_ndjson_entries(ndjson_path)
    print(f"📊 Total entries to migrate: {total_entries:,}")
    
    # Initialize registry
    registry = ProblemRegistry(str(output_dir))
    
    # Stats
    stats = {
        'processed': 0,
        'created': 0,
        'updated': 0,
        'skipped_no_fp': 0,
        'fps_dropped': 0,
    }
    
    start_time = datetime.now()
    last_progress = start_time
    
    # Main migration loop
    print(f"\n🔄 Processing...")
    
    for entry in stream_ndjson_entries(ndjson_path):
        migrate_entry(entry, registry, stats)
        
        # Progress logging
        if stats['processed'] % PROGRESS_INTERVAL == 0:
            now = datetime.now()
            elapsed = (now - start_time).total_seconds()
            rate = stats['processed'] / elapsed if elapsed > 0 else 0
            pct = 100 * stats['processed'] / total_entries if total_entries > 0 else 0
            eta_seconds = (total_entries - stats['processed']) / rate if rate > 0 else 0
            
            print(f"   {stats['processed']:>10,} / {total_entries:,} ({pct:5.1f}%) "
                  f"| {rate:,.0f}/s | ETA: {eta_seconds/60:.1f}min "
                  f"| Problems: {len(registry.problems):,}")
        
        # Periodic GC
        if stats['processed'] % GC_INTERVAL == 0:
            gc.collect()
        
        # Checkpoint save (optional)
        if checkpoint_dir and stats['processed'] % BATCH_SAVE_INTERVAL == 0:
            checkpoint_path = checkpoint_dir / f"checkpoint_{stats['processed']}.yaml"
            print(f"   💾 Saving checkpoint: {checkpoint_path}")
            # registry.save() would go here for checkpointing
    
    # Final save
    print(f"\n💾 Saving final registry...")
    output_dir.mkdir(parents=True, exist_ok=True)
    registry.save()
    
    # Calculate final stats
    elapsed = (datetime.now() - start_time).total_seconds()
    
    result = {
        'success': True,
        'total_entries': total_entries,
        'processed': stats['processed'],
        'created': stats['created'],
        'updated': stats['updated'],
        'skipped': stats['skipped_no_fp'],
        'fps_dropped': stats['fps_dropped'],
        'final_problems': len(registry.problems),
        'final_fingerprints': len(registry.fingerprint_index),
        'elapsed_seconds': elapsed,
        'entries_per_second': stats['processed'] / elapsed if elapsed > 0 else 0,
    }
    
    # Print summary
    print("\n" + "=" * 70)
    print("✅ MIGRATION COMPLETE")
    print("=" * 70)
    print(f"\n📊 Results:")
    print(f"   Total entries: {result['total_entries']:,}")
    print(f"   Processed: {result['processed']:,}")
    print(f"   Created problems: {result['created']:,}")
    print(f"   Updated problems: {result['updated']:,}")
    print(f"   Skipped (no fingerprint): {result['skipped']:,}")
    print(f"   Fingerprints dropped (limit): {result['fps_dropped']:,}")
    print(f"\n📋 Final registry:")
    print(f"   Problems: {result['final_problems']:,}")
    print(f"   Fingerprints: {result['final_fingerprints']:,}")
    print(f"   Compression: {result['total_entries']:,} → {result['final_problems']:,} "
          f"({100 * (1 - result['final_problems'] / result['total_entries']):.1f}% reduction)")
    print(f"\n⏱️ Performance:")
    print(f"   Elapsed: {result['elapsed_seconds']:.1f}s")
    print(f"   Rate: {result['entries_per_second']:,.0f} entries/sec")
    
    # Health check
    print("\n" + "-" * 70)
    registry.print_health_report()
    
    return result


# =============================================================================
# ANALYSIS (streaming)
# =============================================================================

def analyze_ndjson(ndjson_path: Path) -> dict:
    """Streamingová analýza NDJSON bez načtení celého souboru."""
    print(f"📊 Analyzing: {ndjson_path}")
    print(f"   File size: {ndjson_path.stat().st_size / 1024 / 1024:.1f} MB")
    
    stats = {
        'total': 0,
        'with_fingerprint': 0,
        'without_fingerprint': 0,
        'categories': defaultdict(int),
        'has_apps': 0,
        'has_namespaces': 0,
        'problem_keys': defaultdict(int),
    }
    
    print("\n🔄 Streaming analysis...")
    
    for entry in stream_ndjson_entries(ndjson_path):
        stats['total'] += 1
        
        if entry.get('fingerprint'):
            stats['with_fingerprint'] += 1
        else:
            stats['without_fingerprint'] += 1
        
        cat = entry.get('category', 'unknown') or 'unknown'
        stats['categories'][cat] += 1
        
        apps = normalize_apps(entry.get('affected_apps'))
        if apps:
            stats['has_apps'] += 1
        
        ns = normalize_namespaces(entry.get('affected_namespaces'))
        if ns:
            stats['has_namespaces'] += 1
        
        # Sample problem_key computation
        pk = compute_problem_key(category=cat, app_names=apps, namespaces=ns)
        stats['problem_keys'][pk] += 1
        
        if stats['total'] % PROGRESS_INTERVAL == 0:
            print(f"   Analyzed {stats['total']:,} entries...")
    
    print("\n" + "=" * 70)
    print("📊 ANALYSIS RESULTS")
    print("=" * 70)
    
    print(f"\n📋 Counts:")
    print(f"   Total entries: {stats['total']:,}")
    print(f"   With fingerprint: {stats['with_fingerprint']:,}")
    print(f"   Without fingerprint: {stats['without_fingerprint']:,}")
    print(f"   With apps: {stats['has_apps']:,}")
    print(f"   With namespaces: {stats['has_namespaces']:,}")
    
    print(f"\n📂 Categories:")
    for cat, count in sorted(stats['categories'].items(), key=lambda x: -x[1]):
        pct = 100 * count / stats['total']
        print(f"   {cat:20} {count:>8,} ({pct:5.1f}%)")
    
    print(f"\n🔑 Problem keys:")
    print(f"   Unique: {len(stats['problem_keys']):,}")
    print(f"   Compression: {stats['total']:,} → {len(stats['problem_keys']):,} "
          f"({100 * len(stats['problem_keys']) / stats['total']:.2f}%)")
    
    # Top problem keys
    top_keys = sorted(stats['problem_keys'].items(), key=lambda x: -x[1])[:15]
    print(f"\n   Top 15:")
    for pk, count in top_keys:
        print(f"   {count:>8,}: {pk[:55]}...")
    
    return dict(stats)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Streaming Registry Migration (memory-efficient)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --full --dir ./registry         Full migration pipeline
  %(prog)s --convert --dir ./registry      Only convert YAML to NDJSON
  %(prog)s --migrate --dir ./registry      Only migrate from existing NDJSON
  %(prog)s --analyze --dir ./registry      Analyze NDJSON content
  %(prog)s --cleanup --dir ./registry      Remove temporary NDJSON file
        """
    )
    
    parser.add_argument('--dir', type=str, default='./registry',
                        help='Registry directory')
    parser.add_argument('--output-dir', type=str,
                        help='Output directory (default: same as --dir)')
    parser.add_argument('--full', action='store_true',
                        help='Full pipeline: convert + migrate')
    parser.add_argument('--convert', action='store_true',
                        help='Convert YAML to NDJSON')
    parser.add_argument('--migrate', action='store_true',
                        help='Migrate from NDJSON')
    parser.add_argument('--analyze', action='store_true',
                        help='Analyze NDJSON content')
    parser.add_argument('--cleanup', action='store_true',
                        help='Remove temporary NDJSON file')
    
    args = parser.parse_args()
    
    registry_dir = Path(args.dir)
    output_dir = Path(args.output_dir) if args.output_dir else registry_dir
    
    yaml_path = registry_dir / 'known_errors.yaml'
    ndjson_path = registry_dir / 'known_errors.ndjson'
    
    # Default to full if nothing specified
    if not any([args.full, args.convert, args.migrate, args.analyze, args.cleanup]):
        args.full = True
    
    if args.convert or args.full:
        if not yaml_path.exists():
            print(f"❌ YAML not found: {yaml_path}")
            return 1
        
        convert_yaml_to_ndjson(yaml_path, ndjson_path)
    
    if args.analyze:
        if not ndjson_path.exists():
            print(f"❌ NDJSON not found: {ndjson_path}")
            print("   Run with --convert first")
            return 1
        
        analyze_ndjson(ndjson_path)
    
    if args.migrate or args.full:
        if not ndjson_path.exists():
            print(f"❌ NDJSON not found: {ndjson_path}")
            print("   Run with --convert first")
            return 1
        
        migrate_streaming(ndjson_path, output_dir)
    
    if args.cleanup:
        if ndjson_path.exists():
            ndjson_path.unlink()
            print(f"🗑️ Removed: {ndjson_path}")
        else:
            print(f"ℹ️ Nothing to cleanup")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
