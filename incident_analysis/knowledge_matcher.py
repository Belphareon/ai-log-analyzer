#!/usr/bin/env python3
"""
KNOWLEDGE MATCHER
=================

Vrstva mezi ANALYSIS a REPORTING.

DETECTION → ANALYSIS → KNOWLEDGE MATCHING → REPORTING
                              ↑
                        THIS COMPONENT

Pravidla:
- Incident se považuje za "KNOWN" když:
  1. Exact fingerprint match
  2. Fingerprint ∈ cluster (related_fingerprints)
  3. Category + affected_apps match
  4. Pattern match

- Každý incident dostane knowledge field
- KNOWN incidenty mají link na Jiru a workaround
- NEW incidenty jsou flagované pro triage
"""

from typing import List, Optional, Dict
from datetime import datetime, date

try:
    from .knowledge_base import KnowledgeBase, KnowledgeMatch, MatchConfidence
    from .models import IncidentAnalysis, IncidentAnalysisResult
except ImportError:
    from knowledge_base import KnowledgeBase, KnowledgeMatch, MatchConfidence
    from models import IncidentAnalysis, IncidentAnalysisResult


class KnowledgeMatcher:
    """
    Matchuje incidenty proti knowledge base.
    
    Tato komponenta:
    - Nemění logiku analýzy
    - Pouze přidává knowledge context
    - Je oddělená od detection i analysis
    """
    
    def __init__(self, knowledge_base: KnowledgeBase):
        self.kb = knowledge_base
    
    def enrich_incidents(self, result: IncidentAnalysisResult) -> IncidentAnalysisResult:
        """
        Enrichuje všechny incidenty o knowledge matching.
        
        Přidá do každého incidentu:
        - knowledge_status: "KNOWN" nebo "NEW"
        - knowledge_id: KE-xxx nebo KP-xxx
        - knowledge_confidence: EXACT, HIGH, MEDIUM, LOW
        - knowledge_jira: link na Jiru
        - knowledge_workaround: seznam workaroundů
        """
        for incident in result.incidents:
            self._enrich_incident(incident)
        
        return result
    
    def _enrich_incident(self, incident: IncidentAnalysis):
        """Enrichuje jeden incident"""
        # Zkus matchnout podle různých kritérií
        match = self._find_best_match(incident)
        
        # Přidej do incidentu
        incident.knowledge_status = match.status
        incident.knowledge_id = match.known_error_id or match.known_peak_id
        incident.knowledge_confidence = match.confidence
        incident.knowledge_match_reason = match.match_reason
        incident.knowledge_jira = match.jira
        incident.knowledge_workaround = match.workaround
        incident.knowledge_permanent_fix = match.permanent_fix
    
    def _find_best_match(self, incident: IncidentAnalysis) -> KnowledgeMatch:
        """Najde nejlepší match pro incident"""
        # 1. Zkus matchnout podle triggeru
        if incident.trigger:
            match = self.kb.match_incident(
                fingerprint=incident.trigger.fingerprint,
                category=incident.causal_chain.root_cause_type if incident.causal_chain else "",
                affected_apps=incident.scope.apps,
                error_message=incident.trigger.message,
            )
            if match.is_known:
                return match
        
        # 2. Zkus linked errors
        for fp in incident.linked_errors[:5]:
            match = self.kb.match_incident(
                fingerprint=fp,
                category=incident.causal_chain.root_cause_type if incident.causal_chain else "",
                affected_apps=incident.scope.apps,
            )
            if match.is_known:
                return match
        
        # 3. Zkus linked peaks
        for fp in incident.linked_peaks[:5]:
            match = self.kb.match_peak(fp, incident.scope.apps)
            if match.is_known:
                return match
        
        # No match = NEW
        return KnowledgeMatch(status="NEW", confidence=MatchConfidence.NONE)
    
    def get_new_incidents(self, result: IncidentAnalysisResult) -> List[IncidentAnalysis]:
        """Vrátí pouze NEW incidenty"""
        return [i for i in result.incidents 
                if getattr(i, 'knowledge_status', 'NEW') == 'NEW']
    
    def get_known_incidents(self, result: IncidentAnalysisResult) -> List[IncidentAnalysis]:
        """Vrátí pouze KNOWN incidenty"""
        return [i for i in result.incidents 
                if getattr(i, 'knowledge_status', 'NEW') == 'KNOWN']
    
    def get_stats(self, result: IncidentAnalysisResult) -> Dict:
        """Statistiky matchování"""
        new_count = len(self.get_new_incidents(result))
        known_count = len(self.get_known_incidents(result))
        
        # By confidence
        by_confidence = {
            'EXACT': 0,
            'HIGH': 0,
            'MEDIUM': 0,
            'LOW': 0,
        }
        for incident in result.incidents:
            conf = getattr(incident, 'knowledge_confidence', MatchConfidence.NONE)
            if conf and conf != MatchConfidence.NONE:
                by_confidence[conf.value] = by_confidence.get(conf.value, 0) + 1
        
        return {
            'total': result.total_incidents,
            'new': new_count,
            'known': known_count,
            'by_confidence': by_confidence,
        }


class TriageReportGenerator:
    """
    Generuje triage report pro NEW incidenty.
    
    Triage report je určen pro human review a rozhodnutí:
    - Vytvořit nový Known Error?
    - Linkovat na existující issue?
    - False positive - ignorovat?
    """
    
    def __init__(self, matcher: KnowledgeMatcher):
        self.matcher = matcher
    
    def generate_triage_report(self, result: IncidentAnalysisResult) -> str:
        """Generuje triage report"""
        new_incidents = self.matcher.get_new_incidents(result)
        
        if not new_incidents:
            return "✅ No new incidents to triage.\n"
        
        lines = [
            "=" * 70,
            "🆕 NEW INCIDENTS FOR TRIAGE",
            "=" * 70,
            "",
            f"Total: {len(new_incidents)} new incident(s) requiring review",
            "",
        ]
        
        for i, incident in enumerate(new_incidents, 1):
            lines.extend(self._format_triage_item(i, incident))
        
        lines.extend([
            "",
            "=" * 70,
            "TRIAGE ACTIONS:",
            "  1. Review each incident",
            "  2. Decide: Create Known Error / Link existing / Ignore",
            "  3. If creating KE: Use suggested YAML below as starting point",
            "  4. Update knowledge/known_errors.yaml",
            "  5. Update knowledge/known_errors.md (keep 1:1 sync)",
            "=" * 70,
        ])
        
        return "\n".join(lines)
    
    def _format_triage_item(self, index: int, incident: IncidentAnalysis) -> List[str]:
        """Formátuje jeden incident pro triage"""
        lines = [
            "-" * 70,
            f"[{index}] {incident.incident_id} | {incident.severity.value.upper()}",
            "-" * 70,
            "",
        ]
        
        # Root cause
        if incident.causal_chain:
            lines.append(f"Root cause: {incident.causal_chain.root_cause_description}")
        elif incident.trigger:
            lines.append(f"Trigger: {incident.trigger.message[:80]}")
        
        # Apps
        lines.append(f"Apps: {', '.join(incident.scope.apps[:5])}")
        
        # Timing
        if incident.started_at:
            lines.append(f"Started: {incident.started_at.strftime('%Y-%m-%d %H:%M')}")
        
        lines.append(f"Errors: {incident.total_errors:,}")
        
        # Suggested actions
        if incident.recommended_actions:
            lines.append("")
            lines.append("Suggested actions:")
            for action in incident.recommended_actions[:3]:
                lines.append(f"  - {action.title}")
        
        # Decision box
        lines.extend([
            "",
            "DECISION:",
            "  [ ] Create new Known Error (KE-XXX)",
            "  [ ] Link to existing: _____________",
            "  [ ] False positive - ignore",
            "  [ ] Needs more investigation",
            "",
        ])
        
        return lines
    
    def generate_suggested_yaml(self, incident: IncidentAnalysis, next_id: str = "KE-XXX") -> str:
        """
        Generuje YAML návrh pro nový Known Error.
        
        POZOR: Toto je jen NÁVRH pro human review!
        """
        # Fingerprint
        fp = ""
        if incident.trigger:
            fp = incident.trigger.fingerprint.rsplit('-', 1)[0]
        
        # Category
        category = "UNKNOWN"
        if incident.causal_chain:
            category = incident.causal_chain.root_cause_type.upper()
        
        # Description
        description = ""
        if incident.causal_chain:
            description = incident.causal_chain.root_cause_description
        elif incident.title:
            description = incident.title
        
        # Workarounds
        workarounds = []
        for action in incident.recommended_actions[:3]:
            workarounds.append(action.title)
        
        lines = [
            "# === SUGGESTED YAML - REVIEW BEFORE ADDING ===",
            f"# Source: {incident.incident_id}",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"  - id: {next_id}",
            f"    fingerprint: {fp}",
            f"    category: {category}",
            f"    description: >",
            f"      {description}",
            f"    affected_apps:",
        ]
        
        for app in incident.scope.apps[:5]:
            lines.append(f"      - {app}")
        
        lines.extend([
            f"    affected_namespaces:",
        ])
        for ns in incident.scope.namespaces[:3]:
            lines.append(f"      - {ns}")
        
        lines.extend([
            f"    first_seen: {date.today()}",
            f"    jira: ''  # TODO: Create Jira ticket",
            f"    status: OPEN",
            f"    owner: ''  # TODO: Assign owner",
            f"    workaround:",
        ])
        
        if workarounds:
            for w in workarounds:
                lines.append(f"      - {w}")
        else:
            lines.append(f"      - # TODO: Add workaround")
        
        lines.extend([
            f"    permanent_fix:",
            f"      - # TODO: Add permanent fix",
            f"    error_pattern: ''  # Optional: regex for fuzzy matching",
        ])
        
        return "\n".join(lines)


def enrich_with_knowledge(
    result: IncidentAnalysisResult,
    knowledge_dir: str = None
) -> IncidentAnalysisResult:
    """
    Convenience function pro knowledge matching.
    
    Args:
        result: IncidentAnalysisResult z analyzéru
        knowledge_dir: Cesta ke knowledge base
    
    Returns:
        IncidentAnalysisResult s přidaným knowledge contextem
    """
    kb = KnowledgeBase(knowledge_dir)
    if knowledge_dir:
        kb.load()
    
    matcher = KnowledgeMatcher(kb)
    return matcher.enrich_incidents(result)
