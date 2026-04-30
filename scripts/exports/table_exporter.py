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

from core.problem_registry import ProblemRegistry, ProblemEntry, PeakEntry, is_test_peak_counts


# =============================================================================
# DATA MODELS FOR EXPORT
# =============================================================================

@dataclass
class ErrorTableRow:
    """Řádek v errors_table - operátorský view
    
    Pořadí (priority):
    1. Timing: first/last seen - WHEN se to stalo
    2. Frequency + Severity: occurrence + trend - HOW MUCH + HOW BAD
    3. Root Cause + Behavior - CO se děje (z enrichment)
    4. Scope: namespace + app - WHERE
    5. Meta: category, status, jira, notes (na konci)
    """
    first_seen: str                 # ISO format (ZAČÁTEK)
    last_seen: str                  # ISO format
    occurrence_total: int           # Celkový počet
    occurrence_24h: int             # Poslední 24 hodin
    severity: str                   # critical, high, medium, low
    trend_2h: str                   # 2 hours: ↑ increasing | → stable | ↓ decreasing + % změna
    trend_24h: str                  # 24 hours: ↑ increasing | → stable | ↓ decreasing + % změna
    root_cause: str                 # Výsledek analysis (CO se stalo) - z enrichment script
    behavior: str                   # Detailed behavior description
    affected_namespaces: str        # comma-separated
    affected_apps: str              # comma-separated (deployment labels)
    scope: str                      # LOCAL, CROSS_NS, SYSTEMIC
    category: str                   # Type (DB, Code, Auth, Infra, ...) 
    status: str                     # OPEN, MONITORING, RESOLVED
    jira: str                       # Jira ticket link
    notes: str                      # Human notes
    
    # Hidden technical fields (not in main CSV export)
    problem_id: str
    problem_key: str
    flow: str
    error_class: str
    detail: str                     # Klíčová info (metoda, service, endpoint, message snippet)
    score: float                    # Skóre detekce (0-100)
    ratio: float                    # Peak ratio vs. baseline



@dataclass
class PeakTableRow:
    """Řádek v peaks_table - operátorský view

    Pořadí sloupců (priority):
    1. Timing: first/last seen
    2. Frequency: total_errors, occurrence_count, avg_errors_per_peak
    3. Trend: trend_7d, periodicity
    4. Root Cause + Behavior (from enrichment / related problem / teams notif)
    5. Scope: affected_namespaces, affected_apps
    6. Meta: test, activity, peak_id
    """
    first_seen: str
    last_seen: str
    total_errors: int           # raw error count across all peak windows
    occurrence_count: int       # number of peak windows
    avg_errors_per_peak: float
    trend_7d: str               # 7-day trend: ↑ rising / → stable / ↓ falling + %
    periodicity: str            # periodic-daily / periodic-weekly / sporadic / one-time / unknown
    root_cause: str
    behavior: str
    affected_namespaces: str    # top 5 with counts
    affected_apps: str          # top 5 with counts
    test: str
    activity: str               # active/inactive based on 7-day window
    peak_id: str


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

    def _problem_behavior(self, problem: ProblemEntry) -> str:
        behavior = self._clean_unknown(getattr(problem, 'behavior', ''))
        if behavior:
            return behavior
        if getattr(problem, 'sample_messages', None):
            return self._shorten(problem.sample_messages[0], 300)
        detail_parts = [self._clean_unknown(problem.error_class), self._clean_unknown(problem.flow)]
        detail_parts = [part for part in detail_parts if part]
        return " / ".join(detail_parts)

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

    @staticmethod
    def _is_low_signal_peak_text(text: str) -> bool:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return True
        lowered = cleaned.lower()
        if any(marker in lowered for marker in ('error handled', 'unknownerror', 'unknown error', 'classified as unknown')):
            return True
        if len(cleaned) < 40:
            return True
        if '|' not in cleaned and ';' not in cleaned and '->' not in cleaned and lowered.endswith('exception'):
            return True
        return False

    @staticmethod
    def _clean_stack_trace(text: str) -> str:
        """Strip Java/Python stack trace frames, keep only the meaningful first part.

        Input:  "org.springframework...AccessDeniedException: Access is denied at org.spring..."
        Output: "org.springframework...AccessDeniedException: Access is denied"
        
        Also handles single-line traces where frames are separated by ' at '.
        """
        if not text:
            return text
        cleaned = " ".join(text.split())

        # Split on ' at ' (Java inline stack trace) — keep only the part before first frame
        import re
        # Pattern: " at SomeClass.method(" or "\n\tat "
        match = re.search(r'\s+at\s+[a-z][\w$.]+\.\w+\(', cleaned)
        if match:
            cleaned = cleaned[:match.start()].strip()

        # Also strip trailing "..." from shorten()
        if cleaned.endswith('...'):
            cleaned = cleaned[:-3].strip()

        return cleaned.strip()

    @staticmethod
    def _extract_exception_message(root_cause: str, behavior: str) -> str:
        """When root_cause is just a bare exception class name, extract the human message.

        Given:
          root_cause = "AccessDeniedException"
          behavior   = "...AccessDeniedException: Access is denied at org..."
        Returns:
          "Access is denied"
        """
        import re
        if not root_cause or ' ' in root_cause.strip():
            # Already has spaces = already a sentence, not a bare class name
            return root_cause

        # Try "SomeException: actual message" pattern in behavior
        pattern = re.compile(
            r'[A-Z][A-Za-z]+(?:Exception|Error|Denied|Fault|Failure)[^:]*:\s*(.+?)(?:\s+at\s+[a-z]|\s*$)',
            re.DOTALL
        )
        m = pattern.search(behavior or '')
        if m:
            msg = " ".join(m.group(1).split())[:200].strip()
            if msg and len(msg) > 5:
                return msg

        return root_cause

    @staticmethod
    def _is_test_peak_heuristic(peak: PeakEntry) -> bool:
        """Secondary test detection when originator_application_counts is empty.
        
        Checks if the peak's dominant trace ID or affected apps suggest test traffic.
        """
        # Check originator_application_counts first (primary method)
        oac = getattr(peak, 'originator_application_counts', {}) or {}
        if oac:
            return is_test_peak_counts(oac, getattr(peak, 'raw_error_count', 0) or 0)
        
        # Heuristic: check trace_counts for test-originator patterns
        trace_counts = getattr(peak, 'trace_counts', {}) or {}
        for trace_id in trace_counts:
            if trace_id and 'test' in str(trace_id).lower():
                return True
        
        # Heuristic: check if dominant_trace_id is from test
        dom_trace = getattr(peak, 'dominant_trace_id', '') or ''
        if dom_trace and 'test' in dom_trace.lower():
            return True
        
        # Stored flag
        return bool(getattr(peak, 'test', False))

    def _format_peak_behavior(
        self,
        peak: PeakEntry,
        fallback_message: str = '',
        fallback_service: str = '',
    ) -> str:
        """Format peak behavior as multi-line trace flow.

        Output:
            Behavior (trace flow): N messages

              1) app-name
                 "message"
              2) app-name
                 "message"
              ...

        ``fallback_message`` and ``fallback_service`` provide last-resort defaults
        when the peak has no own behavior data (sourced from related ProblemEntry).
        """
        steps = getattr(peak, 'behavior_steps', None) or []
        # Normalize and clean
        clean_steps: List[Dict[str, Any]] = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            app = str(s.get('app', '') or '').strip()
            msg = str(s.get('message', '') or '').strip()
            count = int(s.get('count', 0) or 0)
            msg = self._clean_stack_trace(msg)
            if app or msg:
                clean_steps.append({'app': app or '?', 'message': msg, 'count': count})

        if not clean_steps:
            # Legacy fallback: build a single synthetic step from peak.behavior
            # or from caller-provided fallback (related ProblemEntry).
            legacy = self._clean_unknown(getattr(peak, 'behavior', ''))
            legacy = self._clean_stack_trace(legacy)
            if not legacy and fallback_message:
                legacy = self._clean_stack_trace(fallback_message)
            if not legacy:
                return ''

            # Pick the dominant app from app_counts; if missing, use caller fallback,
            # then any affected app
            dom_app = ''
            app_counts = getattr(peak, 'app_counts', {}) or {}
            if app_counts:
                dom_app = max(app_counts.items(), key=lambda kv: int(kv[1] or 0))[0]
            elif getattr(peak, 'affected_apps', None):
                affected = sorted(peak.affected_apps)
                if affected:
                    dom_app = affected[0]
            if not dom_app and fallback_service:
                dom_app = fallback_service

            total = int(getattr(peak, 'raw_error_count', 0) or 0) or int(
                getattr(peak, 'occurrences', 0) or 1
            )
            lines = [f"Behavior (trace flow): {total:,} messages", ""]
            lines.append(f"  1) {dom_app or '?'}")
            escaped = legacy.replace('"', '\\"')
            lines.append(f'     "{escaped}"')
            return "\n".join(lines)

        total = getattr(peak, 'total_messages', 0) or sum(s['count'] for s in clean_steps)
        if not total:
            total = sum(s['count'] for s in clean_steps) or len(clean_steps)

        lines = [f"Behavior (trace flow): {total:,} messages", ""]
        for i, s in enumerate(clean_steps, 1):
            lines.append(f"  {i}) {s['app']}")
            if s['message']:
                # Wrap message in quotes; escape internal quotes
                escaped = s['message'].replace('"', '\\"')
                lines.append(f'     "{escaped}"')
        return "\n".join(lines)

    def _format_peak_root_cause(
        self,
        peak: PeakEntry,
        fallback_message: str = '',
        fallback_service: str = '',
    ) -> str:
        """Format peak root cause as 'Inferred root cause [confidence]:\n  - app: msg'.

        Uses structured fields when available (root_cause_service, root_cause_confidence),
        otherwise infers from first behavior_step or legacy peak.root_cause.
        ``fallback_message`` and ``fallback_service`` are last-resort defaults
        sourced from the related ProblemEntry by the caller.
        """
        # Get the message
        msg = self._clean_unknown(getattr(peak, 'root_cause', ''))
        msg = self._clean_stack_trace(msg)

        # Get the service (write-back) or first behavior step's app
        service = str(getattr(peak, 'root_cause_service', '') or '').strip()
        confidence = str(getattr(peak, 'root_cause_confidence', '') or '').strip()

        steps = getattr(peak, 'behavior_steps', None) or []
        first_step = next(
            (s for s in steps if isinstance(s, dict) and (s.get('app') or s.get('message'))),
            None,
        )

        if not service and first_step:
            service = str(first_step.get('app', '') or '').strip()

        if not msg and first_step:
            cand = self._clean_stack_trace(str(first_step.get('message', '') or '').strip())
            if cand:
                msg = cand

        # Legacy fallback for both message and service
        legacy_behavior = self._clean_unknown(getattr(peak, 'behavior', ''))
        legacy_behavior = self._clean_stack_trace(legacy_behavior)

        # Enrich: if msg is bare exception class, try to extract from behavior
        enriched = self._extract_exception_message(msg, legacy_behavior)
        if enriched and enriched != msg:
            msg = enriched

        # Last-resort: use legacy peak.behavior, then caller-provided fallback
        if not msg and legacy_behavior:
            msg = legacy_behavior
        if not msg and fallback_message:
            msg = self._clean_stack_trace(fallback_message)

        # Last-resort service: dominant app, affected apps, then caller fallback
        if not service:
            app_counts = getattr(peak, 'app_counts', {}) or {}
            if app_counts:
                top_app = max(app_counts.items(), key=lambda kv: int(kv[1] or 0))[0]
                if top_app:
                    service = str(top_app)
            elif getattr(peak, 'affected_apps', None):
                affected = sorted(peak.affected_apps)
                if affected:
                    service = affected[0]
        if not service and fallback_service:
            service = fallback_service

        if not service and not msg:
            return ''

        if not msg:
            msg = '(unknown)'

        # Default confidence when not set
        if not confidence:
            # higher confidence when we have explicit structured data
            confidence = 'medium' if getattr(peak, 'root_cause_service', '') else 'low'

        if service:
            return f"Inferred root cause [{confidence}]:\n  - {service}: {msg}"
        # No service available — show flat
        return f"Inferred root cause [{confidence}]: {msg}"

    @staticmethod
    def _format_apps_multiline(counts: Optional[Dict[str, int]],
                               fallback: Optional[List[str]] = None,
                               limit: int = 5) -> str:
        """Format app/NS counts as multi-line list, one entry per line.

        Sized so that wide columns can render properly without truncation.
        Format: 'app-name (count)' per line.
        """
        items: List[tuple] = []
        if counts:
            items = sorted(
                ((str(k), int(v or 0)) for k, v in counts.items() if k),
                key=lambda kv: -kv[1],
            )[:limit]
        elif fallback:
            items = [(str(x), 0) for x in fallback[:limit] if x]

        if not items:
            return ''

        lines = []
        for name, c in items:
            if c > 0:
                lines.append(f"{name} ({c:,})")
            else:
                lines.append(name)
        return "\n".join(lines)

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

    @staticmethod
    def _format_top_counts(counts: Optional[Dict[str, int]], fallback_values: Optional[List[str]] = None, limit: int = 5) -> str:
        ranked = [
            (str(key), int(value or 0))
            for key, value in (counts or {}).items()
            if key
        ]
        ranked.sort(key=lambda kv: (-kv[1], kv[0]))
        if ranked:
            items = [
                f"{name} ({count})" if count > 0 else name
                for name, count in ranked[:limit]
            ]
            if len(ranked) > limit:
                items.append(f"+{len(ranked) - limit} more")
            return ", ".join(items)

        fallback = [value for value in (fallback_values or []) if value]
        return ", ".join(fallback[:limit]) if fallback else ""

    def _compute_peak_activity(self, peak: PeakEntry, now: datetime) -> str:
        last_seen = self._ensure_aware(getattr(peak, 'last_seen', None))
        if last_seen is None:
            return 'unknown'
        if last_seen < now - timedelta(days=7):
            return 'inactive'

        occurrence_times = getattr(peak, 'occurrence_times', None) or []
        occurrence_counts = getattr(peak, 'occurrence_counts', None) or []
        aware_times = []
        counts = []
        for i, ts in enumerate(occurrence_times):
            aware_ts = self._ensure_aware(ts)
            if aware_ts:
                aware_times.append(aware_ts)
                counts.append(occurrence_counts[i] if i < len(occurrence_counts) else 1)

        if not aware_times:
            return 'active'

        H = 3600
        current_7d = self._volume_in_window(aware_times, counts, now, 0, 7 * 24 * H)
        previous_7d = self._volume_in_window(aware_times, counts, now, 7 * 24 * H, 14 * 24 * H)
        if previous_7d <= 0:
            return 'active / new'
        ratio = current_7d / previous_7d
        if ratio >= 1.2:
            return 'active / rising'
        if ratio <= 0.8:
            return 'active / falling'
        return 'active / stable'

    def _compute_peak_trend_7d(self, peak: PeakEntry, now: datetime) -> str:
        """Compute 7-day trend for peaks: current week vs previous week.
        
        Falls back to activity-based text when occurrence_times is empty.
        """
        occurrence_times = getattr(peak, 'occurrence_times', None) or []
        occurrence_counts = getattr(peak, 'occurrence_counts', None) or []
        aware_times = []
        counts = []
        for i, ts in enumerate(occurrence_times):
            aware_ts = self._ensure_aware(ts)
            if aware_ts:
                aware_times.append(aware_ts)
                counts.append(occurrence_counts[i] if i < len(occurrence_counts) else 1)

        if not aware_times:
            # Fallback: use last_seen to determine if peak is recent
            last_seen = self._ensure_aware(peak.last_seen)
            if not last_seen:
                return '→ no data'
            days_ago = (now - last_seen).total_seconds() / 86400.0
            if days_ago <= 7:
                return '→ active'
            return '→ inactive'

        H = 3600
        current_7d = self._volume_in_window(aware_times, counts, now, 0, 7 * 24 * H)
        previous_7d = self._volume_in_window(aware_times, counts, now, 7 * 24 * H, 14 * 24 * H)

        return self._format_window_trend(current_7d, float(previous_7d), "7d")

    def _compute_peak_periodicity(self, peak: PeakEntry, now: datetime) -> str:
        """Detect periodicity pattern for peaks.

        Analyzes occurrence_times to classify:
        - periodic-daily: occurs almost every day
        - periodic-weekly: occurs on specific weekdays
        - sporadic: occurs irregularly but repeatedly
        - one-time: occurred only once or twice
        - unknown: not enough data
        
        Falls back to first_seen/last_seen/occurrences when occurrence_times is empty.
        """
        occurrence_times = getattr(peak, 'occurrence_times', None) or []
        aware_times = []
        for ts in occurrence_times:
            aware_ts = self._ensure_aware(ts)
            if aware_ts:
                aware_times.append(aware_ts)

        # Fallback when occurrence_times is empty: use first/last seen + count
        if not aware_times:
            occurrences = max(1, int(getattr(peak, 'occurrences', 0) or 0))
            first_seen = self._ensure_aware(peak.first_seen)
            last_seen = self._ensure_aware(peak.last_seen)
            if occurrences <= 2:
                return 'one-time'
            if first_seen and last_seen:
                span_days = (last_seen - first_seen).total_seconds() / 86400.0
                if span_days < 1:
                    return 'sporadic'
                avg_gap_days = span_days / max(occurrences - 1, 1)
                if avg_gap_days <= 1.5:
                    return 'periodic-daily'
                if avg_gap_days <= 8:
                    return 'periodic-weekly'
                return 'sporadic'
            return 'unknown'

        if len(aware_times) <= 1:
            return 'one-time'
        if len(aware_times) == 2:
            gap = abs((aware_times[-1] - aware_times[0]).total_seconds())
            if gap < 3600:
                return 'one-time'
            return 'sporadic'

        aware_times.sort()

        # Compute inter-occurrence gaps in hours
        gaps_hours = []
        for i in range(1, len(aware_times)):
            gap = (aware_times[i] - aware_times[i - 1]).total_seconds() / 3600.0
            if gap > 0.25:  # ignore sub-15min duplicates
                gaps_hours.append(gap)

        if not gaps_hours:
            return 'one-time'

        # Compute span in days
        span_days = (aware_times[-1] - aware_times[0]).total_seconds() / 86400.0
        if span_days < 1:
            return 'sporadic' if len(aware_times) >= 3 else 'one-time'

        # Average gap
        avg_gap_h = sum(gaps_hours) / len(gaps_hours)

        # Unique days with occurrences
        unique_days = len(set(t.date() for t in aware_times))

        # Daily pattern: occurs on >60% of days in the span
        if span_days >= 3 and unique_days / max(span_days, 1) >= 0.6:
            return 'periodic-daily'

        # Weekly pattern: check if occurrences cluster on specific weekdays
        if span_days >= 14:
            weekday_counts = {}
            for t in aware_times:
                wd = t.weekday()
                weekday_counts[wd] = weekday_counts.get(wd, 0) + 1
            active_weekdays = sum(1 for c in weekday_counts.values() if c >= 2)
            if active_weekdays <= 2 and len(aware_times) >= 4:
                return 'periodic-weekly'

        # Sporadic: multiple occurrences but no clear pattern
        if len(aware_times) >= 3:
            return 'sporadic'

        return 'unknown'

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
            
            # Detail - klíčová info (shorthand)
            detail = f"{problem.error_class}"
            if problem.flow:
                detail = f"{detail} / {problem.flow[:30]}"
            
            row = ErrorTableRow(
                # 1. TIMING
                first_seen=first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "Unknown",
                last_seen=last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "Unknown",
                # 2. FREQUENCY + SEVERITY
                occurrence_total=problem.occurrences,
                occurrence_24h=occurrence_24h,
                severity=self._derive_severity(problem),
                trend_2h=trend_2h,
                trend_24h=trend_24h,
                # 3. ROOT CAUSE + BEHAVIOR
                root_cause=root_cause,
                behavior=behavior,
                # 4. SCOPE
                affected_namespaces=self._format_apps_multiline(
                    getattr(problem, 'ns_counts', None)
                    or getattr(problem, 'namespace_counts', None)
                    or {n: 0 for n in problem.affected_namespaces},
                    sorted(problem.affected_namespaces),
                    limit=5,
                ),
                affected_apps=self._format_apps_multiline(
                    getattr(problem, 'app_counts', None)
                    or {a: 0 for a in problem.affected_apps},
                    sorted(problem.affected_apps),
                    limit=5,
                ),
                scope=problem.scope,
                # 5. META
                category=problem.category,
                status=problem.status,
                jira=problem.jira or "",
                notes=problem.notes or "",
                # TECHNICAL (hidden from main view)
                problem_id=problem.id,
                problem_key=problem_key,
                flow=problem.flow,
                error_class=problem.error_class,
                detail=detail,
                score=self._derive_score(problem, occurrence_24h),
                ratio=self._derive_ratio(problem, occurrence_24h, now),
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

        # Column order: timing → frequency/severity → root cause → scope → meta
        fieldnames = [
            'first_seen', 'last_seen',
            'occurrence_total', 'occurrence_24h', 'severity', 'trend_2h', 'trend_24h',
            'root_cause', 'behavior',
            'affected_namespaces', 'affected_apps', 'scope',
            'category', 'status', 'jira', 'notes',
            'problem_id', 'problem_key', 'flow', 'error_class', 'detail', 'score', 'ratio'
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

            # Main table (compact version) — time → frequency → root cause → scope
            lines.append("## All Problems")
            lines.append("")
            lines.append("| First Seen | Last Seen | Total | 24h | Severity | Trend | Root Cause | Namespaces | Apps | Category | Status |")
            lines.append("|------------|-----------|-------|-----|----------|-------|------------|------------|------|----------|--------|")

            for row in rows:
                apps_short = row.affected_apps[:30] + "..." if len(row.affected_apps) > 30 else row.affected_apps
                ns_short = row.affected_namespaces[:25] + "..." if len(row.affected_namespaces) > 25 else row.affected_namespaces
                rc_short = row.root_cause[:40] + "..." if len(row.root_cause) > 40 else row.root_cause
                first_short = row.first_seen[:10] if row.first_seen else "-"
                last_short = row.last_seen[:10] if row.last_seen else "-"
                lines.append(
                    f"| {first_short} | {last_short} | {row.occurrence_total:,} | "
                    f"{row.occurrence_24h:,} | {row.severity} | {row.trend_24h} | "
                    f"{rc_short} | {ns_short} | {apps_short} | {row.category} | {row.status} |"
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
        """Převede Peak Registry na řádky tabulky.
        
        Retention: Peaks not seen for > 30 days relative to the newest peak
        are excluded from export. All other peaks are included (full history).
        """
        rows = []
        now = datetime.now(timezone.utc)

        # Retention cutoff: relative to the newest peak (not wall-clock)
        # This prevents data loss when the pipeline hasn't run recently
        newest_last_seen = None
        for peak in self.registry.peaks.values():
            ls = self._ensure_aware(peak.last_seen)
            if ls and (newest_last_seen is None or ls > newest_last_seen):
                newest_last_seen = ls
        retention_anchor = newest_last_seen or now
        retention_cutoff = retention_anchor - timedelta(days=30)

        for problem_key, peak in self.registry.peaks.items():
            first_seen = self._ensure_aware(peak.first_seen)
            last_seen = self._ensure_aware(peak.last_seen)

            # Retention: skip peaks not seen in 30 days
            if last_seen and last_seen < retention_cutoff:
                continue

            related_problem = None
            parts = problem_key.split(':') if problem_key else []
            if len(parts) >= 4 and parts[0] == 'PEAK':
                flow = parts[2]
            elif len(parts) > 1:
                flow = parts[1]
            else:
                flow = ''
            related_problem = self._find_related_problem_for_peak(peak, flow)

            # Resolve fallback values from related ProblemEntry once.
            related_root_cause = (
                self._problem_root_cause(related_problem)
                if related_problem is not None else ""
            )
            related_behavior = (
                self._problem_behavior(related_problem)
                if related_problem is not None else ""
            )

            # Pick a fallback service: dominant app (by count) or first affected app
            fallback_service = ''
            app_counts_map = getattr(peak, 'app_counts', {}) or {}
            if app_counts_map:
                fallback_service = max(
                    app_counts_map.items(), key=lambda kv: int(kv[1] or 0)
                )[0]
            elif getattr(peak, 'affected_apps', None):
                affected_sorted = sorted(peak.affected_apps)
                if affected_sorted:
                    fallback_service = affected_sorted[0]

            # Build NEW structured behavior + root_cause via dedicated formatters.
            # Output is multi-line:
            #   behavior:   "Behavior (trace flow): N messages\n  1) app\n     \"msg\""
            #   root_cause: "Inferred root cause [conf]:\n  - app: msg"
            peak_behavior = self._format_peak_behavior(
                peak,
                fallback_message=related_behavior,
                fallback_service=fallback_service,
            )
            peak_root_cause = self._format_peak_root_cause(
                peak,
                fallback_message=related_root_cause or related_behavior,
                fallback_service=fallback_service,
            )

            raw_peak_count = int(getattr(peak, 'raw_error_count', 0) or 0)
            if raw_peak_count <= 0:
                raw_peak_count = max(1, int(peak.max_value or 0))
            occurrence_count = max(1, int(getattr(peak, 'occurrences', 0) or 0))
            avg_errors_per_peak = round(raw_peak_count / occurrence_count, 1)
            is_test_peak = self._is_test_peak_heuristic(peak)
            activity = self._compute_peak_activity(peak, now)
            trend_7d = self._compute_peak_trend_7d(peak, now)
            periodicity = self._compute_peak_periodicity(peak, now)
            
            row = PeakTableRow(
                # 1. TIMING
                first_seen=first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "",
                last_seen=last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "",
                # 2. FREQUENCY
                total_errors=raw_peak_count,
                occurrence_count=occurrence_count,
                avg_errors_per_peak=avg_errors_per_peak,
                # 3. TREND
                trend_7d=trend_7d,
                periodicity=periodicity,
                # 4. ROOT CAUSE + BEHAVIOR (multi-line, no truncation here)
                root_cause=peak_root_cause,
                behavior=peak_behavior,
                # 5. SCOPE - multi-line per app/NS for readability
                affected_namespaces=self._format_apps_multiline(
                    getattr(peak, 'namespace_counts', {}),
                    sorted(peak.affected_namespaces),
                    limit=5,
                ),
                affected_apps=self._format_apps_multiline(
                    getattr(peak, 'app_counts', {}),
                    sorted(peak.affected_apps),
                    limit=5,
                ),
                # 6. META
                test='yes' if is_test_peak else 'no',
                activity=activity,
                peak_id=peak.id,
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

        # Column order: timing → frequency → trend → root cause → scope → meta
        fieldnames = [
            'first_seen', 'last_seen',
            'total_errors', 'occurrence_count', 'avg_errors_per_peak',
            'trend_7d', 'periodicity',
            'root_cause', 'behavior',
            'affected_namespaces', 'affected_apps',
            'test', 'activity', 'peak_id'
        ]

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                row_dict = asdict(row)
                writer.writerow({k: row_dict.get(k, '') for k in fieldnames})

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
            lines.append("_Field semantics: `total_errors` = raw error logs in peak windows, `occurrence_count` = number of peak windows, `periodicity` = pattern frequency._")
            lines.append("")
            lines.append("| First Seen | Last Seen | Errors | Occ | Avg | Trend 7d | Periodicity | Root Cause | Behavior | Namespaces | Applications | Test | Activity | ID |")
            lines.append("|------------|-----------|--------|-----|-----|----------|-------------|------------|----------|------------|--------------|------|----------|------|")

            for row in rows:
                apps_short = row.affected_apps[:60] + "..." if len(row.affected_apps) > 60 else row.affected_apps
                ns_short = row.affected_namespaces[:35] + "..." if len(row.affected_namespaces) > 35 else row.affected_namespaces
                rc_short = row.root_cause[:50] + "..." if len(row.root_cause) > 50 else row.root_cause
                beh_short = row.behavior[:50] + "..." if len(row.behavior) > 50 else row.behavior
                lines.append(
                    f"| {row.first_seen[:10] if row.first_seen else '-'} | "
                    f"{row.last_seen[:10] if row.last_seen else '-'} | "
                    f"{row.total_errors:,} | {row.occurrence_count:,} | {row.avg_errors_per_peak:.1f} | "
                    f"{row.trend_7d} | {row.periodicity} | "
                    f"{rc_short} | {beh_short} | {ns_short} | "
                    f"{apps_short} | {row.test} | {row.activity} | {row.peak_id} |"
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
