#!/usr/bin/env python3
"""
FIX RECOMMENDER
===============

Statické, ale účinné doporučení fixů.

Mapované podle category + pattern:
- DATABASE connection pool → Increase pool size, Check max connections
- TIMEOUT read → Increase timeout, Add circuit breaker
- NETWORK refused → Check service health, Verify firewall

Bez AI, ale:
- Je to akční
- Je to správné
- Je to okamžitě použitelné
"""

from typing import List, Dict, Optional
from datetime import datetime

try:
    from .models import (
        RecommendedAction, ActionPriority, ConfidenceLevel,
        CausalChain, IncidentScope, IncidentTrigger,
        ROOT_CAUSE_RULES, get_root_cause_rule, match_evidence,
    )
except ImportError:
    from models import (
        RecommendedAction, ActionPriority, ConfidenceLevel,
        CausalChain, IncidentScope, IncidentTrigger,
        ROOT_CAUSE_RULES, get_root_cause_rule, match_evidence,
    )


class FixRecommender:
    """Generátor doporučených akcí"""
    
    def __init__(self):
        pass
    
    def recommend_fixes(
        self,
        trigger: IncidentTrigger,
        causal_chain: CausalChain,
        scope: IncidentScope,
        category: str,
        subcategory: str,
        message: str = ""
    ) -> List[RecommendedAction]:
        """
        Generuje doporučené akce pro incident.
        
        Args:
            trigger: Trigger incidentu
            causal_chain: Kauzální řetězec
            scope: Rozsah incidentu
            category: Kategorie erroru
            subcategory: Subkategorie
            message: Error message
        
        Returns:
            Seznam RecommendedAction seřazený podle priority
        """
        actions = []
        
        # 1. Akce z pravidel podle kategorie
        rule_actions = self._get_rule_based_actions(category, subcategory, trigger.app)
        actions.extend(rule_actions)
        
        # 2. Akce podle scope (blast radius)
        scope_actions = self._get_scope_based_actions(scope, category)
        actions.extend(scope_actions)
        
        # 3. Akce podle causal chain
        chain_actions = self._get_chain_based_actions(causal_chain)
        actions.extend(chain_actions)
        
        # 4. Message-specific akce
        message_actions = self._get_message_based_actions(message, trigger.app)
        actions.extend(message_actions)
        
        # Deduplikovat a seřadit
        actions = self._deduplicate_actions(actions)
        actions = self._sort_by_priority(actions)
        
        return actions[:10]  # Max 10 akcí
    
    def _get_rule_based_actions(
        self,
        category: str,
        subcategory: str,
        target_app: str
    ) -> List[RecommendedAction]:
        """Akce z pravidel"""
        actions = []
        
        rule = get_root_cause_rule(category, subcategory)
        if not rule:
            # Fallback akce
            return [
                RecommendedAction(
                    title=f"Investigate {category}/{subcategory} issue",
                    description="Review logs and investigate root cause",
                    priority=ActionPriority.TODAY,
                    target_app=target_app,
                    category=category,
                    steps=["Check application logs", "Review metrics", "Identify pattern"],
                    estimated_effort="30 min",
                    confidence=ConfidenceLevel.LOW,
                )
            ]
        
        for action_def in rule.get('actions', []):
            action = RecommendedAction(
                title=action_def.get('title', ''),
                description=action_def.get('title', ''),  # Same as title for now
                priority=action_def.get('priority', ActionPriority.TODAY),
                target_app=target_app,
                category=category,
                steps=action_def.get('steps', []),
                config_change=action_def.get('config_change', ''),
                code_change=action_def.get('code_change', ''),
                estimated_effort=action_def.get('estimated_effort', ''),
                confidence=ConfidenceLevel.HIGH if action_def.get('priority') == ActionPriority.IMMEDIATE else ConfidenceLevel.MEDIUM,
            )
            actions.append(action)
        
        return actions
    
    def _get_scope_based_actions(
        self,
        scope: IncidentScope,
        category: str
    ) -> List[RecommendedAction]:
        """Akce podle scope"""
        actions = []
        
        # Velký blast radius
        if scope.blast_radius >= 5:
            actions.append(RecommendedAction(
                title="Consider emergency rollback",
                description=f"Incident affects {scope.blast_radius} applications",
                priority=ActionPriority.IMMEDIATE,
                category="operations",
                steps=[
                    "Identify last known good version",
                    "Prepare rollback plan",
                    "Coordinate with affected teams",
                ],
                estimated_effort="15 min",
                confidence=ConfidenceLevel.HIGH,
            ))
        
        # Cross-namespace
        if len(scope.namespaces) >= 3:
            actions.append(RecommendedAction(
                title="Check shared infrastructure",
                description=f"Issue spans {len(scope.namespaces)} namespaces",
                priority=ActionPriority.IMMEDIATE,
                category="infrastructure",
                steps=[
                    "Check shared database health",
                    "Verify network connectivity",
                    "Review service mesh status",
                ],
                estimated_effort="15 min",
                confidence=ConfidenceLevel.MEDIUM,
            ))
        
        # Multiple versions affected
        for app, versions in scope.app_versions.items():
            if len(versions) >= 2:
                actions.append(RecommendedAction(
                    title=f"Compare {app} versions",
                    description=f"Multiple versions affected: {', '.join(versions[:3])}",
                    priority=ActionPriority.TODAY,
                    target_app=app,
                    category="deployment",
                    steps=[
                        "Check if issue exists in all versions",
                        "Identify version-specific behavior",
                        "Consider targeted rollback",
                    ],
                    estimated_effort="30 min",
                    confidence=ConfidenceLevel.MEDIUM,
                ))
        
        return actions
    
    def _get_chain_based_actions(
        self,
        chain: CausalChain
    ) -> List[RecommendedAction]:
        """Akce podle causal chain"""
        actions = []
        
        # Pokud je jasný root cause v jedné app
        if chain.confidence == ConfidenceLevel.HIGH:
            actions.append(RecommendedAction(
                title=f"Focus on {chain.root_cause_app}",
                description=f"High confidence root cause: {chain.root_cause_description}",
                priority=ActionPriority.IMMEDIATE,
                target_app=chain.root_cause_app,
                category=chain.root_cause_type,
                steps=[
                    f"Fix {chain.root_cause_type} issue in {chain.root_cause_app}",
                    "Downstream services should recover automatically",
                ],
                estimated_effort="varies",
                confidence=ConfidenceLevel.HIGH,
            ))
        
        # Pokud je kaskáda
        if len(chain.effects) >= 3:
            actions.append(RecommendedAction(
                title="Monitor cascade recovery",
                description="Multiple services affected, monitor recovery order",
                priority=ActionPriority.TODAY,
                category="monitoring",
                steps=[
                    "Set up alerts for affected services",
                    "Monitor recovery in reverse cascade order",
                    "Document incident timeline",
                ],
                estimated_effort="15 min",
                confidence=ConfidenceLevel.MEDIUM,
            ))
        
        return actions
    
    def _get_message_based_actions(
        self,
        message: str,
        target_app: str
    ) -> List[RecommendedAction]:
        """Akce na základě error message"""
        actions = []
        message_lower = message.lower()
        
        # HikariPool specifická akce
        if 'hikaripool' in message_lower or 'connection pool' in message_lower:
            if 'not available' in message_lower:
                actions.append(RecommendedAction(
                    title="Immediate: Increase HikariCP pool",
                    description="Connection pool exhausted",
                    priority=ActionPriority.IMMEDIATE,
                    target_app=target_app,
                    target_config="spring.datasource.hikari.maximum-pool-size",
                    category="database",
                    config_change="spring.datasource.hikari.maximum-pool-size: 25",
                    steps=[
                        "Update Helm values or ConfigMap",
                        "Apply change (no restart needed for some configs)",
                        "Monitor pool metrics",
                    ],
                    estimated_effort="5 min",
                    confidence=ConfidenceLevel.HIGH,
                ))
        
        # Circuit breaker already open
        if 'circuit' in message_lower and 'open' in message_lower:
            actions.append(RecommendedAction(
                title="Check circuit breaker target",
                description="Circuit breaker is open - target service may be unhealthy",
                priority=ActionPriority.IMMEDIATE,
                target_app=target_app,
                category="resilience",
                steps=[
                    "Identify which service triggered circuit breaker",
                    "Check target service health",
                    "Circuit breaker will auto-recover when target is healthy",
                ],
                estimated_effort="15 min",
                confidence=ConfidenceLevel.HIGH,
            ))
        
        # SSL/TLS issues
        if 'ssl' in message_lower or 'certificate' in message_lower:
            actions.append(RecommendedAction(
                title="Check certificate expiry",
                description="SSL/TLS related error",
                priority=ActionPriority.IMMEDIATE,
                target_app=target_app,
                category="security",
                steps=[
                    "Check certificate expiration date",
                    "Verify certificate chain",
                    "Renew certificate if needed",
                ],
                estimated_effort="30 min",
                confidence=ConfidenceLevel.HIGH,
            ))
        
        # Kafka issues
        if 'kafka' in message_lower:
            if 'rebalance' in message_lower:
                actions.append(RecommendedAction(
                    title="Monitor Kafka consumer group",
                    description="Kafka consumer rebalance in progress",
                    priority=ActionPriority.TODAY,
                    target_app=target_app,
                    category="messaging",
                    steps=[
                        "Check consumer group status",
                        "Verify partition assignment",
                        "Monitor lag during rebalance",
                    ],
                    estimated_effort="15 min",
                    confidence=ConfidenceLevel.MEDIUM,
                ))
        
        # Memory related
        if 'outofmemory' in message_lower or 'heap' in message_lower:
            actions.append(RecommendedAction(
                title="Increase JVM heap size",
                description="Out of memory error",
                priority=ActionPriority.IMMEDIATE,
                target_app=target_app,
                target_config="JAVA_OPTS",
                category="memory",
                config_change="-Xmx4g -Xms2g",
                steps=[
                    "Increase heap in deployment",
                    "Restart pods",
                    "Consider heap dump analysis if recurring",
                ],
                estimated_effort="10 min",
                confidence=ConfidenceLevel.HIGH,
            ))
        
        return actions
    
    def _deduplicate_actions(self, actions: List[RecommendedAction]) -> List[RecommendedAction]:
        """Odstraní duplicitní akce"""
        seen_titles = set()
        unique = []
        
        for action in actions:
            # Normalize title for comparison
            normalized = action.title.lower().strip()
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique.append(action)
        
        return unique
    
    def _sort_by_priority(self, actions: List[RecommendedAction]) -> List[RecommendedAction]:
        """Seřadí akce podle priority"""
        priority_order = {
            ActionPriority.IMMEDIATE: 0,
            ActionPriority.TODAY: 1,
            ActionPriority.THIS_WEEK: 2,
            ActionPriority.BACKLOG: 3,
        }
        
        return sorted(actions, key=lambda a: (
            priority_order.get(a.priority, 99),
            0 if a.confidence == ConfidenceLevel.HIGH else 1,
        ))
    
    def get_immediate_actions(
        self,
        actions: List[RecommendedAction]
    ) -> List[RecommendedAction]:
        """Vrátí pouze IMMEDIATE akce"""
        return [a for a in actions if a.priority == ActionPriority.IMMEDIATE]
    
    def format_actions_text(self, actions: List[RecommendedAction]) -> str:
        """Formátuje akce jako text"""
        if not actions:
            return "No recommended actions"
        
        lines = []
        for action in actions:
            priority_icon = {
                ActionPriority.IMMEDIATE: "🚨",
                ActionPriority.TODAY: "📌",
                ActionPriority.THIS_WEEK: "📋",
                ActionPriority.BACKLOG: "📝",
            }.get(action.priority, "•")
            
            lines.append(f"{priority_icon} [{action.priority.value}] {action.title}")
            
            if action.target_app:
                lines.append(f"   App: {action.target_app}")
            
            if action.config_change:
                lines.append(f"   Config: {action.config_change}")
            
            if action.steps:
                for step in action.steps[:3]:
                    lines.append(f"   - {step}")
            
            if action.estimated_effort:
                lines.append(f"   Effort: {action.estimated_effort}")
            
            lines.append("")
        
        return "\n".join(lines)
