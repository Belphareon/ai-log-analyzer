#!/usr/bin/env python3
"""
INCIDENT REPORT FORMATTER
=========================

Formátuje IncidentAnalysis pro různé režimy:

1. 15-minute operational mode (nejdůležitější)
   - Okamžitě actionable výstup
   - Co se rozbilo, proč, kde, koho se to týká, co s tím

2. Daily mode
   - Agregovaný přehled dne
   - Trendy, statistiky

3. Weekly mode
   - Týdenní trendy
   - Top issues

Exporty:
- Console (human-readable)
- Markdown
- JSON
- Slack
- Jira
"""

from typing import List, Dict, Optional, Any
from datetime import datetime, date
from pathlib import Path
import json

try:
    from .models import (
        IncidentAnalysis, IncidentAnalysisResult,
        IncidentStatus, SeverityLevel, ConfidenceLevel, ActionPriority,
        TimelineEvent, RecommendedAction,
    )
except ImportError:
    from models import (
        IncidentAnalysis, IncidentAnalysisResult,
        IncidentStatus, SeverityLevel, ConfidenceLevel, ActionPriority,
        TimelineEvent, RecommendedAction,
    )


class IncidentReportFormatter:
    """Formatter pro incident reporty"""
    
    SEVERITY_ICONS = {
        SeverityLevel.CRITICAL: '🔴',
        SeverityLevel.HIGH: '🟠',
        SeverityLevel.MEDIUM: '🟡',
        SeverityLevel.LOW: '🟢',
    }
    
    STATUS_ICONS = {
        IncidentStatus.ACTIVE: '🚨',
        IncidentStatus.RESOLVED: '✅',
        IncidentStatus.INVESTIGATING: '🔍',
    }
    
    CONFIDENCE_ICONS = {
        ConfidenceLevel.HIGH: '✓',
        ConfidenceLevel.MEDIUM: '~',
        ConfidenceLevel.LOW: '?',
    }
    
    PRIORITY_ICONS = {
        ActionPriority.IMMEDIATE: '🚨',
        ActionPriority.TODAY: '📌',
        ActionPriority.THIS_WEEK: '📋',
        ActionPriority.BACKLOG: '📝',
    }
    
    # =========================================================================
    # 15-MINUTE MODE (nejdůležitější)
    # =========================================================================
    
    def format_15min(self, result: IncidentAnalysisResult) -> str:
        """
        Formátuje pro 15-minute operational mode.
        
        Výstup optimalizovaný pro:
        - Okamžitou akci
        - Jasné co/kde/proč/jak
        - KNOWN vs NEW rozlišení
        """
        lines = []
        
        # Header
        lines.append("=" * 70)
        lines.append("🔍 INCIDENT ANALYSIS - 15 MIN OPERATIONAL REPORT")
        lines.append("=" * 70)
        lines.append(f"Period: {result.analysis_start.strftime('%H:%M')} - {result.analysis_end.strftime('%H:%M')}")
        lines.append(f"Analysis time: {result.analysis_duration_ms}ms")
        lines.append("")
        
        # Summary
        if result.total_incidents == 0:
            lines.append("✅ NO INCIDENTS DETECTED")
            lines.append("")
            return "\n".join(lines)
        
        # Count NEW vs KNOWN
        new_count = sum(1 for i in result.incidents if getattr(i, 'knowledge_status', 'NEW') == 'NEW')
        known_count = sum(1 for i in result.incidents if getattr(i, 'knowledge_status', 'NEW') == 'KNOWN')
        
        lines.append(f"⚠️ {result.total_incidents} INCIDENT(S) DETECTED")
        lines.append(f"   🆕 {new_count} NEW | 📚 {known_count} KNOWN")
        if result.critical_count > 0:
            lines.append(f"   🔴 {result.critical_count} CRITICAL")
        if result.high_count > 0:
            lines.append(f"   🟠 {result.high_count} HIGH")
        lines.append("")
        
        # Each incident
        for incident in result.incidents:
            lines.extend(self._format_incident_15min(incident))
            lines.append("")
        
        return "\n".join(lines)
    
    def _format_incident_15min(self, incident: IncidentAnalysis) -> List[str]:
        """
        Formátuje jeden incident pro 15min mode.
        
        PRAVIDLA:
        - Max 1 obrazovka (~25 řádků)
        - Jasné FACT vs HYPOTHESIS
        - Priority pro akčnost
        - IMMEDIATE ACTIONS pro SRE ve 3 ráno
        """
        lines = []
        knowledge_status = incident.knowledge_status or "NEW"
        
        # === HEADER s PRIORITY ===
        sev_icon = self.SEVERITY_ICONS.get(incident.severity, '⚪')
        priority = getattr(incident, 'priority', None)
        priority_str = f"[{priority.value}]" if priority else ""
        
        time_range = ""
        if incident.started_at:
            time_range = f"({incident.started_at.strftime('%H:%M')}–{incident.ended_at.strftime('%H:%M') if incident.ended_at else 'ongoing'})"
        
        lines.append("─" * 60)
        if knowledge_status == "KNOWN":
            lines.append(f"{sev_icon} {priority_str} KNOWN INCIDENT {time_range} [{incident.knowledge_id}]")
        else:
            lines.append(f"{sev_icon} {priority_str} 🆕 NEW INCIDENT {time_range}")
        lines.append("─" * 60)
        
        # === FACTS (detekované události) ===
        lines.append("")
        lines.append("FACTS:")
        
        # Trigger
        if incident.trigger:
            lines.append(f"  • {incident.trigger.app}: {incident.trigger.message[:60]}")
        
        # === v5.3: Scope s rolemi ===
        scope = incident.scope
        if scope.has_clear_root:
            # Máme jasný root - zobraz strukturovaně
            root_str = ", ".join(scope.root_apps)
            lines.append(f"  • Root: {root_str}")
            
            if scope.downstream_apps:
                down_str = ", ".join(scope.downstream_apps[:3])
                if len(scope.downstream_apps) > 3:
                    down_str += f" (+{len(scope.downstream_apps) - 3})"
                lines.append(f"  • Downstream: {down_str}")
            
            if scope.collateral_apps:
                coll_str = ", ".join(scope.collateral_apps[:2])
                if len(scope.collateral_apps) > 2:
                    coll_str += f" (+{len(scope.collateral_apps) - 2})"
                lines.append(f"  • Collateral: {coll_str}")
        else:
            # Fallback na plochý seznam
            apps_str = ", ".join(scope.apps[:4])
            if len(scope.apps) > 4:
                apps_str += f" (+{len(scope.apps) - 4})"
            lines.append(f"  • Affected: {apps_str}")
        
        # Metrics
        lines.append(f"  • Errors: {incident.total_errors:,} | Peak: {incident.peak_error_rate:.1f}x baseline")
        
        # Propagation info (v5.3)
        if scope.propagated:
            prop_time = scope.propagation_time_sec or 0
            if prop_time < 60:
                lines.append(f"  • ⚡ PROPAGATED in {prop_time}s across {scope.blast_radius} apps")
            else:
                lines.append(f"  • 📊 Spread to {scope.blast_radius} apps over {prop_time // 60}m {prop_time % 60}s")
        elif scope.is_localized:
            lines.append(f"  • ✓ Localized (single app)")
        
        # Version change - critical signal!
        if scope.version_change_detected:
            lines.append(f"  • ⚠️ VERSION CHANGE: {scope.version_change_app} ({scope.version_change_from} → {scope.version_change_to})")
        
        # === HYPOTHESIS (odvozený root cause) ===
        # Zobrazuj jen pokud máme dostatečnou confidence
        lines.append("")
        lines.append("HYPOTHESIS:")
        if incident.causal_chain and incident.causal_chain.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM):
            conf_icon = self.CONFIDENCE_ICONS.get(incident.causal_chain.confidence, '?')
            lines.append(f"  [{conf_icon}] {incident.causal_chain.root_cause_description}")
        else:
            lines.append(f"  [?] Insufficient data for reliable root cause inference")
        
        # === STATUS ===
        lines.append("")
        if knowledge_status == "KNOWN":
            lines.append(f"STATUS: Known issue {incident.knowledge_id}")
            if incident.knowledge_jira:
                lines.append(f"  Jira: {incident.knowledge_jira}")
        else:
            lines.append("STATUS: NEW - requires triage")
        
        # === IMMEDIATE ACTIONS (klíčové!) ===
        immediate_actions = getattr(incident, 'immediate_actions', [])
        if immediate_actions:
            lines.append("")
            lines.append("IMMEDIATE ACTIONS:")
            for i, action in enumerate(immediate_actions[:3], 1):
                lines.append(f"  {i}. {action}")
        elif knowledge_status == "KNOWN" and incident.knowledge_workaround:
            lines.append("")
            lines.append("IMMEDIATE ACTIONS:")
            lines.append(f"  1. {incident.knowledge_workaround[0]}")
        elif incident.recommended_actions:
            lines.append("")
            lines.append("IMMEDIATE ACTIONS:")
            action = incident.recommended_actions[0]
            lines.append(f"  1. {action.title}")
            if action.config_change:
                lines.append(f"     {action.config_change}")
        
        return lines
    
    # =========================================================================
    # DAILY MODE
    # =========================================================================
    
    def format_daily(self, result: IncidentAnalysisResult, report_date: date = None) -> str:
        """
        Formátuje denní report.
        
        DŮLEŽITÉ: Rozlišujeme:
        - Raw incidents = fingerprint-level detekce z pipeline
        - Operational incidents = agregované podle root cause
        """
        lines = []
        
        lines.append("=" * 70)
        lines.append("📊 DAILY INCIDENT REPORT")
        lines.append("=" * 70)
        lines.append(f"Date: {report_date or result.analysis_start.date()}")
        lines.append("")
        
        # === AGREGACE DO OPERATIONAL INCIDENTS ===
        # Seskupíme podle root_cause_type + root_cause_app
        operational_incidents = self._aggregate_to_operational(result.incidents)
        
        lines.append(f"Raw incidents processed: {result.total_incidents:,}")
        lines.append(f"Operational incidents identified: {len(operational_incidents)}")
        lines.append("")
        
        # Summary by severity (operational)
        op_critical = sum(1 for o in operational_incidents if o['severity'] == SeverityLevel.CRITICAL)
        op_high = sum(1 for o in operational_incidents if o['severity'] == SeverityLevel.HIGH)
        op_medium = sum(1 for o in operational_incidents if o['severity'] == SeverityLevel.MEDIUM)
        op_low = sum(1 for o in operational_incidents if o['severity'] == SeverityLevel.LOW)
        
        lines.append("OPERATIONAL SEVERITY:")
        if op_critical > 0:
            lines.append(f"  🔴 Critical: {op_critical}")
        if op_high > 0:
            lines.append(f"  🟠 High: {op_high}")
        if op_medium > 0:
            lines.append(f"  🟡 Medium: {op_medium}")
        if op_low > 0:
            lines.append(f"  🟢 Low: {op_low}")
        lines.append("")
        
        # Top operational incidents (deduplikované!)
        if operational_incidents:
            lines.append("TOP OPERATIONAL INCIDENTS:")
            lines.append("-" * 50)
            
            # Seřadit podle severity a počtu raw incidents
            sorted_ops = sorted(
                operational_incidents, 
                key=lambda x: (
                    -{'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(x['severity'].value, 0),
                    -x['raw_count'],
                    -x['total_errors']
                )
            )
            
            for op in sorted_ops[:10]:
                sev_icon = self.SEVERITY_ICONS.get(op['severity'], '⚪')
                lines.append(f"{sev_icon} {op['title']}")
                lines.append(f"   Root cause: {op['root_cause']}")
                lines.append(f"   Affected: {', '.join(op['apps'][:5])}")
                lines.append(f"   Raw incidents: {op['raw_count']} | Total errors: {op['total_errors']:,}")
                
                # Immediate actions (safe, ne rollback!)
                if op['actions']:
                    lines.append(f"   → {op['actions'][0]}")
                
                lines.append("")
        
        # Affected apps summary
        all_apps = set()
        for incident in result.incidents:
            all_apps.update(incident.scope.apps)
        
        if all_apps:
            lines.append("AFFECTED APPLICATIONS:")
            for app in sorted(all_apps)[:15]:
                count = sum(1 for i in result.incidents if app in i.scope.apps)
                lines.append(f"  - {app}: {count} raw incident(s)")
        
        return "\n".join(lines)
    
    def _aggregate_to_operational(self, incidents: List[IncidentAnalysis]) -> List[Dict]:
        """
        Agreguje raw incidents do operational incidents.
        
        Klíč agregace: root_cause_type + root_cause_app
        Pokud není root cause, použije se category + první app.
        """
        from collections import defaultdict
        
        groups = defaultdict(list)
        
        for inc in incidents:
            # Určení agregačního klíče
            if inc.causal_chain:
                key = f"{inc.causal_chain.root_cause_type}|{inc.causal_chain.root_cause_app}"
            else:
                # Fallback na kategorii
                category = getattr(inc, 'category', 'unknown')
                if hasattr(category, 'value'):
                    category = category.value
                first_app = inc.scope.apps[0] if inc.scope.apps else 'unknown'
                key = f"{category}|{first_app}"
            
            groups[key].append(inc)
        
        # Převod na operational incidents
        operational = []
        for key, group in groups.items():
            # Reprezentant = nejzávažnější incident ve skupině
            rep = max(group, key=lambda x: (
                {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(x.severity.value, 0),
                x.total_errors or 0
            ))
            
            # Agregované hodnoty
            all_apps = set()
            total_errors = 0
            for inc in group:
                all_apps.update(inc.scope.apps)
                total_errors += inc.total_errors or 0
            
            # Root cause description
            if rep.causal_chain:
                root_cause = rep.causal_chain.root_cause_description
            else:
                root_cause = f"Unknown issue in {rep.scope.apps[0] if rep.scope.apps else 'unknown'}"
            
            # Actions - bezpečné, ne rollback!
            actions = []
            if rep.immediate_actions:
                actions = rep.immediate_actions[:2]
            elif rep.recommended_actions:
                actions = [a.title for a in rep.recommended_actions[:2]]
            
            operational.append({
                'key': key,
                'title': rep.title or f"Issue in {rep.scope.apps[0] if rep.scope.apps else 'unknown'}",
                'severity': rep.severity,
                'root_cause': root_cause,
                'apps': sorted(all_apps),
                'raw_count': len(group),
                'total_errors': total_errors,
                'actions': actions,
                'representative': rep,
            })
        
        return operational
    
    # =========================================================================
    # MARKDOWN
    # =========================================================================
    
    def to_markdown(self, result: IncidentAnalysisResult) -> str:
        """Export do Markdown"""
        lines = []
        
        lines.append("# 🔍 Incident Analysis Report")
        lines.append("")
        lines.append(f"**Period:** {result.analysis_start.strftime('%Y-%m-%d %H:%M')} - {result.analysis_end.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"**Total Incidents:** {result.total_incidents}")
        lines.append("")
        
        # Summary table
        lines.append("## Summary")
        lines.append("")
        lines.append("| Severity | Count |")
        lines.append("|----------|-------|")
        lines.append(f"| 🔴 Critical | {result.critical_count} |")
        lines.append(f"| 🟠 High | {result.high_count} |")
        lines.append(f"| 🟡 Medium | {result.medium_count} |")
        lines.append(f"| 🟢 Low | {result.low_count} |")
        lines.append("")
        
        # Incidents
        lines.append("## Incidents")
        lines.append("")
        
        for incident in result.incidents:
            lines.extend(self._incident_to_markdown(incident))
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def _incident_to_markdown(self, incident: IncidentAnalysis) -> List[str]:
        """Incident do Markdown"""
        lines = []
        
        sev_icon = self.SEVERITY_ICONS.get(incident.severity, '⚪')
        lines.append(f"### {sev_icon} {incident.incident_id}: {incident.title}")
        lines.append("")
        lines.append(f"**Status:** {incident.status.value} | **Severity:** {incident.severity.value}")
        lines.append(f"**Duration:** {incident.duration_sec // 60} min | **Errors:** {incident.total_errors:,}")
        lines.append("")
        
        if incident.causal_chain:
            lines.append("#### Root Cause")
            lines.append("")
            lines.append(f"> {incident.causal_chain.root_cause_description}")
            lines.append(f"> ")
            lines.append(f"> **App:** {incident.causal_chain.root_cause_app}")
            lines.append(f"> **Confidence:** {incident.causal_chain.confidence.value}")
            lines.append("")
        
        lines.append("#### Affected Applications")
        lines.append("")
        for app in incident.scope.apps[:10]:
            lines.append(f"- {app}")
        lines.append("")
        
        if incident.timeline:
            lines.append("#### Timeline")
            lines.append("")
            lines.append("| Time | Event |")
            lines.append("|------|-------|")
            for event in incident.timeline[:10]:
                time_str = event.timestamp.strftime("%H:%M:%S")
                marker = " ⬅️" if event.is_trigger else ""
                lines.append(f"| {time_str} | {event.description}{marker} |")
            lines.append("")
        
        if incident.recommended_actions:
            lines.append("#### Recommended Actions")
            lines.append("")
            for action in incident.recommended_actions[:5]:
                priority_icon = self.PRIORITY_ICONS.get(action.priority, '•')
                lines.append(f"{priority_icon} **{action.title}**")
                if action.config_change:
                    lines.append(f"  ```")
                    lines.append(f"  {action.config_change}")
                    lines.append(f"  ```")
                if action.estimated_effort:
                    lines.append(f"  *Effort: {action.estimated_effort}*")
                lines.append("")
        
        return lines
    
    # =========================================================================
    # JSON
    # =========================================================================
    
    def to_json(self, result: IncidentAnalysisResult) -> str:
        """Export do JSON"""
        return json.dumps(self._to_dict(result), indent=2, default=str)
    
    def _to_dict(self, result: IncidentAnalysisResult) -> Dict:
        """Result to dict"""
        return {
            'analysis': {
                'start': result.analysis_start.isoformat(),
                'end': result.analysis_end.isoformat(),
                'duration_ms': result.analysis_duration_ms,
            },
            'summary': {
                'total_incidents': result.total_incidents,
                'active': result.active_incidents,
                'resolved': result.resolved_incidents,
                'by_severity': {
                    'critical': result.critical_count,
                    'high': result.high_count,
                    'medium': result.medium_count,
                    'low': result.low_count,
                },
            },
            'incidents': [self._incident_to_dict(i) for i in result.incidents],
        }
    
    def _incident_to_dict(self, incident: IncidentAnalysis) -> Dict:
        """Incident to dict"""
        return {
            'id': incident.incident_id,
            'title': incident.title,
            'summary': incident.summary,
            'status': incident.status.value,
            'severity': incident.severity.value,
            'confidence': incident.overall_confidence.value,
            'timing': {
                'started_at': incident.started_at.isoformat() if incident.started_at else None,
                'ended_at': incident.ended_at.isoformat() if incident.ended_at else None,
                'duration_sec': incident.duration_sec,
            },
            'metrics': {
                'total_errors': incident.total_errors,
                'peak_rate': incident.peak_error_rate,
            },
            'scope': {
                'apps': incident.scope.apps,
                'namespaces': incident.scope.namespaces,
                'blast_radius': incident.scope.blast_radius,
            },
            'root_cause': {
                'description': incident.causal_chain.root_cause_description if incident.causal_chain else None,
                'app': incident.causal_chain.root_cause_app if incident.causal_chain else None,
                'type': incident.causal_chain.root_cause_type if incident.causal_chain else None,
                'effects': incident.causal_chain.effects if incident.causal_chain else [],
            } if incident.causal_chain else None,
            'actions': [
                {
                    'title': a.title,
                    'priority': a.priority.value,
                    'config_change': a.config_change,
                    'effort': a.estimated_effort,
                }
                for a in incident.recommended_actions[:5]
            ],
            'timeline': [
                {
                    'time': e.timestamp.isoformat(),
                    'event': e.description,
                    'is_trigger': e.is_trigger,
                }
                for e in incident.timeline[:10]
            ],
        }
    
    # =========================================================================
    # SLACK
    # =========================================================================
    
    def to_slack(self, result: IncidentAnalysisResult, channel: str = "#alerts") -> Dict:
        """Export pro Slack webhook"""
        if result.total_incidents == 0:
            return {
                "channel": channel,
                "text": "✅ No incidents detected",
                "blocks": [],
            }
        
        # Determine color
        if result.critical_count > 0:
            color = "#ff0000"
        elif result.high_count > 0:
            color = "#ff9900"
        else:
            color = "#ffcc00"
        
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🔍 {result.total_incidents} Incident(s) Detected",
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Period:* {result.analysis_start.strftime('%H:%M')} - {result.analysis_end.strftime('%H:%M')}\n"
                           f"*Critical:* {result.critical_count} | *High:* {result.high_count} | *Medium:* {result.medium_count}",
                }
            },
        ]
        
        # Top incidents
        for incident in result.incidents[:3]:
            sev_icon = self.SEVERITY_ICONS.get(incident.severity, '⚪')
            
            text = f"{sev_icon} *{incident.title}*\n"
            if incident.causal_chain:
                text += f"Cause: {incident.causal_chain.root_cause_description}\n"
            text += f"Apps: {', '.join(incident.scope.apps[:3])}"
            
            if incident.recommended_actions:
                top_action = incident.recommended_actions[0]
                text += f"\n→ {top_action.title}"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": text,
                }
            })
        
        return {
            "channel": channel,
            "text": f"{result.total_incidents} incident(s) detected",
            "blocks": blocks,
            "attachments": [{"color": color}],
        }
    
    def to_slack_json(self, result: IncidentAnalysisResult, channel: str = "#alerts") -> str:
        """Slack jako JSON string"""
        return json.dumps(self.to_slack(result, channel), indent=2)
    
    # =========================================================================
    # SAVE
    # =========================================================================
    
    def save_all(self, result: IncidentAnalysisResult, output_dir: str, mode: str = "15min") -> Dict[str, str]:
        """Uloží všechny formáty"""
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        files = {}
        
        # Console/Text
        txt_path = path / f"incidents_{mode}_{timestamp}.txt"
        with open(txt_path, 'w') as f:
            if mode == "15min":
                f.write(self.format_15min(result))
            else:
                f.write(self.format_daily(result))
        files['text'] = str(txt_path)
        
        # Markdown
        md_path = path / f"incidents_{mode}_{timestamp}.md"
        with open(md_path, 'w') as f:
            f.write(self.to_markdown(result))
        files['markdown'] = str(md_path)
        
        # JSON
        json_path = path / f"incidents_{mode}_{timestamp}.json"
        with open(json_path, 'w') as f:
            f.write(self.to_json(result))
        files['json'] = str(json_path)
        
        # Slack
        slack_path = path / f"slack_{mode}_{timestamp}.json"
        with open(slack_path, 'w') as f:
            f.write(self.to_slack_json(result))
        files['slack'] = str(slack_path)
        
        return files
