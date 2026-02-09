#!/usr/bin/env python3
"""
Table Exporter - Operátorský view na Problem Registry
=====================================================

Export pravidla (V6.1):
- latest/   → VŽDY přepsat (overwrite) - aktuální snapshot
- daily/    → 1× denně, kontrola existence
- weekly/   → 1× týdně, kontrola existence

Struktura:
    exports/
    ├── latest/
    │   ├── errors_table.csv
    │   ├── errors_table.md
    │   ├── peaks_table.csv
    │   └── peaks_table.md
    ├── daily/
    │   ├── 2026-01-26-errors.md
    │   └── 2026-01-26-peaks.md
    └── weekly/
        └── 2026-W04-summary.md

NIKDY negenerovat timestamped soubory při 15min bězích!

Použití:
    from exports import TableExporter

    exporter = TableExporter(registry)
    exporter.export_latest('/path/to/exports')  # overwrite
    exporter.export_daily('/path/to/exports')   # once per day

CLI:
    python table_exporter.py --registry ../registry --output ./exports
"""

import os
import sys
import csv
import json
import argparse
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

# Add paths
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR.parent / 'core'))

from core.problem_registry import ProblemRegistry, ProblemEntry, PeakEntry


# =============================================================================
# DATA MODELS FOR EXPORT
# =============================================================================

@dataclass
class ErrorTableRow:
    """Řádek v errors_table - operátorský view (V6)"""
    problem_id: str
    problem_key: str
    category: str
    flow: str
    error_class: str
    affected_apps: str              # comma-separated (deployment labels)
    affected_namespaces: str        # comma-separated
    deployment_labels: str          # V6: explicitní deployment labels (app-v1, app-v2)
    app_versions: str               # V6: POUZE semantic versions (3.5.0, 3.5.1)
    fingerprint_count: int
    occurrences: int
    first_seen: str                 # ISO format
    last_seen: str                  # ISO format
    age_days: int
    last_seen_days_ago: int
    scope: str                      # LOCAL, CROSS_NS, SYSTEMIC
    status: str                     # OPEN, MONITORING, RESOLVED
    jira: str                       # Jira ticket link
    notes: str                      # Human notes


@dataclass
class PeakTableRow:
    """Řádek v peaks_table - operátorský view"""
    peak_id: str
    problem_key: str
    category: str
    peak_type: str              # SPIKE, BURST, SUSTAINED
    affected_apps: str
    affected_namespaces: str
    peak_count: int
    baseline_rate: float
    peak_ratio: float
    first_seen: str
    last_seen: str
    occurrence_count: int
    status: str


# =============================================================================
# TABLE EXPORTER
# =============================================================================

class TableExporter:
    """
    Exportuje Problem Registry do tabulkových formátů.

    Generuje OPERÁTORSKÝ VIEW - ne raw data, ale:
    - Agregované metriky
    - Human-readable formáty
    - Filtrovatelné sloupce
    """

    def __init__(self, registry: ProblemRegistry):
        self.registry = registry
        self.generated_at = datetime.now(timezone.utc)

    @staticmethod
    def _ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    # =========================================================================
    # ERRORS TABLE
    # =========================================================================

    def get_errors_rows(self) -> List[ErrorTableRow]:
        """Převede Problem Registry na řádky tabulky."""
        rows = []
        now = datetime.now(timezone.utc)

        for problem_key, problem in self.registry.problems.items():
            # Calculate age
            age_days = 0
            last_seen_days = 0

            first_seen = self._ensure_aware(problem.first_seen)
            last_seen = self._ensure_aware(problem.last_seen)

            if first_seen:
                age_days = (now - first_seen).days
            if last_seen:
                last_seen_days = (now - last_seen).days

            # V6: Separate deployment_labels from app_versions
            deployment_labels = ", ".join(sorted(problem.deployments_seen)[:10]) if problem.deployments_seen else ""
            app_versions = ", ".join(sorted(problem.app_versions_seen)[:5]) if problem.app_versions_seen else ""

            row = ErrorTableRow(
                problem_id=problem.id,
                problem_key=problem_key,
                category=problem.category,
                flow=problem.flow,
                error_class=problem.error_class,
                affected_apps=", ".join(sorted(problem.affected_apps)[:10]),
                affected_namespaces=", ".join(sorted(problem.affected_namespaces)),
                deployment_labels=deployment_labels,  # V6
                app_versions=app_versions,            # V6: ONLY semantic versions
                fingerprint_count=len(problem.fingerprints),
                occurrences=problem.occurrences,
                first_seen=first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "",
                last_seen=last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "",
                age_days=age_days,
                last_seen_days_ago=last_seen_days,
                scope=problem.scope,
                status=problem.status,
                jira=problem.jira or "",
                notes=problem.notes or "",
            )
            rows.append(row)

        # Sort by last_seen DESC (most recent first)
        rows.sort(key=lambda r: r.last_seen or "", reverse=True)

        return rows

    def export_errors_csv(self, output_path: str) -> str:
        """Export errors jako CSV."""
        rows = self.get_errors_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', newline='', encoding='utf-8') as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow(asdict(row))
            else:
                # Empty file with headers (V6 schema)
                writer = csv.DictWriter(f, fieldnames=[
                    'problem_id', 'problem_key', 'category', 'flow', 'error_class',
                    'affected_apps', 'affected_namespaces', 'deployment_labels', 'app_versions',
                    'fingerprint_count', 'occurrences', 'first_seen', 'last_seen',
                    'age_days', 'last_seen_days_ago', 'scope', 'status', 'jira', 'notes'
                ])
                writer.writeheader()

        return str(path)

    def export_errors_markdown(self, output_path: str) -> str:
        """Export errors jako Markdown tabulka."""
        rows = self.get_errors_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# Error Problems Table",
            f"",
            f"**Generated:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total problems:** {len(rows)}",
            f"",
        ]

        if rows:
            # Summary by category
            by_category = {}
            for row in rows:
                by_category[row.category] = by_category.get(row.category, 0) + 1

            lines.append("## Summary by Category")
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|----------|-------|")
            for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
                lines.append(f"| {cat} | {count} |")
            lines.append("")

            # Summary by scope
            by_scope = {}
            for row in rows:
                by_scope[row.scope] = by_scope.get(row.scope, 0) + 1

            lines.append("## Summary by Scope")
            lines.append("")
            lines.append("| Scope | Count |")
            lines.append("|-------|-------|")
            for scope, count in sorted(by_scope.items(), key=lambda x: -x[1]):
                lines.append(f"| {scope} | {count} |")
            lines.append("")

            # Main table (compact version)
            lines.append("## All Problems")
            lines.append("")
            lines.append("| ID | Category | Flow | Apps | Occurrences | Last Seen | Status |")
            lines.append("|-------|----------|------|------|-------------|-----------|--------|")

            for row in rows:
                apps_short = row.affected_apps[:30] + "..." if len(row.affected_apps) > 30 else row.affected_apps
                last_seen_short = row.last_seen[:10] if row.last_seen else "-"
                lines.append(
                    f"| {row.problem_id} | {row.category} | {row.flow} | "
                    f"{apps_short} | {row.occurrences:,} | {last_seen_short} | {row.status} |"
                )

            # Detailed section for recent problems
            recent_rows = [r for r in rows if r.last_seen_days_ago <= 7]
            if recent_rows:
                lines.append("")
                lines.append("## Recent Problems (last 7 days)")
                lines.append("")

                for row in recent_rows[:20]:
                    lines.append(f"### {row.problem_id}: {row.category}/{row.flow}")
                    lines.append("")
                    lines.append(f"- **Error class:** {row.error_class}")
                    lines.append(f"- **Scope:** {row.scope}")
                    lines.append(f"- **Occurrences:** {row.occurrences:,}")
                    lines.append(f"- **Apps:** {row.affected_apps}")
                    lines.append(f"- **Namespaces:** {row.affected_namespaces}")
                    if row.app_versions:
                        lines.append(f"- **Versions:** {row.app_versions}")
                    lines.append(f"- **First seen:** {row.first_seen}")
                    lines.append(f"- **Last seen:** {row.last_seen}")
                    if row.jira:
                        lines.append(f"- **Jira:** {row.jira}")
                    if row.notes:
                        lines.append(f"- **Notes:** {row.notes}")
                    lines.append("")
        else:
            lines.append("*No problems in registry.*")

        with open(path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

        return str(path)

    def export_errors_json(self, output_path: str) -> str:
        """Export errors jako JSON."""
        rows = self.get_errors_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'generated_at': self.generated_at.isoformat(),
            'total_problems': len(rows),
            'summary': {
                'by_category': {},
                'by_scope': {},
                'by_status': {},
            },
            'problems': [asdict(row) for row in rows],
        }

        # Build summaries
        for row in rows:
            data['summary']['by_category'][row.category] = data['summary']['by_category'].get(row.category, 0) + 1
            data['summary']['by_scope'][row.scope] = data['summary']['by_scope'].get(row.scope, 0) + 1
            data['summary']['by_status'][row.status] = data['summary']['by_status'].get(row.status, 0) + 1

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return str(path)

    # =========================================================================
    # PEAKS TABLE
    # =========================================================================

    def get_peaks_rows(self) -> List[PeakTableRow]:
        """Převede Peak Registry na řádky tabulky."""
        rows = []

        for problem_key, peak in self.registry.peaks.items():
            first_seen = self._ensure_aware(peak.first_seen)
            last_seen = self._ensure_aware(peak.last_seen)
            
            # Extract category from problem_key (format: "category:flow:peak_type")
            category = problem_key.split(':')[0] if ':' in problem_key else 'unknown'
            
            row = PeakTableRow(
                peak_id=peak.id,
                problem_key=problem_key,
                category=category,
                peak_type=peak.peak_type,
                affected_apps=", ".join(sorted(peak.affected_apps)[:10]),
                affected_namespaces=", ".join(sorted(peak.affected_namespaces)),
                peak_count=peak.occurrences,
                baseline_rate=peak.max_value,
                peak_ratio=peak.max_ratio,
                first_seen=first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "",
                last_seen=last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "",
                occurrence_count=peak.occurrences,
                status=peak.status,
            )
            rows.append(row)

        # Sort by last_seen DESC
        rows.sort(key=lambda r: r.last_seen or "", reverse=True)

        return rows

    def export_peaks_csv(self, output_path: str) -> str:
        """Export peaks jako CSV."""
        rows = self.get_peaks_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', newline='', encoding='utf-8') as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
                writer.writeheader()
                for row in rows:
                    writer.writerow(asdict(row))
            else:
                writer = csv.DictWriter(f, fieldnames=[
                    'peak_id', 'problem_key', 'category', 'peak_type',
                    'affected_apps', 'affected_namespaces', 'peak_count',
                    'baseline_rate', 'peak_ratio', 'first_seen', 'last_seen',
                    'occurrence_count', 'status'
                ])
                writer.writeheader()

        return str(path)

    def export_peaks_markdown(self, output_path: str) -> str:
        """Export peaks jako Markdown."""
        rows = self.get_peaks_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# Peak Events Table",
            f"",
            f"**Generated:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total peaks:** {len(rows)}",
            f"",
        ]

        if rows:
            lines.append("| ID | Category | Type | Apps | Peak Ratio | Last Seen | Status |")
            lines.append("|-------|----------|------|------|------------|-----------|--------|")

            for row in rows:
                apps_short = row.affected_apps[:25] + "..." if len(row.affected_apps) > 25 else row.affected_apps
                lines.append(
                    f"| {row.peak_id} | {row.category} | {row.peak_type} | "
                    f"{apps_short} | {row.peak_ratio:.1f}x | {row.last_seen[:10] if row.last_seen else '-'} | {row.status} |"
                )
        else:
            lines.append("*No peaks in registry.*")

        with open(path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

        return str(path)

    def export_peaks_json(self, output_path: str) -> str:
        """Export peaks jako JSON."""
        rows = self.get_peaks_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'generated_at': self.generated_at.isoformat(),
            'total_peaks': len(rows),
            'peaks': [asdict(row) for row in rows],
        }

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return str(path)

    # =========================================================================
    # ATOMIC WRITE HELPER
    # =========================================================================

    def _write_atomic(self, path: Path, content: str) -> None:
        """
        Atomic write - tmp soubor + rename.
        Safe při crashi, zajistí konzistenci.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write to temp file in same directory (same filesystem for atomic rename)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
            os.replace(tmp_path, path)  # Atomic on POSIX
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # =========================================================================
    # LATEST EXPORTS (OVERWRITE)
    # =========================================================================

    def export_latest(self, output_dir: str) -> Dict[str, str]:
        """
        Exportuje do latest/ složky - VŽDY přepíše.

        Toto je DEFAULT pro 15-min běhy.
        Odpovídá na otázku: "Jaký je stav TEĎ?"

        Struktura:
            exports/latest/
            ├── errors_table.csv
            ├── errors_table.md
            ├── errors_table.json
            ├── peaks_table.csv
            ├── peaks_table.md
            └── peaks_table.json
        """
        latest_dir = Path(output_dir) / 'latest'
        latest_dir.mkdir(parents=True, exist_ok=True)

        files = {}

        # Errors - atomic overwrite
        files['errors_csv'] = self.export_errors_csv(latest_dir / 'errors_table.csv')
        files['errors_md'] = self.export_errors_markdown(latest_dir / 'errors_table.md')
        files['errors_json'] = self.export_errors_json(latest_dir / 'errors_table.json')

        # Peaks - atomic overwrite
        files['peaks_csv'] = self.export_peaks_csv(latest_dir / 'peaks_table.csv')
        files['peaks_md'] = self.export_peaks_markdown(latest_dir / 'peaks_table.md')
        files['peaks_json'] = self.export_peaks_json(latest_dir / 'peaks_table.json')

        return files

    # =========================================================================
    # DAILY EXPORTS (ONCE PER DAY)
    # =========================================================================

    def export_daily(self, output_dir: str, force: bool = False) -> Dict[str, str]:
        """
        Exportuje do daily/ složky - pouze 1× denně.

        Kontroluje existenci souboru před zápisem.
        force=True přepíše i existující.

        Struktura:
            exports/daily/
            ├── 2026-01-26-errors.csv
            ├── 2026-01-26-errors.md
            ├── 2026-01-26-peaks.csv
            └── 2026-01-26-peaks.md
        """
        daily_dir = Path(output_dir) / 'daily'
        daily_dir.mkdir(parents=True, exist_ok=True)

        date_str = self.generated_at.strftime('%Y-%m-%d')
        files = {}

        # Errors
        errors_csv = daily_dir / f'{date_str}-errors.csv'
        errors_md = daily_dir / f'{date_str}-errors.md'

        if force or not errors_csv.exists():
            files['errors_csv'] = self.export_errors_csv(errors_csv)
        if force or not errors_md.exists():
            files['errors_md'] = self.export_errors_markdown(errors_md)

        # Peaks
        peaks_csv = daily_dir / f'{date_str}-peaks.csv'
        peaks_md = daily_dir / f'{date_str}-peaks.md'

        if force or not peaks_csv.exists():
            files['peaks_csv'] = self.export_peaks_csv(peaks_csv)
        if force or not peaks_md.exists():
            files['peaks_md'] = self.export_peaks_markdown(peaks_md)

        return files

    # =========================================================================
    # WEEKLY EXPORTS (ONCE PER WEEK)
    # =========================================================================

    def export_weekly(self, output_dir: str, force: bool = False) -> Dict[str, str]:
        """
        Exportuje do weekly/ složky - pouze 1× týdně (summary).

        Struktura:
            exports/weekly/
            └── 2026-W04-summary.md
        """
        weekly_dir = Path(output_dir) / 'weekly'
        weekly_dir.mkdir(parents=True, exist_ok=True)

        week_str = self.generated_at.strftime('%Y-W%W')
        files = {}

        summary_path = weekly_dir / f'{week_str}-summary.md'

        if force or not summary_path.exists():
            files['summary'] = self._export_weekly_summary(summary_path)

        return files

    def _export_weekly_summary(self, output_path: Path) -> str:
        """Generuje týdenní summary report."""
        errors_rows = self.get_errors_rows()
        peaks_rows = self.get_peaks_rows()

        # Filter to last 7 days
        week_ago = self.generated_at - timedelta(days=7)
        recent_errors = [r for r in errors_rows if r.last_seen_days_ago <= 7]
        recent_peaks = [r for r in peaks_rows
                        if r.last_seen and datetime.strptime(r.last_seen, "%Y-%m-%d %H:%M").replace(tzinfo=None) > week_ago.replace(tzinfo=None)]

        lines = [
            f"# Weekly Summary - {self.generated_at.strftime('%Y-W%W')}",
            f"",
            f"**Generated:** {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Period:** {week_ago.strftime('%Y-%m-%d')} to {self.generated_at.strftime('%Y-%m-%d')}",
            f"",
            f"## Overview",
            f"",
            f"- **Total problems:** {len(errors_rows)}",
            f"- **Active this week:** {len(recent_errors)}",
            f"- **Total peaks:** {len(peaks_rows)}",
            f"- **Peaks this week:** {len(recent_peaks)}",
            f"",
        ]

        # Category breakdown for active problems
        if recent_errors:
            by_cat = {}
            for r in recent_errors:
                by_cat[r.category] = by_cat.get(r.category, 0) + 1

            lines.append("## Active Problems by Category")
            lines.append("")
            lines.append("| Category | Count |")
            lines.append("|----------|-------|")
            for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
                lines.append(f"| {cat} | {cnt} |")
            lines.append("")

        # Top 10 by occurrences this week
        if recent_errors:
            lines.append("## Top 10 Most Frequent (This Week)")
            lines.append("")
            top10 = sorted(recent_errors, key=lambda r: r.occurrences, reverse=True)[:10]
            for i, r in enumerate(top10, 1):
                lines.append(f"{i}. **{r.problem_key}** - {r.occurrences:,} occurrences")
            lines.append("")

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

        return str(output_path)

    # =========================================================================
    # EXPORT ALL (BACKWARD COMPAT - NOW CALLS LATEST)
    # =========================================================================

    def export_all(self, output_dir: str) -> Dict[str, str]:
        """
        DEPRECATED: Pro zpětnou kompatibilitu.
        Volá export_latest() - VŽDY overwrite.

        Pro nové implementace používej přímo:
        - export_latest()  pro 15-min běhy
        - export_daily()   pro denní snapshot
        - export_weekly()  pro týdenní report
        """
        return self.export_latest(output_dir)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def export_latest(registry: ProblemRegistry, output_dir: str) -> Dict[str, str]:
    """
    Hlavní funkce pro 15-min běhy.
    Exportuje do latest/ - VŽDY overwrite.
    """
    exporter = TableExporter(registry)
    return exporter.export_latest(output_dir)


def export_daily(registry: ProblemRegistry, output_dir: str, force: bool = False) -> Dict[str, str]:
    """
    Funkce pro denní snapshot.
    Exportuje do daily/ - pouze 1× denně.
    """
    exporter = TableExporter(registry)
    return exporter.export_daily(output_dir, force=force)


def export_weekly(registry: ProblemRegistry, output_dir: str, force: bool = False) -> Dict[str, str]:
    """
    Funkce pro týdenní report.
    Exportuje do weekly/ - pouze 1× týdně.
    """
    exporter = TableExporter(registry)
    return exporter.export_weekly(output_dir, force=force)


# Backward compatibility aliases
def export_errors_table(registry: ProblemRegistry, output_dir: str) -> Dict[str, str]:
    """DEPRECATED: Použij export_latest()."""
    return export_latest(registry, output_dir)


def export_peaks_table(registry: ProblemRegistry, output_dir: str) -> Dict[str, str]:
    """DEPRECATED: Použij export_latest()."""
    return export_latest(registry, output_dir)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Export Problem Registry to tables (CSV, MD, JSON)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Export Modes:
  latest  - VŽDY overwrite (default, pro 15-min běhy)
  daily   - 1× denně, kontrola existence
  weekly  - 1× týdně, summary report
  all     - latest + daily + weekly

Struktura výstupu:
  exports/
  ├── latest/        ← overwrite
  │   ├── errors_table.csv
  │   ├── errors_table.md
  │   └── peaks_table.*
  ├── daily/         ← once per day
  │   └── 2026-01-26-errors.*
  └── weekly/        ← once per week
      └── 2026-W04-summary.md

Examples:
  %(prog)s --registry ../registry --output ./exports
  %(prog)s --registry ../registry --output ./exports --mode daily
  %(prog)s --registry ../registry --output ./exports --mode all --force
        """
    )

    parser.add_argument('--registry', type=str, default='../registry',
                        help='Registry directory (default: ../registry)')
    parser.add_argument('--output', type=str, default='./exports',
                        help='Output directory (default: ./exports)')
    parser.add_argument('--mode', type=str,
                        choices=['latest', 'daily', 'weekly', 'all'],
                        default='latest',
                        help='Export mode (default: latest)')
    parser.add_argument('--force', action='store_true',
                        help='Force overwrite daily/weekly even if exists')

    args = parser.parse_args()

    # Load registry
    print(f"Loading registry from {args.registry}...")
    registry = ProblemRegistry(args.registry)

    if not registry.load():
        print("Registry empty or not found, creating empty tables...")

    print(f"   Problems: {len(registry.problems)}")
    print(f"   Peaks: {len(registry.peaks)}")

    # Export
    exporter = TableExporter(registry)
    all_files = {}

    if args.mode in ('latest', 'all'):
        print(f"\nExporting to latest/ (overwrite)...")
        files = exporter.export_latest(args.output)
        all_files.update({f'latest_{k}': v for k, v in files.items()})
        print(f"   {len(files)} files written")

    if args.mode in ('daily', 'all'):
        print(f"\nExporting to daily/ (once per day)...")
        files = exporter.export_daily(args.output, force=args.force)
        if files:
            all_files.update({f'daily_{k}': v for k, v in files.items()})
            print(f"   {len(files)} files written")
        else:
            print(f"   Skipped (already exists, use --force to overwrite)")

    if args.mode in ('weekly', 'all'):
        print(f"\nExporting to weekly/ (once per week)...")
        files = exporter.export_weekly(args.output, force=args.force)
        if files:
            all_files.update({f'weekly_{k}': v for k, v in files.items()})
            print(f"   {len(files)} files written")
        else:
            print(f"   Skipped (already exists, use --force to overwrite)")

    print(f"\nDone. Total: {len(all_files)} files")

    return 0


if __name__ == '__main__':
    sys.exit(main())
