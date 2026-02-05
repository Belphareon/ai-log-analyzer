#!/usr/bin/env python3
"""
DAILY REPORT FORMATTER
======================

Formátuje DailyReportBundle do:
- Markdown (primární)
- Text (konzole)
- JSON (backend)
"""

from typing import Dict, List
from datetime import datetime
from pathlib import Path
import json

try:
    from .daily_report_models import (
        DailyReport, DailyReportBundle, DayStatus
    )
except ImportError:
    from daily_report_models import (
        DailyReport, DailyReportBundle, DayStatus
    )


class DailyReportFormatter:
    """Formatter pro denní reporty"""
    
    SEVERITY_ICONS = {
        'critical': '🔴',
        'high': '🟠',
        'medium': '🟡',
        'low': '🟢',
        'info': '⚪',
    }
    
    STATUS_ICONS = {
        DayStatus.CRITICAL: '🔴 CRITICAL',
        DayStatus.DEGRADING: '🟠 DEGRADING',
        DayStatus.STABLE: '🟢 STABLE',
        DayStatus.IMPROVING: '🔵 IMPROVING',
    }
    
    # =========================================================================
    # MARKDOWN
    # =========================================================================
    
    def to_markdown(self, bundle: DailyReportBundle) -> str:
        """Generuje Markdown"""
        lines = []
        
        # Header
        lines.append("# 📊 Daily Error Analysis Report")
        lines.append("")
        lines.append(f"**Generated:** {bundle.metadata.generated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"**Period:** {bundle.metadata.date_range_from} to {bundle.metadata.date_range_to}")
        lines.append(f"**Total Records:** {bundle.metadata.input_records:,}")
        lines.append(f"**Total Incidents:** {bundle.metadata.total_incidents:,}")
        lines.append("")
        
        # Executive Summary
        if bundle.cross_day_trends:
            lines.extend(self._md_executive_summary(bundle.cross_day_trends))
        
        # Daily Reports
        lines.append("---")
        lines.append("")
        lines.append("# 📅 Daily Reports")
        lines.append("")
        
        for report in bundle.daily_reports:
            lines.extend(self._md_daily(report))
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _md_executive_summary(self, trends) -> List[str]:
        """Executive summary do MD"""
        lines = []
        lines.append("## 📈 Executive Summary")
        lines.append("")
        lines.append(f"**Overall Status:** {self.STATUS_ICONS.get(trends.overall_status, '⚪')}")
        lines.append(f"**Error Trend:** {trends.overall_errors_trend:+.1f}% over period")
        lines.append(f"**Incident Trend:** {trends.overall_incidents_trend:+.1f}% over period")
        lines.append("")
        
        if trends.top_growing:
            lines.append("### 📈 Top Growing Issues")
            lines.append("")
            lines.append("| Growth | Message |")
            lines.append("|--------|---------|")
            for fp, msg, change in trends.top_growing[:5]:
                lines.append(f"| +{change:.0f}% | `{msg}` |")
            lines.append("")
        
        if trends.top_new_issues:
            lines.append("### 🆕 New Issues This Period")
            lines.append("")
            for fp, msg, count in trends.top_new_issues[:5]:
                lines.append(f"- `{msg}` ({count:,} occurrences)")
            lines.append("")
        
        return lines
    
    def _md_daily(self, report: DailyReport) -> List[str]:
        """Jeden den do MD"""
        lines = []
        
        status_icon = self.STATUS_ICONS.get(report.conclusion.status, '⚪')
        lines.append(f"## 📆 {report.date} - {status_icon}")
        lines.append("")
        
        # Conclusion first
        lines.append("### 📋 Summary")
        lines.append("")
        for point in report.conclusion.summary_points:
            lines.append(f"- {point}")
        lines.append("")
        
        if report.conclusion.action_items:
            lines.append("**Action Items:**")
            for action in report.conclusion.action_items:
                lines.append(f"- {action}")
            lines.append("")
        
        # Statistics
        lines.append("### 📊 Statistics")
        lines.append("")
        stats = report.statistics
        lines.append(f"- **Total Errors:** {stats.total_errors:,}")
        lines.append(f"- **Unique Issues:** {stats.total_incidents:,}")
        lines.append("")
        
        lines.append("**By Severity:**")
        for sev in ['critical', 'high', 'medium', 'low', 'info']:
            count = stats.by_severity.get(sev, 0)
            if count > 0:
                lines.append(f"- {self.SEVERITY_ICONS.get(sev, '⚪')} {sev}: {count}")
        lines.append("")
        
        # Clusters
        if report.error_clusters:
            lines.append("### 🔗 Error Clusters")
            lines.append("")
            for cluster in report.error_clusters[:5]:
                lines.append(f"#### {cluster.cluster_id}: {cluster.category}")
                lines.append(f"**Occurrences:** {cluster.total_occurrences:,}")
                lines.append(f"**Apps:** {', '.join(cluster.affected_apps[:5])}")
                lines.append(f"**Hypothesis:** {cluster.hypothesis}")
                lines.append("")
                if cluster.suggested_fixes:
                    lines.append("**Suggested Fix:**")
                    for fix in cluster.suggested_fixes[:3]:
                        lines.append(f"- {fix}")
                lines.append("")
        
        # Peaks
        if report.peaks:
            lines.append("### 📈 Peaks")
            lines.append("")
            lines.append("| Type | Ratio | Apps | Message |")
            lines.append("|------|-------|------|---------|")
            for peak in report.peaks[:10]:
                apps = ', '.join(peak.apps[:2])
                msg = peak.message[:40]
                lines.append(f"| {peak.peak_type} | {peak.ratio:.1f}x | {apps} | `{msg}` |")
            lines.append("")
        
        # Per App
        if report.errors_per_app:
            lines.append("### 📱 Per Application")
            lines.append("")
            lines.append("| App | Errors | Issues | Top Error |")
            lines.append("|-----|--------|--------|-----------|")
            for app in report.errors_per_app[:15]:
                top = app.top_errors[0]['message'][:30] if app.top_errors else "-"
                lines.append(f"| {app.app_name} | {app.total_errors:,} | {app.unique_fingerprints} | `{top}` |")
            lines.append("")
        
        # Known vs New
        lines.append("### 🆕 Known vs New")
        lines.append("")
        lines.append(f"- **New Errors:** {report.known_vs_new.new_errors}")
        lines.append(f"- **Known Errors:** {report.known_vs_new.known_errors}")
        if report.known_vs_new.new_peaks > 0 or report.known_vs_new.known_peaks > 0:
            lines.append(f"- **New Peaks:** {report.known_vs_new.new_peaks}")
            lines.append(f"- **Known Peaks:** {report.known_vs_new.known_peaks}")
        lines.append("")
        
        return lines
    
    # =========================================================================
    # CONSOLE/TEXT
    # =========================================================================
    
    def to_console(self, bundle: DailyReportBundle) -> str:
        """Konzolový výstup"""
        lines = []
        
        lines.append("=" * 80)
        lines.append("📊 DAILY ERROR ANALYSIS REPORT")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Generated: {bundle.metadata.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Period: {bundle.metadata.date_range_from} to {bundle.metadata.date_range_to}")
        lines.append(f"Records: {bundle.metadata.input_records:,} | Incidents: {bundle.metadata.total_incidents:,}")
        lines.append("")
        
        # Cross-day
        if bundle.cross_day_trends:
            t = bundle.cross_day_trends
            lines.append("📈 EXECUTIVE SUMMARY")
            lines.append("-" * 40)
            lines.append(f"   Status: {t.overall_status.value}")
            lines.append(f"   Error Trend: {t.overall_errors_trend:+.1f}%")
            
            if t.top_growing:
                lines.append("")
                lines.append("   Top Growing:")
                for fp, msg, change in t.top_growing[:3]:
                    lines.append(f"      +{change:.0f}%  {msg}")
            lines.append("")
        
        # Daily
        for report in bundle.daily_reports:
            lines.append("=" * 80)
            lines.extend(self._console_daily(report))
        
        lines.append("=" * 80)
        return "\n".join(lines)
    
    def _console_daily(self, report: DailyReport) -> List[str]:
        """Jeden den pro konzoli"""
        lines = []
        
        status = report.conclusion.status.value
        lines.append(f"📆 {report.date} - {status}")
        lines.append("-" * 40)
        
        # Summary points
        for point in report.conclusion.summary_points[:5]:
            lines.append(f"   {point}")
        
        # Actions
        if report.conclusion.action_items:
            lines.append("")
            lines.append("   ACTION ITEMS:")
            for action in report.conclusion.action_items[:3]:
                lines.append(f"   → {action}")
        
        # Stats
        stats = report.statistics
        lines.append("")
        lines.append(f"   📊 Errors: {stats.total_errors:,} | Issues: {stats.total_incidents:,}")
        
        # Severity
        sev_parts = []
        for sev in ['critical', 'high', 'medium', 'low']:
            cnt = stats.by_severity.get(sev, 0)
            if cnt > 0:
                sev_parts.append(f"{self.SEVERITY_ICONS[sev]} {sev}:{cnt}")
        if sev_parts:
            lines.append(f"   {' | '.join(sev_parts)}")
        
        # Top cluster
        if report.error_clusters:
            c = report.error_clusters[0]
            lines.append("")
            lines.append(f"   🔗 Top Cluster: {c.category}")
            lines.append(f"      {c.total_occurrences:,} occurrences | Apps: {', '.join(c.affected_apps[:3])}")
            lines.append(f"      Hypothesis: {c.hypothesis[:60]}")
        
        # Peaks
        if report.peaks:
            lines.append("")
            lines.append("   📈 Top Peaks:")
            for peak in report.peaks[:3]:
                lines.append(f"      {peak.peak_type} {peak.ratio:.1f}x | {', '.join(peak.apps[:2])} | {peak.message[:40]}")
        
        # Known/New
        lines.append("")
        lines.append(f"   🆕 New: {report.known_vs_new.new_errors} | Known: {report.known_vs_new.known_errors}")
        lines.append("")
        
        return lines
    
    # =========================================================================
    # JSON
    # =========================================================================
    
    def to_json(self, bundle: DailyReportBundle) -> str:
        """JSON výstup"""
        return json.dumps(self._to_dict(bundle), indent=2, default=str)
    
    def _to_dict(self, bundle: DailyReportBundle) -> Dict:
        """Bundle to dict"""
        return {
            'metadata': {
                'generated_at': bundle.metadata.generated_at.isoformat(),
                'date_range': {
                    'from': str(bundle.metadata.date_range_from),
                    'to': str(bundle.metadata.date_range_to),
                },
                'input_records': bundle.metadata.input_records,
                'total_incidents': bundle.metadata.total_incidents,
                'pipeline_version': bundle.metadata.pipeline_version,
            },
            'cross_day_trends': self._trends_dict(bundle.cross_day_trends) if bundle.cross_day_trends else None,
            'daily_reports': [self._daily_dict(r) for r in bundle.daily_reports],
        }
    
    def _trends_dict(self, t) -> Dict:
        return {
            'overall_status': t.overall_status.value,
            'overall_errors_trend': t.overall_errors_trend,
            'overall_incidents_trend': t.overall_incidents_trend,
            'top_growing': [{'fp': fp, 'msg': m, 'change': c} for fp, m, c in t.top_growing],
            'top_new': [{'fp': fp, 'msg': m, 'count': c} for fp, m, c in t.top_new_issues],
        }
    
    def _daily_dict(self, r: DailyReport) -> Dict:
        return {
            'date': str(r.date),
            'status': r.conclusion.status.value,
            'statistics': {
                'total_errors': r.statistics.total_errors,
                'total_incidents': r.statistics.total_incidents,
                'by_severity': r.statistics.by_severity,
                'by_category': r.statistics.by_category,
            },
            'conclusion': {
                'summary': r.conclusion.summary_points,
                'actions': r.conclusion.action_items,
            },
            'clusters': [
                {
                    'id': c.cluster_id,
                    'category': c.category,
                    'occurrences': c.total_occurrences,
                    'apps': c.affected_apps,
                    'hypothesis': c.hypothesis,
                    'fixes': c.suggested_fixes,
                }
                for c in r.error_clusters
            ],
            'peaks': [
                {
                    'type': p.peak_type,
                    'ratio': p.ratio,
                    'apps': p.apps,
                    'message': p.message,
                }
                for p in r.peaks
            ],
            'known_vs_new': {
                'new_errors': r.known_vs_new.new_errors,
                'known_errors': r.known_vs_new.known_errors,
            },
        }
    
    # =========================================================================
    # SAVE
    # =========================================================================
    
    def save_all(self, bundle: DailyReportBundle, output_dir: str) -> Dict[str, str]:
        """Uloží všechny formáty"""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        date_range = f"{bundle.metadata.date_range_from}_{bundle.metadata.date_range_to}"
        
        files = {}
        
        md_path = path / f"report_{date_range}_{timestamp}.md"
        with open(md_path, 'w') as f:
            f.write(self.to_markdown(bundle))
        files['markdown'] = str(md_path)
        
        txt_path = path / f"report_{date_range}_{timestamp}.txt"
        with open(txt_path, 'w') as f:
            f.write(self.to_console(bundle))
        files['text'] = str(txt_path)
        
        json_path = path / f"report_{date_range}_{timestamp}.json"
        with open(json_path, 'w') as f:
            f.write(self.to_json(bundle))
        files['json'] = str(json_path)
        
        return files
