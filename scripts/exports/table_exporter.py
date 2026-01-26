#!/usr/bin/env python3
"""
Table Exporter - Operátorský view na Problem Registry
=====================================================

Generuje filtrovatelné tabulky:
- errors_table.csv  → Excel, Jira import
- errors_table.md   → human-readable
- errors_table.json → API, další zpracování

Zdroj dat:
- ProblemRegistry (known_problems.yaml)
- PeakRegistry (known_peaks.yaml)
- Runtime incident snapshot (optional)

Použití:
    from exports import TableExporter

    exporter = TableExporter(registry)
    exporter.export_all('/path/to/output')

    # Nebo jednotlivě:
    exporter.export_csv('/path/to/errors_table.csv')
    exporter.export_markdown('/path/to/errors_table.md')
    exporter.export_json('/path/to/errors_table.json')

CLI:
    python table_exporter.py --registry ../registry --output ./exports
"""

import os
import sys
import csv
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
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
        self.generated_at = datetime.now()

    # =========================================================================
    # ERRORS TABLE
    # =========================================================================

    def get_errors_rows(self) -> List[ErrorTableRow]:
        """Převede Problem Registry na řádky tabulky."""
        rows = []
        now = datetime.now()

        for problem_key, problem in self.registry.problems.items():
            # Calculate age
            age_days = 0
            last_seen_days = 0

            if problem.first_seen:
                age_days = (now - problem.first_seen).days
            if problem.last_seen:
                last_seen_days = (now - problem.last_seen).days

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
                first_seen=problem.first_seen.strftime("%Y-%m-%d %H:%M") if problem.first_seen else "",
                last_seen=problem.last_seen.strftime("%Y-%m-%d %H:%M") if problem.last_seen else "",
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
            row = PeakTableRow(
                peak_id=peak.id,
                problem_key=problem_key,
                category=peak.category,
                peak_type=peak.peak_type,
                affected_apps=", ".join(sorted(peak.affected_apps)[:10]),
                affected_namespaces=", ".join(sorted(peak.affected_namespaces)),
                peak_count=peak.peak_count,
                baseline_rate=peak.baseline_rate,
                peak_ratio=peak.peak_ratio,
                first_seen=peak.first_seen.strftime("%Y-%m-%d %H:%M") if peak.first_seen else "",
                last_seen=peak.last_seen.strftime("%Y-%m-%d %H:%M") if peak.last_seen else "",
                occurrence_count=peak.occurrence_count,
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
    # EXPORT ALL
    # =========================================================================

    def export_all(self, output_dir: str) -> Dict[str, str]:
        """
        Exportuje všechny tabulky do output_dir.

        Returns:
            Dict s cestami k vygenerovaným souborům.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = self.generated_at.strftime('%Y%m%d_%H%M%S')

        files = {}

        # Errors tables
        files['errors_csv'] = self.export_errors_csv(output_path / f'errors_table_{timestamp}.csv')
        files['errors_md'] = self.export_errors_markdown(output_path / f'errors_table_{timestamp}.md')
        files['errors_json'] = self.export_errors_json(output_path / f'errors_table_{timestamp}.json')

        # Also create "latest" symlinks/copies
        files['errors_csv_latest'] = self.export_errors_csv(output_path / 'errors_table_latest.csv')
        files['errors_md_latest'] = self.export_errors_markdown(output_path / 'errors_table_latest.md')
        files['errors_json_latest'] = self.export_errors_json(output_path / 'errors_table_latest.json')

        # Peaks tables
        files['peaks_csv'] = self.export_peaks_csv(output_path / f'peaks_table_{timestamp}.csv')
        files['peaks_md'] = self.export_peaks_markdown(output_path / f'peaks_table_{timestamp}.md')
        files['peaks_json'] = self.export_peaks_json(output_path / f'peaks_table_{timestamp}.json')

        files['peaks_csv_latest'] = self.export_peaks_csv(output_path / 'peaks_table_latest.csv')
        files['peaks_md_latest'] = self.export_peaks_markdown(output_path / 'peaks_table_latest.md')
        files['peaks_json_latest'] = self.export_peaks_json(output_path / 'peaks_table_latest.json')

        return files


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def export_errors_table(registry: ProblemRegistry, output_dir: str) -> Dict[str, str]:
    """Convenience function - exportuje jen errors tabulky."""
    exporter = TableExporter(registry)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    return {
        'csv': exporter.export_errors_csv(output_path / f'errors_table_{timestamp}.csv'),
        'md': exporter.export_errors_markdown(output_path / f'errors_table_{timestamp}.md'),
        'json': exporter.export_errors_json(output_path / f'errors_table_{timestamp}.json'),
        'csv_latest': exporter.export_errors_csv(output_path / 'errors_table_latest.csv'),
        'md_latest': exporter.export_errors_markdown(output_path / 'errors_table_latest.md'),
        'json_latest': exporter.export_errors_json(output_path / 'errors_table_latest.json'),
    }


def export_peaks_table(registry: ProblemRegistry, output_dir: str) -> Dict[str, str]:
    """Convenience function - exportuje jen peaks tabulky."""
    exporter = TableExporter(registry)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    return {
        'csv': exporter.export_peaks_csv(output_path / f'peaks_table_{timestamp}.csv'),
        'md': exporter.export_peaks_markdown(output_path / f'peaks_table_{timestamp}.md'),
        'json': exporter.export_peaks_json(output_path / f'peaks_table_{timestamp}.json'),
        'csv_latest': exporter.export_peaks_csv(output_path / 'peaks_table_latest.csv'),
        'md_latest': exporter.export_peaks_markdown(output_path / 'peaks_table_latest.md'),
        'json_latest': exporter.export_peaks_json(output_path / 'peaks_table_latest.json'),
    }


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Export Problem Registry to tables (CSV, MD, JSON)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --registry ../registry --output ./exports
  %(prog)s --registry ../registry --output ./exports --format csv
  %(prog)s --registry ../registry --output ./exports --errors-only
        """
    )

    parser.add_argument('--registry', type=str, default='../registry',
                        help='Registry directory (default: ../registry)')
    parser.add_argument('--output', type=str, default='./exports',
                        help='Output directory (default: ./exports)')
    parser.add_argument('--format', type=str, choices=['all', 'csv', 'md', 'json'], default='all',
                        help='Output format (default: all)')
    parser.add_argument('--errors-only', action='store_true',
                        help='Export only errors table')
    parser.add_argument('--peaks-only', action='store_true',
                        help='Export only peaks table')

    args = parser.parse_args()

    # Load registry
    print(f"📂 Loading registry from {args.registry}...")
    registry = ProblemRegistry(args.registry)

    if not registry.load():
        print("⚠️ Registry empty or not found, creating empty tables...")

    print(f"   Problems: {len(registry.problems)}")
    print(f"   Peaks: {len(registry.peaks)}")

    # Export
    exporter = TableExporter(registry)
    output_path = Path(args.output)
    output_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    files = []

    # Errors
    if not args.peaks_only:
        if args.format in ('all', 'csv'):
            f = exporter.export_errors_csv(output_path / f'errors_table_{timestamp}.csv')
            files.append(f)
            exporter.export_errors_csv(output_path / 'errors_table_latest.csv')
        if args.format in ('all', 'md'):
            f = exporter.export_errors_markdown(output_path / f'errors_table_{timestamp}.md')
            files.append(f)
            exporter.export_errors_markdown(output_path / 'errors_table_latest.md')
        if args.format in ('all', 'json'):
            f = exporter.export_errors_json(output_path / f'errors_table_{timestamp}.json')
            files.append(f)
            exporter.export_errors_json(output_path / 'errors_table_latest.json')

    # Peaks
    if not args.errors_only:
        if args.format in ('all', 'csv'):
            f = exporter.export_peaks_csv(output_path / f'peaks_table_{timestamp}.csv')
            files.append(f)
            exporter.export_peaks_csv(output_path / 'peaks_table_latest.csv')
        if args.format in ('all', 'md'):
            f = exporter.export_peaks_markdown(output_path / f'peaks_table_{timestamp}.md')
            files.append(f)
            exporter.export_peaks_markdown(output_path / 'peaks_table_latest.md')
        if args.format in ('all', 'json'):
            f = exporter.export_peaks_json(output_path / f'peaks_table_{timestamp}.json')
            files.append(f)
            exporter.export_peaks_json(output_path / 'peaks_table_latest.json')

    print(f"\n✅ Exported {len(files)} files to {args.output}/")
    for f in files:
        print(f"   📄 {Path(f).name}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
