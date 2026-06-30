#!/usr/bin/env python3
"""
Problem Report Generator - Problem-centric report
==================================================

ZÁSADNÍ ZMĚNA:
- Iteruje přes PROBLÉMY, ne incidenty
- Žádné "top incidents" nebo "top operational incidents"
- Jeden kvalitní seznam problémů

Report struktura:
1. Executive Summary (pouze actionable problémy)
2. Problem List (seřazeno podle priority)
3. Per-problem detail:
   - Root cause
   - Propagation
   - Version impact
   - Sample trace
4. Statistics (na konci, oddělené)
"""

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import json

from .problem_aggregator import ProblemAggregate, sort_problems_by_priority
from .trace_analysis import (
    TraceFlow,
    get_representative_traces,
    enrich_all_problems_with_traces,
)
from .root_cause import enrich_problems_with_root_cause
from .propagation import enrich_problems_with_propagation, get_propagation_summary
from .version_analysis import enrich_problems_with_version_analysis, get_version_summary
from .category_refinement import refine_all_problems, get_refinement_stats


# =============================================================================
# DURATION HELPERS
# =============================================================================

def _format_duration_sec(seconds: int) -> str:
    """Formats duration in seconds to human-readable: 45s / 23m 5s / 5h 12m 3s"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s"
    else:
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        return f"{h}h {m}m {s}s"


# =============================================================================

class ProblemReportGenerator:
    """
    Generátor problem-centric reportů.

    Použití:
        generator = ProblemReportGenerator(problems, trace_flows)
        report = generator.generate_text_report()
        generator.save_reports('/path/to/output')
    """

    def __init__(
        self,
        problems: Dict[str, ProblemAggregate],
        trace_flows: Dict[str, List[TraceFlow]] = None,
        analysis_start: datetime = None,
        analysis_end: datetime = None,
        run_id: str = "",
        registry_problems: Dict[str, Any] = None,
        trace_pattern_index: Dict[str, Any] = None,
    ):
        self.problems = problems
        self.trace_flows = trace_flows or {}
        self.analysis_start = analysis_start
        self.analysis_end = analysis_end
        self.run_id = run_id
        self.registry_problems = registry_problems or {}
        # trace_id -> reálný TracePattern (z pipeline, když build_trace_patterns=True)
        self.trace_pattern_index = trace_pattern_index or {}

        # Enrich problems with analysis
        self._enrich_problems()

    def _get_registry_problem(self, problem: ProblemAggregate) -> Optional[Any]:
        return self.registry_problems.get(problem.problem_key)

    def _format_registry_history(self, problem: ProblemAggregate) -> List[str]:
        registry_problem = self._get_registry_problem(problem)
        if not registry_problem or not getattr(registry_problem, 'first_seen', None):
            return []

        current_first_seen = getattr(problem, 'first_seen', None)
        registry_first_seen = registry_problem.first_seen

        if current_first_seen and registry_first_seen >= current_first_seen:
            return []

        return [
            f"  Known since: {registry_first_seen.strftime('%Y-%m-%d %H:%M')} (registry)"
        ]

    def _enrich_problems(self, output_dir: str = None):
        """Obohatí problémy o všechny analýzy."""
        total = len(self.problems)
        print(f"   Enriching {total} problems...", flush=True)

        # 0. Napoj na reálné trace patterny z pipeline (pokud jsou k dispozici).
        if self.trace_pattern_index:
            self._match_trace_patterns()

        # 1. Trace behavior - MUSÍ BÝT PRVNÍ pro trace-based root cause
        print("   [1/5] Trace enrichment...", flush=True)
        enrich_all_problems_with_traces(self.problems, output_dir=output_dir, verbose=True)

        # 2. Root cause (fallback když pattern-based root cause chybí).
        #    ZÁMĚRNĚ NEpředáváme trace_flows: pochází z build_trace_flow s
        #    fabrikovanými timestampy/pořadím. Fallback se tak bere z reálného
        #    incidentu s nejvyšším score, ne z fake flow.
        print("   [2/5] Root cause inference...", flush=True)
        enrich_problems_with_root_cause(self.problems, None)

        # 3. Propagation (scope) jen z reálných dat problému (apps/namespaces).
        #    Bez trace_flows je propagation_time_ms = 0 (N/A) místo nesmyslné
        #    duration přes celý rozsah problému.
        print("   [3/5] Propagation analysis...", flush=True)
        enrich_problems_with_propagation(self.problems, None)

        # 4. Version analysis
        print("   [4/5] Version analysis...", flush=True)
        enrich_problems_with_version_analysis(self.problems)

        # 5. Category refinement
        print("   [5/5] Category refinement...", flush=True)
        refine_all_problems(self.problems)

        print("   ✓ Enrichment complete", flush=True)

    def _match_trace_patterns(self):
        """Každému problému přiřaď JEHO reálný trace pattern – s ownershipem.

        Fingerprint-grouping rozděluje jeden propagovaný trace do víc problémů
        (root služba vs. následná služba). Aby se STEJNÁ propagace neukázala
        dvakrát, přiřadíme pattern jen tomu problému, jehož dominantní app je
        root-cause služba patternu (u multi-hop) / jeho jediná app (single-hop).
        Ostatní problémy spadnou na poctivý fallback (top patterns).
        """
        # 1. Dominantní app každého problému (podle reálných per-app počtů).
        dominant: Dict[str, Optional[str]] = {}
        for key, problem in self.problems.items():
            problem.trace_pattern = None
            app_counts = getattr(problem, 'app_counts', {}) or {}
            if app_counts:
                dominant[key] = max(app_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
            elif problem.apps:
                dominant[key] = sorted(problem.apps)[0]
            else:
                dominant[key] = None

        # 2. Pro každý problém vyber pattern, jehož root služba == jeho dominantní app.
        for key, problem in self.problems.items():
            candidates = {}
            for tid in (getattr(problem, 'trace_ids', None) or set()):
                pat = self.trace_pattern_index.get(tid)
                if pat is not None:
                    candidates[id(pat)] = pat

            best = None
            for pat in candidates.values():
                rc = pat.root_cause or {}
                owner_app = rc.get('service') or (pat.propagation_path[0] if pat.propagation_path else None)
                if owner_app and owner_app == dominant.get(key):
                    if best is None or pat.total_errors > best.total_errors:
                        best = pat
            problem.trace_pattern = best

    def generate_text_report(self, max_problems: int = 20) -> str:
        """
        Generuje textový report.

        Args:
            max_problems: Maximum problémů v reportu

        Returns:
            Formátovaný text report
        """
        lines = []

        # Header
        lines.extend(self._format_header())

        # Executive Summary
        lines.extend(self._format_executive_summary())

        # Problem List
        lines.extend(self._format_problem_list(max_problems))

        # Statistics (na konci)
        lines.extend(self._format_statistics())

        return "\n".join(lines)

    def _format_header(self) -> List[str]:
        """Formátuje header reportu."""
        lines = [
            "=" * 70,
            "PROBLEM ANALYSIS REPORT",
            "=" * 70,
            "",
        ]

        if self.analysis_start and self.analysis_end:
            lines.append(f"Period: {self.analysis_start.strftime('%Y-%m-%d %H:%M')} - {self.analysis_end.strftime('%Y-%m-%d %H:%M')}")

        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if self.run_id:
            lines.append(f"Run ID: {self.run_id}")

        lines.append("")
        return lines

    def _format_executive_summary(self) -> List[str]:
        """Formátuje executive summary."""
        lines = [
            "-" * 70,
            "EXECUTIVE SUMMARY",
            "-" * 70,
            "",
        ]

        # Počty
        total = len(self.problems)
        critical = sum(1 for p in self.problems.values() if p.max_severity == 'critical')
        high = sum(1 for p in self.problems.values() if p.max_severity == 'high')
        with_spike = sum(1 for p in self.problems.values() if p.has_spike)
        new_problems = sum(1 for p in self.problems.values() if p.has_new)
        cross_ns = sum(1 for p in self.problems.values() if p.is_cross_namespace)

        lines.append(f"Total problems: {total}")
        lines.append(f"  - Critical: {critical}")
        lines.append(f"  - High: {high}")
        lines.append(f"  - With spike: {with_spike}")
        lines.append(f"  - New: {new_problems}")
        lines.append(f"  - Cross-namespace: {cross_ns}")
        lines.append("")

        # Top issues - POUZE relevantní problémy
        # Filtr: musí splnit aspoň 1 podmínku
        MIN_OCCURRENCES = 50
        actionable_problems = [
            p for p in sort_problems_by_priority(self.problems)
            if self._is_actionable_problem(p, MIN_OCCURRENCES)
        ]

        if actionable_problems:
            lines.append("Top issues (actionable):")
            for i, problem in enumerate(actionable_problems[:5], 1):
                severity_icon = self._severity_icon(problem.max_severity)
                # Confidence z trace_root_cause pokud existuje
                confidence = ""
                if problem.trace_root_cause:
                    conf = problem.trace_root_cause.get('confidence', '')
                    if conf:
                        confidence = f" [{conf}]"
                lines.append(
                    f"  {i}. {severity_icon} [{problem.category}] {problem.error_class} "
                    f"({problem.total_occurrences:,} occ){confidence}"
                )
        else:
            lines.append("Top issues: No high-priority actionable problems found.")

        lines.append("")
        return lines

    def _is_actionable_problem(self, problem: ProblemAggregate, min_occ: int = 50) -> bool:
        """
        Určí, zda je problém actionable pro Executive Summary.

        Podmínky (OR):
        1. severity >= HIGH
        2. total_occurrences >= min_occ
        3. has_spike == True
        4. trace_root_cause confidence == 'high'
        5. is_cross_namespace == True

        Vyloučení:
        - category == 'unknown' AND total_occurrences < min_occ
        - error_class == 'unknown_error' AND occurrences == 0
        """
        # Vyloučení: bezvýznamné unknown problémy
        if problem.category == 'unknown' and problem.total_occurrences < min_occ:
            # Ale povol pokud má jiné signály
            if not (problem.has_spike or problem.is_cross_namespace):
                return False

        if problem.error_class == 'unknown_error' and problem.total_occurrences == 0:
            return False

        # Pozitivní podmínky (OR)
        if problem.max_severity in ('critical', 'high'):
            return True
        if problem.total_occurrences >= min_occ:
            return True
        if problem.has_spike:
            return True
        if problem.is_cross_namespace:
            return True
        if problem.trace_root_cause and problem.trace_root_cause.get('confidence') == 'high':
            return True

        return False

    def _format_problem_list(self, max_problems: int) -> List[str]:
        """Formátuje seznam problémů."""
        lines = [
            "-" * 70,
            "PROBLEM DETAILS",
            "-" * 70,
            "",
        ]

        sorted_problems = sort_problems_by_priority(self.problems)

        for i, problem in enumerate(sorted_problems[:max_problems], 1):
            lines.extend(self._format_single_problem(problem, i))
            lines.append("")

        if len(sorted_problems) > max_problems:
            lines.append(f"... and {len(sorted_problems) - max_problems} more problems (see CSV export)")
            lines.append("")

        return lines

    def _format_single_problem(self, problem: ProblemAggregate, index: int) -> List[str]:
        """Formátuje jeden problém."""
        lines = []

        # Header
        severity_icon = self._severity_icon(problem.max_severity)
        lines.append(f"{'─' * 50}")
        lines.append(f"#{index} {severity_icon} {problem.category.upper()}: {problem.error_class}")
        lines.append(f"{'─' * 50}")

        # Basic info
        lines.append(f"  Problem key: {problem.problem_key}")
        lines.append(f"  Severity: {problem.max_severity.upper()} (score: {problem.max_score:.0f})")
        lines.append(f"  Occurrences: {problem.total_occurrences:,} across {problem.incident_count} incidents")
        lines.append(f"  Flags: {problem.flag_summary}")

        # Time
        if problem.first_seen and problem.last_seen:
            lines.append(f"  Time: {problem.first_seen.strftime('%Y-%m-%d %H:%M')} - {problem.last_seen.strftime('%H:%M')} ({_format_duration_sec(problem.duration_sec)})")
        lines.extend(self._format_registry_history(problem))

        # Scope
        lines.append(f"  Scope: {len(problem.apps)} apps, {len(problem.namespaces)} namespaces")
        if problem.apps:
            app_counts = getattr(problem, 'app_counts', {})
            if app_counts:
                sorted_apps = sorted(app_counts.items(), key=lambda x: -x[1])[:5]
                apps_str = ', '.join(f"{a} ({c:,})" for a, c in sorted_apps)
            else:
                apps_str = ', '.join(sorted(problem.apps)[:5])
            lines.append(f"    Apps: {apps_str}")
        if problem.namespaces:
            ns_counts = getattr(problem, 'ns_counts', {})
            if ns_counts:
                sorted_ns = sorted(ns_counts.items(), key=lambda x: -x[1])[:5]
                ns_str = ', '.join(f"{n} ({c:,})" for n, c in sorted_ns)
            else:
                ns_str = ', '.join(sorted(problem.namespaces)[:5])
            lines.append(f"    Namespaces: {ns_str}")

        lines.append("")

        # === BEHAVIOR (dominant patterns across incidents) ===
        # POZOR: trace_flow_summary nese agregované dominantní patterny napříč
        # VŠEMI incidenty/trace problému (summarize_problem_patterns), NE kroky
        # jednoho trace. Dříve se to renderovalo jako single-trace flow s jedním
        # TraceID + číslovanými kroky, což vytvářelo falešnou propagaci a nesedělo
        # s logy v ES (zobrazená message nepatřila uvedenému TraceID).
        # Nově: poctivý přehled top patternů s reálným count/share/ns + reálným
        # příkladem trace PRO KAŽDÝ pattern.
        #
        # NEJLEPŠÍ varianta: pokud máme reálné trace patterny (z raw eventů přes
        # trace_timeline), ukaž skutečnou propagaci po časové ose + occurrences
        # (počet trace), total errors, avg/occ, errors-per-app a root cause/outcome.
        trace_pattern = getattr(problem, 'trace_pattern', None)
        if trace_pattern is not None and getattr(trace_pattern, 'representative', None):
            from .trace_timeline import format_pattern_behavior
            lines.append("  Behavior (real trace propagation):")
            lines.extend(format_pattern_behavior(trace_pattern, indent="    "))
            lines.append("")
        elif problem.trace_flow_summary:
            patterns = problem.trace_flow_summary
            shown_events = sum(int(p.get('count', 0) or 0) for p in patterns)
            # Celkový počet eventů problému (kvůli konzistenci se share_pct, který
            # je počítán relativně k total_occurrences). Fallback na součet patternů.
            total_events = int(getattr(problem, 'total_occurrences', 0) or 0) or shown_events or len(patterns)
            lines.append(f"  Behavior (top patterns): {total_events:,} events, top {len(patterns)} shown")
            lines.append("")

            for i, pattern in enumerate(patterns, 1):
                app = pattern.get('app', '?')
                msg = pattern.get('message', '')
                count = int(pattern.get('count', 0) or 0)
                share = pattern.get('share_pct')
                # Dopočítej share, pokud chybí, ale máme count i total
                if share is None and count > 0 and total_events > 0:
                    share = round(count / total_events * 100, 1)

                if count > 0 and share is not None:
                    lines.append(f"    {i}) {app} ({count:,} events, {share:.0f}%)")
                elif count > 0:
                    lines.append(f"    {i}) {app} ({count:,} events)")
                else:
                    lines.append(f"    {i}) {app}")
                lines.append(f"       \"{msg}\"")

                ns_list = pattern.get('namespaces') or []
                if ns_list:
                    lines.append(f"       Namespaces: {', '.join(ns_list[:5])}")

                # Reálný příklad trace PRO TENTO pattern (ne falešný společný TraceID)
                trace_ids = pattern.get('trace_ids') or []
                if trace_ids:
                    lines.append(f"       Example trace: {trace_ids[0]}")

            lines.append("")

            # Inferred root cause z dominantních patternů
            if problem.trace_root_cause:
                confidence = problem.trace_root_cause.get('confidence', 'unknown')
                lines.append(f"  Inferred root cause [{confidence}]:")
                lines.append(f"    - {problem.trace_root_cause.get('service', '?')}: {problem.trace_root_cause.get('message', '')}")
                lines.append("")

        # Root Cause (fallback/legacy)
        root_cause = getattr(problem, 'root_cause', None)
        if root_cause and not problem.trace_root_cause:
            lines.append(f"  Root cause [{root_cause.confidence}]:")
            lines.append(f"    Service: {root_cause.service}")
            lines.append(f"    Error: {root_cause.message}")

        # Cross-service scope BEZ kauzálních šipek / root / duration. Affected apps
        # jsou vypsané výše ("Apps:"). Bez reálného pořadí eventů nelze určit směr
        # "propagace" – proto NEpíšeme A → B → C ani Duration (ta dříve pocházela
        # z fabrikovaného trace flow). Uvádíme jen faktický rozsah přes namespaces.
        # (Když máme reálný trace_pattern, propagace už je vykreslená výše.)
        propagation = getattr(problem, 'propagation_result', None)
        if (getattr(problem, 'trace_pattern', None) is None
                and propagation and propagation.service_count > 1
                and propagation.namespace_count > 1):
            lines.append(
                f"  Spread: {propagation.service_count} services / "
                f"{propagation.namespace_count} namespaces"
            )

        # Version Impact
        version_impact = getattr(problem, 'version_impact', None)
        if version_impact and version_impact.total_versions > 0:
            lines.extend(version_impact.to_report_lines())

        # Sample message
        if problem.normalized_message:
            lines.append(f"  Message: {problem.normalized_message}")

        return lines

    def _format_statistics(self) -> List[str]:
        """Formátuje statistiky na konci."""
        lines = [
            "-" * 70,
            "STATISTICS",
            "-" * 70,
            "",
        ]

        # Category distribution
        categories = {}
        for p in self.problems.values():
            categories[p.category] = categories.get(p.category, 0) + 1

        lines.append("By category:")
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            pct = 100 * count / len(self.problems) if self.problems else 0
            lines.append(f"  {cat}: {count} ({pct:.1f}%)")

        lines.append("")

        # Refinement stats
        refinement = get_refinement_stats(self.problems)
        if refinement['total_refined'] > 0:
            lines.append(f"Category refinement: {refinement['total_refined']} problems reclassified")
            for change, count in refinement['refinements'].items():
                lines.append(f"  {change}: {count}")
            lines.append("")

        # Propagation summary
        prop_summary = get_propagation_summary(self.problems)
        if prop_summary['total_cascades'] > 0 or prop_summary['cross_namespace_count'] > 0:
            lines.append("Propagation:")
            lines.append(f"  Cascades: {prop_summary['total_cascades']}")
            lines.append(f"  Cross-namespace: {prop_summary['cross_namespace_count']}")
            lines.append(f"  Avg fan-out: {prop_summary['avg_fan_out']:.1f}")
            lines.append("")

        # Version summary
        version_summary = get_version_summary(self.problems)
        if version_summary['total_version_spikes'] > 0:
            lines.append("Version issues:")
            lines.append(f"  Version spikes: {version_summary['total_version_spikes']}")
            lines.append(f"  Regressions: {version_summary['total_regressions']}")
            lines.append(f"  New version issues: {version_summary['total_new_version_issues']}")
            lines.append("")

        return lines

    def _severity_icon(self, severity: str) -> str:
        """Vrátí ikonu pro severity."""
        icons = {
            'critical': '🔴',
            'high': '🟠',
            'medium': '🟡',
            'low': '🟢',
            'info': '⚪',
        }
        return icons.get(severity, '⚪')

    def save_reports(
        self,
        output_dir: str,
        prefix: str = "problem_report"
    ) -> Dict[str, str]:
        """
        Uloží všechny reporty.

        Args:
            output_dir: Výstupní adresář
            prefix: Prefix názvů souborů

        Returns:
            Dict[type, filepath]
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        files = {}

        # 1. Text report
        text_report = self.generate_text_report()
        text_path = output_path / f"{prefix}_{timestamp}.txt"
        with open(text_path, 'w', encoding='utf-8') as f:
            f.write(text_report)
        files['text'] = str(text_path)

        # 2. JSON report
        json_data = self._to_json_data()
        json_path = output_path / f"{prefix}_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, default=str)
        files['json'] = str(json_path)

        return files

    def _to_json_data(self) -> dict:
        """Serializuje do JSON struktury."""
        sorted_problems = sort_problems_by_priority(self.problems)

        return {
            'metadata': {
                'generated': datetime.now().isoformat(),
                'run_id': self.run_id,
                'analysis_start': self.analysis_start.isoformat() if self.analysis_start else None,
                'analysis_end': self.analysis_end.isoformat() if self.analysis_end else None,
            },
            'summary': {
                'total_problems': len(self.problems),
                'by_severity': {
                    'critical': sum(1 for p in self.problems.values() if p.max_severity == 'critical'),
                    'high': sum(1 for p in self.problems.values() if p.max_severity == 'high'),
                    'medium': sum(1 for p in self.problems.values() if p.max_severity == 'medium'),
                    'low': sum(1 for p in self.problems.values() if p.max_severity == 'low'),
                    'info': sum(1 for p in self.problems.values() if p.max_severity == 'info'),
                },
                'by_category': self._count_by_category(),
            },
            'problems': [self._problem_to_json(p) for p in sorted_problems],
        }

    def _problem_to_json(self, problem: ProblemAggregate) -> dict:
        """Serializuje jeden problém."""
        data = problem.to_dict()
        registry_problem = self._get_registry_problem(problem)

        # Přidej enriched data
        if hasattr(problem, 'root_cause') and problem.root_cause:
            data['root_cause'] = problem.root_cause.to_dict()
        if hasattr(problem, 'propagation_result') and problem.propagation_result:
            data['propagation'] = problem.propagation_result.to_dict()
        if hasattr(problem, 'version_impact') and problem.version_impact:
            data['version_impact'] = problem.version_impact.to_dict()
        if registry_problem:
            data['registry_first_seen'] = registry_problem.first_seen.isoformat() if registry_problem.first_seen else None
            data['registry_last_seen'] = registry_problem.last_seen.isoformat() if registry_problem.last_seen else None

        return data

    def _count_by_category(self) -> dict:
        """Počítá problémy podle kategorie."""
        counts = {}
        for p in self.problems.values():
            counts[p.category] = counts.get(p.category, 0) + 1
        return counts


def generate_problem_report(
    incidents: List[Any],
    output_dir: str = None,
    analysis_start: datetime = None,
    analysis_end: datetime = None,
    run_id: str = "",
) -> str:
    """
    Convenience funkce pro generování reportu z incidentů.

    Args:
        incidents: Seznam incidentů z pipeline
        output_dir: Volitelný výstupní adresář
        analysis_start: Začátek analyzovaného období
        analysis_end: Konec analyzovaného období
        run_id: ID běhu

    Returns:
        Text report
    """
    from .problem_aggregator import aggregate_by_problem_key
    from .trace_analysis import get_representative_traces

    # 1. Agreguj incidenty do problémů
    problems = aggregate_by_problem_key(incidents)

    # 2. Získej reprezentativní traces
    trace_flows = get_representative_traces(problems)

    # 3. Generuj report
    generator = ProblemReportGenerator(
        problems=problems,
        trace_flows=trace_flows,
        analysis_start=analysis_start,
        analysis_end=analysis_end,
        run_id=run_id,
    )

    # 4. Ulož pokud je output_dir
    if output_dir:
        generator.save_reports(output_dir)

    return generator.generate_text_report()
