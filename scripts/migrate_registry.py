#!/usr/bin/env python3
"""
MIGRAČNÍ SKRIPT - Inteligentní sloučení 700k → stovky problem_keys
=====================================================================

Funkce:
1. Analýza starého formátu
2. Preview migrace bez změn
3. Inteligentní sloučení duplicit
4. Zachování metadata (timestamps, occurrences)
5. Health metriky po migraci

Použití:
    python migrate_registry.py --analyze                   # Analýza stavu
    python migrate_registry.py --dry-run                   # Preview migrace
    python migrate_registry.py --migrate                   # Spustit migraci
    python migrate_registry.py --health                    # Health check
"""

import os
import sys
import argparse
import yaml
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Any

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / 'core'))

from core.problem_registry import (
    ProblemRegistry,
    ProblemEntry,
    compute_problem_key,
    extract_flow,
    extract_error_class,
    MAX_FINGERPRINTS_PER_PROBLEM,
    MAX_PROBLEMS_WARNING,
)


# =============================================================================
# ANALYSIS
# =============================================================================

def analyze_old_registry(registry_dir: str) -> dict:
    """
    Detailní analýza starého formátu registry.
    
    Detekuje:
    - Velikost a distribuci
    - Duplicitní patterns
    - Timestamp anomálie
    - Potential problem_keys
    """
    old_path = Path(registry_dir)
    
    errors_file = old_path / 'known_errors.yaml'
    if not errors_file.exists():
        print(f"❌ File not found: {errors_file}")
        return {}
    
    print("📂 Loading old registry...")
    with open(errors_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or []
    
    print("=" * 70)
    print("📊 OLD REGISTRY ANALYSIS")
    print("=" * 70)
    
    print(f"\n📁 File: {errors_file}")
    print(f"📋 Total entries: {len(data):,}")
    
    # File size
    file_size = errors_file.stat().st_size
    print(f"💾 File size: {file_size / 1024 / 1024:.2f} MB")
    
    # ==========================================================================
    # CATEGORY DISTRIBUTION
    # ==========================================================================
    categories = defaultdict(int)
    for item in data:
        cat = item.get('category', 'unknown')
        categories[cat] += 1
    
    print(f"\n📂 By category:")
    if data:
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            pct = 100 * count / len(data)
            bar = "█" * int(pct / 2)
            print(f"   {cat:20} {count:>8,} ({pct:5.1f}%) {bar}")
    else:
        print("   (empty registry)")
    
    # ==========================================================================
    # PROBLEM KEY PROJECTION
    # ==========================================================================
    print("\n🔑 Computing problem_keys...")
    problem_keys = defaultdict(list)
    
    for item in data:
        fp = item.get('fingerprint', '')
        cat = item.get('category', 'unknown')
        apps = item.get('affected_apps', [])
        
        pk = compute_problem_key(
            category=cat,
            app_names=apps,
        )
        problem_keys[pk].append(fp)
    
    print(f"\n   Unique problem_keys: {len(problem_keys):,}")
    if len(data) > 0:
        print(f"   Compression ratio: {len(data):,} → {len(problem_keys):,} ({100 * len(problem_keys) / len(data):.1f}%)")
    else:
        print("   Compression ratio: N/A (empty registry)")

    # Distribution of fingerprints per problem_key
    fp_counts = [len(fps) for fps in problem_keys.values()]

    if fp_counts:
        print(f"\n📈 Fingerprints per problem_key:")
        print(f"   Min: {min(fp_counts)}")
        print(f"   Max: {max(fp_counts)}")
        print(f"   Avg: {sum(fp_counts) / len(fp_counts):.1f}")
        print(f"   Median: {sorted(fp_counts)[len(fp_counts) // 2]}")
    else:
        print("\n📈 Fingerprints per problem_key: N/A (no data)")
    
    if fp_counts:
        # How many would exceed limit
        over_limit = sum(1 for c in fp_counts if c > MAX_FINGERPRINTS_PER_PROBLEM)
        print(f"   Over {MAX_FINGERPRINTS_PER_PROBLEM} fps: {over_limit}")

        # Top problem_keys
        top_keys = sorted(problem_keys.items(), key=lambda x: -len(x[1]))[:15]
        print(f"\n🔝 Top 15 problem_keys by fingerprint count:")
        for pk, fps in top_keys:
            print(f"   {len(fps):>6,} fps: {pk[:60]}...")
    
    # ==========================================================================
    # TIMESTAMP ANALYSIS
    # ==========================================================================
    print("\n⏰ Timestamp analysis:")
    
    first_seens = []
    last_seens = []
    identical_ts = 0
    no_first_seen = 0
    
    for item in data:
        fs = item.get('first_seen')
        ls = item.get('last_seen')
        
        if not fs:
            no_first_seen += 1
            continue
        
        try:
            first_dt = datetime.fromisoformat(fs.replace('Z', '+00:00').replace('+00:00', ''))
            first_seens.append(first_dt)
        except:
            pass
        
        try:
            if ls:
                last_dt = datetime.fromisoformat(ls.replace('Z', '+00:00').replace('+00:00', ''))
                last_seens.append(last_dt)
        except:
            pass
        
        if fs == ls:
            identical_ts += 1
    
    if first_seens:
        print(f"   Earliest first_seen: {min(first_seens)}")
        print(f"   Latest first_seen: {max(first_seens)}")
    if last_seens:
        print(f"   Latest last_seen: {max(last_seens)}")
    
    print(f"   Missing first_seen: {no_first_seen:,}")

    if identical_ts > 0 and len(data) > 0:
        pct = 100 * identical_ts / len(data)
        print(f"\n   ⚠️  first_seen = last_seen: {identical_ts:,} ({pct:.1f}%)")
        if pct > 50:
            print("      This strongly suggests timestamps are from script run time!")
    
    # ==========================================================================
    # OCCURRENCE ANALYSIS
    # ==========================================================================
    print("\n📊 Occurrence analysis:")

    occurrences = [item.get('occurrences', 0) for item in data]
    unique_occ = sorted(set(occurrences)) if occurrences else []
    occ_counts = defaultdict(int)

    if occurrences:
        print(f"   Unique values: {len(unique_occ)}")
        print(f"   Min: {min(occurrences)}")
        print(f"   Max: {max(occurrences):,}")
        print(f"   Total: {sum(occurrences):,}")

        if len(unique_occ) < 30:
            print(f"   Distribution: {unique_occ[:20]}{'...' if len(unique_occ) > 20 else ''}")

            # Most common values
            for o in occurrences:
                occ_counts[o] += 1

            print(f"\n   Most common occurrence values:")
            for val, count in sorted(occ_counts.items(), key=lambda x: -x[1])[:5]:
                print(f"      {val}: {count:,} entries ({100 * count / len(data):.1f}%)")

            # If most entries have same occurrence value = likely counting runs
            if len(data) > 0 and max(occ_counts.values()) / len(data) > 0.5:
                print("\n   ⚠️  Most entries have same occurrence count!")
                print("      This suggests occurrences = number of runs, not actual events.")
    else:
        print("   (no data)")
    
    # ==========================================================================
    # APP/NAMESPACE ANALYSIS
    # ==========================================================================
    print("\n📱 Entity analysis:")
    
    all_apps = set()
    all_ns = set()
    for item in data:
        all_apps.update(item.get('affected_apps', []))
        all_ns.update(item.get('affected_namespaces', []))
    
    print(f"   Unique apps: {len(all_apps)}")
    print(f"   Unique namespaces: {len(all_ns)}")
    
    # ==========================================================================
    # SUMMARY
    # ==========================================================================
    result = {
        'total_entries': len(data),
        'file_size_mb': file_size / 1024 / 1024,
        'categories': dict(categories),
        'problem_keys_count': len(problem_keys),
        'compression_ratio': len(problem_keys) / len(data) if data else 0,
        'unique_apps': len(all_apps),
        'unique_namespaces': len(all_ns),
        'identical_timestamps': identical_ts,
        'identical_timestamps_pct': 100 * identical_ts / len(data) if data else 0,
        'timestamp_bug_likely': identical_ts / len(data) > 0.5 if data else False,
    }
    
    print("\n" + "=" * 70)
    print("📋 ANALYSIS SUMMARY")
    print("=" * 70)
    print(f"   Entries: {result['total_entries']:,}")
    print(f"   → Problem keys: {result['problem_keys_count']:,}")
    print(f"   Compression: {100 * (1 - result['compression_ratio']):.1f}%")
    
    issues = []
    if result['timestamp_bug_likely']:
        issues.append("Timestamps appear to be from run time, not event time")
    if occ_counts and len(unique_occ) < 30 and len(data) > 0 and max(occ_counts.values()) / len(data) > 0.5:
        issues.append("Occurrences appear to count runs, not events")
    
    if issues:
        print(f"\n   ⚠️  Issues detected:")
        for issue in issues:
            print(f"      • {issue}")
    
    return result


# =============================================================================
# MIGRATION
# =============================================================================

def preview_migration(old_dir: str) -> dict:
    """
    Preview migrace - zobrazí co by se stalo.
    """
    old_path = Path(old_dir)
    
    errors_file = old_path / 'known_errors.yaml'
    if not errors_file.exists():
        print(f"❌ File not found: {errors_file}")
        return {}
    
    print("📂 Loading registry for preview...")
    with open(errors_file, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or []
    
    # Group by problem_key
    problem_groups = defaultdict(lambda: {
        'fingerprints': [],
        'apps': set(),
        'namespaces': set(),
        'first_seen': None,
        'last_seen': None,
        'occurrences': 0,
        'category': None,
        'statuses': set(),
    })
    
    for item in data:
        fp = item.get('fingerprint', '')
        cat = item.get('category', 'unknown')
        apps = item.get('affected_apps', [])
        namespaces = item.get('affected_namespaces', [])
        
        pk = compute_problem_key(
            category=cat,
            app_names=apps,
        )
        
        group = problem_groups[pk]
        group['fingerprints'].append(fp)
        group['apps'].update(apps)
        group['namespaces'].update(namespaces)
        group['category'] = cat
        group['occurrences'] += item.get('occurrences', 1)
        group['statuses'].add(item.get('status', 'OPEN'))
        
        # Track timestamps (corrected: use min/max)
        if item.get('first_seen'):
            try:
                ts = datetime.fromisoformat(item['first_seen'].replace('Z', '+00:00').replace('+00:00', ''))
                if group['first_seen'] is None or ts < group['first_seen']:
                    group['first_seen'] = ts
            except:
                pass
        
        if item.get('last_seen'):
            try:
                ts = datetime.fromisoformat(item['last_seen'].replace('Z', '+00:00').replace('+00:00', ''))
                if group['last_seen'] is None or ts > group['last_seen']:
                    group['last_seen'] = ts
            except:
                pass
    
    print("=" * 70)
    print("📋 MIGRATION PREVIEW")
    print("=" * 70)
    
    print(f"\n Old entries: {len(data):,}")
    print(f" New problems: {len(problem_groups):,}")
    print(f" Reduction: {100 * (1 - len(problem_groups) / len(data)):.1f}%")
    
    # Sample output
    print(f"\n📝 Sample new entries (first 15):")
    print("-" * 70)
    
    sorted_groups = sorted(
        problem_groups.items(),
        key=lambda x: -len(x[1]['fingerprints'])
    )
    
    for i, (pk, group) in enumerate(sorted_groups[:15], 1):
        fp_count = len(group['fingerprints'])
        app_list = ', '.join(sorted(group['apps'])[:3])
        if len(group['apps']) > 3:
            app_list += '...'
        
        print(f"\n{i}. {pk}")
        print(f"   Fingerprints: {fp_count:,}")
        print(f"   Occurrences: {group['occurrences']:,}")
        print(f"   Apps: {len(group['apps'])} ({app_list})")
        print(f"   Namespaces: {', '.join(sorted(group['namespaces']))}")
        print(f"   First seen: {group['first_seen']}")
        print(f"   Last seen: {group['last_seen']}")
    
    return {
        'old_count': len(data),
        'new_count': len(problem_groups),
        'reduction_pct': 100 * (1 - len(problem_groups) / len(data)) if data else 0,
        'problem_groups': {pk: len(g['fingerprints']) for pk, g in sorted_groups[:50]},
    }


def run_migration(old_dir: str, new_dir: str = None, backup: bool = True) -> dict:
    """
    Spustí kompletní migraci.
    """
    old_path = Path(old_dir)
    new_path = Path(new_dir) if new_dir else old_path
    
    errors_file = old_path / 'known_errors.yaml'
    if not errors_file.exists():
        print(f"❌ File not found: {errors_file}")
        return {'success': False, 'error': 'File not found'}
    
    print("=" * 70)
    print("🔄 RUNNING MIGRATION")
    print("=" * 70)
    
    print(f"\n Old registry: {old_dir}")
    print(f" New registry: {new_path}")
    
    # Create backup
    if backup:
        backup_dir = old_path / f'backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        for f in old_path.glob('*.yaml'):
            shutil.copy(f, backup_dir / f.name)
        for f in old_path.glob('*.md'):
            shutil.copy(f, backup_dir / f.name)
        
        print(f"\n📦 Backup created: {backup_dir}")
    
    # Load old data
    print("\n📂 Loading old registry...")
    with open(errors_file, 'r', encoding='utf-8') as f:
        old_data = yaml.safe_load(f) or []
    
    print(f"   Loaded {len(old_data):,} entries")
    
    # Create new registry
    new_registry = ProblemRegistry(str(new_path))

    # Process entries
    print("\n🔄 Processing entries...")

    processed = 0
    skipped = 0

    # Mapping tracking for CSV export (old_id → problem_key)
    mapping_records = []
    
    for item in old_data:
        fingerprint = item.get('fingerprint')
        if not fingerprint:
            skipped += 1
            continue
        
        category = item.get('category', 'unknown')
        apps = item.get('affected_apps', [])
        namespaces = item.get('affected_namespaces', [])
        occurrences = item.get('occurrences', 1)
        
        # Parse timestamps
        first_seen = None
        last_seen = None
        
        if item.get('first_seen'):
            try:
                first_seen = datetime.fromisoformat(
                    item['first_seen'].replace('Z', '+00:00').replace('+00:00', '')
                )
            except:
                pass
        
        if item.get('last_seen'):
            try:
                last_seen = datetime.fromisoformat(
                    item['last_seen'].replace('Z', '+00:00').replace('+00:00', '')
                )
            except:
                pass
        
        # Compute problem_key
        problem_key = compute_problem_key(
            category=category,
            app_names=apps,
            namespaces=namespaces,
        )
        
        # Update or create problem
        if problem_key in new_registry.problems:
            problem = new_registry.problems[problem_key]
            
            # Update timestamps (min/max)
            if first_seen and (problem.first_seen is None or first_seen < problem.first_seen):
                problem.first_seen = first_seen
            if last_seen and (problem.last_seen is None or last_seen > problem.last_seen):
                problem.last_seen = last_seen
            
            # Update counts
            problem.occurrences += occurrences
            
            # Add fingerprint (with limit check)
            if fingerprint not in problem.fingerprints:
                if len(problem.fingerprints) < MAX_FINGERPRINTS_PER_PROBLEM:
                    problem.fingerprints.append(fingerprint)
            
            # Update entities
            problem.affected_apps.update(apps)
            problem.affected_namespaces.update(namespaces)
            
        else:
            # Create new problem
            new_registry._problem_counter += 1
            parts = problem_key.split(':')
            
            problem = ProblemEntry(
                id=f"KP-{new_registry._problem_counter:06d}",
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
                status=item.get('status', 'OPEN'),
                jira=item.get('jira'),
                notes=item.get('notes'),
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
            
            new_registry.problems[problem_key] = problem
        
        # Index fingerprint
        new_registry.fingerprint_index[fingerprint] = problem_key
        processed += 1

        # Track mapping for CSV export
        old_id = item.get('id', f'unknown-{processed}')
        new_problem_id = new_registry.problems[problem_key].id
        mapping_records.append({
            'old_id': old_id,
            'fingerprint': fingerprint,
            'category': category,
            'problem_key': problem_key,
            'new_problem_id': new_problem_id,
        })

        # Progress
        if processed % 10000 == 0:
            print(f"   Processed {processed:,}...")
    
    # Save new registry
    print("\n💾 Saving new registry...")
    new_registry.save()
    
    # Results
    result = {
        'success': True,
        'old_entries': len(old_data),
        'processed': processed,
        'skipped': skipped,
        'new_problems': len(new_registry.problems),
        'new_fingerprints': len(new_registry.fingerprint_index),
        'reduction_pct': 100 * (1 - len(new_registry.problems) / len(old_data)) if old_data else 0,
    }
    
    print("\n" + "=" * 70)
    print("✅ MIGRATION COMPLETE")
    print("=" * 70)
    print(f"\n   Old entries: {result['old_entries']:,}")
    print(f"   Processed: {result['processed']:,}")
    print(f"   Skipped: {result['skipped']:,}")
    print(f"\n   New problems: {result['new_problems']:,}")
    print(f"   Fingerprints indexed: {result['new_fingerprints']:,}")
    print(f"   Reduction: {result['reduction_pct']:.1f}%")
    
    # Print health report
    print("\n" + "-" * 70)
    new_registry.print_health_report()

    # Export mapping CSV for audit/validation
    if mapping_records:
        import csv
        csv_path = new_path / f'migration_mapping_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        with open(csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['old_id', 'fingerprint', 'category', 'problem_key', 'new_problem_id'])
            writer.writeheader()
            writer.writerows(mapping_records)
        print(f"\n📄 Mapping CSV exported: {csv_path}")
        print(f"   Records: {len(mapping_records):,}")
        result['mapping_csv'] = str(csv_path)

    return result


def check_health(registry_dir: str) -> dict:
    """
    Kontrola zdraví registry.
    """
    registry = ProblemRegistry(registry_dir)
    
    if not registry.load():
        print("❌ Failed to load registry")
        return {'success': False}
    
    return registry.print_health_report()


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Registry Migration Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --analyze                    Analyze current registry
  %(prog)s --dry-run                    Preview migration
  %(prog)s --migrate                    Run migration
  %(prog)s --migrate --no-backup        Run migration without backup
  %(prog)s --health                     Check registry health
  %(prog)s --dir ./my-registry          Use custom directory
        """
    )
    
    parser.add_argument('--dir', type=str, default='./registry',
                        help='Registry directory (default: ./registry)')
    parser.add_argument('--output-dir', type=str,
                        help='Output directory for migration (default: same as --dir)')
    parser.add_argument('--analyze', action='store_true',
                        help='Analyze old registry')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview migration')
    parser.add_argument('--migrate', action='store_true',
                        help='Run migration')
    parser.add_argument('--health', action='store_true',
                        help='Check registry health')
    parser.add_argument('--no-backup', action='store_true',
                        help='Skip backup during migration')
    parser.add_argument('--json', action='store_true',
                        help='Output as JSON')
    
    args = parser.parse_args()
    
    # Default action = analyze
    if not any([args.analyze, args.dry_run, args.migrate, args.health]):
        args.analyze = True
    
    result = {}
    
    if args.analyze:
        result = analyze_old_registry(args.dir)
    
    if args.dry_run:
        result = preview_migration(args.dir)
    
    if args.migrate:
        result = run_migration(
            args.dir,
            args.output_dir,
            backup=not args.no_backup
        )
    
    if args.health:
        result = check_health(args.dir)
    
    if args.json and result:
        # Clean result for JSON
        clean_result = {}
        for k, v in result.items():
            if isinstance(v, datetime):
                clean_result[k] = v.isoformat()
            elif isinstance(v, set):
                clean_result[k] = list(v)
            else:
                clean_result[k] = v
        print(json.dumps(clean_result, indent=2, default=str))
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
