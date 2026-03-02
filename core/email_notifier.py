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
    
    def _send_email(self, subject: str, body: str, html_body: str = None) -> bool:
        """Send email via SMTP with optional HTML version."""
        if not self.is_enabled():
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = self.teams_email
            
            # Plain text version (required)
            text_part = MIMEText(body, 'plain', 'utf-8')
            msg.attach(text_part)
            
            # HTML version (if provided)
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
        
        # Wiki link
        wiki_url = "https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis"

        body += f"\nTimestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body += f"\nDetaily ZDE: {wiki_url}\n"

        # HTML version with clickable link
        if summary:
            html_summary = f'<pre style="background: #f5f5f5; padding: 10px; border-radius: 4px;">{summary}</pre>'
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2>AI Log Analyzer - Backfill Completed</h2>
                <hr style="border: 1px solid #ddd;">
                {html_summary}
                <p style="margin-top: 20px;">
                    <a href="{wiki_url}" style="background: #0066cc; color: white; padding: 10px 15px; text-decoration: none; border-radius: 4px; display: inline-block;">
                        📖 View Detailed Analysis
                    </a>
                </p>
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                    Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </body>
            </html>
            """
        else:
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2>AI Log Analyzer - Backfill Completed</h2>
                <hr style="border: 1px solid #ddd;">
                <p><strong>Status:</strong> {status}</p>
                <p><strong>Duration:</strong> {duration_minutes:.1f} minutes</p>
                <h3>Results:</h3>
                <ul>
                    <li>Days processed: {days_processed}</li>
                    <li>Successful: {successful_days}</li>
                    <li>Failed: {failed_days}</li>
                    <li>Total incidents: {total_incidents:,}</li>
                    <li>Saved to DB: {saved_count:,}</li>
                </ul>
                <p style="margin-top: 20px;">
                    <a href="{wiki_url}" style="background: #0066cc; color: white; padding: 10px 15px; text-decoration: none; border-radius: 4px; display: inline-block;">
                        📖 View Detailed Analysis
                    </a>
                </p>
                <p style="color: #666; font-size: 12px; margin-top: 20px;">
                    Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </p>
            </body>
            </html>
            """
        
        return self._send_email(subject, body, html_body)

    def send_regular_phase_peak_alert(
        self,
        peak_message: str
    ) -> bool:
        """Send peak alert notification for regular 15-minute phase via email (simple mode).
        
        This is the simple/fallback mode that wraps a pre-formatted text message.
        For detailed peak information, use send_regular_phase_peak_alert_detailed() instead.
        """
        
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
        peak_category: str,
        peak_error_class: str,
        is_known: bool,
        is_continues: bool,
        peak_id: str,
        error_count: int,
        window_start: datetime,
        window_end: datetime,
        affected_apps: list,
        affected_namespaces: list,
        trace_steps: list,
        root_cause: dict = None,
        propagation_info: dict = None,
        severity_icon: str = "⚠️"
    ) -> bool:
        """Send detailed peak alert notification for regular 15-minute phase.
        
        Structured, detailed email with only relevant peak information.
        
        Args:
            peak_category: Peak category (e.g., "ConnectionTimeoutException")
            peak_error_class: Error class
            is_known: Whether this is a known peak
            is_continues: Whether peak continues from previous window
            peak_id: Peak ID (for KNOWN peaks) or empty string
            error_count: Total error/incident count for this peak
            window_start: When the peak window started
            window_end: When the peak window ended
            affected_apps: List of affected application names
            affected_namespaces: List of affected namespaces
            trace_steps: List of trace flow steps (each with 'app' and 'message')
            root_cause: Dict with 'service' and 'message' keys (only for NEW peaks)
            propagation_info: Dict with propagation details (only for NEW peaks)
            severity_icon: Severity icon (🔴/🟠/🟡/⚪)
        """
        
        if not self.is_enabled():
            return False
        
        # Determine peak status
        peak_status = "KNOWN" if is_known else "NEW"
        if is_known and is_continues:
            peak_status = f"KNOWN (continued)"
        
        status_color = "#d32f2f" if peak_status == "NEW" else "#f57c00"  # Red for NEW, Orange for KNOWN
        
        # Format time range
        time_range = f"{window_start.strftime('%Y-%m-%d %H:%M')} - {window_end.strftime('%H:%M')}"
        
        # Build text body
        body_lines = [
            f"[AI Log Analyzer] {severity_icon} PEAK ALERT",
            "",
            f"Status: {peak_status}",
            f"Time: {time_range}",
            f"Peak: {peak_category} / {peak_error_class}",
            "",
            f"Raw Errors: {error_count:,}",
            f"Affected Apps: {', '.join(affected_apps) if affected_apps else 'N/A'}",
            f"Namespaces: {', '.join(affected_namespaces) if affected_namespaces else 'N/A'}",
        ]
        
        if trace_steps:
            body_lines.extend([
                "",
                "Behavior Flow:",
            ])
            for step in trace_steps[:7]:  # Max 7 steps
                app = step.get('app', '?') if isinstance(step, dict) else getattr(step, 'app', '?')
                msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                body_lines.append(f"  {app}: {msg}")
        
        if root_cause and peak_status == "NEW":
            body_lines.extend([
                "",
                f"Root Cause: {root_cause.get('service', '?')}",
                f"  {root_cause.get('message', '')}",
            ])
        
        if propagation_info and peak_status == "NEW" and propagation_info.get('service_count', 0) > 1:
            body_lines.extend([
                "",
                f"Propagation: {propagation_info.get('type', 'Unknown')}",
                f"  Services affected: {propagation_info.get('service_count', 'N/A')}",
            ])
        
        body = "\n".join(body_lines)
        
        # Build HTML body
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: 'Segoe UI', Arial, sans-serif; color: #333; background-color: #f5f5f5; margin: 0; padding: 20px; }}
                .container {{ max-width: 700px; margin: 0 auto; background-color: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
                .header {{ background-color: {status_color}; color: white; padding: 20px; }}
                .header h1 {{ margin: 0; font-size: 22px; }}
                .header .subtitle {{ margin: 5px 0 0 0; font-size: 14px; opacity: 0.95; }}
                .content {{ padding: 20px; }}
                .section {{ margin-bottom: 20px; }}
                .section-title {{ font-weight: 600; color: #1976d2; margin-bottom: 10px; border-bottom: 2px solid #e0e0e0; padding-bottom: 5px; }}
                .info-row {{ display: flex; margin-bottom: 8px; }}
                .info-label {{ font-weight: 600; width: 160px; color: #555; }}
                .info-value {{ flex: 1; color: #333; }}
                .trace-step {{ background-color: #f9f9f9; padding: 10px; margin-bottom: 8px; border-left: 3px solid #42a5f5; }}
                .trace-app {{ font-weight: 600; color: #1565c0; margin-bottom: 3px; }}
                .trace-msg {{ color: #666; font-size: 13px; word-break: break-word; }}
                .root-cause {{ background-color: #fff3e0; padding: 12px; border-left: 4px solid #ff6f00; margin-bottom: 15px; }}
                .root-cause-label {{ font-weight: 600; color: #e65100; }}
                .propagation {{ background-color: #f3e5f5; padding: 12px; border-left: 4px solid #7b1fa2; }}
                .propagation-label {{ font-weight: 600; color: #6a1b9a; }}
                .footer {{ text-align: center; padding: 15px; border-top: 1px solid #e0e0e0; background-color: #fafafa; font-size: 12px; color: #999; }}
                .btn {{ display: inline-block; padding: 10px 15px; margin: 5px 5px 5px 0; border-radius: 4px; text-decoration: none; font-weight: 600; color: white; }}
                .btn-primary {{ background-color: #1976d2; }}
                .btn-secondary {{ background-color: #f57c00; }}
                .links {{ margin-top: 20px; padding-top: 15px; border-top: 1px solid #e0e0e0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>{severity_icon} Peak Alert - {peak_status}</h1>
                    <div class="subtitle">Regular Phase Detection - {time_range}</div>
                </div>
                <div class="content">
                    <div class="section">
                        <div class="section-title">Peak Details</div>
                        <div class="info-row">
                            <div class="info-label">Category:</div>
                            <div class="info-value"><strong>{peak_category}</strong></div>
                        </div>
                        <div class="info-row">
                            <div class="info-label">Error Class:</div>
                            <div class="info-value">{peak_error_class}</div>
                        </div>
                        <div class="info-row">
                            <div class="info-label">Raw Errors:</div>
                            <div class="info-value"><strong>{error_count:,}</strong></div>
                        </div>
                        <div class="info-row">
                            <div class="info-label">Status:</div>
                            <div class="info-value">{peak_status}</div>
                        </div>
                        {f'<div class="info-row"><div class="info-label">Peak ID:</div><div class="info-value">{peak_id}</div></div>' if is_known and peak_id else ''}
                    </div>
                    
                    <div class="section">
                        <div class="section-title">Affected</div>
                        <div class="info-row">
                            <div class="info-label">Applications:</div>
                            <div class="info-value">{', '.join(affected_apps) if affected_apps else 'N/A'}</div>
                        </div>
                        <div class="info-row">
                            <div class="info-label">Namespaces:</div>
                            <div class="info-value">{', '.join(affected_namespaces) if affected_namespaces else 'N/A'}</div>
                        </div>
                    </div>
                    
                    {f'''
                    <div class="section">
                        <div class="section-title">Behavior Flow</div>
                        {chr(10).join(f'<div class="trace-step"><div class="trace-app">{step.get("app", "?") if isinstance(step, dict) else getattr(step, "app", "?")}</div><div class="trace-msg">{step.get("message", "") if isinstance(step, dict) else getattr(step, "message", "")}</div></div>' for step in trace_steps[:7])}
                    </div>
                    ''' if trace_steps else ''}
                    
                    {f'''
                    <div class="section">
                        <div class="root-cause">
                            <div class="root-cause-label">Inferred Root Cause</div>
                            <div style="margin-top: 8px;"><strong>{root_cause.get("service", "?")}</strong></div>
                            <div style="color: #d84315; margin-top: 4px;">{root_cause.get("message", "")}</div>
                        </div>
                    </div>
                    ''' if root_cause and peak_status == "NEW" else ''}
                    
                    {f'''
                    <div class="section">
                        <div class="propagation">
                            <div class="propagation-label">Service Propagation</div>
                            <div style="margin-top: 8px;">Services affected: <strong>{propagation_info.get("service_count", "N/A")}</strong></div>
                            <div style="color: #555; margin-top: 4px; font-size: 13px;">{propagation_info.get("type", "Unknown")}</div>
                        </div>
                    </div>
                    ''' if propagation_info and peak_status == "NEW" and propagation_info.get("service_count", 0) > 1 else ''}
                    
                    <div class="links">
                        <a href="https://wiki.kb.cz/spaces/CCAT/pages/1334314203/Known+Peaks+-+Daily+Update" class="btn btn-secondary">📖 Known Peaks</a>
                        <a href="https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis" class="btn btn-primary">📊 Recent Analysis</a>
                    </div>
                </div>
                <div class="footer">
                    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | AI Log Analyzer
                </div>
            </div>
        </body>
        </html>
        """
        
        subject = f"[AI Log Analyzer] {severity_icon} {peak_status} PEAK - {peak_category}"
        return self._send_email(subject, body, html_body)

