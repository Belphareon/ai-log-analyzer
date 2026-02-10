#!/usr/bin/env python3
"""
Teams Webhook Integration
=========================

Sends notifications to Microsoft Teams about backfill and regular phase completion.

Environment Variables:
    TEAMS_WEBHOOK_URL: Microsoft Teams Incoming Webhook URL
    TEAMS_ENABLED: true/false (default: false)
    TEAMS_EMAIL: Teams channel email as fallback (e.g., xxx@emea.teams.ms)
"""

import os
import requests
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

try:
    from core.email_notifier import EmailNotifier
    HAS_EMAIL = True
except ImportError:
    HAS_EMAIL = False


class TeamsNotifier:
    """Sends formatted messages to Microsoft Teams via Incoming Webhook."""
    
    def __init__(self):
        self.webhook_url = os.getenv('TEAMS_WEBHOOK_URL', '').strip()
        self.enabled = os.getenv('TEAMS_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.host = os.getenv('HOSTNAME', 'unknown-host')
        self.env = os.getenv('ENVIRONMENT', 'production')
        # Email is PRIMARY when webhook DNS fails
        self.email_notifier = EmailNotifier() if HAS_EMAIL else None
        self.use_email_primary = os.getenv('TEAMS_USE_EMAIL_PRIMARY', 'true').lower() in ('true', '1', 'yes')
    
    def is_enabled(self) -> bool:
        """Check if Teams notifications are enabled."""
        return self.enabled and bool(self.webhook_url)
    
    def _send_message(self, message_body: Dict[str, Any]) -> bool:
        """Send message to Teams webhook."""
        if not self.is_enabled():
            return False
        
        try:
            response = requests.post(
                self.webhook_url,
                json=message_body,
                timeout=10
            )
            response.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            print(f"⚠️ Failed to send Teams webhook: {e}")
            
            # Try email fallback
            if self.email_fallback and self.email_fallback.is_enabled():
                print("📧 Attempting email fallback...")
                # Email fallback handled in send_backfill_completed
            
            return False
    
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
        """Send completion notification for backfill.
        
        Strategy: Use EMAIL as PRIMARY method (webhook DNS often fails in K8s).
        If email succeeds, skip webhook. If email fails, try webhook as fallback.
        """
        
        # Extract EXECUTIVE SUMMARY from problem report if available
        summary_text_plain = ""
        if problem_report:
            import re
            match = re.search(
                r'^-{70}\nEXECUTIVE SUMMARY\n-{70}\n(.*?)\n-{70}',
                problem_report,
                re.MULTILINE | re.DOTALL
            )
            if match:
                summary_text_plain = match.group(1).strip()
        
        # === PRIMARY: Try email first (more reliable in K8s) ===
        if self.use_email_primary and self.email_notifier and self.email_notifier.is_enabled():
            print("📧 Using email as primary notification method...")
            success = self.email_notifier.send_backfill_completed(
                days_processed=days_processed,
                successful_days=successful_days,
                failed_days=failed_days,
                total_incidents=total_incidents,
                saved_count=saved_count,
                duration_minutes=duration_minutes,
                summary=summary_text_plain
            )
            if success:
                print("✅ Email notification sent successfully")
                return True
            else:
                print("⚠️ Email notification failed, trying webhook as fallback...")
        
        # === FALLBACK: Try webhook ===
        color = "28a745" if failed_days == 0 else "ffc107"
        if summary_text_plain:
            text_content = f"**Log Analyzer run at {datetime.now().strftime('%m/%d/%Y %H:%M:%S')}**\n\n**Run Summary:**\n\n{summary_text_plain}"
        else:
            text_content = f"**Log Analyzer run at {datetime.now().strftime('%m/%d/%Y %H:%M:%S')}**\n\nBackfill completed: {successful_days}/{days_processed} days processed, {total_incidents:,} incidents saved"
        
        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": "Log Analyzer - Backfill completed",
            "themeColor": color,
            "sections": [{"text": text_content}]
        }
        
        return self._send_message(message)
    
    def send_backfill_error(
        self,
        error_message: str,
        days_attempted: int,
        error_count: int
    ) -> bool:
        """Send error notification for backfill failures."""
        
        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"Backfill error on {self.host}",
            "themeColor": "dc3545",
            "sections": [
                {
                    "activityTitle": "❌ Backfill Failed",
                    "activitySubtitle": f"Host: {self.host} | Environment: {self.env}",
                    "facts": [
                        {"name": "Error Message", "value": error_message},
                        {"name": "Days Attempted", "value": str(days_attempted)},
                        {"name": "Errors", "value": str(error_count)},
                        {"name": "Timestamp", "value": datetime.now().isoformat()},
                    ]
                }
            ]
        }
        
        return self._send_message(message)
    
    def send_regular_phase_completed(
        self,
        new_incidents: int,
        total_processed: int,
        peaks_detected: int,
        errors: int,
        registry_updated: bool,
        duration_seconds: float
    ) -> bool:
        """Send completion notification for regular 15-minute phase."""
        
        color = "28a745" if errors == 0 else "ffc107"
        
        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": f"Regular phase completed on {self.host}",
            "themeColor": color,
            "sections": [
                {
                    "activityTitle": "✅ Regular Phase Completed",
                    "activitySubtitle": f"Host: {self.host} | Environment: {self.env}",
                    "facts": [
                        {"name": "New Incidents", "value": str(new_incidents)},
                        {"name": "Total Processed", "value": str(total_processed)},
                        {"name": "Peaks Detected", "value": str(peaks_detected)},
                        {"name": "Errors", "value": str(errors)},
                        {"name": "Registry Updated", "value": "Yes" if registry_updated else "No"},
                        {"name": "Duration", "value": f"{duration_seconds:.1f} seconds"},
                        {"name": "Timestamp", "value": datetime.now().isoformat()},
                    ]
                }
            ]
        }
        
        return self._send_message(message)


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
