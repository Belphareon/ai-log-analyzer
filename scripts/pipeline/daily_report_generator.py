#!/usr/bin/env python3
"""
DAILY REPORT GENERATOR
======================

Generuje denní reporty:
1. Rozdělí IncidentCollection per day
2. Pro každý den: stats, errors, peaks, known_vs_new, trend, conclusion
3. Cross-day trends
"""

from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

try:
    from .daily_report_models import (
        DailyReport, DailyReportBundle, ReportMetadata,
        DailyStatistics, AppErrorSummary, ErrorCluster, TimelineEvent,
        PeakDetail, KnownVsNew, TrendVsPreviousDay, DailyConclusion,
        CrossDayTrends, DayStatus, KnownIssuesRegistry, KnownIssue,
        get_root_cause, infer_day_status
    )
    from .incident import Incident, IncidentCollection
except ImportError:
    from daily_report_models import (
        DailyReport, DailyReportBundle, ReportMetadata,
        DailyStatistics, AppErrorSummary, ErrorCluster, TimelineEvent,
        PeakDetail, KnownVsNew, TrendVsPreviousDay, DailyConclusion,
        CrossDayTrends, DayStatus, KnownIssuesRegistry, KnownIssue,
        get_root_cause, infer_day_status
    )
    from incident import Incident, IncidentCollection


class DailyReportGenerator:
    """Generátor denních reportů"""
    
    def __init__(self, registry: KnownIssuesRegistry = None):
        self.registry = registry or KnownIssuesRegistry()
    
    def generate_bundle(
        self,
        collection: IncidentCollection,
        update_registry: bool = False
    ) -> DailyReportBundle:
        """Hlavní metoda - generuje kompletní bundle"""
        
        # 1. Split by day
        by_day = self._split_by_day(collection)
        
        if not by_day:
            return DailyReportBundle(
                metadata=ReportMetadata(
                    generated_at=datetime.now(timezone.utc),
                    date_range_from=date.today(),
                    date_range_to=date.today(),
                    input_records=0,
                    total_incidents=0,
                    pipeline_version="1.0",
                )
            )
        
        # 2. Generate daily reports
        daily_reports = []
        sorted_dates = sorted(by_day.keys())
        
        prev_report = None
        for d in sorted_dates:
            report = self._generate_daily(d, by_day[d], prev_report, update_registry)
            daily_reports.append(report)
            prev_report = report
        
        # 3. Cross-day trends
        cross_day = self._calc_cross_day_trends(daily_reports)
        
        # 4. Build bundle
        return DailyReportBundle(
            metadata=ReportMetadata(
                generated_at=datetime.now(timezone.utc),
                date_range_from=sorted_dates[0],
                date_range_to=sorted_dates[-1],
                input_records=collection.input_records,
                total_incidents=collection.total_incidents,
                pipeline_version=collection.pipeline_version or "1.0",
            ),
            daily_reports=daily_reports,
            cross_day_trends=cross_day,
        )
    
    def _split_by_day(self, collection: IncidentCollection) -> Dict[date, List[Incident]]:
        """Rozdělí incidenty per day"""
        by_day = defaultdict(list)
        for inc in collection.incidents:
            if inc.time.first_seen:
                d = inc.time.first_seen.date()
            else:
                d = date.today()
            by_day[d].append(inc)
        return dict(by_day)
    
    def _generate_daily(
        self,
        day: date,
        incidents: List[Incident],
        prev_report: Optional[DailyReport],
        update_registry: bool
    ) -> DailyReport:
        """Generuje report pro jeden den"""
        
        report = DailyReport(date=day)
        
        # 1. Statistics
        report.statistics = self._calc_statistics(incidents)
        
        # 2. Per-app analysis
        report.errors_per_app = self._analyze_per_app(incidents)
        
        # 3. Error clusters
        report.error_clusters = self._find_clusters(incidents)
        
        # 4. Timeline
        report.error_timeline = self._build_timeline(incidents)
        
        # 5. Peaks
        report.peaks = self._analyze_peaks(incidents)
        
        # 6. Known vs New
        report.known_vs_new = self._check_known_new(incidents, update_registry)
        
        # 7. Trend vs previous
        report.trend = self._calc_trend(report.statistics, prev_report)
        
        # 8. Conclusion
        report.conclusion = self._generate_conclusion(report)
        
        return report
    
    def _calc_statistics(self, incidents: List[Incident]) -> DailyStatistics:
        """Spočítá statistiky"""
        stats = DailyStatistics()
        
        for inc in incidents:
            stats.total_errors += inc.stats.current_count
            stats.total_incidents += 1
            
            sev = inc.severity.value
            stats.by_severity[sev] = stats.by_severity.get(sev, 0) + 1
            
            cat = inc.category.value
            stats.by_category[cat] = stats.by_category.get(cat, 0) + 1
            
            for ns in inc.namespaces:
                stats.by_namespace[ns] = stats.by_namespace.get(ns, 0) + inc.stats.current_count
            
            for app in inc.apps:
                stats.by_app[app] = stats.by_app.get(app, 0) + inc.stats.current_count
        
        return stats
    
    def _analyze_per_app(self, incidents: List[Incident]) -> List[AppErrorSummary]:
        """Per-app analýza"""
        app_data: Dict[str, AppErrorSummary] = {}
        fp_to_apps: Dict[str, Set[str]] = defaultdict(set)
        
        for inc in incidents:
            for app in inc.apps:
                fp_to_apps[inc.fingerprint].add(app)
            
            for app in inc.apps:
                if app not in app_data:
                    app_data[app] = AppErrorSummary(app_name=app)
                
                summary = app_data[app]
                summary.total_errors += inc.stats.current_count
                summary.unique_fingerprints += 1
                
                for v in inc.versions:
                    if v and v not in summary.versions:
                        summary.versions.append(v)
                
                for ns in inc.namespaces:
                    if ns not in summary.namespaces:
                        summary.namespaces.append(ns)
                
                flags = []
                if inc.flags.is_new: flags.append("NEW")
                if inc.flags.is_spike: flags.append("SPIKE")
                if inc.flags.is_burst: flags.append("BURST")
                
                summary.top_errors.append({
                    'fingerprint': inc.fingerprint,
                    'message': inc.normalized_message[:100],
                    'count': inc.stats.current_count,
                    'severity': inc.severity.value,
                    'flags': flags,
                })
        
        # Related apps + sort
        for app, summary in app_data.items():
            for err in summary.top_errors:
                fp = err['fingerprint']
                for other in fp_to_apps.get(fp, set()) - {app}:
                    if other not in summary.related_apps:
                        summary.related_apps.append(other)
            
            summary.top_errors.sort(key=lambda x: -x['count'])
            summary.top_errors = summary.top_errors[:10]
        
        return sorted(app_data.values(), key=lambda x: -x.total_errors)
    
    def _find_clusters(self, incidents: List[Incident]) -> List[ErrorCluster]:
        """Najde error clusters"""
        by_category: Dict[str, List[Incident]] = defaultdict(list)
        for inc in incidents:
            key = f"{inc.category.value}/{inc.subcategory}"
            by_category[key].append(inc)
        
        clusters = []
        cluster_id = 0
        
        for category, cat_incs in by_category.items():
            if len(cat_incs) < 2:
                continue
            
            # Group by apps overlap
            app_groups: Dict[frozenset, List[Incident]] = defaultdict(list)
            for inc in cat_incs:
                app_key = frozenset(inc.apps[:3])
                app_groups[app_key].append(inc)
            
            for app_key, group in app_groups.items():
                if len(group) < 2:
                    continue
                
                cluster_id += 1
                hypothesis, fixes = get_root_cause(category)
                
                cluster = ErrorCluster(
                    cluster_id=f"CLU-{cluster_id:03d}",
                    category=category,
                    hypothesis=hypothesis,
                    suggested_fixes=fixes,
                )
                
                all_apps = set()
                all_ns = set()
                timestamps = []
                
                for inc in group:
                    cluster.fingerprints.append(inc.fingerprint)
                    cluster.total_occurrences += inc.stats.current_count
                    all_apps.update(inc.apps)
                    all_ns.update(inc.namespaces)
                    
                    if inc.time.first_seen:
                        timestamps.append(inc.time.first_seen)
                    if inc.time.last_seen:
                        timestamps.append(inc.time.last_seen)
                    
                    if len(cluster.sample_messages) < 3:
                        cluster.sample_messages.append(inc.normalized_message[:150])
                
                cluster.affected_apps = list(all_apps)
                cluster.affected_namespaces = list(all_ns)
                if timestamps:
                    cluster.first_seen = min(timestamps)
                    cluster.last_seen = max(timestamps)
                
                clusters.append(cluster)
        
        clusters.sort(key=lambda c: -c.total_occurrences)
        return clusters[:10]
    
    def _build_timeline(self, incidents: List[Incident]) -> List[TimelineEvent]:
        """Staví timeline"""
        events = []
        
        sorted_incs = sorted(
            [i for i in incidents if i.time.first_seen],
            key=lambda x: x.time.first_seen
        )
        
        if not sorted_incs:
            return events
        
        # First error
        first = sorted_incs[0]
        events.append(TimelineEvent(
            timestamp=first.time.first_seen,
            event_type="first_error",
            description=f"First error: {first.error_type}",
            fingerprints=[first.fingerprint],
            apps=first.apps[:2],
        ))
        
        # Spikes
        for inc in sorted_incs:
            if inc.flags.is_spike:
                events.append(TimelineEvent(
                    timestamp=inc.time.first_seen,
                    event_type="spike",
                    description=f"Spike: {inc.error_type} ({inc.stats.trend_ratio:.1f}x)",
                    fingerprints=[inc.fingerprint],
                    apps=inc.apps[:2],
                ))
        
        # Cross-namespace
        for inc in sorted_incs:
            if inc.flags.is_cross_namespace and len(inc.namespaces) >= 3:
                events.append(TimelineEvent(
                    timestamp=inc.time.first_seen,
                    event_type="cross_namespace",
                    description=f"Cross-NS: {inc.error_type} in {len(inc.namespaces)} namespaces",
                    fingerprints=[inc.fingerprint],
                    apps=inc.apps[:2],
                ))
        
        events.sort(key=lambda e: e.timestamp)
        return events[:20]
    
    def _analyze_peaks(self, incidents: List[Incident]) -> List[PeakDetail]:
        """Analýza peaků"""
        peaks = []
        
        for inc in incidents:
            if not (inc.flags.is_spike or inc.flags.is_burst):
                continue
            
            peak = PeakDetail(
                fingerprint=inc.fingerprint,
                peak_type="SPIKE" if inc.flags.is_spike else "BURST",
                apps=inc.apps,
                namespaces=inc.namespaces,
                baseline_rate=inc.stats.baseline_rate,
                peak_rate=inc.stats.current_rate,
                ratio=inc.stats.trend_ratio,
                first_seen=inc.time.first_seen,
                last_seen=inc.time.last_seen,
                duration_sec=inc.time.duration_sec,
                message=inc.normalized_message[:100],
            )
            
            # Infer cause
            cat = inc.category.value
            if cat == 'database':
                peak.likely_cause = "Database overload"
            elif cat == 'network':
                peak.likely_cause = "Network/service issues"
            elif cat == 'timeout':
                peak.likely_cause = "Downstream slowdown"
            elif cat == 'external':
                peak.likely_cause = "External service degradation"
            else:
                peak.likely_cause = "Unknown"
            
            peaks.append(peak)
        
        peaks.sort(key=lambda p: -p.ratio)
        return peaks[:20]
    
    def _check_known_new(self, incidents: List[Incident], update: bool) -> KnownVsNew:
        """Known vs new check"""
        result = KnownVsNew()
        
        for inc in incidents:
            fp = inc.fingerprint
            
            if self.registry.is_known_error(fp):
                result.known_errors += 1
            else:
                result.new_errors += 1
                result.new_error_fingerprints.append(fp)
                if update:
                    self.registry.errors[fp] = KnownIssue(
                        fingerprint=fp,
                        description=inc.normalized_message[:100],
                        first_seen=date.today(),
                        category=inc.category.value,
                    )
            
            if inc.flags.is_spike or inc.flags.is_burst:
                if self.registry.is_known_peak(fp):
                    result.known_peaks += 1
                else:
                    result.new_peaks += 1
                    result.new_peak_fingerprints.append(fp)
                    if update:
                        self.registry.peaks[fp] = KnownIssue(
                            fingerprint=fp,
                            description=inc.normalized_message[:100],
                            first_seen=date.today(),
                            category=inc.category.value,
                        )
        
        return result
    
    def _calc_trend(self, stats: DailyStatistics, prev: Optional[DailyReport]) -> TrendVsPreviousDay:
        """Trend oproti předchozímu dni"""
        trend = TrendVsPreviousDay()
        
        if prev:
            prev_stats = prev.statistics
            
            if prev_stats.total_errors > 0:
                trend.errors_change_pct = (
                    (stats.total_errors - prev_stats.total_errors) / prev_stats.total_errors * 100
                )
            
            if prev_stats.total_incidents > 0:
                trend.incidents_change_pct = (
                    (stats.total_incidents - prev_stats.total_incidents) / prev_stats.total_incidents * 100
                )
        
        critical = stats.by_severity.get('critical', 0)
        trend.status = infer_day_status(trend.errors_change_pct, trend.incidents_change_pct, critical)
        
        return trend
    
    def _generate_conclusion(self, report: DailyReport) -> DailyConclusion:
        """Generuje závěr"""
        conclusion = DailyConclusion()
        conclusion.status = report.trend.status
        
        stats = report.statistics
        points = []
        actions = []
        
        # Critical/high
        critical = stats.by_severity.get('critical', 0)
        high = stats.by_severity.get('high', 0)
        
        if critical > 0:
            points.append(f"🔴 {critical} CRITICAL issues require immediate attention")
            actions.append("⚡ Investigate critical issues immediately")
        
        if high > 5:
            points.append(f"🟠 {high} high severity issues detected")
        
        # Trend
        if report.trend.status == DayStatus.DEGRADING:
            points.append(f"📈 Error rate increasing ({report.trend.errors_change_pct:+.1f}% vs previous day)")
        elif report.trend.status == DayStatus.IMPROVING:
            points.append(f"📉 Error rate decreasing ({report.trend.errors_change_pct:+.1f}% vs previous day)")
        
        # New issues
        if report.known_vs_new.new_errors > 10:
            points.append(f"🆕 {report.known_vs_new.new_errors} new error patterns detected")
            actions.append("📋 Triage new error patterns")
        
        # Clusters
        if report.error_clusters:
            top = report.error_clusters[0]
            points.append(f"🔗 Top cluster: {top.category} ({top.total_occurrences:,} occurrences)")
            if top.suggested_fixes:
                actions.append(f"🔧 {top.category}: {top.suggested_fixes[0]}")
        
        # Peaks
        spike_count = sum(1 for p in report.peaks if p.peak_type == "SPIKE")
        burst_count = sum(1 for p in report.peaks if p.peak_type == "BURST")
        
        if spike_count > 0:
            points.append(f"📈 {spike_count} error spikes detected")
        
        if burst_count > 3:
            points.append(f"💥 {burst_count} bursts detected")
            actions.append("📊 Review burst patterns")
        
        conclusion.summary_points = points
        conclusion.action_items = actions[:5]
        
        return conclusion
    
    def _calc_cross_day_trends(self, daily_reports: List[DailyReport]) -> CrossDayTrends:
        """Cross-day trends"""
        if not daily_reports:
            return CrossDayTrends(period_start=date.today(), period_end=date.today())
        
        trends = CrossDayTrends(
            period_start=daily_reports[0].date,
            period_end=daily_reports[-1].date,
        )
        
        # Track fingerprints
        fp_daily_counts: Dict[str, Dict[date, int]] = defaultdict(dict)
        fp_messages: Dict[str, str] = {}
        
        for report in daily_reports:
            for app in report.errors_per_app:
                for err in app.top_errors:
                    fp = err['fingerprint']
                    fp_daily_counts[fp][report.date] = fp_daily_counts[fp].get(report.date, 0) + err['count']
                    fp_messages[fp] = err['message']
        
        # Growing fingerprints
        growing = []
        for fp, daily in fp_daily_counts.items():
            dates = sorted(daily.keys())
            if len(dates) >= 2:
                first_half = sum(daily.get(d, 0) for d in dates[:len(dates)//2]) or 1
                second_half = sum(daily.get(d, 0) for d in dates[len(dates)//2:])
                change = ((second_half - first_half) / first_half) * 100
                if change > 20:
                    growing.append((fp, fp_messages.get(fp, '')[:50], change))
        
        growing.sort(key=lambda x: -x[2])
        trends.top_growing = growing[:5]
        
        # New from last day
        if daily_reports:
            last = daily_reports[-1]
            for fp in last.known_vs_new.new_error_fingerprints[:5]:
                for app in last.errors_per_app:
                    for err in app.top_errors:
                        if err['fingerprint'] == fp:
                            trends.top_new_issues.append((fp, err['message'][:50], err['count']))
                            break
        
        # Overall trend
        if len(daily_reports) >= 2:
            first_errors = daily_reports[0].statistics.total_errors
            last_errors = daily_reports[-1].statistics.total_errors
            if first_errors > 0:
                trends.overall_errors_trend = ((last_errors - first_errors) / first_errors) * 100
            
            first_incidents = daily_reports[0].statistics.total_incidents
            last_incidents = daily_reports[-1].statistics.total_incidents
            if first_incidents > 0:
                trends.overall_incidents_trend = ((last_incidents - first_incidents) / first_incidents) * 100
        
        trends.overall_status = daily_reports[-1].trend.status if daily_reports else DayStatus.STABLE
        
        return trends
