#!/usr/bin/env python3
"""
Email Notification via SMTP
============================

Sends email notifications when Teams webhook fails (DNS issues).

Environment Variables:
    TEAMS_EMAIL: Teams channel email (e.g., xxx@emea.teams.ms)
    SMTP_HOST: SMTP server (default: localhost)
    SMTP_PORT: SMTP port (default: 25)
    EMAIL_FROM: Sender email (default: ai-log-analyzer@kb.cz)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional


class EmailNotifier:
    """Sends email notifications as fallback for Teams."""
    
    def __init__(self):
        self.teams_email = os.getenv('TEAMS_EMAIL', '').strip()
        self.smtp_host = os.getenv('SMTP_HOST', 'localhost')
        self.smtp_port = int(os.getenv('SMTP_PORT', '25'))
        self.from_email = os.getenv('EMAIL_FROM', 'ai-log-analyzer@kb.cz')
        self.enabled = bool(self.teams_email)
    
    def is_enabled(self) -> bool:
        """Check if email notifications are configured."""
        return self.enabled
    
    def _send_email(self, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        """Send email via SMTP."""
        if not self.is_enabled():
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = self.teams_email
            
            # Plain text version
            text_part = MIMEText(body, 'plain', 'utf-8')
            msg.attach(text_part)

            # Optional HTML version
            if html_body:
                html_part = MIMEText(html_body, 'html', 'utf-8')
                msg.attach(html_part)
            
            # Send via SMTP
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as smtp:
                smtp.send_message(msg)
            
            return True
        except Exception as e:
            print(f"⚠️ Failed to send email: {e}")
            return False
    
    def send_backfill_completed(
        self,
        days_processed: int,
        successful_days: int,
        failed_days: int,
        total_incidents: int,
        saved_count: int,
        duration_minutes: float,
        summary: str = None
    ) -> bool:
        """Send backfill completion notification via email."""
        
        status = "✅ SUCCESS" if failed_days == 0 else "⚠️ PARTIAL"
        
        subject = f"[AI Log Analyzer] {status} - Backfill Complete ({days_processed} days)"
        
        if summary:
            body = f"{summary.strip()}\n"
        else:
            body = f"""AI Log Analyzer - Backfill Completed
{'='*70}

Status: {status}
Duration: {duration_minutes:.1f} minutes

Results:
    • Days processed: {days_processed}
    • Successful: {successful_days}
    • Failed: {failed_days}
    • Total incidents: {total_incidents:,}
    • Saved to DB: {saved_count:,}

"""
        
        wiki_url = "https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis"
        body += f"\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body += f"\nDetaily ZDE: {wiki_url}\n"
        
        return self._send_email(subject, body)

    def send_regular_phase_peak_alert(
        self,
        peak_message: str
    ) -> bool:
        """Send peak alert notification for regular 15-minute phase via email."""
        
        subject = "[Log Analyzer] ⚠️ PEAK ALERTING - (last 15 mins)"
        
        body = f"{peak_message.strip()}\n"
        
        # Wiki links
        known_peaks_url = "https://wiki.kb.cz/spaces/CCAT/pages/1334314203/Known+Peaks+-+Daily+Update"
        recent_incidents_url = "https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis"
        
        body += f"\nDetaily known peaku ZDE: {known_peaks_url}\n"
        
        # HTML version with formatted styling and clickable links
        html_body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; color: #333; background-color: #f9f9f9; margin: 0; padding: 20px;">
            <div style="max-width: 800px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px; border-left: 4px solid #ff9800;">
                <pre style="background: #f5f5f5; padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 12px;">{peak_message}</pre>
                <p style="margin-top: 20px;">
                    <a href="{known_peaks_url}" style="background: #ff9800; color: white; padding: 10px 15px; text-decoration: none; border-radius: 4px; display: inline-block; margin-right: 10px;">
                        📖 Detaily known peaku
                    </a>
                    <a href="{recent_incidents_url}" style="background: #0066cc; color: white; padding: 10px 15px; text-decoration: none; border-radius: 4px; display: inline-block;">
                        📊 Recent Incidents
                    </a>
                </p>
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </div>
        </body>
        </html>
        """
        
        return self._send_email(subject, body, html_body)

    def send_regular_phase_peak_alert_detailed(
        self,
        peak_error_class: str,
        peak_error_details: str,
        peak_type: str,
        is_known: bool,
        is_continues: bool,
        peak_id: str,
        error_count: int,
        window_start: datetime,
        window_end: datetime,
        affected_apps: list,
        affected_namespaces: list,
        namespace_counts: dict,
        trace_steps: list,
        root_cause: dict = None,
        propagation_info: dict = None,
        severity_icon: str = "⚠️"
    ) -> bool:
        """Send detailed peak alert notification for regular phase."""
        if not self.is_enabled():
            return False

        peak_status = "KNOWN" if is_known else "NEW"
        continuation = " (continued)" if is_known and is_continues else ""
        time_range = f"{window_start.strftime('%Y-%m-%d %H:%M')} - {window_end.strftime('%H:%M')}"

        namespace_counts = namespace_counts or {}
        ns_count_parts = []
        for ns in sorted(affected_namespaces or []):
            count = namespace_counts.get(ns)
            if isinstance(count, int) and count > 0:
                ns_count_parts.append(f"{ns} ({count})")
            else:
                ns_count_parts.append(ns)
        namespaces_text = ", ".join(ns_count_parts) if ns_count_parts else "N/A"

        body_lines = [
            f"[AI Log Analyzer] {severity_icon} PEAK ALERT",
            "",
            f"Status: {peak_status}{continuation}",
            f"Time: {time_range}",
            f"Error Class: {peak_error_class}",
            f"Peak Type: {peak_type}",
            "",
            f"Error Info: {peak_error_details}",
            f"Raw Errors: {error_count:,}",
            f"Affected Apps: {', '.join(affected_apps) if affected_apps else 'N/A'}",
            f"Namespaces: {namespaces_text}",
        ]

        if trace_steps:
            body_lines.extend(["", "Behavior Flow:"])
            for step in trace_steps[:7]:
                app = step.get('app', '?') if isinstance(step, dict) else getattr(step, 'app', '?')
                msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                body_lines.append(f"  {app}: {msg}")

        if root_cause and not is_known:
            body_lines.extend([
                "",
                f"Root Cause: {root_cause.get('service', '?')}",
                f"  {root_cause.get('message', '')}",
            ])

        if propagation_info and not is_known and propagation_info.get('service_count', 0) > 1:
            body_lines.extend([
                "",
                f"Propagation: {propagation_info.get('type', 'Unknown')}",
                f"  Services affected: {propagation_info.get('service_count', 'N/A')}",
            ])

        body = "\n".join(body_lines)

        html_trace = ""
        if trace_steps:
            trace_rows = []
            for step in trace_steps[:7]:
                app = step.get('app', '?') if isinstance(step, dict) else getattr(step, 'app', '?')
                msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                trace_rows.append(
                    f'<div style="padding:10px;margin-bottom:8px;border:1px solid #d9d9d9;">'
                    f'<div style="font-weight:700;">{app}</div>'
                    f'<div style="font-size:13px;word-break:break-word;">{msg}</div>'
                    f'</div>'
                )
            html_trace = (
                '<div style="margin-bottom:20px;">'
                '<div style="font-weight:700;text-decoration:underline;margin-bottom:10px;">Behavior Flow</div>'
                + "".join(trace_rows)
                + '</div>'
            )

        html_root = ""
        if root_cause and not is_known:
            html_root = (
                '<div style="margin-bottom:20px;">'
                '<div style="padding:12px;border:1px solid #d9d9d9;">'
                '<div style="font-weight:700;text-decoration:underline;">Inferred Root Cause</div>'
                f'<div style="margin-top:8px;"><strong>{root_cause.get("service", "?")}</strong></div>'
                f'<div style="margin-top:4px;">{root_cause.get("message", "")}</div>'
                '</div>'
                '</div>'
            )

        html_propagation = ""
        if propagation_info and not is_known and propagation_info.get('service_count', 0) > 1:
            html_propagation = (
                '<div style="margin-bottom:20px;">'
                '<div style="padding:12px;border:1px solid #d9d9d9;">'
                '<div style="font-weight:700;text-decoration:underline;">Service Propagation</div>'
                f'<div style="margin-top:8px;">Services affected: <strong>{propagation_info.get("service_count", "N/A")}</strong></div>'
                f'<div style="margin-top:4px;font-size:13px;">{propagation_info.get("type", "Unknown")}</div>'
                '</div>'
                '</div>'
            )

        html_body = f"""
        <html>
        <body style="font-family:'Segoe UI',Arial,sans-serif;color:#222;background-color:#ffffff;margin:0;padding:20px;">
            <div style="max-width:760px;margin:0 auto;border:1px solid #cfcfcf;">
                <div style="padding:16px;border-bottom:1px solid #cfcfcf;">
                    <h1 style="margin:0;font-size:21px;font-weight:700;">{severity_icon} Peak Alert - {peak_status}{continuation}</h1>
                    <div style="margin-top:4px;font-size:14px;">Regular Phase Detection - {time_range}</div>
                </div>
                <div style="padding:20px;">
                    <div style="margin-bottom:20px;">
                        <div style="font-weight:700;text-decoration:underline;margin-bottom:10px;">Peak Details</div>
                        <div><strong>Error Class:</strong> {peak_error_class}</div>
                        <div><strong>Error Info:</strong> {peak_error_details}</div>
                        <div><strong>Peak Type:</strong> {peak_type}</div>
                        <div><strong>Raw Errors:</strong> {error_count:,}</div>
                        <div><strong>Status:</strong> {peak_status}{continuation}</div>
                        {f'<div><strong>Peak ID:</strong> {peak_id}</div>' if is_known and peak_id else ''}
                    </div>
                    <div style="margin-bottom:20px;">
                        <div style="font-weight:700;text-decoration:underline;margin-bottom:10px;">Affected Scope</div>
                        <div><strong>Applications:</strong> {', '.join(affected_apps) if affected_apps else 'N/A'}</div>
                        <div><strong>Namespaces:</strong> {namespaces_text}</div>
                    </div>
                    {html_trace}
                    {html_root}
                    {html_propagation}
                    <div style="margin-top:20px;padding-top:15px;border-top:1px solid #d9d9d9;">
                        <a href="https://wiki.kb.cz/spaces/CCAT/pages/1334314203/Known+Peaks+-+Daily+Update" style="font-weight:700;text-decoration:underline;margin-right:16px;color:#222;">📖 Known Peaks</a>
                        <a href="https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis" style="font-weight:700;text-decoration:underline;color:#222;">📊 Recent Analysis</a>
                    </div>
                </div>
                <div style="text-align:center;padding:14px;border-top:1px solid #cfcfcf;font-size:12px;color:#555;">
                    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | AI Log Analyzer
                </div>
            </div>
        </body>
        </html>
        """

        subject = f"[AI Log Analyzer] {severity_icon} {peak_status} {peak_type} - {peak_error_class}"
        return self._send_email(subject, body, html_body)
