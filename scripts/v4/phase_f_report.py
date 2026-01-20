#!/usr/bin/env python3
"""
FÁZE F: Report
==============

Vstup: Incident objects (kompletní)
Výstup: JSON (primární), MD/text (sekundární)

✅ Pouze renderování
✅ Žádné počítání
✅ Žádná logika

MD report jen renderuje evidence, nic nepočítá.
"""

import json
from typing import Dict, List, Any
from datetime import datetime
from pathlib import Path

# Import from same package
try:
    from .incident import Incident, IncidentCollection, IncidentSeverity, IncidentCategory
except ImportError:
    from incident import Incident, IncidentCollection, IncidentSeverity, IncidentCategory


class PhaseF_Report:
    """
    FÁZE F: Report
    
    Renderuje incidenty do různých formátů.
    NEMĚŘÍ, NEPOČÍTÁ, jen formátuje.
    """
    
    def __init__(self):
        pass
    
    # =========================================================================
    # JSON OUTPUT (PRIMARY)
    # =========================================================================
    
    def to_json(
        self,
        collection: IncidentCollection,
        indent: int = 2,
    ) -> str:
        """
        Renderuje kolekci do JSON.
        
        JSON je primární výstup - kompletní data.
        """
        return collection.to_json(indent=indent)
    
    def save_json(
        self,
        collection: IncidentCollection,
        filepath: str,
    ):
        """Uloží JSON do souboru"""
        with open(filepath, 'w') as f:
            f.write(self.to_json(collection))
    
    # =========================================================================
    # CONSOLE OUTPUT
    # =========================================================================
    
    def to_console(
        self,
        collection: IncidentCollection,
    ) -> str:
        """
        Renderuje kolekci pro konzoli.
        
        Stručný přehled s emoji.
        """
        lines = []
        
        # Header
        lines.append("=" * 80)
        lines.append("🔍 INCIDENT REPORT")
        lines.append("=" * 80)
        lines.append("")
        
        # Summary
        lines.append(f"📊 SUMMARY")
        lines.append(f"   Run ID: {collection.run_id}")
        lines.append(f"   Timestamp: {collection.run_timestamp.isoformat()}")
        lines.append(f"   Input records: {collection.input_records:,}")
        lines.append(f"   Total incidents: {collection.total_incidents}")
        lines.append("")
        
        # By severity
        lines.append(f"📈 BY SEVERITY")
        severity_icons = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢",
            "info": "⚪",
        }
        for sev, count in sorted(collection.by_severity.items(), 
                                  key=lambda x: ["critical", "high", "medium", "low", "info"].index(x[0])):
            icon = severity_icons.get(sev, "⚪")
            lines.append(f"   {icon} {sev}: {count}")
        lines.append("")
        
        # By category
        lines.append(f"📁 BY CATEGORY")
        for cat, count in sorted(collection.by_category.items(), key=lambda x: -x[1]):
            lines.append(f"   {cat}: {count}")
        lines.append("")
        
        # Top incidents
        lines.append("=" * 80)
        lines.append("🎯 TOP INCIDENTS")
        lines.append("=" * 80)
        
        # Sort by score
        sorted_incidents = sorted(collection.incidents, key=lambda x: x.score, reverse=True)
        
        for i, inc in enumerate(sorted_incidents[:10], 1):
            icon = severity_icons.get(inc.severity.value, "⚪")
            lines.append("")
            lines.append(f"{i}. {icon} [{inc.severity.value.upper()}] Score: {inc.score:.0f}")
            lines.append(f"   ID: {inc.id}")
            lines.append(f"   Category: {inc.category.value}/{inc.subcategory}")
            lines.append(f"   Error: {inc.error_type}")
            lines.append(f"   Message: {inc.normalized_message[:60]}...")
            lines.append(f"   Apps: {', '.join(inc.apps[:3])}")
            lines.append(f"   Namespaces: {', '.join(inc.namespaces[:3])} ({len(inc.namespaces)} total)")
            
            # Flags
            active_flags = []
            if inc.flags.is_new:
                active_flags.append("NEW")
            if inc.flags.is_spike:
                active_flags.append("SPIKE")
            if inc.flags.is_burst:
                active_flags.append("BURST")
            if inc.flags.is_regression:
                active_flags.append("REGRESSION")
            if inc.flags.is_cross_namespace:
                active_flags.append("CROSS-NS")
            
            if active_flags:
                lines.append(f"   Flags: {', '.join(active_flags)}")
            
            # Evidence (zkráceně)
            if inc.evidence:
                lines.append(f"   Evidence:")
                for ev in inc.evidence[:2]:
                    lines.append(f"      [{ev.rule}] {ev.message[:50]}")
        
        lines.append("")
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def print_console(self, collection: IncidentCollection):
        """Tiskne na konzoli"""
        print(self.to_console(collection))
    
    # =========================================================================
    # MARKDOWN OUTPUT
    # =========================================================================
    
    def to_markdown(
        self,
        collection: IncidentCollection,
    ) -> str:
        """
        Renderuje kolekci do Markdown.
        
        MD jen renderuje data - nic nepočítá!
        """
        lines = []
        
        # Title
        lines.append("# Incident Report")
        lines.append("")
        lines.append(f"**Generated:** {collection.run_timestamp.isoformat()}")
        lines.append(f"**Pipeline Version:** {collection.pipeline_version}")
        lines.append(f"**Run ID:** {collection.run_id}")
        lines.append("")
        
        # Summary table
        lines.append("## Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Input Records | {collection.input_records:,} |")
        lines.append(f"| Total Incidents | {collection.total_incidents} |")
        lines.append(f"| Critical | {collection.by_severity.get('critical', 0)} |")
        lines.append(f"| High | {collection.by_severity.get('high', 0)} |")
        lines.append(f"| Medium | {collection.by_severity.get('medium', 0)} |")
        lines.append(f"| Low | {collection.by_severity.get('low', 0)} |")
        lines.append("")
        
        # By category
        lines.append("## By Category")
        lines.append("")
        lines.append("| Category | Count |")
        lines.append("|----------|-------|")
        for cat, count in sorted(collection.by_category.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {count} |")
        lines.append("")
        
        # Incidents
        lines.append("## Incidents")
        lines.append("")
        
        # Sort by score
        sorted_incidents = sorted(collection.incidents, key=lambda x: x.score, reverse=True)
        
        for inc in sorted_incidents[:20]:
            severity_badge = {
                "critical": "🔴 CRITICAL",
                "high": "🟠 HIGH",
                "medium": "🟡 MEDIUM",
                "low": "🟢 LOW",
                "info": "⚪ INFO",
            }.get(inc.severity.value, inc.severity.value)
            
            lines.append(f"### {inc.id}")
            lines.append("")
            lines.append(f"**Severity:** {severity_badge} (Score: {inc.score:.0f})")
            lines.append("")
            lines.append(f"**Category:** {inc.category.value}/{inc.subcategory}")
            lines.append("")
            lines.append(f"**Error Type:** `{inc.error_type}`")
            lines.append("")
            lines.append(f"**Message:**")
            lines.append(f"```")
            lines.append(inc.normalized_message)
            lines.append(f"```")
            lines.append("")
            
            # Stats
            lines.append("**Stats:**")
            lines.append(f"- Current rate: {inc.stats.current_rate}")
            lines.append(f"- Baseline (EWMA): {inc.stats.baseline_rate:.2f}")
            lines.append(f"- Trend: {inc.stats.trend_direction} ({inc.stats.trend_ratio:.2f}x)")
            lines.append("")
            
            # Affected
            lines.append("**Affected:**")
            lines.append(f"- Apps: {', '.join(inc.apps[:5])}")
            lines.append(f"- Namespaces: {', '.join(inc.namespaces[:5])} ({len(inc.namespaces)} total)")
            lines.append("")
            
            # Flags
            active_flags = []
            if inc.flags.is_new:
                active_flags.append("🆕 NEW")
            if inc.flags.is_spike:
                active_flags.append("📈 SPIKE")
            if inc.flags.is_burst:
                active_flags.append("💥 BURST")
            if inc.flags.is_regression:
                active_flags.append("🔄 REGRESSION")
            if inc.flags.is_cascade:
                active_flags.append("🔗 CASCADE")
            if inc.flags.is_cross_namespace:
                active_flags.append("🌐 CROSS-NS")
            
            if active_flags:
                lines.append(f"**Flags:** {' '.join(active_flags)}")
                lines.append("")
            
            # Evidence
            if inc.evidence:
                lines.append("**Evidence:**")
                for ev in inc.evidence:
                    lines.append(f"- `{ev.rule}`: {ev.message}")
                lines.append("")
            
            # Score breakdown
            lines.append("**Score Breakdown:**")
            lines.append(f"- Base: {inc.score_breakdown.base_score:.1f}")
            if inc.score_breakdown.spike_bonus:
                lines.append(f"- Spike: +{inc.score_breakdown.spike_bonus:.1f}")
            if inc.score_breakdown.new_bonus:
                lines.append(f"- New: +{inc.score_breakdown.new_bonus:.1f}")
            if inc.score_breakdown.regression_bonus:
                lines.append(f"- Regression: +{inc.score_breakdown.regression_bonus:.1f}")
            if inc.score_breakdown.cross_ns_bonus:
                lines.append(f"- Cross-NS: +{inc.score_breakdown.cross_ns_bonus:.1f}")
            lines.append("")
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)
    
    def save_markdown(
        self,
        collection: IncidentCollection,
        filepath: str,
    ):
        """Uloží Markdown do souboru"""
        with open(filepath, 'w') as f:
            f.write(self.to_markdown(collection))
    
    # =========================================================================
    # SNAPSHOT (for replay)
    # =========================================================================
    
    def save_snapshot(
        self,
        collection: IncidentCollection,
        output_dir: str,
    ) -> Dict[str, str]:
        """
        Uloží kompletní snapshot pro replay.
        
        Vytváří:
        - incidents.json (hlavní data)
        - report.md (lidsky čitelný)
        - summary.json (pro porovnání)
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = collection.run_timestamp.strftime("%Y%m%d_%H%M%S")
        
        files = {}
        
        # Main JSON
        json_path = output_path / f"incidents_{timestamp}.json"
        self.save_json(collection, str(json_path))
        files['json'] = str(json_path)
        
        # Markdown
        md_path = output_path / f"report_{timestamp}.md"
        self.save_markdown(collection, str(md_path))
        files['markdown'] = str(md_path)
        
        # Summary (for quick comparison)
        summary = {
            "run_id": collection.run_id,
            "timestamp": collection.run_timestamp.isoformat(),
            "total_incidents": collection.total_incidents,
            "by_severity": collection.by_severity,
            "by_category": collection.by_category,
            "top_scores": [
                {"id": inc.id, "score": inc.score, "severity": inc.severity.value}
                for inc in sorted(collection.incidents, key=lambda x: x.score, reverse=True)[:10]
            ]
        }
        summary_path = output_path / f"summary_{timestamp}.json"
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        files['summary'] = str(summary_path)
        
        return files


# ============================================================================
# CLI
# ============================================================================

if __name__ == "__main__":
    from incident import Incident, IncidentCollection, Flags, Stats, TimeInfo, ScoreBreakdown, Evidence
    from datetime import datetime
    
    # Create test collection
    collection = IncidentCollection(
        run_id="test-001",
        run_timestamp=datetime.utcnow(),
        input_file="test.json",
        input_records=1000,
    )
    
    # Add test incidents
    inc1 = Incident(
        id="inc-20260120-001",
        fingerprint="abc123",
        normalized_message="Connection to <IP>:<PORT> refused",
        error_type="ConnectionError",
        apps=["bl-pcb-v1"],
        namespaces=["pcb-sit-01-app", "pcb-dev-01-app"],
    )
    inc1.stats.current_rate = 50
    inc1.stats.baseline_rate = 10
    inc1.stats.trend_ratio = 5.0
    inc1.stats.trend_direction = "increasing"
    inc1.flags.is_spike = True
    inc1.flags.is_cross_namespace = True
    inc1.evidence.append(Evidence(rule="spike_ewma", baseline=10, current=50, threshold=3.0, message="current > ewma * 3"))
    inc1.score = 75
    inc1.score_breakdown.base_score = 30
    inc1.score_breakdown.spike_bonus = 25
    inc1.score_breakdown.cross_ns_bonus = 20
    inc1.severity = IncidentSeverity.HIGH
    inc1.category = IncidentCategory.NETWORK
    inc1.subcategory = "connection_refused"
    
    collection.add_incident(inc1)
    
    # Report
    reporter = PhaseF_Report()
    
    print("=== FÁZE F: Report ===\n")
    reporter.print_console(collection)
