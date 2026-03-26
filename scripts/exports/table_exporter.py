#!/usr/bin/env python3
"""
Table Exporter - Operátorský view na Problem Registry
=====================================================

Export pravidla:
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
    """Řádek v errors_table - operátorský view
    
    Nové pořadí (priority):
    1. First Seen / Last Seen - WHEN se to stalo
    2. Occurrence - HOW MUCH (total + last 24h)
    3. Trend - zda se to zhoršuje/zlepšuje
    4. Root Cause - CO se děje (z enrichment)
    5. Category - WHERE (jakého typu je to error)
    6. Detail - KEY info (jméno metody, service, endpoint)
    7. Informativní - Score, Ratio, Scope (na konci)
    """
    first_seen: str                 # ISO format (ZAČÁTEK)
    last_seen: str                  # ISO format
    occurrence_total: int           # Celkový počet
    occurrence_24h: int             # Poslední 24 hodin
    trend_2h: str                   # 2 hours: ↑ increasing | → stable | ↓ decreasing + % změna
    trend_24h: str                  # 24 hours: ↑ increasing | → stable | ↓ decreasing + % změna
    root_cause: str                 # Výsledek analysis (CO se stalo) - z enrichment script
    category: str                   # Type (DB, Code, Auth, Infra, ...) 
    detail: str                     # Klíčová info (metoda, service, endpoint, message snippet)
    
    # Originální pole (historické, ale zachované)
    problem_id: str
    problem_key: str
    flow: str
    error_class: str
    affected_apps: str              # comma-separated (deployment labels)
    affected_namespaces: str        # comma-separated
    scope: str                      # LOCAL, CROSS_NS, SYSTEMIC
    status: str                     # OPEN, MONITORING, RESOLVED
    jira: str                       # Jira ticket link
    notes: str                      # Human notes
    
    # Informativní (na konci pro zájemce)
    severity: str                   # critical, high, medium, low
    score: float                    # Skóre detekce (0-100)
    ratio: float                    # Peak ratio vs. baseline
    behavior: str
    activity_status: str = ''       # ACTIVE (<7d), STALE (7-30d), OLD (>30d)



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
    root_cause: str
    behavior: str


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
        self.trend_change_threshold_pct = float(os.getenv('TREND_CHANGE_THRESHOLD_PCT', '200'))
        self.trend_display_cap_pct = float(os.getenv('TREND_DISPLAY_CAP_PCT', '200'))

    @staticmethod
    def _clean_unknown(value: Optional[str]) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        lowered = text.lower()
        if lowered in {"unknown", "unknownerror", "unclassified", "n/a", "none", "null"}:
            return ""
        return text

    @staticmethod
    def _shorten(text: str, limit: int = 180) -> str:
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= limit:
            return cleaned
        return cleaned[: limit - 3] + "..."

    # Category derived from error_class when category is unknown
    _ERROR_CLASS_TO_CATEGORY = {
        'not_found_error': 'business', 'constraint_violation': 'business',
        'validation_error': 'business', 'mismatched_input_exception': 'business',
        'mismatched_input': 'business', 'invalid_format_exception': 'business',
        'invalid_format': 'business', 'query_param_exception': 'business',
        'path_param_exception': 'business', 'null_pointer': 'business',
        'illegal_state_exception': 'business', 'not_supported_exception': 'business',
        'json_parse_exception': 'business', 'json_mapping_exception': 'business',
        'invalid_type_id_exception': 'business', 'json_error': 'business',
        'access_denied': 'auth', 'unauthorized': 'auth', 'authentication_error': 'auth',
        'forbidden': 'auth', 'token_expired': 'auth',
        'server_error': 'external', 'gateway_error': 'external',
        'rest_client_exception': 'external', 'http_client_error': 'external',
        'data_integrity_violation_exception': 'database', 'database_error': 'database',
        'connection_error': 'network', 'io_error': 'network',
        'timeout': 'timeout', 'timeout_error': 'timeout',
        'memory_error': 'memory',
    }

    def _backfill_category(self, category: str, error_class: str) -> str:
        """Derive category from error_class when category is unknown."""
        if category.lower() not in ('unknown', 'unclassified', ''):
            return category
        return self._ERROR_CLASS_TO_CATEGORY.get(error_class.lower(), category)

    def _problem_behavior(self, problem: ProblemEntry) -> str:
        # 1. Explicit behavior field
        behavior = self._clean_unknown(getattr(problem, 'behavior', ''))
        if behavior:
            return self._shorten(behavior, 180)
        # 2. Trace flow – use first non-empty message from trace steps
        trace_flow = getattr(problem, 'trace_flow_summary', None)
        if trace_flow:
            for step in trace_flow:
                msg = self._clean_unknown(step.get('message', ''))
                if msg:
                    return self._shorten(msg, 180)
        # 3. Sample messages from registry
        sample_msgs = getattr(problem, 'sample_messages', None)
        if sample_msgs:
            msg = self._clean_unknown(sample_msgs[0])
            if msg:
                return self._shorten(msg, 180)
        # 4. Description (not empty)
        desc = self._clean_unknown(getattr(problem, 'description', ''))
        if desc:
            return self._shorten(desc, 180)
        # No meaningful fallback – return empty rather than useless error_class/flow
        return ""

    def _problem_root_cause(self, problem: ProblemEntry) -> str:
        # Priority 1: root_cause field (populated by write-back from trace enrichment)
        explicit_root = self._clean_unknown(getattr(problem, 'root_cause', ''))
        if explicit_root:
            return self._shorten(explicit_root, 180)
        # Priority 2: description
        desc_root = self._clean_unknown(getattr(problem, 'description', ''))
        if desc_root:
            return self._shorten(desc_root, 180)
        # Priority 3: error_class as last resort
        err_class = self._clean_unknown(getattr(problem, 'error_class', ''))
        if err_class:
            return self._shorten(err_class, 180)
        return ""

    def _format_window_trend(self, current: int, baseline: float, label: str) -> str:
        """Format trend as percentage only — no word labels like 'returned' or 'new'."""
        if current == 0 and baseline <= 0:
            return f"{label}: → 0"

        if baseline <= 0:
            # No baseline available — show raw count
            return f"{label}: ↑ {current}"

        change_pct = ((current - baseline) / baseline) * 100.0
        capped = max(-self.trend_display_cap_pct, min(self.trend_display_cap_pct, abs(change_pct)))

        if abs(change_pct) >= self.trend_change_threshold_pct:
            arrow = "↑" if change_pct > 0 else "↓"
            suffix = "+" if abs(change_pct) > self.trend_display_cap_pct else ""
            sign = "+" if change_pct > 0 else "-"
            return f"{label}: {arrow} {sign}{capped:.0f}%{suffix}"
        sign = "+" if change_pct >= 0 else ""
        return f"{label}: → {sign}{change_pct:.0f}%"

    @staticmethod
    def _volume_in_window(aware_times: list, counts: list, now: datetime,
                          start_sec: float, end_sec: float) -> int:
        """Sum error counts in [now - end_sec, now - start_sec)."""
        total = 0
        for i, ts in enumerate(aware_times):
            delta = (now - ts).total_seconds()
            if start_sec <= delta < end_sec:
                total += counts[i] if i < len(counts) else 1
        return total

    def _compute_error_trend(self, problem: ProblemEntry, now: datetime) -> tuple[str, str, int]:
        occurrence_times = getattr(problem, 'occurrence_times', None) or []
        occurrence_counts = getattr(problem, 'occurrence_counts', None) or []
        aware_times = []
        counts = []
        for i, ts in enumerate(occurrence_times):
            aware_ts = self._ensure_aware(ts)
            if aware_ts:
                aware_times.append(aware_ts)
                counts.append(occurrence_counts[i] if i < len(occurrence_counts) else 1)

        if not aware_times:
            return "2h: → 0", "24h: → 0", 0

        H = 3600  # seconds in hour

        # --- Short trend (2h): current 2h vs average of previous 2h slots (up to 12h) ---
        current_2h = self._volume_in_window(aware_times, counts, now, 0, 2 * H)
        baseline_slots_2h = []
        for slot in range(1, 6):  # slots 1-5 → 2h-4h, 4h-6h, ... 10h-12h
            vol = self._volume_in_window(aware_times, counts, now, slot * 2 * H, (slot + 1) * 2 * H)
            baseline_slots_2h.append(vol)
        # Filter out zero-only baseline (all slots zero means no data)
        non_zero_slots = [v for v in baseline_slots_2h if v > 0]
        baseline_2h = sum(non_zero_slots) / len(non_zero_slots) if non_zero_slots else 0.0

        # --- Long trend (24h): current 24h vs average of previous days (up to 7 days) ---
        current_24h = self._volume_in_window(aware_times, counts, now, 0, 24 * H)
        baseline_slots_24h = []
        for day in range(1, 7):  # days 1-6
            vol = self._volume_in_window(aware_times, counts, now, day * 24 * H, (day + 1) * 24 * H)
            baseline_slots_24h.append(vol)
        non_zero_days = [v for v in baseline_slots_24h if v > 0]
        baseline_24h = sum(non_zero_days) / len(non_zero_days) if non_zero_days else 0.0

        short_trend = self._format_window_trend(current_2h, baseline_2h, "2h")
        long_trend = self._format_window_trend(current_24h, baseline_24h, "24h")

        return short_trend, long_trend, current_24h

    def _find_related_problem_for_peak(self, peak: PeakEntry, flow: str) -> Optional[ProblemEntry]:
        candidates: List[ProblemEntry] = []
        for problem in self.registry.problems.values():
            if flow and problem.flow != flow:
                continue
            if peak.affected_namespaces and not (set(peak.affected_namespaces) & set(problem.affected_namespaces)):
                continue
            candidates.append(problem)

        if not candidates:
            return None

        candidates.sort(
            key=lambda p: (
                len(set(peak.affected_namespaces) & set(p.affected_namespaces)),
                len(set(peak.affected_apps) & set(p.affected_apps)),
                p.occurrences,
                p.last_seen or datetime.min,
            ),
            reverse=True,
        )
        return candidates[0]

    @staticmethod
    def _ensure_aware(value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    # =========================================================================
    # SEVERITY / SCORE / RATIO DERIVATION
    # =========================================================================

    _SEVERITY_MAP = {
        'SYSTEMIC': 'critical',
        'CROSS_NS': 'high',
    }
    _CATEGORY_BOOST = {'database', 'auth', 'security', 'infrastructure'}

    def _derive_severity(self, problem: ProblemEntry) -> str:
        """Derive severity from scope + category + enriched data."""
        # Priority 1: write-back from enrichment
        enriched = getattr(problem, '_enriched_severity', None)
        if enriched and enriched not in ('info', 'unknown'):
            return enriched
        # Priority 2: scope-based
        sev = self._SEVERITY_MAP.get(problem.scope, 'low')
        # Boost for critical categories
        if problem.category in self._CATEGORY_BOOST and sev == 'low':
            sev = 'medium'
        return sev

    def _derive_score(self, problem: ProblemEntry, occurrence_24h: int) -> float:
        """Derive detection score: log-normalized daily rate (0-100)."""
        enriched = getattr(problem, '_enriched_score', 0.0)
        if enriched > 0:
            return round(enriched, 1)
        import math
        if occurrence_24h <= 0:
            return 0.0
        # log10(count) scaled: 1→0, 10→33, 100→66, 1000→100
        raw = math.log10(max(occurrence_24h, 1)) / 3.0 * 100.0
        return round(min(raw, 100.0), 1)

    def _derive_ratio(self, problem: ProblemEntry, current_24h: int, now: datetime) -> float:
        """Derive ratio: current 24h volume vs historical daily average."""
        occurrence_times = getattr(problem, 'occurrence_times', None) or []
        occurrence_counts = getattr(problem, 'occurrence_counts', None) or []
        aware_times = []
        counts = []
        for i, ts in enumerate(occurrence_times):
            aware_ts = self._ensure_aware(ts)
            if aware_ts:
                aware_times.append(aware_ts)
                counts.append(occurrence_counts[i] if i < len(occurrence_counts) else 1)

        H = 3600
        baseline_days = []
        for day in range(1, 7):
            vol = self._volume_in_window(aware_times, counts, now, day * 24 * H, (day + 1) * 24 * H)
            baseline_days.append(vol)
        non_zero = [v for v in baseline_days if v > 0]
        if not non_zero:
            return 1.0
        avg = sum(non_zero) / len(non_zero)
        return round(current_24h / avg, 2) if avg > 0 else 1.0

    # =========================================================================
    # ERRORS TABLE
    # =========================================================================

    def get_errors_rows(self) -> List[ErrorTableRow]:
        """Převede Problem Registry na řádky tabulky."""
        rows = []
        now = datetime.now(timezone.utc)

        for problem_key, problem in self.registry.problems.items():
            first_seen = self._ensure_aware(problem.first_seen)
            last_seen = self._ensure_aware(problem.last_seen)

            trend_2h, trend_24h, occurrence_24h = self._compute_error_trend(problem, now)
            
            # Root Cause - extract from description or analysis
            # NOTE: ProblemEntry uses 'description' field, enrichment may populate it
            root_cause = self._problem_root_cause(problem)
            behavior = self._problem_behavior(problem)

            # Category: backfill from error_class when category is unknown
            category = self._backfill_category(problem.category, problem.error_class)

            # Activity status: ACTIVE / STALE / OLD based on last_seen age
            if last_seen:
                age_days = (now - last_seen).days
                if age_days <= 7:
                    activity_status = 'ACTIVE'
                elif age_days <= 30:
                    activity_status = 'STALE'
                else:
                    activity_status = 'OLD'
            else:
                activity_status = 'UNKNOWN'

            # Detail - klíčová info (shorthand)
            detail = f"{problem.error_class}"
            if problem.flow:
                detail = f"{detail} / {problem.flow[:30]}"

            row = ErrorTableRow(
                # NOVÉ POŘADÍ
                first_seen=first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "Unknown",
                last_seen=last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "Unknown",
                occurrence_total=problem.occurrences,
                occurrence_24h=occurrence_24h,
                trend_2h=trend_2h,
                trend_24h=trend_24h,
                root_cause=root_cause,
                category=problem.category,
                detail=detail,
                
                # ORIGINÁLNÍ POLE (zachované pro kompatibilitu)
                problem_id=problem.id,
                problem_key=problem_key,
                flow=problem.flow,
                error_class=problem.error_class,
                affected_apps=", ".join(sorted(problem.affected_apps)[:10]),
                affected_namespaces=", ".join(sorted(problem.affected_namespaces)),
                scope=problem.scope,
                status=problem.status,
                jira=problem.jira or "",
                notes=problem.notes or "",
                
                # INFORMATIVNÍ (na konci)
                severity=self._derive_severity(problem),
                score=self._derive_score(problem, occurrence_24h),
                ratio=self._derive_ratio(problem, occurrence_24h, now),
                behavior=behavior,
                activity_status=activity_status,
            )
            rows.append(row)

        # Sort by last_seen DESC (most recent first)
        rows.sort(key=lambda r: r.last_seen or "", reverse=True)

        return rows

    def export_errors_csv(self, output_path: str) -> str:
        """Export errors jako CSV ."""
        rows = self.get_errors_rows()

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # NOVÉ pořadí sloupců - dle designu
        fieldnames = [
            'first_seen', 'last_seen', 'occurrence_total', 'occurrence_24h', 'trend_2h', 'trend_24h',
            'root_cause', 'behavior',   # behavior immediately next to root_cause
            'category', 'detail',
            # Historické
            'problem_id', 'problem_key', 'flow', 'error_class',
            'affected_apps', 'affected_namespaces', 'scope', 'status', 'activity_status', 'jira', 'notes',
            # Informativní
            'severity', 'score', 'ratio',
        ]

        with open(path, 'w', newline='', encoding='utf-8') as f:
            if rows:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    row_dict = asdict(row)
                    # Seřaď dle fieldnames
                    ordered = {k: row_dict.get(k, '') for k in fieldnames}
                    writer.writerow(ordered)
            else:
                # Empty file with headers 
                writer = csv.DictWriter(f, fieldnames=fieldnames)
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
            lines.append("| ID | Age | Category | Root Cause | Behavior | Apps | Occurrences | Last Seen | Status |")
            lines.append("|-------|-----|----------|-----------|----------|------|-------------|-----------|--------|")

            for row in rows:
                apps_short = row.affected_apps[:25] + "..." if len(row.affected_apps) > 25 else row.affected_apps
                last_seen_short = row.last_seen[:10] if row.last_seen else "-"
                rc_short = (row.root_cause[:55] + "...") if len(row.root_cause) > 58 else row.root_cause
                beh_short = (row.behavior[:55] + "...") if len(row.behavior) > 58 else row.behavior
                lines.append(
                    f"| {row.problem_id} | {row.activity_status} | {row.category} | {rc_short} | {beh_short} | "
                    f"{apps_short} | {row.occurrence_total:,} | {last_seen_short} | {row.status} |"
                )

            # Detailed section for recent problems
            recent_rows = [r for r in rows if r.last_seen]  # Just check if has last_seen
            if recent_rows:
                lines.append("")
                lines.append("## Recent Problems")
                lines.append("")

                for row in recent_rows[:20]:
                    lines.append(f"### {row.problem_id}: {row.category}/{row.flow}")
                    lines.append("")
                    lines.append(f"- **Error class:** {row.error_class}")
                    lines.append(f"- **Scope:** {row.scope}")
                    lines.append(f"- **Occurrences:** {row.occurrence_total:,}")
                    lines.append(f"- **Apps:** {row.affected_apps}")
                    lines.append(f"- **Namespaces:** {row.affected_namespaces}")
                    lines.append(f"- **First seen:** {row.first_seen}")
                    lines.append(f"- **Last seen:** {row.last_seen}")
                    if row.root_cause:
                        lines.append(f"- **Root cause:** {row.root_cause}")
                    if row.behavior:
                        lines.append("- **Behavior:**")
                        for bline in row.behavior.splitlines():
                            lines.append(f"  {bline}")
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
            
            # Extract category from problem_key
            # Formats:
            #   "PEAK:category:flow:peak_type" (current)
            #   "category:flow:peak_type"      (legacy)
            parts = problem_key.split(':') if problem_key else []
            if len(parts) >= 4 and parts[0] == 'PEAK':
                category = parts[1]
                flow = parts[2]
            elif len(parts) >= 1:
                category = parts[0]
                flow = parts[1] if len(parts) > 1 else ''
            else:
                category = 'unknown'
                flow = ''

            related_problem = self._find_related_problem_for_peak(peak, flow)
            category_clean = self._clean_unknown(category)
            if not category_clean and related_problem is not None:
                category_clean = self._clean_unknown(getattr(related_problem, 'category', '')) or category

            peak_root_cause = self._clean_unknown(getattr(peak, 'root_cause', ''))
            if not peak_root_cause and related_problem is not None:
                peak_root_cause = self._problem_root_cause(related_problem)

            peak_behavior = self._clean_unknown(getattr(peak, 'behavior', ''))
            if not peak_behavior and related_problem is not None:
                peak_behavior = self._problem_behavior(related_problem)

            raw_peak_count = int(getattr(peak, 'raw_error_count', 0) or 0)
            if raw_peak_count <= 0:
                raw_peak_count = max(1, int(peak.max_value or 0))
            
            row = PeakTableRow(
                peak_id=peak.id,
                problem_key=problem_key,
                category=category_clean or category,
                peak_type=peak.peak_type,
                affected_apps=", ".join(sorted(peak.affected_apps)[:10]),
                affected_namespaces=", ".join(sorted(peak.affected_namespaces)),
                peak_count=raw_peak_count,
                baseline_rate=peak.max_value,
                peak_ratio=round(float(peak.max_ratio or 0), 2),
                first_seen=first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "",
                last_seen=last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "",
                occurrence_count=peak.occurrences,
                status=peak.status,
                root_cause=self._shorten(peak_root_cause, 180),
                behavior=self._shorten(peak_behavior, 180),
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
            fieldnames = [
                'peak_id', 'problem_key', 'category', 'peak_type',
                'affected_apps', 'affected_namespaces', 'peak_count',
                'baseline_rate', 'peak_ratio', 'first_seen', 'last_seen',
                'occurrence_count', 'status', 'root_cause', 'behavior'
            ]
            if rows:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for row in rows:
                    row_dict = asdict(row)
                    writer.writerow({k: row_dict.get(k, '') for k in fieldnames})
            else:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
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
            lines.append("_Field semantics: `peak_count` = raw error logs in peak windows, `occurrence_count` = number of peak windows._")
            lines.append("")
            lines.append("| ID | Category | Type | Apps | Peak Ratio | Last Seen | Status |")
            lines.append("|-------|----------|------|------|------------|-----------|--------|")

            for row in rows:
                apps_short = row.affected_apps[:25] + "..." if len(row.affected_apps) > 25 else row.affected_apps
                lines.append(
                    f"| {row.peak_id} | {row.category} | {row.peak_type} | "
                    f"{apps_short} | {row.peak_ratio:.2f}x | {row.last_seen[:10] if row.last_seen else '-'} | {row.status} |"
                )
            # Peak Details section
            lines.append("")
            lines.append("## Peak Details")
            lines.append("")
            for row in rows[:30]:
                lines.append(f"### {row.peak_id}: {row.category} ({row.peak_type})")
                lines.append("")
                lines.append(f"- **Apps:** {row.affected_apps}")
                lines.append(f"- **Namespaces:** {row.affected_namespaces}")
                lines.append(f"- **Peak count:** {row.peak_count:,} | **Ratio:** {row.peak_ratio:.2f}x | **Occurrences:** {row.occurrence_count}")
                lines.append(f"- **First seen:** {row.first_seen} | **Last seen:** {row.last_seen}")
                lines.append(f"- **Status:** {row.status}")
                if row.root_cause:
                    lines.append(f"- **Root cause:** {row.root_cause}")
                if row.behavior:
                    lines.append("- **Behavior:**")
                    for bline in row.behavior.splitlines():
                        lines.append(f"  {bline}")
                lines.append("")
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
        recent_errors = [r for r in errors_rows if r.last_seen]  # Filter rows with timestamps
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
