#!/usr/bin/env python3
"""
Exports - CSV/JSON exporty oddělené od reportu
==============================================

Report = pro člověka (čitelný text)
CSV = pro práci (import do tabulky, dashboardu)

Exporty:
- problems_summary.csv - přehled všech problémů
- version_stats.csv - version impact per problem
- propagation_stats.csv - propagation info
- registry_health.csv - health metriky registry

Verze: 6.0
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from .problem_aggregator import ProblemAggregate, sort_problems_by_priority


class ProblemExporter:
    """
    Exportér problémů do CSV/JSON formátů.

    Použití:
        exporter = ProblemExporter(problems)
        exporter.export_all('/path/to/output')
    """

    def __init__(
        self,
        problems: Dict[str, ProblemAggregate],
        run_id: str = "",
        analysis_date: datetime = None,
    ):
        self.problems = problems
        self.run_id = run_id
        self.analysis_date = analysis_date or datetime.now()

    def export_all(self, output_dir: str, prefix: str = "") -> Dict[str, str]:
        """
        Exportuje všechny formáty.

        Returns:
            Dict[export_type, filepath]
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = self.analysis_date.strftime('%Y%m%d')
        if prefix:
            prefix = f"{prefix}_"

        files = {}

        # 1. Problems summary
        path = output_path / f"{prefix}problems_summary_{timestamp}.csv"
        self.export_problems_csv(str(path))
        files['problems_summary'] = str(path)

        # 2. Version stats
        path = output_path / f"{prefix}version_stats_{timestamp}.csv"
        self.export_version_stats_csv(str(path))
        files['version_stats'] = str(path)

        # 3. Propagation stats
        path = output_path / f"{prefix}propagation_stats_{timestamp}.csv"
        self.export_propagation_csv(str(path))
        files['propagation_stats'] = str(path)

        # 4. Full JSON
        path = output_path / f"{prefix}problems_full_{timestamp}.json"
        self.export_full_json(str(path))
        files['full_json'] = str(path)

        return files

    def export_problems_csv(self, filepath: str):
        """
        Exportuje přehled problémů do CSV.

        Sloupce:
        - problem_key, category, flow, error_class
        - severity, score
        - occurrences, incidents
        - apps, namespaces
        - first_seen, last_seen, duration_sec
        - flags (spike, burst, new, cross_ns)
        - root_cause_service, root_cause_message
        """
        sorted_problems = sort_problems_by_priority(self.problems)

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'problem_key',
                'category',
                'flow',
                'error_class',
                'severity',
                'score',
                'occurrences',
                'incidents',
                'fingerprints',
                'apps',
                'namespaces',
                'app_count',
                'namespace_count',
                'first_seen',
                'last_seen',
                'duration_sec',
                'is_spike',
                'is_burst',
                'is_new',
                'is_cross_ns',
                'representative_trace_id',  # V6.1
                'root_cause_service',
                'root_cause_message',
                'propagation_type',
                'normalized_message',
            ])

            # Data
            for problem in sorted_problems:
                root_cause = getattr(problem, 'root_cause', None)
                propagation = getattr(problem, 'propagation_result', None)

                # Použij trace_root_cause pokud existuje, jinak fallback na root_cause
                trace_rc = getattr(problem, 'trace_root_cause', None)
                rc_service = trace_rc.get('service', '') if trace_rc else (root_cause.service if root_cause else '')
                rc_message = trace_rc.get('message', '') if trace_rc else (root_cause.message if root_cause else '')

                writer.writerow([
                    problem.problem_key,
                    problem.category,
                    problem.flow,
                    problem.error_class,
                    problem.max_severity,
                    round(problem.max_score, 1),
                    problem.total_occurrences,
                    problem.incident_count,
                    len(problem.fingerprints),
                    ';'.join(sorted(problem.apps)[:10]),
                    ';'.join(sorted(problem.namespaces)[:10]),
                    len(problem.apps),
                    len(problem.namespaces),
                    problem.first_seen.isoformat() if problem.first_seen else '',
                    problem.last_seen.isoformat() if problem.last_seen else '',
                    problem.duration_sec,
                    int(problem.has_spike),
                    int(problem.has_burst),
                    int(problem.has_new),
                    int(problem.is_cross_namespace),
                    problem.representative_trace_id or '',  # V6.1
                    rc_service,
                    rc_message[:200].replace('\n', ' '),
                    propagation.propagation_type if propagation else '',
                    (problem.normalized_message[:200] if problem.normalized_message else '').replace('\n', ' '),
                ])

    def export_version_stats_csv(self, filepath: str):
        """
        Exportuje version statistiky do CSV.

        Sloupce:
        - problem_key, version, occurrences, incidents
        - first_seen, last_seen
        - is_spike_version, is_regression
        """
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'problem_key',
                'category',
                'version',
                'occurrences',
                'incidents',
                'percentage',
                'first_seen',
                'last_seen',
                'is_spike_version',
            ])

            # Data
            for problem in self.problems.values():
                version_impact = getattr(problem, 'version_impact', None)
                if not version_impact or not version_impact.versions:
                    continue

                total = version_impact.total_occurrences or 1

                for version, stats in version_impact.versions.items():
                    is_spike = version == version_impact.spike_version

                    writer.writerow([
                        problem.problem_key,
                        problem.category,
                        version,
                        stats.occurrence_count,
                        stats.incident_count,
                        round(100 * stats.occurrence_count / total, 1),
                        stats.first_seen.isoformat() if stats.first_seen else '',
                        stats.last_seen.isoformat() if stats.last_seen else '',
                        int(is_spike),
                    ])

    def export_propagation_csv(self, filepath: str):
        """
        Exportuje propagation statistiky do CSV.

        Sloupce:
        - problem_key, root_service, affected_services
        - service_count, namespace_count, fan_out
        - propagation_time_ms, propagation_type
        """
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'problem_key',
                'category',
                'root_service',
                'affected_services',
                'service_count',
                'namespace_count',
                'fan_out',
                'propagation_time_ms',
                'propagation_type',
                'is_cascading',
            ])

            # Data
            for problem in self.problems.values():
                propagation = getattr(problem, 'propagation_result', None)
                if not propagation or propagation.service_count <= 1:
                    continue

                writer.writerow([
                    problem.problem_key,
                    problem.category,
                    propagation.root_service,
                    ';'.join(propagation.affected_services[:10]),
                    propagation.service_count,
                    propagation.namespace_count,
                    propagation.fan_out,
                    propagation.propagation_time_ms,
                    propagation.propagation_type,
                    int(propagation.is_cascading),
                ])

    def export_full_json(self, filepath: str):
        """
        Exportuje kompletní data do JSON.
        """
        sorted_problems = sort_problems_by_priority(self.problems)

        data = {
            'metadata': {
                'exported': datetime.now().isoformat(),
                'run_id': self.run_id,
                'analysis_date': self.analysis_date.isoformat(),
                'total_problems': len(self.problems),
            },
            'summary': {
                'by_severity': self._count_by_field('max_severity'),
                'by_category': self._count_by_field('category'),
                'total_occurrences': sum(p.total_occurrences for p in self.problems.values()),
                'total_incidents': sum(p.incident_count for p in self.problems.values()),
            },
            'problems': [],
        }

        for problem in sorted_problems:
            problem_data = problem.to_dict()

            # Enriched data
            if hasattr(problem, 'root_cause') and problem.root_cause:
                problem_data['root_cause'] = problem.root_cause.to_dict()
            if hasattr(problem, 'propagation_result') and problem.propagation_result:
                problem_data['propagation'] = problem.propagation_result.to_dict()
            if hasattr(problem, 'version_impact') and problem.version_impact:
                problem_data['version_impact'] = problem.version_impact.to_dict()

            data['problems'].append(problem_data)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, default=str)

    def _count_by_field(self, field: str) -> dict:
        """Počítá problémy podle pole."""
        counts = {}
        for p in self.problems.values():
            value = getattr(p, field, 'unknown')
            counts[value] = counts.get(value, 0) + 1
        return counts


def export_registry_health_csv(
    registry: Any,
    filepath: str,
    timestamp: datetime = None
):
    """
    Exportuje health metriky registry do CSV.

    Args:
        registry: ProblemRegistry instance
        filepath: Cesta k výstupnímu souboru
        timestamp: Timestamp pro záznam
    """
    timestamp = timestamp or datetime.now()

    # Získej health metriky
    if hasattr(registry, 'get_health_metrics'):
        health = registry.get_health_metrics()
    else:
        health = {
            'total_problems': len(registry.problems) if hasattr(registry, 'problems') else 0,
            'total_fingerprints': len(registry.fingerprint_index) if hasattr(registry, 'fingerprint_index') else 0,
            'health_score': 100,
        }

    # Append to CSV (create if not exists)
    file_exists = Path(filepath).exists()

    with open(filepath, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                'timestamp',
                'total_problems',
                'total_fingerprints',
                'total_peaks',
                'health_score',
                'new_problems_24h',
                'new_fingerprints_24h',
                'fingerprints_dropped',
            ])

        writer.writerow([
            timestamp.isoformat(),
            health.get('total_problems', 0),
            health.get('total_fingerprints', 0),
            health.get('total_peaks', 0),
            health.get('health_score', 100),
            health.get('new_problems_24h', 0),
            health.get('new_fingerprints_24h', 0),
            health.get('fingerprints_dropped', 0),
        ])


def export_migration_mapping_csv(
    mapping: Dict[str, str],
    filepath: str
):
    """
    Exportuje mapping starých KE-ID na nové problem_key.

    Připomínka z analýzy:
    "loguj mapping starých KE-ID → nové problem_key jako CSV"

    Args:
        mapping: Dict[old_ke_id, new_problem_key]
        filepath: Cesta k výstupnímu souboru
    """
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)

        writer.writerow(['old_ke_id', 'new_problem_key', 'migration_date'])

        migration_date = datetime.now().isoformat()

        for old_id, new_key in sorted(mapping.items()):
            writer.writerow([old_id, new_key, migration_date])
