#!/usr/bin/env python3
"""
Teams Notification (Email Only)
===============================

Sends notifications about backfill and regular phase completion.
Teams webhook is disabled (CNTLM required in pod).

Environment Variables:
    TEAMS_ENABLED: true/false (default: false)
    TEAMS_USE_EMAIL_PRIMARY: true/false (default: true)
"""

import os
from typing import Optional, Dict

try:
    from core.email_notifier import EmailNotifier
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False


class TeamsNotifier:
    """Sends formatted messages via email (Teams webhook disabled)."""

    def __init__(self):
        self.enabled = os.getenv('TEAMS_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.host = os.getenv('HOSTNAME', 'unknown-host')
        self.env = os.getenv('ENVIRONMENT', 'production')
        self.email_notifier = EmailNotifier() if HAS_EMAIL else None
        self.use_email_primary = os.getenv('TEAMS_USE_EMAIL_PRIMARY', 'true').lower() in ('true', '1', 'yes')

    def is_enabled(self) -> bool:
        """Check if notifications are enabled."""
        return self.enabled and self.email_notifier is not None and self.email_notifier.is_enabled()

    def _build_report_snippet(
        self,
        problem_report: Optional[str],
        peaks_info: Optional[Dict[str, int]] = None
    ) -> str:
        if not problem_report:
            return ""

        import re

        lines = []

        # Header
        header_match = re.search(
            r'Period: (.+?)\nGenerated: (.+?)\nRun ID: (.+?)(?:\n|$)',
            problem_report
        )
        if header_match:
            period, generated, run_id = header_match.groups()
            lines.extend([
                f"Period: {period}",
                f"Generated: {generated}",
                f"Run ID: {run_id}",
                ""
            ])

        # Executive Summary
        exec_match = re.search(
            r'^-{70}\nEXECUTIVE SUMMARY\n-{70}\n(.*?)\n-{70}',
            problem_report,
            re.MULTILINE | re.DOTALL
        )
        if exec_match:
            lines.append("Executive Summary")
            for line in exec_match.group(1).strip().splitlines():
                cleaned = line.lstrip()
                if cleaned.startswith("- "):
                    cleaned = cleaned[2:]
                lines.append(cleaned)

        # Peaks info
        if peaks_info:
            total_peaks = peaks_info.get('total')
            new_peaks = peaks_info.get('new')
            spikes = peaks_info.get('spikes')
            bursts = peaks_info.get('bursts')

            if total_peaks is not None or new_peaks is not None or spikes is not None or bursts is not None:
                lines.append("")
                parts = []
                if total_peaks is not None and new_peaks is not None:
                    known_peaks = max(total_peaks - new_peaks, 0)
                    parts.append(f"Peaks: total {total_peaks} (known {known_peaks}, new {new_peaks})")
                elif total_peaks is not None:
                    parts.append(f"Peaks: total {total_peaks}")
                elif new_peaks is not None:
                    parts.append(f"Peaks: new {new_peaks}")

                if spikes is not None:
                    parts.append(f"Spikes: {spikes}")
                if bursts is not None:
                    parts.append(f"Bursts: {bursts}")

                lines.extend(parts)

        return "\n".join([l for l in lines if l is not None])

    def send_backfill_completed(
        self,
        days_processed: int,
        successful_days: int,
        failed_days: int,
        total_incidents: int,
        saved_count: int,
        registry_updates: Dict[str, int],
        duration_minutes: float,
        problem_report: str = None
    ) -> bool:
        """Send completion notification for backfill (email only)."""

        if not (self.use_email_primary and self.email_notifier and self.email_notifier.is_enabled()):
            print("⚠️ Email notifier not enabled")
            return False

        peaks_info = {
            'total': registry_updates.get('total_peaks'),
            'new': registry_updates.get('new_peaks')
        } if registry_updates else None

        report_snippet = self._build_report_snippet(problem_report, peaks_info=peaks_info)

        success = self.email_notifier.send_backfill_completed(
            days_processed=days_processed,
            successful_days=successful_days,
            failed_days=failed_days,
            total_incidents=total_incidents,
            saved_count=saved_count,
            duration_minutes=duration_minutes,
            summary=report_snippet
        )

        if success:
            print("✅ Email notification sent successfully")
            return True

        print("⚠️ Email notification failed")
        return False

    def send_backfill_error(
        self,
        error_message: str,
        days_attempted: int,
        error_count: int
    ) -> bool:
        """Backfill error notification (webhook disabled)."""
        print(f"⚠️ Backfill error: {error_message} (days_attempted={days_attempted}, error_count={error_count})")
        return False

    def send_regular_phase_completed(
        self,
        new_incidents: int,
        total_processed: int,
        peaks_detected: int,
        errors: int,
        registry_updated: bool,
        duration_seconds: float,
        problem_report: str = None,
        peaks_info: Optional[Dict[str, int]] = None,
        summary_override: Optional[str] = None
    ) -> bool:
        """Send completion notification for regular 15-minute phase (email only)."""

        if not (self.email_notifier and self.email_notifier.is_enabled()):
            print("⚠️ Email notifier not enabled")
            return False

        report_snippet = self._build_report_snippet(problem_report, peaks_info=peaks_info)

        summary = summary_override or report_snippet or (
            f"Window completed with {new_incidents} new incidents, "
            f"{peaks_detected} peaks, {errors} errors."
        )

        return self.email_notifier.send_backfill_completed(
            days_processed=1,
            successful_days=1 if errors == 0 else 0,
            failed_days=1 if errors > 0 else 0,
            total_incidents=total_processed,
            saved_count=total_processed,
            duration_minutes=duration_seconds / 60.0,
            summary=summary
        )


# Singleton instance
_notifier_instance: Optional[TeamsNotifier] = None


def get_notifier() -> TeamsNotifier:
    """Get or create the Teams notifier singleton."""
    global _notifier_instance
    if _notifier_instance is None:
        _notifier_instance = TeamsNotifier()
    return _notifier_instance


def reset_notifier() -> None:
    """Reset the notifier (for testing)."""
    global _notifier_instance
    _notifier_instance = None
