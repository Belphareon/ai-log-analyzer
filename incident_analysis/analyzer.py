#!/usr/bin/env python3
"""
INCIDENT ANALYSIS ENGINE
========================

Hlavní engine pro analýzu incidentů.

Tok dat:
IncidentCollection (DETECTION)
       ↓
IncidentAnalysisEngine (ANALYSIS) ← THIS
       ↓
IncidentAnalysis[] (per-problém)
       ↓
ReportFormatter (daily / weekly / 15min)

Engine:
1. Detekuje incidenty z IncidentCollection
2. Pro každý incident staví timeline
3. Inferuje kauzální řetězec
4. Generuje doporučené akce
5. Vrací IncidentAnalysis objekty
"""

from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import hashlib
import time

try:
    from .models import (
        IncidentAnalysis, IncidentAnalysisResult,
        IncidentStatus, SeverityLevel, TriggerType, ConfidenceLevel,
        IncidentTrigger, IncidentScope, TimelineEvent,
        CausalChain, RecommendedAction, ActionPriority,
    )
    from .timeline_builder import TimelineBuilder
    from .causal_inference import CausalInferenceEngine
    from .fix_recommender import FixRecommender
except ImportError:
    from models import (
        IncidentAnalysis, IncidentAnalysisResult,
        IncidentStatus, SeverityLevel, TriggerType, ConfidenceLevel,
        IncidentTrigger, IncidentScope, TimelineEvent,
        CausalChain, RecommendedAction, ActionPriority,
    )
    from timeline_builder import TimelineBuilder
    from causal_inference import CausalInferenceEngine
    from fix_recommender import FixRecommender


class IncidentAnalysisEngine:
    """
    Engine pro analýzu incidentů.
    
    Transformuje raw detekční data na actionable IncidentAnalysis objekty.
    """
    
    # Prahy pro grupování incidentů
    INCIDENT_WINDOW_SEC = 900  # 15 min - události v tomto okně patří k jednomu incidentu
    MIN_EVENTS_FOR_INCIDENT = 2  # Minimálně 2 události pro vytvoření incidentu
    
    def __init__(self):
        self.timeline_builder = TimelineBuilder(window_sec=60)
        self.causal_engine = CausalInferenceEngine()
        self.fix_recommender = FixRecommender()
        self._incident_counter = 0
    
    def analyze(
        self,
        incidents: List['Incident'],
        analysis_start: datetime = None,
        analysis_end: datetime = None,
    ) -> IncidentAnalysisResult:
        """
        Hlavní metoda - analyzuje incidenty z detekce.
        
        Args:
            incidents: Seznam Incident objektů z detekce
            analysis_start: Začátek analyzovaného období
            analysis_end: Konec analyzovaného období
        
        Returns:
            IncidentAnalysisResult s analyzovanými incidenty
        """
        start_time = time.time()
        
        if not incidents:
            return IncidentAnalysisResult(
                analysis_start=analysis_start or datetime.now(timezone.utc),
                analysis_end=analysis_end or datetime.now(timezone.utc),
            )
        
        # 1. Převést na raw události
        raw_events = self._incidents_to_events(incidents)
        
        # 2. Grupovat události do incidentů
        incident_groups = self._group_into_incidents(raw_events)
        
        # 3. Analyzovat každou skupinu
        analyzed = []
        for group in incident_groups:
            analysis = self._analyze_incident_group(group)
            if analysis:
                analyzed.append(analysis)
        
        # 4. Seřadit podle severity a času
        analyzed.sort(key=lambda a: (
            0 if a.severity == SeverityLevel.CRITICAL else
            1 if a.severity == SeverityLevel.HIGH else
            2 if a.severity == SeverityLevel.MEDIUM else 3,
            a.started_at or datetime.max,
        ))
        
        # 5. Statistiky
        result = IncidentAnalysisResult(
            analysis_start=analysis_start or min(e['timestamp'] for e in raw_events) if raw_events else datetime.now(timezone.utc),
            analysis_end=analysis_end or max(e['timestamp'] for e in raw_events) if raw_events else datetime.now(timezone.utc),
            incidents=analyzed,
            total_incidents=len(analyzed),
            active_incidents=sum(1 for a in analyzed if a.status == IncidentStatus.ACTIVE),
            resolved_incidents=sum(1 for a in analyzed if a.status == IncidentStatus.RESOLVED),
            critical_count=sum(1 for a in analyzed if a.severity == SeverityLevel.CRITICAL),
            high_count=sum(1 for a in analyzed if a.severity == SeverityLevel.HIGH),
            medium_count=sum(1 for a in analyzed if a.severity == SeverityLevel.MEDIUM),
            low_count=sum(1 for a in analyzed if a.severity == SeverityLevel.LOW),
            analysis_duration_ms=int((time.time() - start_time) * 1000),
        )
        
        return result
    
    def _incidents_to_events(self, incidents: List['Incident']) -> List[Dict]:
        """Převede Incident objekty na raw události"""
        events = []
        
        for inc in incidents:
            # Určit event_type
            if inc.flags.is_spike:
                event_type = 'spike'
            elif inc.flags.is_burst:
                event_type = 'burst'
            else:
                event_type = 'error'
            
            event = {
                'timestamp': inc.time.first_seen or datetime.now(timezone.utc),
                'app': inc.apps[0] if inc.apps else 'unknown',
                'namespace': inc.namespaces[0] if inc.namespaces else '',
                'version': inc.versions[0] if inc.versions else '',
                'event_type': event_type,
                'fingerprint': inc.fingerprint,
                'error_type': inc.error_type,
                'message': inc.normalized_message,
                'error_count': inc.stats.current_count,
                'ratio': inc.stats.trend_ratio,
                'is_new': inc.flags.is_new,
                'is_spike': inc.flags.is_spike,
                'is_burst': inc.flags.is_burst,
                'is_cross_namespace': inc.flags.is_cross_namespace,
                'category': inc.category.value if hasattr(inc.category, 'value') else str(inc.category),
                'subcategory': inc.subcategory,
                'severity': inc.severity.value if hasattr(inc.severity, 'value') else str(inc.severity),
                'score': inc.score,
                # Reference na originální incident
                '_incident': inc,
            }
            events.append(event)
        
        return events
    
    def _group_into_incidents(self, events: List[Dict]) -> List[List[Dict]]:
        """
        Grupuje události do incidentů.
        
        Pravidla:
        - Události se stejným fingerprint base patří k sobě
        - Události v časovém okně patří k sobě
        - Cross-app události se stejnou kategorií mohou patřit k jednomu incidentu
        """
        if not events:
            return []
        
        # Seřadit podle času
        sorted_events = sorted(events, key=lambda e: e['timestamp'])
        
        # Grupovat
        groups: List[List[Dict]] = []
        used_indices: Set[int] = set()
        
        for i, event in enumerate(sorted_events):
            if i in used_indices:
                continue
            
            # Začít novou skupinu
            group = [event]
            used_indices.add(i)
            
            # Najít související události
            for j, other in enumerate(sorted_events):
                if j in used_indices:
                    continue
                
                if self._events_related(event, other, group):
                    group.append(other)
                    used_indices.add(j)
            
            # Pouze skupiny s dostatkem událostí nebo důležitými událostmi
            if len(group) >= self.MIN_EVENTS_FOR_INCIDENT or self._is_important_event(event):
                groups.append(group)
        
        return groups
    
    def _events_related(self, event1: Dict, event2: Dict, group: List[Dict]) -> bool:
        """Určí, zda jsou události související"""
        # Časové okno
        time_diff = abs((event1['timestamp'] - event2['timestamp']).total_seconds())
        if time_diff > self.INCIDENT_WINDOW_SEC:
            return False
        
        # Stejný fingerprint base (bez date suffixu)
        fp1_base = event1['fingerprint'].rsplit('-', 1)[0]
        fp2_base = event2['fingerprint'].rsplit('-', 1)[0]
        if fp1_base == fp2_base:
            return True
        
        # Stejná app
        if event1['app'] == event2['app']:
            return True
        
        # Stejná kategorie + blízký čas = pravděpodobně souvisí
        if event1['category'] == event2['category'] and time_diff <= 300:
            return True
        
        # Cross-namespace event se váže k ostatním
        if event1.get('is_cross_namespace') or event2.get('is_cross_namespace'):
            if time_diff <= 300:
                return True
        
        return False
    
    def _is_important_event(self, event: Dict) -> bool:
        """Určí, zda je událost důležitá sama o sobě"""
        # Spike/burst jsou důležité
        if event.get('is_spike') or event.get('is_burst'):
            return True
        
        # Cross-namespace je důležitý
        if event.get('is_cross_namespace'):
            return True
        
        # Vysoké severity je důležité
        if event.get('severity') in ('critical', 'high'):
            return True
        
        # Vysoký ratio je důležitý
        if event.get('ratio', 1.0) >= 5.0:
            return True
        
        return False
    
    def _analyze_incident_group(self, events: List[Dict]) -> Optional[IncidentAnalysis]:
        """Analyzuje skupinu událostí jako jeden incident"""
        if not events:
            return None
        
        self._incident_counter += 1
        
        # 1. Detekovat trigger
        trigger = self.timeline_builder.detect_trigger(events)
        
        # 2. Postavit timeline
        timeline = self.timeline_builder.build_timeline(events, trigger)
        
        # 3. Určit scope a propagation
        scope, propagation = self._build_scope(events)
        
        # 4. Určit kategorii
        category = self._determine_category(events)
        subcategory = self._determine_subcategory(events, category)
        
        # 5. Inferovat causal chain
        causal_chain = None
        if trigger:
            message = trigger.message
            causal_chain = self.causal_engine.infer_causal_chain(
                trigger, timeline, category, subcategory, message
            )
        
        # 6. Generovat doporučené akce
        actions = []
        if trigger and causal_chain:
            message = trigger.message
            actions = self.fix_recommender.recommend_fixes(
                trigger, causal_chain, scope, category, subcategory, message
            )
        
        # 7. Určit severity
        severity = self._determine_severity(events, scope, causal_chain)
        
        # 8. Určit status
        status = self._determine_status(events)
        
        # 9. Vytvořit IncidentAnalysis
        incident = IncidentAnalysis(
            incident_id=f"INC-{self._incident_counter:05d}",
            status=status,
            severity=severity,
            trigger=trigger,
            scope=scope,
            propagation=propagation,  # v5.3: odděleno od scope
            timeline=timeline,
            causal_chain=causal_chain,
            recommended_actions=actions,
            total_errors=sum(e.get('error_count', 0) for e in events),
            peak_error_rate=max(e.get('ratio', 1.0) for e in events),
        )
        
        # Timing
        timestamps = [e['timestamp'] for e in events if e.get('timestamp')]
        if timestamps:
            incident.started_at = min(timestamps)
            incident.ended_at = max(timestamps)
            incident.duration_sec = int((incident.ended_at - incident.started_at).total_seconds())
        
        # Linked fingerprints
        incident.linked_errors = list(set(e['fingerprint'] for e in events if e.get('event_type') == 'error'))
        incident.linked_peaks = list(set(e['fingerprint'] for e in events if e.get('event_type') in ('spike', 'burst')))
        
        # Title a summary
        incident.title = self._generate_title(incident)
        incident.summary = self._generate_summary(incident)
        
        # Confidence
        incident.overall_confidence = causal_chain.confidence if causal_chain else ConfidenceLevel.LOW
        
        # Priority (klíčové pro operační použití!)
        from .models import calculate_priority
        incident.priority, incident.priority_reasons = calculate_priority(
            knowledge_status=incident.knowledge_status,
            severity=severity,
            blast_radius=scope.blast_radius,
            is_worsening=False,  # TODO: porovnat s předchozím během
            namespace_count=len(scope.namespaces),
            propagated=propagation.propagated,
            propagation_time_sec=propagation.propagation_time_sec,
        )
        
        # Immediate actions (1-3 kroky pro SRE ve 3 ráno)
        incident.immediate_actions = self._generate_immediate_actions(incident)
        
        return incident
    
    def _generate_immediate_actions(self, incident: IncidentAnalysis) -> List[str]:
        """
        Generuje 1-3 bezprostřední akce.
        
        VYLEPŠENO v5.3: Actions zohledňují kontext (WHAT + WHERE + HOW BAD + HOW NEW + PROPAGATION)
        Ne jen category → šablona, ale:
        - is_new
        - affected_apps_count
        - version_change_detected
        - severity
        - propagation (rychlost šíření)
        """
        actions = []
        
        # === BUILD ACTION CONTEXT ===
        is_new = incident.knowledge_status == "NEW"
        is_known = incident.knowledge_status == "KNOWN"
        scope = incident.scope
        propagation = incident.propagation  # v5.3: odděleno od scope
        affected_apps_count = scope.blast_radius
        is_widespread = affected_apps_count >= 3
        
        # v5.3: Propagation context (z incident.propagation, ne scope!)
        is_fast_propagation = propagation.propagated and propagation.propagation_time_sec and propagation.propagation_time_sec < 30
        is_localized = scope.is_localized
        root_app = scope.root_apps[0] if scope.root_apps else None
        
        # Version change detection
        has_version_change = scope.version_change_detected
        version_info = ""
        if has_version_change:
            version_info = f"{scope.version_change_app} ({scope.version_change_from} → {scope.version_change_to})"
        
        # Root cause info
        rc_type = ""
        rc_app = ""
        if incident.causal_chain:
            rc_type = incident.causal_chain.root_cause_type.lower()
            rc_app = incident.causal_chain.root_cause_app or root_app or ""
        elif root_app:
            rc_app = root_app
        
        category = getattr(incident, 'category', '')
        if hasattr(category, 'value'):
            category = category.value.lower()
        else:
            category = str(category).lower()
        
        # === GENERATE CONTEXT-AWARE ACTIONS ===
        
        # 0. v5.3: Fast propagation = nejvyšší priorita
        if is_fast_propagation and is_new:
            actions.append(f"URGENT: Fast propagation detected ({propagation.propagation_time_sec}s) - check {root_app or 'root service'}")
        
        # 1. Version change detected - highest priority signal!
        if has_version_change and is_new:
            actions.append(f"Review recent deployment of {version_info}")
        
        # 2. Category + context specific actions
        if 'database' in rc_type or 'database' in category:
            if is_new:
                actions.append(f"Check DB connection pool on {rc_app or 'affected service'}")
            elif is_known:
                actions.append("Monitor - known DB issue, check if worsening")
        
        elif 'timeout' in rc_type or 'timeout' in category:
            if is_widespread:
                actions.append(f"Check shared dependency latency (affects {affected_apps_count} apps)")
            else:
                actions.append(f"Check latency and dependencies of {rc_app or 'affected service'}")
        
        elif 'auth' in rc_type or 'auth' in category:
            if is_widespread:
                actions.append("Check auth provider status page")
            else:
                actions.append(f"Verify auth configuration on {rc_app or 'affected service'}")
        
        elif 'memory' in rc_type or 'memory' in category:
            actions.append(f"Check memory/heap on {rc_app or 'affected service'}")
            if is_new:
                actions.append("Consider pod restart if memory leak suspected")
        
        elif 'external' in rc_type or 'external' in category:
            actions.append("Verify external service availability")
            if is_new:
                actions.append("Check circuit breaker status")
        
        elif 'network' in rc_type or 'network' in category:
            if is_widespread:
                actions.append("Check network infrastructure / service mesh")
            else:
                actions.append(f"Verify network connectivity to {rc_app or 'target service'}")
        
        else:
            # Generic fallback - but still context-aware
            if is_new and is_widespread:
                actions.append(f"Identify common factor across {affected_apps_count} affected apps")
            elif is_new and is_localized:
                # v5.3: Lokální incident = jednodušší diagnostika
                actions.append(f"Check logs on {rc_app or root_app or 'affected service'}")
            elif is_new:
                actions.append(f"Check logs and metrics on {rc_app or 'affected service'}")
            elif is_known:
                actions.append("Monitor - check if pattern matches known issue")
        
        # 3. Status-based follow-up action
        if is_new and not actions:
            actions.append("Investigate and classify incident")
        
        if is_new and len(actions) < 3:
            # v5.3: Lokální incident nepotřebuje Jiru okamžitě
            if is_localized:
                actions.append("Monitor for 15 min before escalating")
            else:
                actions.append("Create Jira if persists >15 min")
        elif is_known and len(actions) < 2:
            actions.append("No immediate action - known stable issue")
        
        # Max 3 actions, avoid duplicates
        seen = set()
        unique_actions = []
        for a in actions:
            if a not in seen:
                seen.add(a)
                unique_actions.append(a)
        
        return unique_actions[:3]
    
    def _build_scope(self, events: List[Dict]) -> Tuple[IncidentScope, 'IncidentPropagation']:
        """
        Staví scope incidentu.
        
        v5.3: Klasifikuje role aplikací (root, downstream, collateral)
              a vrací také IncidentPropagation
              
        Returns:
            Tuple[IncidentScope, IncidentPropagation]
        """
        from .models import IncidentPropagation
        
        scope = IncidentScope()
        propagation = IncidentPropagation()
        
        apps = set()
        namespaces = set()
        fingerprints = set()
        app_versions: Dict[str, Set[str]] = defaultdict(set)
        app_timestamps: Dict[str, datetime] = {}  # v5.3: pro klasifikaci rolí
        app_error_counts: Dict[str, int] = defaultdict(int)  # v5.3: pro určení root
        
        for event in events:
            app = event.get('app', 'unknown')
            apps.add(app)
            
            ns = event.get('namespace', '')
            if ns:
                namespaces.add(ns)
            
            fp = event.get('fingerprint', '')
            if fp:
                fingerprints.add(fp)
            
            version = event.get('version', '')
            if version:
                app_versions[app].add(version)
            
            error_count = event.get('error_count', 0)
            scope.total_errors += error_count
            app_error_counts[app] += error_count
            
            # Track první timestamp pro každou app
            ts = event.get('timestamp')
            if ts:
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    except:
                        ts = None
                if ts and (app not in app_timestamps or ts < app_timestamps[app]):
                    app_timestamps[app] = ts
        
        scope.apps = list(apps)
        scope.namespaces = list(namespaces)
        scope.fingerprints = list(fingerprints)
        scope.fingerprint_count = len(fingerprints)
        scope.app_versions = {app: list(versions) for app, versions in app_versions.items()}
        
        # Detekce změny verzí (v5.2)
        scope.detect_version_changes()
        
        # === v5.3: Klasifikace rolí aplikací ===
        if app_timestamps:
            # Root = app s nejdřívějším timestamp NEBO nejvíce errory
            first_app = min(app_timestamps.items(), key=lambda x: x[1])[0] if app_timestamps else None
            
            # Pokud více apps má stejný čas, vezmi tu s nejvíce errory
            if first_app:
                first_ts = app_timestamps[first_app]
                candidates = [app for app, ts in app_timestamps.items() 
                             if abs((ts - first_ts).total_seconds()) < 5]  # ±5s tolerance
                if len(candidates) > 1:
                    first_app = max(candidates, key=lambda a: app_error_counts.get(a, 0))
            
            # classify_app_roles nastaví root/downstream/collateral a vrátí propagation
            propagation = scope.classify_app_roles(first_app, app_timestamps)
        
        return scope, propagation
    
    def _determine_category(self, events: List[Dict]) -> str:
        """Určí hlavní kategorii"""
        categories = [e.get('category', 'unknown') for e in events]
        if categories:
            # Nejčastější kategorie
            from collections import Counter
            return Counter(categories).most_common(1)[0][0]
        return 'unknown'
    
    def _determine_subcategory(self, events: List[Dict], category: str) -> str:
        """Určí subkategorii"""
        subcats = [e.get('subcategory', 'general') for e in events if e.get('category') == category]
        if subcats:
            from collections import Counter
            return Counter(subcats).most_common(1)[0][0]
        return 'general'
    
    def _determine_severity(
        self,
        events: List[Dict],
        scope: IncidentScope,
        causal_chain: Optional[CausalChain]
    ) -> SeverityLevel:
        """Určí severity incidentu"""
        # Critical pokud:
        # - Blast radius >= 5 apps
        # - Severity critical v eventech
        # - Ratio >= 20x
        if scope.blast_radius >= 5:
            return SeverityLevel.CRITICAL
        
        if any(e.get('severity') == 'critical' for e in events):
            return SeverityLevel.CRITICAL
        
        if any(e.get('ratio', 1.0) >= 20 for e in events):
            return SeverityLevel.CRITICAL
        
        # High pokud:
        # - Blast radius >= 3 apps
        # - Severity high v eventech
        # - Ratio >= 10x
        if scope.blast_radius >= 3:
            return SeverityLevel.HIGH
        
        if any(e.get('severity') == 'high' for e in events):
            return SeverityLevel.HIGH
        
        if any(e.get('ratio', 1.0) >= 10 for e in events):
            return SeverityLevel.HIGH
        
        # Medium pokud:
        # - Spike nebo burst
        # - Multiple fingerprints
        if any(e.get('is_spike') or e.get('is_burst') for e in events):
            return SeverityLevel.MEDIUM
        
        if scope.fingerprint_count >= 3:
            return SeverityLevel.MEDIUM
        
        return SeverityLevel.LOW
    
    def _determine_status(self, events: List[Dict]) -> IncidentStatus:
        """Určí status incidentu"""
        # Pro teď: pokud je poslední událost < 5 min stará, je aktivní
        timestamps = [e['timestamp'] for e in events if e.get('timestamp')]
        if timestamps:
            latest = max(timestamps)
            if (datetime.now(timezone.utc) - latest.replace(tzinfo=timezone.utc)).total_seconds() < 300:
                return IncidentStatus.ACTIVE
        
        return IncidentStatus.RESOLVED
    
    def _generate_title(self, incident: IncidentAnalysis) -> str:
        """Generuje title incidentu"""
        if incident.trigger:
            app = incident.trigger.app
            category = incident.causal_chain.root_cause_type if incident.causal_chain else 'unknown'
            return f"{category.title()} issue in {app}"
        
        if incident.scope.apps:
            return f"Issue in {', '.join(incident.scope.apps[:3])}"
        
        return f"Incident {incident.incident_id}"
    
    def _generate_summary(self, incident: IncidentAnalysis) -> str:
        """Generuje summary incidentu"""
        parts = []
        
        if incident.causal_chain:
            parts.append(incident.causal_chain.root_cause_description)
        
        if incident.scope.blast_radius > 1:
            parts.append(f"Affects {incident.scope.blast_radius} apps")
        
        if incident.total_errors > 0:
            parts.append(f"{incident.total_errors:,} errors")
        
        if incident.peak_error_rate > 1:
            parts.append(f"{incident.peak_error_rate:.1f}x peak")
        
        return " | ".join(parts) if parts else "Unknown issue"


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

def analyze_incidents(
    incidents: List['Incident'],
    analysis_start: datetime = None,
    analysis_end: datetime = None,
) -> IncidentAnalysisResult:
    """
    Convenience function pro analýzu incidentů.
    
    Args:
        incidents: Seznam Incident objektů
        analysis_start: Začátek období
        analysis_end: Konec období
    
    Returns:
        IncidentAnalysisResult
    """
    engine = IncidentAnalysisEngine()
    return engine.analyze(incidents, analysis_start, analysis_end)
