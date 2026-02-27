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

