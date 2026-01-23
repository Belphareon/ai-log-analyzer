#!/usr/bin/env python3
"""
CAUSAL INFERENCE ENGINE
=======================

Pravidlová inference root cause a kauzálního řetězce.

Bez AI, ale s jasnými pravidly:
- Pokud error předchází peak → error je příčina
- Pokud DB error předchází multiple app errors → DB je root
- Pokud gateway peak následuje po backend error → backend je příčina

Výstup:
ROOT CAUSE:
Database connection pool exhaustion in order-service

EFFECT:
- payment-service timeouts
- gateway traffic spike
"""

from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

try:
    from .models import (
        CausalChain, CausalLink, ConfidenceLevel,
        IncidentTrigger, TimelineEvent, TriggerType,
        ROOT_CAUSE_RULES, get_root_cause_rule, match_evidence,
    )
except ImportError:
    from models import (
        CausalChain, CausalLink, ConfidenceLevel,
        IncidentTrigger, TimelineEvent, TriggerType,
        ROOT_CAUSE_RULES, get_root_cause_rule, match_evidence,
    )


class CausalInferenceEngine:
    """Engine pro inference kauzality"""
    
    # Časové prahy
    IMMEDIATE_EFFECT_SEC = 60      # Effect do 60s = silná korelace
    LIKELY_EFFECT_SEC = 300        # Effect do 5 min = pravděpodobná korelace
    POSSIBLE_EFFECT_SEC = 900      # Effect do 15 min = možná korelace
    
    # Kategorie které typicky způsobují kaskády
    CASCADE_CATEGORIES = ['database', 'network', 'external', 'auth']
    
    def __init__(self):
        pass
    
    def infer_causal_chain(
        self,
        trigger: IncidentTrigger,
        timeline: List[TimelineEvent],
        category: str,
        subcategory: str,
        message: str = ""
    ) -> CausalChain:
        """
        Inferuje kauzální řetězec z triggeru a timeline.
        
        Args:
            trigger: Trigger incidentu
            timeline: Timeline událostí
            category: Kategorie erroru (database, network, ...)
            subcategory: Subkategorie (connection_pool, timeout, ...)
            message: Error message pro evidence matching
        
        Returns:
            CausalChain s root cause a effects
        """
        # Najít pravidlo pro kategorii
        rule = get_root_cause_rule(category, subcategory)
        
        # Základní root cause description
        if rule:
            root_description = rule.get('description', f'{category}/{subcategory} issue')
            evidence_patterns = rule.get('evidence', [])
        else:
            root_description = self._infer_description_from_message(category, subcategory, message)
            evidence_patterns = []
        
        # Najít evidence
        evidence = []
        if evidence_patterns and message:
            matched = match_evidence(message, evidence_patterns)
            evidence.extend([f"Found '{p}' in error message" for p in matched])
        
        # Vytvořit chain
        chain = CausalChain(
            root_cause_fingerprint=trigger.fingerprint,
            root_cause_app=trigger.app,
            root_cause_type=category,
            root_cause_description=root_description,
            evidence=evidence,
        )
        
        # Najít effects v timeline
        chain.links = self._find_causal_links(trigger, timeline)
        chain.effects = self._summarize_effects(chain.links, timeline)
        
        # Určit confidence
        chain.confidence = self._calculate_confidence(trigger, chain.links, evidence)
        
        return chain
    
    def _infer_description_from_message(
        self,
        category: str,
        subcategory: str,
        message: str
    ) -> str:
        """Inferuje popis z message, pokud není pravidlo"""
        message_lower = message.lower()
        
        # Database
        if category == 'database':
            if 'pool' in message_lower or 'hikari' in message_lower:
                return "Database connection pool exhausted"
            if 'deadlock' in message_lower:
                return "Database deadlock detected"
            if 'constraint' in message_lower or 'duplicate' in message_lower:
                return "Database constraint violation"
            return "Database error"
        
        # Network
        if category == 'network':
            if 'refused' in message_lower:
                return "Connection refused - target service may be down"
            if 'reset' in message_lower:
                return "Connection reset by peer"
            return "Network connectivity issue"
        
        # Timeout
        if category == 'timeout':
            if 'read' in message_lower:
                return "Read timeout - downstream service slow"
            if 'connect' in message_lower:
                return "Connection timeout - cannot reach target"
            return "Request timeout"
        
        # External
        if category == 'external':
            if '429' in message_lower or 'rate' in message_lower:
                return "External API rate limit exceeded"
            if '503' in message_lower or 'unavailable' in message_lower:
                return "External service unavailable"
            return "External service issue"
        
        # Memory
        if category == 'memory':
            return "Out of memory - heap exhausted"
        
        # Business
        if category == 'business':
            if 'not found' in message_lower or 'does not exist' in message_lower:
                return "Referenced entity not found"
            if 'validation' in message_lower:
                return "Input validation failure"
            return "Business logic error"
        
        return f"Unknown issue in {category}/{subcategory}"
    
    def _find_causal_links(
        self,
        trigger: IncidentTrigger,
        timeline: List[TimelineEvent]
    ) -> List[CausalLink]:
        """Najde kauzální linky z triggeru na effects"""
        links = []
        trigger_time = trigger.timestamp
        
        for event in timeline:
            # Přeskočit trigger samotný
            if event.fingerprint == trigger.fingerprint and event.timestamp == trigger_time:
                continue
            
            # Pouze události po triggeru
            if event.timestamp <= trigger_time:
                continue
            
            time_delta = int((event.timestamp - trigger_time).total_seconds())
            
            # Určit confidence podle času
            if time_delta <= self.IMMEDIATE_EFFECT_SEC:
                confidence = ConfidenceLevel.HIGH
            elif time_delta <= self.LIKELY_EFFECT_SEC:
                confidence = ConfidenceLevel.MEDIUM
            elif time_delta <= self.POSSIBLE_EFFECT_SEC:
                confidence = ConfidenceLevel.LOW
            else:
                continue  # Příliš daleko
            
            # Různá app = pravděpodobnější effect
            if event.app != trigger.app:
                # Zvýšit confidence pro downstream app
                if self._is_likely_downstream(trigger.app, event.app):
                    if confidence == ConfidenceLevel.MEDIUM:
                        confidence = ConfidenceLevel.HIGH
            
            link = CausalLink(
                cause_fingerprint=trigger.fingerprint,
                effect_fingerprint=event.fingerprint,
                cause_app=trigger.app,
                effect_app=event.app,
                cause_type=trigger.trigger_type.value,
                effect_type=event.event_type,
                time_delta_sec=time_delta,
                confidence=confidence,
            )
            links.append(link)
        
        return links
    
    def _is_likely_downstream(self, cause_app: str, effect_app: str) -> bool:
        """Heuristika pro downstream app detection"""
        # Gateway/proxy typicky downstream
        if 'gateway' in effect_app.lower() or 'proxy' in effect_app.lower():
            return True
        
        # BFF typicky downstream
        if 'bff' in effect_app.lower():
            return True
        
        # Notification typicky downstream
        if 'notification' in effect_app.lower():
            return True
        
        return False
    
    def _summarize_effects(
        self,
        links: List[CausalLink],
        timeline: List[TimelineEvent]
    ) -> List[str]:
        """Shrne effects do human-readable seznamu"""
        effects = []
        seen_apps = set()
        
        for link in links:
            if link.effect_app not in seen_apps:
                effect_type = link.effect_type
                
                if effect_type == 'error':
                    effects.append(f"{link.effect_app} errors")
                elif effect_type == 'spike':
                    effects.append(f"{link.effect_app} traffic spike")
                elif effect_type == 'timeout':
                    effects.append(f"{link.effect_app} timeouts")
                elif effect_type == 'peak':
                    effects.append(f"{link.effect_app} load peak")
                else:
                    effects.append(f"{link.effect_app} affected")
                
                seen_apps.add(link.effect_app)
        
        return effects
    
    def _calculate_confidence(
        self,
        trigger: IncidentTrigger,
        links: List[CausalLink],
        evidence: List[str]
    ) -> ConfidenceLevel:
        """Spočítá celkovou confidence"""
        score = 0
        
        # Evidence z pravidel
        score += len(evidence) * 20
        
        # Typ triggeru
        if trigger.trigger_type == TriggerType.SPIKE:
            score += 30  # Spike je jasný indikátor
        elif trigger.trigger_type == TriggerType.BURST:
            score += 25
        elif trigger.trigger_type == TriggerType.NEW_ERROR:
            score += 20
        elif trigger.trigger_type == TriggerType.CROSS_NAMESPACE:
            score += 35  # Cross-namespace je velmi jasný
        
        # Počet high-confidence links
        high_conf_links = sum(1 for l in links if l.confidence == ConfidenceLevel.HIGH)
        score += high_conf_links * 15
        
        # Multiple affected apps
        affected_apps = len(set(l.effect_app for l in links))
        if affected_apps >= 3:
            score += 20
        elif affected_apps >= 2:
            score += 10
        
        # Map score to confidence
        if score >= 80:
            return ConfidenceLevel.HIGH
        elif score >= 50:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW
    
    def infer_cascade_pattern(
        self,
        timeline: List[TimelineEvent]
    ) -> Optional[str]:
        """Detekuje pattern kaskády"""
        if len(timeline) < 3:
            return None
        
        # Seřadit podle času
        sorted_events = sorted(timeline, key=lambda e: e.timestamp)
        
        # Hledat patterny
        apps_order = []
        for event in sorted_events:
            if event.app not in apps_order:
                apps_order.append(event.app)
        
        if len(apps_order) >= 3:
            return f"Cascade: {' → '.join(apps_order[:5])}"
        
        return None
    
    def detect_common_patterns(
        self,
        trigger: IncidentTrigger,
        timeline: List[TimelineEvent]
    ) -> List[str]:
        """Detekuje běžné patterny"""
        patterns = []
        
        # Database cascade
        if trigger.trigger_type in (TriggerType.SPIKE, TriggerType.BURST):
            trigger_msg = trigger.message.lower()
            if any(kw in trigger_msg for kw in ['database', 'sql', 'jdbc', 'hikari', 'pool']):
                downstream_count = sum(1 for e in timeline if e.app != trigger.app)
                if downstream_count >= 2:
                    patterns.append("Database issue causing downstream cascading failures")
        
        # Timeout cascade
        timeout_count = sum(1 for e in timeline if 'timeout' in e.event_type or 'timeout' in e.description.lower())
        if timeout_count >= 3:
            patterns.append("Timeout cascade - multiple services affected")
        
        # Gateway amplification
        gateway_events = [e for e in timeline if 'gateway' in e.app.lower()]
        if gateway_events and len(timeline) > len(gateway_events):
            patterns.append("Backend issue amplified through gateway")
        
        return patterns


def format_causal_chain_text(chain: CausalChain) -> str:
    """Formátuje causal chain jako text"""
    lines = []
    
    lines.append("ROOT CAUSE:")
    lines.append(f"  {chain.root_cause_description}")
    lines.append(f"  App: {chain.root_cause_app}")
    lines.append(f"  Type: {chain.root_cause_type}")
    lines.append(f"  Confidence: {chain.confidence.value}")
    
    if chain.evidence:
        lines.append("")
        lines.append("EVIDENCE:")
        for e in chain.evidence:
            lines.append(f"  - {e}")
    
    if chain.effects:
        lines.append("")
        lines.append("EFFECTS:")
        for effect in chain.effects:
            lines.append(f"  - {effect}")
    
    return "\n".join(lines)
