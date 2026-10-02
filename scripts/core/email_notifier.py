#!/usr/bin/env python3
"""
Email + Teams Webhook Notifications
====================================

Sends notifications via email and/or Microsoft Teams incoming webhook.
Both channels can be enabled independently or together.

Environment Variables:
    TEAMS_ENABLED: true/false (default: false) - master switch
    TEAMS_WEBHOOK_URL: Microsoft Teams Incoming Webhook URL (optional)
    TEAMS_EMAIL: Teams channel email, e.g. xxx@emea.teams.ms (optional)
    SMTP_HOST: SMTP server (default: localhost)
    SMTP_PORT: SMTP port (default: 25)
    EMAIL_FROM: Sender email (default: ai-log-analyzer@kb.cz)
"""

import os
import smtplib
import requests
from html import escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo


class EmailNotifier:
    """Sends notifications via email and/or Teams incoming webhook."""
    
    def __init__(self):
        self.teams_email = os.getenv('TEAMS_EMAIL', '').strip()
        self.smtp_host = os.getenv('SMTP_HOST', 'localhost')
        self.smtp_port = int(os.getenv('SMTP_PORT', '25'))
        self.from_email = os.getenv('EMAIL_FROM', 'ai-log-analyzer@kb.cz')
        self.webhook_url = os.getenv('TEAMS_WEBHOOK_URL', '').strip()
        self.master_enabled = os.getenv('TEAMS_ENABLED', 'false').lower() in ('true', '1', 'yes')
        self.enabled = self.master_enabled and (bool(self.teams_email) or bool(self.webhook_url))
        self.last_delivery_results: List[Dict[str, Any]] = []
    
    def is_enabled(self) -> bool:
        """Check if at least one notification channel (email or webhook) is configured and enabled."""
        return self.enabled

    def get_last_delivery_results(self) -> List[Dict[str, Any]]:
        """Return a copy of per-destination outcomes from the latest send."""
        return [dict(result) for result in self.last_delivery_results]

    def _record_delivery(
        self,
        destination: str,
        delivered: bool,
        provider_message: str,
    ) -> None:
        self.last_delivery_results.append({
            'destination': destination,
            'status': 'delivered' if delivered else 'failed',
            'provider_message': provider_message[:4000],
            'attempted_at': datetime.now(timezone.utc),
        })
    
    def _send_webhook(self, subject: str, body: str) -> bool:
        """Send message to Microsoft Teams incoming webhook."""
        if not self.webhook_url:
            return False

        message = {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "summary": subject,
            "themeColor": "28a745",
            "sections": [
                {
                    "activityTitle": subject,
                    "text": body.replace("\n", "\n\n")
                }
            ]
        }

        try:
            response = requests.post(self.webhook_url, json=message, timeout=10)
            response.raise_for_status()
            self._record_delivery(
                'teams_webhook', True, f'HTTP {response.status_code}'
            )
            print("✅ Teams webhook accepted message")
            return True
        except requests.exceptions.RequestException as e:
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            provider_message = (
                f'HTTP {status_code}'
                if status_code
                else e.__class__.__name__
            )
            self._record_delivery('teams_webhook', False, provider_message)
            print(f"⚠️ Failed to send Teams webhook message: {provider_message}")
            return False

    def _send_email(self, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        """Send notification via whichever channel(s) are configured (email and/or webhook)."""
        self.last_delivery_results = []
        if not self.is_enabled():
            return False

        results = []

        if self.webhook_url:
            results.append(self._send_webhook(subject, body))

        if self.teams_email:
            results.append(self._send_email_smtp(subject, body, html_body))

        return any(results)

    def _send_email_smtp(self, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        """Send email via SMTP."""
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
                refused = smtp.send_message(msg)

            if refused:
                self._record_delivery(
                    'teams_email', False,
                    f'SMTP refused {len(refused)} recipient(s)',
                )
                print(f"⚠️ SMTP refused recipients: {refused}")
                return False

            self._record_delivery('teams_email', True, 'SMTP accepted message')
            print(f"✅ SMTP accepted message to {self.teams_email}")
            
            return True
        except Exception as e:
            self._record_delivery('teams_email', False, str(e))
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

    def send_workflow_lifecycle_alert(self, diagnostic_message: str) -> bool:
        """Send a persisted, high-confidence workflow lifecycle alert."""
        subject = "[AI Log Analyzer] WORKFLOW LIFECYCLE ALERT"
        return self._send_email(subject, f"{diagnostic_message.strip()}\n")

    def send_regular_phase_peak_alert_detailed(
        self,
        peak_error_class: str,
        peak_error_details: str,
        peak_type: str,
        peak_identifier: str,
        is_known: bool,
        is_continues: bool,
        peak_id: str,
        error_count: int,
        window_start: datetime,
        window_end: datetime,
        affected_apps: list,
        app_counts: dict,
        affected_namespaces: list,
        namespace_counts: dict,
        trace_steps: list,
        behavior_text: str = "",
        root_cause: dict = None,
        propagation_info: dict = None,
        continuation_summary: dict = None,
        severity_icon: str = "⚠️"
    ) -> bool:
        """Send detailed peak alert notification for regular phase."""
        if not self.is_enabled():
            return False

        peak_status = "KNOWN" if is_known else "NEW"
        continuation = " (continued)" if is_known and is_continues else ""
        trend_value = None
        if is_known and is_continues and continuation_summary:
            trend_value = continuation_summary.get('trend')

        def _format_behavior_line(step: Dict[str, Any]) -> str:
            app = step.get('app', '?') if isinstance(step, dict) else getattr(step, 'app', '?')
            msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
            extras = []
            if isinstance(step, dict):
                count = step.get('count')
                share_pct = step.get('share_pct')
                namespaces = step.get('namespaces') or []
                if isinstance(count, int) and count > 0:
                    extras.append(f"count={count}")
                if isinstance(share_pct, (int, float)) and share_pct > 0:
                    extras.append(f"share={share_pct:.1f}%")
                if namespaces:
                    extras.append(f"ns={','.join(namespaces[:3])}")
            prefix = f"{app} [{' ; '.join(extras)}]" if extras else str(app)
            return f"{prefix}: {msg}"

        prague_tz = ZoneInfo('Europe/Prague')
        ws_local = window_start.astimezone(prague_tz) if window_start else None
        we_local = window_end.astimezone(prague_tz) if window_end else None
        ws_utc = window_start.astimezone(ZoneInfo('UTC')) if window_start else None
        we_utc = window_end.astimezone(ZoneInfo('UTC')) if window_end else None

        local_range = (
            f"{ws_local.strftime('%Y-%m-%d %H:%M %Z')} - {we_local.strftime('%H:%M %Z')}"
            if ws_local and we_local else "N/A"
        )
        utc_range = (
            f"{ws_utc.strftime('%Y-%m-%d %H:%M UTC')} - {we_utc.strftime('%H:%M UTC')}"
            if ws_utc and we_utc else "N/A"
        )

        namespace_counts = namespace_counts or {}
        app_counts = app_counts or {}

        def _format_count_scope(items: list, counts: dict, limit: int = 5) -> str:
            ranked = []
            seen = set()
            for name in items or []:
                if not name or name in seen:
                    continue
                seen.add(name)
                ranked.append((name, int(counts.get(name, 0) or 0)))
            ranked.sort(key=lambda kv: (-kv[1], kv[0]))
            if not ranked:
                return "N/A"
            display = [
                f"{name} ({count})" if count > 0 else name
                for name, count in ranked[:limit]
            ]
            if len(ranked) > limit:
                display.append(f"+{len(ranked) - limit} more")
            return ", ".join(display)

        namespaces_text = _format_count_scope(affected_namespaces, namespace_counts)
        apps_text = _format_count_scope(affected_apps, app_counts)

        body_lines = [
            f"[AI Log Analyzer] {severity_icon} PEAK ALERT",
            "",
            f"Status: {peak_status}{continuation}",
            f"Time (CET/CEST): {local_range}",
            f"Time (UTC): {utc_range}",
            f"Error Class: {peak_error_class}",
            f"Peak Type: {peak_type}",
            f"Peak Key: {peak_identifier}",
            "",
            f"Error Info: {peak_error_details}",
            f"Raw Errors: {error_count:,}",
            f"Affected Apps: {apps_text}",
            f"Namespaces: {namespaces_text}",
        ]

        if behavior_text:
            body_lines.append(f"Behavior: {behavior_text}")

        if is_known and is_continues and continuation_summary:
            body_lines.extend([
                "",
                "Continuation Summary:",
            ])
            if continuation_summary.get('trend'):
                body_lines.append(f"  Trend: {continuation_summary.get('trend')}")
            prev_avg = continuation_summary.get('previous_average_errors')
            if isinstance(prev_avg, int) and prev_avg > 0:
                body_lines.append(f"  Previous window average: {prev_avg:,}")
            new_namespaces = continuation_summary.get('new_namespaces', []) or []
            new_apps = continuation_summary.get('new_apps', []) or []
            if new_namespaces:
                body_lines.append(f"  New namespaces: {', '.join(new_namespaces)}")
            if new_apps:
                body_lines.append(f"  New apps: {', '.join(new_apps)}")
            top_types = continuation_summary.get('top_error_types')
            if top_types:
                body_lines.append(f"  Top error types: {top_types}")

        if trace_steps:
            body_lines.extend(["", "Behavior Flow:"])
            for step in trace_steps[:7]:
                body_lines.append(f"  {_format_behavior_line(step)}")

        if root_cause:
            body_lines.extend([
                "",
                f"Root Cause: {root_cause.get('service', '?')}",
                f"  {root_cause.get('message', '')}",
            ])

        if propagation_info and propagation_info.get('service_count', 0) > 1:
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
                meta = _format_behavior_line(step).split(': ', 1)[0]
                trace_rows.append(
                    f'<div style="padding:10px;margin-bottom:8px;border:1px solid #d9d9d9;">'
                    f'<div style="font-weight:700;">{meta}</div>'
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
        if root_cause:
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
        if propagation_info and propagation_info.get('service_count', 0) > 1:
            html_propagation = (
                '<div style="margin-bottom:20px;">'
                '<div style="padding:12px;border:1px solid #d9d9d9;">'
                '<div style="font-weight:700;text-decoration:underline;">Service Propagation</div>'
                f'<div style="margin-top:8px;">Services affected: <strong>{propagation_info.get("service_count", "N/A")}</strong></div>'
                f'<div style="margin-top:4px;font-size:13px;">{propagation_info.get("type", "Unknown")}</div>'
                '</div>'
                '</div>'
            )

        html_continuation = ""
        if is_known and is_continues and continuation_summary:
            prev_avg_html = ""
            prev_avg = continuation_summary.get('previous_average_errors')
            if isinstance(prev_avg, int) and prev_avg > 0:
                prev_avg_html = f'<div><strong>Previous window average:</strong> {prev_avg:,}</div>'
            new_namespaces = continuation_summary.get('new_namespaces', []) or []
            new_apps = continuation_summary.get('new_apps', []) or []
            top_types = continuation_summary.get('top_error_types') or 'N/A'
            trend_html = ''
            if continuation_summary.get('trend'):
                trend_html = f'<div style="margin-top:8px;"><strong>Trend:</strong> {continuation_summary.get("trend")}</div>'

            html_continuation = (
                '<div style="margin-bottom:20px;">'
                '<div style="padding:12px;border:1px solid #808080;">'
                '<div style="font-weight:700;text-decoration:underline;">Continuation Summary</div>'
                f'{trend_html}'
                f'{prev_avg_html}'
                f'<div><strong>New namespaces:</strong> {", ".join(new_namespaces) if new_namespaces else "none"}</div>'
                f'<div><strong>New apps:</strong> {", ".join(new_apps) if new_apps else "none"}</div>'
                f'<div><strong>Top error types:</strong> {top_types}</div>'
                '</div>'
                '</div>'
            )

        # Build Trend display from continuation_summary if available
        trend_display = f" | Trend: {trend_value}" if trend_value else ""
        
        html_body = f"""
        <html>
        <body style="font-family:'Segoe UI',Arial,sans-serif;color:inherit;background:transparent;margin:0;padding:20px;">
            <div style="max-width:760px;margin:0 auto;border:1px solid #808080;">
                <div style="padding:16px;border-bottom:1px solid #cfcfcf;">
                    <h1 style="margin:0;font-size:21px;font-weight:700;">{peak_error_class} | Status: {peak_status}{continuation}{trend_display}</h1>
                    <div style="margin-top:4px;font-size:14px;">Regular Phase Detection - {local_range}</div>
                </div>
                <div style="padding:20px;">
                    <div style="margin-bottom:20px;">
                        <div style="font-weight:700;text-decoration:underline;margin-bottom:10px;">Summary</div>
                        <div><strong>This window errors:</strong> {error_count:,}</div>"""
        
        if is_known and is_continues and continuation_summary:
            prev_avg = continuation_summary.get('previous_average_errors', 0)
            if isinstance(prev_avg, int) and prev_avg > 0:
                pct_change = ((error_count - prev_avg) / prev_avg * 100) if prev_avg > 0 else 0
                html_body += f'<div><strong>Previous window avg:</strong> {prev_avg:,} ({pct_change:+.0f}%)</div>'
        
        if is_known and peak_id:
            html_body += f'<div><strong>Peak ID:</strong> {peak_id}</div>'
        
        html_body += f"""
                    </div>
                    
                    <div style="margin-bottom:20px;">
                        <div style="font-weight:700;text-decoration:underline;margin-bottom:10px;">Error Details</div>
                        <div><strong>Error Info:</strong> {peak_error_details}</div>
                        <div><strong>Peak Type:</strong> {peak_type}</div>
                    </div>
                    
                    <div style="margin-bottom:20px;">
                        <div style="font-weight:700;text-decoration:underline;margin-bottom:10px;">Affected Scope</div>
                        <div><strong>Applications:</strong> {apps_text}</div>
                        <div><strong>Namespaces:</strong> {namespaces_text}</div>
                        <div><strong>Behavior:</strong> {behavior_text or 'N/A'}</div>
                    </div>
                    
                    {html_root}
                    {html_continuation}
                    {html_trace}
                    {html_propagation}
                    
                    <div style="margin-top:20px;padding-top:15px;border-top:1px solid #d9d9d9;">
                        <a href="https://wiki.kb.cz/spaces/CCAT/pages/1334314203/Known+Peaks+-+Daily+Update" style="font-weight:700;text-decoration:underline;margin-right:16px;color:#4ea1ff;">📖 Known Peaks</a>
                        <a href="https://wiki.kb.cz/spaces/CCAT/pages/1334314207/Recent+Incidents+-+Daily+Problem+Analysis" style="font-weight:700;text-decoration:underline;color:#4ea1ff;">📊 Recent Analysis</a>
                    </div>
                </div>
                <div style="text-align:center;padding:14px;border-top:1px solid #cfcfcf;font-size:12px;color:#555;">
                    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | AI Log Analyzer
                </div>
            </div>
        </body>
        </html>
        """

        subject = (
            f"[AI Log Analyzer] {severity_icon} {trend_symbol} {peak_error_class} "
            f"{error_count:,} ({status_short})"
        )
        return self._send_email(subject, body, html_body)

    def send_regular_phase_peak_digest(
        self,
        window_start: datetime,
        window_end: datetime,
        alerts: List[Dict[str, Any]],
        summary: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send an operator-centered digest with auditable cause-family impact."""
        operator_digest_enabled = os.getenv(
            'ALERT_OPERATOR_DIGEST_ENABLED', 'true'
        ).strip().lower() not in {'0', 'false', 'no', 'off'}
        if not operator_digest_enabled:
            return self._send_legacy_regular_phase_peak_digest(
                window_start, window_end, alerts, summary
            )
        if not self.is_enabled():
            return False

        summary = summary or {}
        prague_tz = ZoneInfo('Europe/Prague')
        ws_local = window_start.astimezone(prague_tz) if window_start else None
        we_local = window_end.astimezone(prague_tz) if window_end else None
        local_time_range = (
            f"{ws_local.strftime('%H:%M')} - {we_local.strftime('%H:%M')}"
            if ws_local and we_local else 'N/A'
        )
        local_date = (
            f"{ws_local.day}.{ws_local.month}.{ws_local.year}"
            if ws_local else 'N/A'
        )
        subject = f"AI Log Analyzer | {local_time_range} | {local_date}"

        def _metric(value: Any) -> str:
            if value is None:
                return 'n/a'
            try:
                number = float(value)
            except (TypeError, ValueError):
                return str(value)
            if number.is_integer():
                return f"{int(number):,}"
            return f"{number:,.1f}"

        def _scope(counts: Any, limit: int = 4) -> str:
            if not isinstance(counts, dict) or not counts:
                return 'n/a'
            ranked = sorted(
                counts.items(),
                key=lambda item: (-int(item[1] or 0), str(item[0])),
            )
            parts = [f"{name} ({_metric(count)})" for name, count in ranked[:limit]]
            if len(ranked) > limit:
                parts.append(f"+{len(ranked) - limit} more")
            return ', '.join(parts)

        def _families(alert: Dict[str, Any]) -> List[Dict[str, Any]]:
            families = [
                dict(family)
                for family in (alert.get('cause_families') or [])
                if isinstance(family, dict)
            ]
            if families:
                return families
            root_cause = alert.get('root_cause') or {}
            app_counts = alert.get('app_counts') or {}
            top_app = next(iter(app_counts), 'unknown-app')
            root_app = (
                root_cause.get('service', top_app)
                if isinstance(root_cause, dict) else top_app
            )
            return [{
                'canonical_cause': (
                    alert.get('root_cause_text')
                    or alert.get('error_class')
                    or 'Unknown cause'
                ),
                'root_app': root_app,
                'operation': 'unknown-operation',
                'outward_status': None,
                'assessment': 'unknown',
                'confidence': 'low',
                'next_action': 'Inspect the representative trace and assign an owner classification.',
                'raw_error_lines': int(alert.get('error_count', 0) or 0),
                'unique_operations': None,
                'amplification': None,
                'app_counts': app_counts,
                'namespace_counts': alert.get('namespace_counts') or {},
                'representative_trace_id': alert.get('trace_id') or '',
                'trace_ids': (),
                'operation_count_method': 'unavailable',
                'operation_count_confidence': 'low',
                'operation_count_reason': 'trace coverage unavailable',
            }]

        assessment_labels = {
            'technical_failure': 'TECHNICAL FAILURE',
            'business_rejection': 'BUSINESS / DATA REJECTION',
            'expected_outcome_logged_as_error': 'LIKELY EXPECTED OUTCOME',
            'unknown': 'NEEDS TRIAGE',
        }
        assessment_colors = {
            'technical_failure': '#b42318',
            'business_rejection': '#b54708',
            'expected_outcome_logged_as_error': '#175cd3',
            'unknown': '#475467',
        }

        normalized_alerts = [(alert, _families(alert)) for alert in alerts]
        all_trace_ids = {
            str(trace_id)
            for _alert, families in normalized_alerts
            for family in families
            for trace_id in (family.get('trace_ids') or ())
            if trace_id
        }
        represented_families = [
            family
            for _alert, families in normalized_alerts
            for family in families
        ]
        operation_counts = [
            int(family.get('unique_operations') or 0)
            for family in represented_families
            if family.get('unique_operations') is not None
        ]
        represented_operations = (
            None
            if any(
                family.get('unique_operations') is None
                for family in represented_families
            )
            else sum(operation_counts)
        )
        represented_operation_text = (
            f'{represented_operations:,}'
            if represented_operations is not None
            else 'n/a (one or more families have unavailable operation boundaries)'
        )
        raw_window_errors = int(summary.get('raw_window_errors', 0) or 0)
        family_count = sum(len(families) for _alert, families in normalized_alerts)
        represented_raw_lines = sum(
            int(alert.get('error_count', 0) or 0) for alert in alerts
        )
        reconciliation_rows = [
            alert.get('cause_reconciliation') or {}
            for alert in alerts
            if alert.get('cause_reconciliation')
        ]
        unexplained_raw_lines = sum(
            int(row.get('unexplained_raw_lines', 0) or 0)
            for row in reconciliation_rows
        )
        reconciliation_statuses = sorted({
            str(row.get('status') or alert.get('cause_evidence_status') or 'unknown')
            for alert, row in (
                (alert, alert.get('cause_reconciliation') or {})
                for alert in alerts
            )
            if row or alert.get('cause_evidence_status')
        })
        policy_summary = summary.get('notification_policy') or {}
        primary_count = int(
            policy_summary.get(
                'primary_send',
                sum(alert.get('policy_outcome') == 'primary_send' for alert in alerts),
            )
            or 0
        )
        digest_only_count = int(
            policy_summary.get(
                'digest_only',
                sum(alert.get('policy_outcome') == 'digest_only' for alert in alerts),
            )
            or 0
        )
        route_suppressed_count = int(
            policy_summary.get('route_suppressed', 0) or 0
        )

        lines = [
            'Operator Peak Report',
            f'Window: {local_date} {local_time_range} Europe/Prague',
            '',
            'WINDOW SIGNAL',
            f'  Raw ERROR lines fetched: {_metric(raw_window_errors)}' if raw_window_errors else '  Raw ERROR lines fetched: n/a',
            f'  Alert candidates: {len(alerts):,}',
            f'  Primary updates: {primary_count:,}',
            f'  Digest-only updates: {digest_only_count:,}',
            f'  Route-suppressed candidates: {route_suppressed_count:,}',
            f'  Cause families represented: {family_count:,}',
            f'  Raw lines represented by alerts: {represented_raw_lines:,}',
            f'  Operation occurrences represented: {represented_operation_text}',
            f'  Trace IDs represented as evidence: {len(all_trace_ids):,}',
        ]
        if reconciliation_rows:
            lines.extend([
                f'  Cause evidence status: {", ".join(reconciliation_statuses)}',
                f'  Cause unexplained raw lines: {unexplained_raw_lines:,}',
            ])

        html_alerts = []
        for alert_index, (alert, families) in enumerate(normalized_alerts, start=1):
            peak_type = str(alert.get('peak_type') or 'SPIKE')
            status = 'KNOWN' if alert.get('is_known') else 'NEW'
            policy_outcome = str(alert.get('policy_outcome') or 'primary_send')
            origin_label = str(
                alert.get('test_origin_label')
                or alert.get('test_originator_application')
                or ''
            )
            if policy_outcome != 'primary_send':
                summary_line = (
                    f'  {alert_index}. {alert.get("error_class", "unknown")} | '
                    f'{policy_outcome.upper()} | '
                    f'state={alert.get("policy_episode_state", "n/a")} | '
                    f'errors={int(alert.get("error_count", 0) or 0):,}'
                )
                if origin_label:
                    summary_line += f' | origin={origin_label}'
                lines.append(summary_line)
                html_alerts.append(
                    '<section style="margin-top:14px;padding:10px 12px;'
                    'border-top:1px solid #d0d5dd;">'
                    f'<strong>Candidate {alert_index}: '
                    f'{escape(str(alert.get("error_class", "unknown")))}</strong> '
                    f'<span>{escape(policy_outcome.upper())} | '
                    f'state={escape(str(alert.get("policy_episode_state", "n/a")))}, '
                    f'errors={int(alert.get("error_count", 0) or 0):,}'
                    f'{f" | origin={escape(origin_label)}" if origin_label else ""}'
                    '</span></section>'
                )
                continue
            reconciliation = alert.get('cause_reconciliation') or {}
            evidence_status = str(
                alert.get('cause_evidence_status')
                or reconciliation.get('status')
                or 'unknown'
            )
            evidence_reason = str(reconciliation.get('reason') or '')
            unexplained = int(
                reconciliation.get(
                    'unexplained_raw_lines',
                    alert.get('unexplained_raw_lines', 0),
                )
                or 0
            )
            threshold_decisions = [
                decision
                for decision in (alert.get('threshold_evidence') or [])
                if isinstance(decision, dict)
            ]
            why_lines = []
            if threshold_decisions:
                for decision in threshold_decisions:
                    observed = decision.get('observed_value')
                    effective = decision.get('effective_threshold')
                    ratio = None
                    if isinstance(observed, (int, float)) and isinstance(effective, (int, float)) and effective > 0:
                        ratio = observed / effective
                    ratio_text = f", {ratio:.1f}x" if ratio is not None else ''
                    snapshot = str(decision.get('threshold_snapshot_id') or 'n/a')
                    percentile_level = decision.get('percentile_level')
                    try:
                        percentile_label = f"P{int(float(percentile_level) * 100)}"
                    except (TypeError, ValueError):
                        percentile_label = 'P93'
                    why_lines.append(
                        f"{decision.get('namespace') or 'unknown namespace'}: "
                        f"{_metric(observed)} ERROR lines vs effective threshold "
                        f"{_metric(effective)}{ratio_text}; {percentile_label}={_metric(decision.get('percentile_threshold'))}, "
                        f"CAP={_metric(decision.get('cap_threshold'))}, "
                        f"trigger={decision.get('triggered_by') or 'n/a'}, snapshot={snapshot}"
                    )
            else:
                why_lines.append(
                    f'{peak_type} detector triggered; structured P93/CAP evidence is unavailable.'
                )

            lines.extend([
                '',
                f'ALERT {alert_index}: {peak_type} | {status} | {policy_outcome.upper()}',
                'WHY ALERTED',
            ])
            lines.append(
                f'  Cause evidence: {evidence_status.upper()}; '
                f'unexplained raw lines={unexplained:,}'
                + (f'; {evidence_reason}' if evidence_reason else '')
            )
            if origin_label:
                lines.append(f'  Test origin: {origin_label}')
            lines.extend(f'  {line}' for line in why_lines)

            html_why = ''.join(
                f'<li style="margin:4px 0;">{escape(line)}</li>'
                for line in why_lines
            )
            html_why += (
                '<li style="margin:4px 0;">'
                f'Cause evidence: {escape(evidence_status.upper())}; '
                f'unexplained raw lines={unexplained:,}'
                f'{f"; {escape(evidence_reason)}" if evidence_reason else ""}'
                '</li>'
            )
            html_families = []
            for family_index, family in enumerate(families, start=1):
                assessment = str(family.get('assessment') or 'unknown')
                assessment_label = assessment_labels.get(assessment, assessment.upper())
                canonical_cause = str(family.get('canonical_cause') or 'Unknown cause')
                root_app = str(family.get('root_app') or 'unknown-app')
                operation = str(family.get('operation') or 'unknown-operation')
                outward_status = family.get('outward_status')
                confidence = str(family.get('confidence') or 'low')
                raw_lines = int(family.get('raw_error_lines', 0) or 0)
                traced_lines_value = family.get('traced_error_lines')
                traced_lines = (
                    int(traced_lines_value or 0)
                    if traced_lines_value is not None else
                    (raw_lines if family.get('unique_operations') is not None else 0)
                )
                unsegmented_lines_value = family.get('unsegmented_error_lines')
                unsegmented_lines = (
                    int(unsegmented_lines_value or 0)
                    if unsegmented_lines_value is not None else
                    max(0, raw_lines - traced_lines)
                )
                unique_operations = family.get('unique_operations')
                operation_count_method = str(
                    family.get('operation_count_method')
                    or ('trace_id' if unique_operations is not None else 'unavailable')
                )
                operation_count_confidence = str(
                    family.get('operation_count_confidence')
                    or ('medium' if unique_operations is not None else 'low')
                )
                operation_count_reason = str(
                    family.get('operation_count_reason') or ''
                )
                amplification = family.get('amplification')
                amplification_text = (
                    f"{float(amplification):.1f}"
                    if isinstance(amplification, (int, float)) else 'n/a'
                )
                trace_id = str(family.get('representative_trace_id') or '')
                next_action = str(
                    family.get('next_action')
                    or 'Inspect the representative trace and assign an owner classification.'
                )
                impact = (
                    f"{_metric(unique_operations)} unique operations | "
                    f"{raw_lines:,} raw ERROR lines | {amplification_text}x amplification | "
                    f"coverage: {traced_lines:,} traced, {unsegmented_lines:,} unsegmented ERROR lines"
                    if unique_operations is not None else
                    f"Unique operations n/a ({operation_count_reason or 'operation boundaries unavailable'}) | "
                    f"{raw_lines:,} raw ERROR lines | "
                    f"coverage: {traced_lines:,} traced, {unsegmented_lines:,} unsegmented ERROR lines"
                )
                operation_evidence = (
                    f"method={operation_count_method}, "
                    f"confidence={operation_count_confidence}"
                )
                outcome = (
                    f"operation={operation}, outward_status={outward_status or 'n/a'}"
                )
                scope = (
                    f"apps: {_scope(family.get('app_counts'))}; "
                    f"namespaces: {_scope(family.get('namespace_counts'))}"
                )

                lines.extend([
                    '',
                    f'CAUSE {alert_index}.{family_index}: [{assessment_label}] {canonical_cause}',
                    'WHAT ACTUALLY FAILED',
                    f'  {root_app}: {canonical_cause}',
                    f'  {outcome}',
                    'IMPACT',
                    f'  {impact}',
                    f'  Operation count evidence: {operation_evidence}',
                    f'  Current scope - {scope}',
                    'ASSESSMENT',
                    f'  {assessment_label} ({confidence} confidence)',
                    'EVIDENCE',
                    f"  Representative trace: {trace_id or 'n/a'}",
                    'NEXT ACTION',
                    f'  {next_action}',
                ])

                color = assessment_colors.get(assessment, '#475467')
                html_families.append(f'''
<div style="margin-top:14px;border:1px solid #d0d5dd;border-left:5px solid {color};padding:14px;background:#ffffff;">
  <div style="font-size:16px;font-weight:700;color:{color};">{escape(assessment_label)}</div>
  <div style="font-size:17px;font-weight:700;margin-top:4px;">{escape(canonical_cause)}</div>
  <div style="margin-top:12px;"><strong>WHAT ACTUALLY FAILED</strong><br>{escape(root_app)}: {escape(canonical_cause)}<br>{escape(outcome)}</div>
    <div style="margin-top:10px;"><strong>IMPACT</strong><br>{escape(impact)}<br>Operation count evidence: {escape(operation_evidence)}<br>{escape(scope)}</div>
  <div style="margin-top:10px;"><strong>ASSESSMENT</strong><br>{escape(assessment_label)} ({escape(confidence)} confidence)</div>
  <div style="margin-top:10px;"><strong>EVIDENCE</strong><br>Representative trace: {escape(trace_id or 'n/a')}</div>
  <div style="margin-top:10px;"><strong>NEXT ACTION</strong><br>{escape(next_action)}</div>
</div>''')

            html_alerts.append(f'''
<section style="margin-top:20px;padding-top:16px;border-top:2px solid #344054;">
  <div style="font-size:18px;font-weight:700;">Alert {alert_index}: {escape(peak_type)} | {escape(status)}</div>
  <div style="margin-top:10px;font-weight:700;">WHY ALERTED</div>
  <ul style="margin:6px 0 0 20px;padding:0;">{html_why}</ul>
  {''.join(html_families)}
</section>''')

        body = '\n'.join(lines)
        html_body = f'''
<html>
<body style="font-family:'Segoe UI',Arial,sans-serif;color:#101828;background:#f2f4f7;margin:0;padding:20px;">
  <main style="max-width:900px;margin:0 auto;background:#ffffff;border:1px solid #d0d5dd;padding:22px;">
    <h1 style="font-size:23px;margin:0;">Operator Peak Report</h1>
    <div style="margin-top:4px;color:#475467;">{escape(local_date)} {escape(local_time_range)} Europe/Prague</div>
    <div style="margin-top:18px;padding:14px;background:#f9fafb;border:1px solid #eaecf0;">
      <strong>WINDOW SIGNAL</strong><br>
      Raw ERROR lines fetched: {escape(_metric(raw_window_errors) if raw_window_errors else 'n/a')}<br>
      Alert groups sent: {len(alerts):,}<br>
      Cause families represented: {family_count:,}<br>
      Raw lines represented by alerts: {represented_raw_lines:,}<br>
    Operation occurrences represented: {escape(represented_operation_text)}<br>
    Trace IDs represented as evidence: {len(all_trace_ids):,}
    </div>
    {''.join(html_alerts)}
    <div style="margin-top:20px;padding-top:12px;border-top:1px solid #d0d5dd;font-size:12px;color:#667085;">
      Generated {escape(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))} | AI Log Analyzer
    </div>
  </main>
</body>
</html>'''
        return self._send_email(subject, body, html_body)

    def _send_legacy_regular_phase_peak_digest(
        self,
        window_start: datetime,
        window_end: datetime,
        alerts: List[Dict[str, Any]],
        summary: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Send one digest email for all dispatched alerts in current window."""
        if not self.is_enabled():
            return False

        summary = summary or {}

        prague_tz = ZoneInfo('Europe/Prague')
        ws_local = window_start.astimezone(prague_tz) if window_start else None
        we_local = window_end.astimezone(prague_tz) if window_end else None
        if ws_local and we_local:
            local_time_range = f"{ws_local.strftime('%H:%M')} - {we_local.strftime('%H:%M')}"
            local_date = f"{ws_local.day}.{ws_local.month}.{ws_local.year}"
        else:
            local_time_range = "N/A"
            local_date = "N/A"

        total_errors = sum(int(a.get('error_count', 0) or 0) for a in alerts)
        raw_window_errors = int(summary.get('raw_window_errors', 0) or 0)
        detected_peak_problems = int(summary.get('detected_peak_problems', 0) or 0)
        suppressed_count = int(summary.get('suppressed_alerts', 0) or 0)
        omitted_alerts = int(summary.get('omitted_alerts', 0) or 0)
        max_alerts = int(summary.get('max_alerts', 0) or 0)
        affected_apps = set(summary.get('affected_apps') or ())
        if not affected_apps:
            affected_apps = {
                app
                for alert in alerts
                for app in (alert.get('all_app_counts') or alert.get('app_counts') or {})
            }
        affected_namespaces = set(summary.get('affected_namespaces') or ())
        if not affected_namespaces:
            affected_namespaces = {
                namespace
                for alert in alerts
                for namespace in (alert.get('all_namespace_counts') or alert.get('namespace_counts') or {})
            }
        subject = f"AI Log Analyzer | {local_time_range} | {local_date}"

        lines = [
            "Peak Alerts",
            "",
            "Window Summary:",
            f"  Raw ERROR logs in window: {raw_window_errors:,}" if raw_window_errors else "  Raw ERROR logs in window: n/a",
            f"  Peak problems detected: {detected_peak_problems:,}" if detected_peak_problems else "  Peak problems detected: n/a",
            f"  Applications affected: {len(affected_apps):,}",
            f"  Namespaces affected: {len(affected_namespaces):,}",
            f"  Alerts sent: {len(alerts):,}",
            f"  Error events represented by alerts: {total_errors:,}",
        ]

        if suppressed_count > 0:
            lines.append(f"  Suppressed alerts: {suppressed_count:,}")
        if omitted_alerts > 0:
            if max_alerts > 0:
                lines.append(f"  Alerts outside top-{max_alerts} limit: {omitted_alerts:,}")
            else:
                lines.append(f"  Alerts outside send limit: {omitted_alerts:,}")

        lines.extend([
            "",
            "Dispatched Alerts:",
        ])

        for idx, alert in enumerate(alerts, start=1):
            trend = alert.get('trend') or '-'
            error_class = alert.get('error_class', 'unknown')
            error_count = int(alert.get('error_count', 0) or 0)
            peak_type = alert.get('peak_type', 'SPIKE')
            status = "KNOWN" if alert.get('is_known') else "NEW"
            lines.append(
                f"  {idx}. {error_class} | {peak_type} | {status} | trend={trend} | errors={error_count:,}"
            )

        lines.extend(["", "Details:"])
        for idx, alert in enumerate(alerts, start=1):
            error_class = str(alert.get('error_class', 'unknown') or 'unknown')
            root_cause = str(alert.get('root_cause_text', '') or 'N/A')
            behavior = str(alert.get('behavior_text', '') or alert.get('detail_message', '') or 'N/A')
            trace_id = str(alert.get('trace_id', '') or 'N/A')
            app_counts = alert.get('app_counts', {}) or {}
            namespace_counts = alert.get('namespace_counts', {}) or {}
            ns_detail_parts = [
                f"{ns}({count})"
                for ns, count in sorted(namespace_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            ]
            ns_detail_display = ', '.join(ns_detail_parts) if ns_detail_parts else 'N/A'
            app_detail_parts = [
                f"{app}({count})"
                for app, count in sorted(app_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            ]
            app_detail_display = ', '.join(app_detail_parts) if app_detail_parts else 'N/A'
            originator_display = str(alert.get('originator_display', '') or '')
            lines.extend([
                f"  {idx}. {error_class}",
                f"     Applications: {app_detail_display}",
                f"     Namespaces: {ns_detail_display}",
            ])
            if originator_display:
                lines.append(f"     Originator: {originator_display}")
            lines.extend([
                f"     Root cause: {root_cause}",
                f"     Behavior:",
            ])
            # Behavior as numbered lines
            for bline in behavior.split('\n'):
                if bline.strip():
                    lines.append(f"       {bline.strip()}")
            lines.append(f"     Trace ID: {trace_id}")

        body = "\n".join(lines)

        rows = []
        for alert in alerts:
            trend = alert.get('trend') or '-'
            error_class = alert.get('error_class', 'unknown')
            error_count = int(alert.get('error_count', 0) or 0)
            peak_type = alert.get('peak_type', 'SPIKE')
            status = "KNOWN" if alert.get('is_known') else "NEW"
            # Build NS list from namespace_counts with raw error counts
            namespace_counts = alert.get('namespace_counts', {})
            ns_ranked = sorted(namespace_counts.items(), key=lambda kv: (-kv[1], kv[0])) if namespace_counts else []
            ns_display_parts = [f"{ns}({count})" for ns, count in ns_ranked[:3]]
            ns_display = ', '.join(ns_display_parts) if ns_display_parts else 'N/A'
            if len(ns_ranked) > 3:
                ns_display += f" +{len(ns_ranked)-3}"
            rows.append(
                "<tr>"
                f"<td style=\"padding:8px;border:1px solid #d9d9d9;\">{error_class}</td>"
                f"<td style=\"padding:8px;border:1px solid #d9d9d9;\">{peak_type}</td>"
                f"<td style=\"padding:8px;border:1px solid #d9d9d9;\">{status}</td>"
                f"<td style=\"padding:8px;border:1px solid #d9d9d9;\">{ns_display}</td>"
                f"<td style=\"padding:8px;border:1px solid #d9d9d9;\">{trend}</td>"
                f"<td style=\"padding:8px;border:1px solid #d9d9d9;text-align:right;\">{error_count:,}</td>"
                "</tr>"
            )

        detail_blocks = []
        for idx, alert in enumerate(alerts, start=1):
            error_class = str(alert.get('error_class', 'unknown') or 'unknown')
            root_cause = str(alert.get('root_cause_text', '') or 'N/A')
            behavior = str(alert.get('behavior_text', '') or alert.get('detail_message', '') or 'N/A')
            trace_id = str(alert.get('trace_id', '') or 'N/A')
            app_counts = alert.get('app_counts', {}) or {}
            app_ranked = sorted(app_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            apps_display_parts = [f"{app}({count})" for app, count in app_ranked[:5]]
            apps_display = ', '.join(apps_display_parts) if apps_display_parts else 'N/A'
            if len(app_ranked) > 5:
                apps_display += f" +{len(app_ranked)-5}"
            namespace_counts = alert.get('namespace_counts', {}) or {}
            ns_detail_parts = [
                f"{ns}({count})"
                for ns, count in sorted(namespace_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            ]
            ns_detail_display = ', '.join(ns_detail_parts) if ns_detail_parts else 'N/A'
            originator_display = str(alert.get('originator_display', '') or '')

            # Behavior as numbered HTML lines
            behavior_html_lines = []
            for bline in behavior.split('\n'):
                stripped = bline.strip()
                if stripped:
                    behavior_html_lines.append(f"<div style=\"padding-left:16px;\">{stripped}</div>")
            behavior_html = '\n'.join(behavior_html_lines) if behavior_html_lines else 'N/A'

            originator_html = f'<div style="padding:0 12px 6px 12px;"><strong>Originator:</strong> {originator_display}</div>' if originator_display else ''
            
            detail_html = f"""<div style="margin-top:18px;margin-bottom:14px;border-left:4px solid #2c5aa0;border-radius:4px;overflow:hidden;background:white;border:1px solid #d9d9d9;">
<div style="background:#2c5aa0;padding:10px;font-weight:700;color:white;">{idx}. {error_class}</div>
<div style="padding:12px;"><strong>Applications:</strong> {apps_display}</div>
<div style="padding:0 12px 6px 12px;"><strong>Namespaces:</strong> {ns_detail_display}</div>
{originator_html}<div style="padding:0 12px 6px 12px;"><strong>Root cause:</strong> {root_cause}</div>
<div style="padding:0 12px 6px 12px;"><strong>Behavior:</strong>
{behavior_html}
</div>
<div style="padding:0 12px 12px 12px;"><strong>Trace ID:</strong> {trace_id}</div>
</div>"""
            detail_blocks.append(detail_html)

        html_body = f"""
        <html>
        <body style="font-family:'Segoe UI',Arial,sans-serif;color:#1f2937;background:#f0f4f8;margin:0;padding:20px;">
            <div style="max-width:900px;margin:0 auto;border:1px solid #2c5aa0;border-radius:10px;background:white;overflow:hidden;">
                <div style="padding:16px 20px;border-bottom:2px solid #2c5aa0;background:#2c5aa0;color:white;">
                    <h1 style="margin:0;font-size:22px;font-weight:700;">Peak Alerts</h1>
                </div>
                <div style="padding:20px;">
                    <div style="font-size:16px;margin-bottom:8px;"><strong>Raw ERROR logs in window:</strong> {raw_window_errors:,}</div>
                    <div style="font-size:16px;margin-bottom:8px;"><strong>Peak problems detected:</strong> {detected_peak_problems:,}</div>
                    <div style="font-size:16px;margin-bottom:8px;"><strong>Applications affected:</strong> {len(affected_apps):,}</div>
                    <div style="font-size:16px;margin-bottom:8px;"><strong>Namespaces affected:</strong> {len(affected_namespaces):,}</div>
                    <div style="font-size:16px;margin-bottom:8px;"><strong>Alerts sent:</strong> {len(alerts):,}</div>
                    <div style="font-size:16px;margin-bottom:14px;"><strong>Error events represented by alerts:</strong> {total_errors:,}</div>
                    <table style="margin-top:12px;border-collapse:collapse;width:100%;font-size:14px;">
                        <thead>
                            <tr style="background:#2c5aa0;color:white;">
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Error Class</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Peak Type</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Status</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">NS (Raw)</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Trend</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:right;">Errors</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(rows)}
                        </tbody>
                    </table>

                    <div style="margin-top:12px;font-size:14px;color:#475569;">
                        {'Suppressed alerts: ' + format(suppressed_count, ',') if suppressed_count > 0 else ''}
                        {'<br>' if suppressed_count > 0 and omitted_alerts > 0 else ''}
                        {('Alerts outside top-' + str(max_alerts) + ' limit: ' + format(omitted_alerts, ',')) if omitted_alerts > 0 and max_alerts > 0 else ('Alerts outside send limit: ' + format(omitted_alerts, ',')) if omitted_alerts > 0 else ''}
                    </div>

                    <div style="margin-top:18px;font-size:17px;font-weight:700;color:#2c5aa0;">Details</div>
                    <div style="margin-top:8px;">
                        {''.join(detail_blocks)}
                    </div>
                </div>
                <div style="text-align:center;padding:14px;border-top:2px solid #2c5aa0;background:#f0f4f8;font-size:12px;color:#555;">
                    Generated: {datetime.now().strftime('%H:%M:%S')} | AI Log Analyzer
                </div>
            </div>
        </body>
        </html>
        """

        return self._send_email(subject, body, html_body)
