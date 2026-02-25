#!/usr/bin/env python3
"""
Version Analysis - Version-aware analýza problémů
=================================================

UŽ MÁŠ DATA - VYUŽIJ JE!

Funkce:
1. Počítá occurrences per version
2. Detekuje spike po deployi nové verze
3. Identifikuje regrese

Report output:
    Version impact:
    - 3.5.0: 2 113
    - 3.5.1: 9 874 (↑ +367%)


"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict
import re


@dataclass
class VersionStats:
    """Statistiky pro jednu verzi."""
    version: str
    occurrence_count: int = 0
    incident_count: int = 0
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    namespaces: set = field(default_factory=set)
    apps: set = field(default_factory=set)

    def to_dict(self) -> dict:
        return {
            'version': self.version,
            'occurrence_count': self.occurrence_count,
            'incident_count': self.incident_count,
            'first_seen': self.first_seen.isoformat() if self.first_seen else None,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'namespaces': sorted(self.namespaces),
            'apps': sorted(self.apps),
        }


@dataclass
class VersionImpact:
    """Výsledek version analýzy pro problém."""

    # Verze a jejich statistiky
    versions: Dict[str, VersionStats] = field(default_factory=dict)

    # Sorted by count (desc)
    versions_sorted: List[Tuple[str, int]] = field(default_factory=list)

    # Detekce
    has_version_spike: bool = False      # Jedna verze má výrazně více
    spike_version: str = ""              # Verze se spikem
    spike_ratio: float = 0.0             # Poměr spike vs baseline

    has_regression: bool = False         # Problém se vrátil v nové verzi
    regression_version: str = ""         # Verze s regresí

    has_new_version_issue: bool = False  # Problém jen v nové verzi
    new_version: str = ""                # Nová verze

    # Totals
    total_versions: int = 0
    total_occurrences: int = 0

    def to_dict(self) -> dict:
        return {
            'versions': {k: v.to_dict() for k, v in self.versions.items()},
            'versions_sorted': self.versions_sorted,
            'has_version_spike': self.has_version_spike,
            'spike_version': self.spike_version,
            'spike_ratio': self.spike_ratio,
            'has_regression': self.has_regression,
            'regression_version': self.regression_version,
            'has_new_version_issue': self.has_new_version_issue,
            'new_version': self.new_version,
            'total_versions': self.total_versions,
            'total_occurrences': self.total_occurrences,
        }

    def to_report_lines(self) -> List[str]:
        """Formátuje pro textový report."""
        lines = []

        if not self.versions_sorted:
            lines.append("  No version data")
            return lines

        # Header
        lines.append(f"  Version impact ({self.total_versions} versions, {self.total_occurrences:,} occurrences):")

        # Top 5 versions
        prev_count = None
        for i, (version, count) in enumerate(self.versions_sorted[:5]):
            # Percentage
            pct = 100 * count / self.total_occurrences if self.total_occurrences > 0 else 0

            # Change indicator
            change = ""
            if prev_count and prev_count > 0:
                delta = 100 * (count - prev_count) / prev_count
                if delta > 0:
                    change = f" (↑ +{delta:.0f}%)"
                elif delta < 0:
                    change = f" (↓ {delta:.0f}%)"

            # Spike marker
            spike_marker = " ⚠️" if version == self.spike_version else ""

            lines.append(f"    - {version}: {count:,} ({pct:.1f}%){change}{spike_marker}")
            prev_count = count

        if len(self.versions_sorted) > 5:
            lines.append(f"    ... and {len(self.versions_sorted) - 5} more versions")

        # Alerts
        if self.has_version_spike:
            lines.append(f"  ⚠️ Version spike: {self.spike_version} ({self.spike_ratio:.1f}x baseline)")
        if self.has_new_version_issue:
            lines.append(f"  🆕 New version issue: {self.new_version}")
        if self.has_regression:
            lines.append(f"  🔄 Regression detected in: {self.regression_version}")

        return lines


def analyze_versions(problem: Any) -> VersionImpact:
    """
    Analyzuje version distribution pro problém.

    Args:
        problem: ProblemAggregate

    Returns:
        VersionImpact
    """
    result = VersionImpact()

    # Sbírej data z incidentů
    for incident in problem.incidents:
        for version in incident.app_versions:
            if not version:
                continue

            if version not in result.versions:
                result.versions[version] = VersionStats(version=version)

            stats = result.versions[version]
            stats.occurrence_count += incident.stats.current_count
            stats.incident_count += 1
            stats.namespaces.update(incident.namespaces)
            stats.apps.update(incident.apps)

            # Timestamps
            if incident.time.first_seen:
                if stats.first_seen is None or incident.time.first_seen < stats.first_seen:
                    stats.first_seen = incident.time.first_seen
            if incident.time.last_seen:
                if stats.last_seen is None or incident.time.last_seen > stats.last_seen:
                    stats.last_seen = incident.time.last_seen

    # Totals
    result.total_versions = len(result.versions)
    result.total_occurrences = sum(v.occurrence_count for v in result.versions.values())

    # Sort by count
    result.versions_sorted = sorted(
        [(v.version, v.occurrence_count) for v in result.versions.values()],
        key=lambda x: -x[1]
    )

    # Detekce anomálií
    if result.versions_sorted:
        _detect_version_anomalies(result)

    return result


def _detect_version_anomalies(result: VersionImpact):
    """Detekuje version spike, regression, new version issues."""

    if len(result.versions_sorted) < 2:
        return

    # 1. Version spike detection
    # Top verze má >3x více než průměr ostatních
    top_version, top_count = result.versions_sorted[0]
    other_counts = [c for _, c in result.versions_sorted[1:]]
    avg_other = sum(other_counts) / len(other_counts) if other_counts else 0

    if avg_other > 0 and top_count > avg_other * 3:
        result.has_version_spike = True
        result.spike_version = top_version
        result.spike_ratio = top_count / avg_other

    # 2. Parse versions for comparison
    parsed_versions = []
    for version, count in result.versions_sorted:
        parsed = _parse_semver(version)
        if parsed:
            parsed_versions.append((version, count, parsed))

    if len(parsed_versions) < 2:
        return

    # Sort by version (newest first)
    parsed_versions.sort(key=lambda x: x[2], reverse=True)

    # 3. New version issue
    # Nejnovější verze má >50% všech occurrences
    newest = parsed_versions[0]
    if newest[1] > result.total_occurrences * 0.5:
        result.has_new_version_issue = True
        result.new_version = newest[0]

    # 4. Regression detection
    # Starší verze měla problém, pak zmizelo, teď je znovu
    # (zjednodušeno: pokud máme verzi s gaps)
    if len(parsed_versions) >= 3:
        # Check if middle version has significantly less
        for i in range(1, len(parsed_versions) - 1):
            prev_count = parsed_versions[i - 1][1]
            curr_count = parsed_versions[i][1]
            next_count = parsed_versions[i + 1][1]

            if curr_count < prev_count * 0.2 and curr_count < next_count * 0.2:
                # Middle version has much less = possible regression
                result.has_regression = True
                result.regression_version = parsed_versions[0][0]  # Newest
                break


def _parse_semver(version: str) -> Optional[Tuple[int, int, int]]:
    """
    Parsuje semantic version (X.Y.Z).

    Returns:
        Tuple (major, minor, patch) nebo None
    """
    match = re.match(r'^v?(\d+)\.(\d+)\.(\d+)', version)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def enrich_problems_with_version_analysis(problems: dict) -> dict:
    """
    Obohatí problémy o version analýzu.

    Args:
        problems: Dict[problem_key, ProblemAggregate]

    Returns:
        Stejný dict, problémy mají nový atribut 'version_impact'
    """
    for key, problem in problems.items():
        version_impact = analyze_versions(problem)
        problem.version_impact = version_impact

    return problems


def get_version_summary(problems: dict) -> dict:
    """
    Vytvoří summary verzí přes všechny problémy.

    Returns:
        {
            'total_version_spikes': int,
            'total_regressions': int,
            'total_new_version_issues': int,
            'most_problematic_versions': List[str],
        }
    """
    spikes = 0
    regressions = 0
    new_issues = 0
    version_problems: Dict[str, int] = {}

    for problem in problems.values():
        if not hasattr(problem, 'version_impact'):
            continue

        vi = problem.version_impact

        if vi.has_version_spike:
            spikes += 1
            version_problems[vi.spike_version] = version_problems.get(vi.spike_version, 0) + 1
        if vi.has_regression:
            regressions += 1
        if vi.has_new_version_issue:
            new_issues += 1

    # Top problematic versions
    top_versions = sorted(version_problems.items(), key=lambda x: -x[1])[:5]

    return {
        'total_version_spikes': spikes,
        'total_regressions': regressions,
        'total_new_version_issues': new_issues,
        'most_problematic_versions': [v[0] for v in top_versions],
        'version_problem_counts': dict(top_versions),
    }
