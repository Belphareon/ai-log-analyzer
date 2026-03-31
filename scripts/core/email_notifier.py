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
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo


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
                refused = smtp.send_message(msg)

            if refused:
                print(f"⚠️ SMTP refused recipients: {refused}")
                return False

            print(f"✅ SMTP accepted message to {self.teams_email}")
            
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
        peak_identifier: str,
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
        continuation_summary: dict = None,
        severity_icon: str = "⚠️"
    ) -> bool:
        """Send detailed peak alert notification for regular phase."""
        if not self.is_enabled():
            return False

        peak_status = "KNOWN" if is_known else "NEW"
        continuation = " (continued)" if is_known and is_continues else ""
        trend_value = continuation_summary.get('trend', 'stable') if continuation_summary else 'stable'
        trend_symbol = {'rising': '↑', 'falling': '↓', 'stable': '→'}.get(trend_value, '→')
        status_short = 'CONT' if is_continues else ('KNOWN' if is_known else 'NEW')

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
            f"Time (CET/CEST): {local_range}",
            f"Time (UTC): {utc_range}",
            f"Error Class: {peak_error_class}",
            f"Peak Type: {peak_type}",
            f"Peak Key: {peak_identifier}",
            "",
            f"Error Info: {peak_error_details}",
            f"Raw Errors: {error_count:,}",
            f"Affected Apps: {', '.join(affected_apps) if affected_apps else 'N/A'}",
            f"Namespaces: {namespaces_text}",
        ]

        if is_known and is_continues and continuation_summary:
            body_lines.extend([
                "",
                "Continuation Summary:",
                f"  Trend: {continuation_summary.get('trend', 'stable')}",
            ])
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

        html_continuation = ""
        if is_known and is_continues and continuation_summary:
            prev_avg_html = ""
            prev_avg = continuation_summary.get('previous_average_errors')
            if isinstance(prev_avg, int) and prev_avg > 0:
                prev_avg_html = f'<div><strong>Previous window average:</strong> {prev_avg:,}</div>'
            new_namespaces = continuation_summary.get('new_namespaces', []) or []
            new_apps = continuation_summary.get('new_apps', []) or []
            top_types = continuation_summary.get('top_error_types') or 'N/A'

            html_continuation = (
                '<div style="margin-bottom:20px;">'
                '<div style="padding:12px;border:1px solid #808080;">'
                '<div style="font-weight:700;text-decoration:underline;">Continuation Summary</div>'
                f'<div style="margin-top:8px;"><strong>Trend:</strong> {continuation_summary.get("trend", "stable")}</div>'
                f'{prev_avg_html}'
                f'<div><strong>New namespaces:</strong> {", ".join(new_namespaces) if new_namespaces else "none"}</div>'
                f'<div><strong>New apps:</strong> {", ".join(new_apps) if new_apps else "none"}</div>'
                f'<div><strong>Top error types:</strong> {top_types}</div>'
                '</div>'
                '</div>'
            )

        # Build Trend display from continuation_summary if available
        trend_display = trend_value
        
        html_body = f"""
        <html>
        <body style="font-family:'Segoe UI',Arial,sans-serif;color:inherit;background:transparent;margin:0;padding:20px;">
            <div style="max-width:760px;margin:0 auto;border:1px solid #808080;">
                <div style="padding:16px;border-bottom:1px solid #cfcfcf;">
                    <h1 style="margin:0;font-size:21px;font-weight:700;">{peak_error_class} | Status: {peak_status}{continuation} | Trend: {trend_display}</h1>
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
                        <div><strong>Applications:</strong> {', '.join(affected_apps) if affected_apps else 'N/A'}</div>
                        <div><strong>Namespaces:</strong> {namespaces_text}</div>
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
        suppressed_count: int = 0,
    ) -> bool:
        """Send one digest email for all dispatched alerts in current window.

        Correlated alerts (same trace_id + same namespace set) are grouped into
        a single detail block so the reader sees ONE incident, not N duplicates.
        The summary table still lists every error_class for searchability.
        """
        if not self.is_enabled():
            return False

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
        subject = f"AI Log Analyzer | {local_time_range} | {local_date}"

        # ── Correlation: group alerts that share the same trace_id + namespaces ──
        groups: List[Dict[str, Any]] = []          # ordered list of groups
        group_index: Dict[str, int] = {}           # correlation_key → index in groups
        for alert in alerts:
            tid = str(alert.get('trace_id', '') or '').strip()
            ns_set = frozenset((alert.get('namespace_counts') or {}).keys())
            # Only correlate when trace_id is known AND namespaces overlap
            corr_key = f"{tid}||{'|'.join(sorted(ns_set))}" if tid else None
            if corr_key and corr_key in group_index:
                groups[group_index[corr_key]]['alerts'].append(alert)
            else:
                idx = len(groups)
                entry = {'alerts': [alert], 'correlation_key': corr_key}
                groups.append(entry)
                if corr_key:
                    group_index[corr_key] = idx

        # ── PLAIN TEXT body ──────────────────────────────────────────────────
        lines = [
            "Peak Alerts",
            "",
            f"Total errors in sent alerts: {total_errors:,}",
            "",
        ]
        # Summary table header
        lines.append(f"{'Error Class':<45} {'Type':<7} {'Status':<8} {'NS':<25} {'Trend':<8} {'Errors':>10}")
        lines.append("-" * 110)
        for alert in alerts:
            trend = alert.get('trend', 'stable')
            error_class = str(alert.get('error_class', 'unknown'))[:44]
            error_count = int(alert.get('error_count', 0) or 0)
            peak_type = alert.get('peak_type', 'SPIKE')
            status = "KNOWN" if alert.get('is_known') else "NEW"
            namespace_counts = alert.get('namespace_counts', {}) or {}
            ns_list = sorted(namespace_counts.keys())
            ns_display = ', '.join(ns_list[:3]) if ns_list else 'N/A'
            if len(ns_list) > 3:
                ns_display += f" +{len(ns_list)-3}"
            lines.append(f"  {error_class:<43} {peak_type:<7} {status:<8} {ns_display:<25} {trend:<8} {error_count:>10,}")
        lines.append("")

        # Details section - one block per group
        lines.append("Details:")
        for gidx, group in enumerate(groups, start=1):
            grp_alerts = group['alerts']
            primary = grp_alerts[0]
            trace_id = str(primary.get('trace_id', '') or 'N/A')
            # Merge trace_steps from all alerts in group, dedup by normalized message
            all_trace_steps = []
            seen_normalized = set()
            for a in grp_alerts:
                for step in (a.get('trace_steps', []) or []):
                    s_msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                    # Normalize: strip object addresses, hex IDs, numbers for dedup
                    norm = re.sub(r'@[0-9a-fA-F]{2,}', '@<ADDR>', s_msg)
                    norm = re.sub(r'\b[0-9a-fA-F]{8,}\b', '<HEX>', norm)
                    norm = re.sub(r'\b\d+\b', '<N>', norm)
                    norm = re.sub(r'\s+', ' ', norm).strip().lower()[:200]
                    if norm not in seen_normalized:
                        all_trace_steps.append(step)
                        seen_normalized.add(norm)
            trace_steps = all_trace_steps
            root_cause_d = primary.get('root_cause') or {}
            propagation_info = primary.get('propagation_info') or {}

            # Header: list correlated error classes
            class_parts = []
            total_grp_errors = 0
            for a in grp_alerts:
                ec = str(a.get('error_class', 'unknown'))
                cnt = int(a.get('error_count', 0) or 0)
                class_parts.append(f"{ec} ({cnt:,})")
                total_grp_errors += cnt

            if len(grp_alerts) > 1:
                lines.append(f"  {gidx}. CORRELATED INCIDENT ({len(grp_alerts)} error classes, {total_grp_errors:,} total)")
                for cp in class_parts:
                    lines.append(f"       - {cp}")
            else:
                lines.append(f"  {gidx}. {class_parts[0]}")

            # Merged apps/NS from all alerts in group
            merged_app_counts: Dict[str, int] = {}
            merged_ns_counts: Dict[str, int] = {}
            for a in grp_alerts:
                for app, cnt in (a.get('app_counts') or {}).items():
                    merged_app_counts[app] = merged_app_counts.get(app, 0) + cnt
                for ns, cnt in (a.get('namespace_counts') or {}).items():
                    merged_ns_counts[ns] = merged_ns_counts.get(ns, 0) + cnt
            if merged_app_counts:
                top_apps = sorted(merged_app_counts.items(), key=lambda x: -x[1])[:5]
                apps_display = ', '.join(f"{a} ({n:,})" for a, n in top_apps)
            else:
                apps = sorted(set(app for a in grp_alerts for app in (a.get('affected_apps') or [])))
                apps_display = ', '.join(apps[:5])
            ns_display = ', '.join(f"{ns} ({cnt:,})" for ns, cnt in sorted(merged_ns_counts.items(), key=lambda x: -x[1])) or 'N/A'
            root_cause_text = str(primary.get('root_cause_text', '') or 'N/A')
            lines.extend([
                f"     Applications: {apps_display}",
                f"     Namespaces (raw): {ns_display}",
                f"     Root cause: {root_cause_text}",
            ])
            # Trace flow - merged from all correlated alerts
            if trace_steps:
                lines.append(f"     Behavior (trace flow): {len(trace_steps)} unique messages")
                lines.append("")
                for si, step in enumerate(trace_steps, start=1):
                    s_app = step.get('app', '?') if isinstance(step, dict) else getattr(step, 'app', '?')
                    s_msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                    s_count = step.get('occurrence_count', 1) if isinstance(step, dict) else getattr(step, 'occurrence_count', 1)
                    count_label = f" [x{s_count}]" if s_count > 1 else ""
                    lines.append(f"       {si}) {s_app}{count_label}")
                    lines.append(f"          \"{s_msg[:200]}\"")
            if root_cause_d and root_cause_d.get('message'):
                confidence = root_cause_d.get('confidence', '')
                conf_label = f' [{confidence}]' if confidence else ''
                lines.append(f"     Inferred root cause{conf_label}:")
                lines.append(f"       - {root_cause_d.get('service', '?')}: {root_cause_d.get('message', '')[:200]}")
            if propagation_info and propagation_info.get('service_count', 0) > 1:
                prop_type = propagation_info.get('type', '')
                prop_count = propagation_info.get('service_count', '')
                prop_short = propagation_info.get('short_string', '')
                lines.append(f"     Propagation [{prop_type}]: {prop_count} services")
                if prop_short:
                    lines.append(f"       {prop_short}")
            lines.append(f"     Trace ID: {trace_id}")
            lines.append("")

        body = "\n".join(lines)

        # ── HTML body ────────────────────────────────────────────────────────
        # Summary table rows (all alerts individually for searchability)
        rows = []
        for alert in alerts:
            trend = alert.get('trend', 'stable')
            error_class = alert.get('error_class', 'unknown')
            error_count = int(alert.get('error_count', 0) or 0)
            peak_type = alert.get('peak_type', 'SPIKE')
            status = "KNOWN" if alert.get('is_known') else "NEW"
            namespace_counts = alert.get('namespace_counts', {})
            ns_list = sorted(namespace_counts.keys()) if namespace_counts else []
            ns_display = ', '.join(ns_list[:3]) if ns_list else 'N/A'
            if len(ns_list) > 3:
                ns_display += f" +{len(ns_list)-3}"
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

        # Detail blocks - one per correlated group
        detail_blocks = []
        for gidx, group in enumerate(groups, start=1):
            grp_alerts = group['alerts']
            primary = grp_alerts[0]
            trace_id = str(primary.get('trace_id', '') or 'N/A')
            # Merge trace_steps from all alerts in group, dedup by normalized message
            all_trace_steps = []
            seen_normalized = set()
            for a in grp_alerts:
                for step in (a.get('trace_steps', []) or []):
                    s_msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                    # Normalize: strip object addresses, hex IDs, numbers for dedup
                    norm = re.sub(r'@[0-9a-fA-F]{2,}', '@<ADDR>', s_msg)
                    norm = re.sub(r'\b[0-9a-fA-F]{8,}\b', '<HEX>', norm)
                    norm = re.sub(r'\b\d+\b', '<N>', norm)
                    norm = re.sub(r'\s+', ' ', norm).strip().lower()[:200]
                    if norm not in seen_normalized:
                        all_trace_steps.append(step)
                        seen_normalized.add(norm)
            trace_steps = all_trace_steps
            root_cause_d = primary.get('root_cause') or {}
            root_cause_text = str(primary.get('root_cause_text', '') or 'N/A')
            propagation_info = primary.get('propagation_info') or {}

            # Merged counts
            merged_app_counts: Dict[str, int] = {}
            merged_ns_counts: Dict[str, int] = {}
            for a in grp_alerts:
                for app, cnt in (a.get('app_counts') or {}).items():
                    merged_app_counts[app] = merged_app_counts.get(app, 0) + cnt
                for ns, cnt in (a.get('namespace_counts') or {}).items():
                    merged_ns_counts[ns] = merged_ns_counts.get(ns, 0) + cnt
            if merged_app_counts:
                top_apps = sorted(merged_app_counts.items(), key=lambda x: -x[1])[:5]
                apps_display = ', '.join(f"{a} ({n:,})" for a, n in top_apps)
                if len(merged_app_counts) > 5:
                    apps_display += f" +{len(merged_app_counts)-5}"
            else:
                apps = sorted(set(app for a in grp_alerts for app in (a.get('affected_apps') or [])))
                apps_display = ', '.join(apps[:5])
            ns_detail_display = ', '.join(
                f"{ns} ({cnt:,})" for ns, cnt in sorted(merged_ns_counts.items(), key=lambda x: -x[1])
            ) or 'N/A'

            # Header: correlated or single
            total_grp_errors = sum(int(a.get('error_count', 0) or 0) for a in grp_alerts)
            if len(grp_alerts) > 1:
                class_tags = ''.join(
                    f'<span style="display:inline-block;background:#e8f0fe;border:1px solid #b0c4de;border-radius:4px;'
                    f'padding:2px 8px;margin:2px 4px 2px 0;font-size:13px;">'
                    f'{a.get("error_class","?")} ({int(a.get("error_count",0) or 0):,})</span>'
                    for a in grp_alerts
                )
                header_html = (
                    f'<div style="background:#2c5aa0;padding:10px;font-weight:700;color:white;">'
                    f'{gidx}. Correlated Incident ({total_grp_errors:,} total errors)</div>'
                    f'<div style="padding:8px 12px;background:#f0f4f8;">{class_tags}</div>'
                )
            else:
                ec = str(grp_alerts[0].get('error_class', 'unknown'))
                header_html = (
                    f'<div style="background:#2c5aa0;padding:10px;font-weight:700;color:white;">'
                    f'{gidx}. {ec}</div>'
                )

            # Behavior HTML - merged from all correlated alerts
            behavior_html_parts = []
            if trace_steps:
                behavior_html_parts.append(
                    f'<div style="margin-top:6px;font-weight:700;text-decoration:underline;">Behavior (trace flow): {len(trace_steps)} unique messages</div>'
                )
                for si, step in enumerate(trace_steps, start=1):
                    s_app = step.get('app', '?') if isinstance(step, dict) else getattr(step, 'app', '?')
                    s_msg = step.get('message', '') if isinstance(step, dict) else getattr(step, 'message', '')
                    s_count = step.get('occurrence_count', 1) if isinstance(step, dict) else getattr(step, 'occurrence_count', 1)
                    count_html = f' <span style="color:#c62828;font-weight:600;">[x{s_count}]</span>' if s_count > 1 else ''
                    esc_msg = s_msg.replace('<', '&lt;').replace('>', '&gt;')[:300]
                    behavior_html_parts.append(
                        f'<div style="margin-top:4px;padding-left:12px;font-size:13px;">'
                        f'<strong>{si}) {s_app}</strong>{count_html}<br>'
                        f'&nbsp;&nbsp;&nbsp;&quot;{esc_msg}&quot;</div>'
                    )
            if root_cause_d and root_cause_d.get('message'):
                confidence = root_cause_d.get('confidence', '')
                conf_label = f' [{confidence}]' if confidence else ''
                rc_service = root_cause_d.get('service', '')
                rc_msg = root_cause_d.get('message', '').replace('<', '&lt;').replace('>', '&gt;')[:300]
                behavior_html_parts.append(
                    f'<div style="margin-top:8px;font-weight:600;">Inferred root cause{conf_label}:</div>'
                    f'<div style="padding-left:12px;font-size:13px;">- {rc_service}: {rc_msg}</div>'
                )
            if propagation_info and propagation_info.get('service_count', 0) > 1:
                prop_type = propagation_info.get('type', '')
                prop_count = propagation_info.get('service_count', '')
                prop_short = propagation_info.get('short_string', '')
                duration_ms = int(propagation_info.get('duration_ms', 0) or 0)
                duration_str = ''
                if duration_ms > 0:
                    total_sec = duration_ms // 1000
                    ms_rem = duration_ms % 1000
                    minutes = total_sec // 60
                    seconds = total_sec % 60
                    if minutes > 0:
                        duration_str = f'{minutes}m {seconds}s'
                    elif seconds > 0:
                        duration_str = f'{seconds}s {ms_rem}ms'
                    else:
                        duration_str = f'{ms_rem}ms'
                behavior_html_parts.append(
                    f'<div style="margin-top:8px;font-weight:600;">Propagation [{prop_type}]: {prop_count} services</div>'
                )
                if prop_short:
                    behavior_html_parts.append(f'<div style="padding-left:12px;font-size:13px;">{prop_short}</div>')
                if duration_str:
                    behavior_html_parts.append(f'<div style="padding-left:12px;font-size:13px;">Duration: {duration_str}</div>')
            if not behavior_html_parts:
                raw_behavior = str(primary.get('detail_message', '') or '')
                if raw_behavior:
                    behavior_html_parts.append(f'<div style="font-size:13px;">{raw_behavior[:300]}</div>')
            behavior_html = ''.join(behavior_html_parts) if behavior_html_parts else '<div style="color:#888;font-size:13px;">N/A</div>'

            detail_html = (
                f'<div style="margin-top:18px;margin-bottom:14px;border-left:4px solid #2c5aa0;border-radius:4px;overflow:hidden;'
                f'background:white;border:1px solid #d9d9d9;">'
                f'{header_html}'
                f'<div style="padding:12px;"><strong>Applications:</strong> {apps_display}</div>'
                f'<div style="padding:0 12px 6px 12px;"><strong>Namespaces (raw):</strong> {ns_detail_display}</div>'
                f'<div style="padding:0 12px 6px 12px;"><strong>Root cause:</strong> {root_cause_text}</div>'
                f'<div style="padding:0 12px 6px 12px;">{behavior_html}</div>'
                f'<div style="padding:0 12px 12px 12px;"><strong>Trace ID:</strong> {trace_id}</div>'
                f'</div>'
            )
            detail_blocks.append(detail_html)

        html_body = f"""
        <html>
        <body style="font-family:'Segoe UI',Arial,sans-serif;color:#1f2937;background:#f0f4f8;margin:0;padding:20px;">
            <div style="max-width:900px;margin:0 auto;border:1px solid #2c5aa0;border-radius:10px;background:white;overflow:hidden;">
                <div style="padding:16px 20px;border-bottom:2px solid #2c5aa0;background:#2c5aa0;color:white;">
                    <h1 style="margin:0;font-size:22px;font-weight:700;">Peak Alerts</h1>
                </div>
                <div style="padding:20px;">
                    <div style="font-size:16px;margin-bottom:14px;"><strong>Total errors in sent alerts:</strong> {total_errors:,}</div>
                    <table style="margin-top:12px;border-collapse:collapse;width:100%;font-size:14px;">
                        <thead>
                            <tr style="background:#2c5aa0;color:white;">
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Error Class</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Peak Type</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Status</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">NS</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:left;">Trend</th>
                                <th style="padding:8px;border:1px solid #2c5aa0;text-align:right;">Errors</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(rows)}
                        </tbody>
                    </table>

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
