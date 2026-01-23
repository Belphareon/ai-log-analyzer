#!/usr/bin/env python3
"""
TIMELINE BUILDER
================

Staví časovou osu incidentu z jednotlivých událostí.

Timeline ukazuje:
- Kdy začal problém
- Jak se šířil
- Které aplikace byly zasaženy v jakém pořadí
- Kdy skončil (pokud skončil)

Příklad:
09:01 errors start (order)
09:02 spike (order)  
09:04 downstream errors (payment)
09:06 peak traffic (gateway)
"""

from typing import List, Dict, Optional, Set, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

try:
    from .models import TimelineEvent, IncidentTrigger, TriggerType
except ImportError:
    from models import TimelineEvent, IncidentTrigger, TriggerType


class TimelineBuilder:
    """Staví timeline incidentu"""
    
    def __init__(self, window_sec: int = 60):
        """
        Args:
            window_sec: Okno pro grupování událostí (default 60s)
        """
        self.window_sec = window_sec
    
    def build_timeline(
        self,
        events: List[Dict],
        trigger: Optional[IncidentTrigger] = None
    ) -> List[TimelineEvent]:
        """
        Staví timeline z raw událostí.
        
        Args:
            events: Seznam událostí s keys:
                - timestamp: datetime
                - app: str
                - namespace: str
                - event_type: str (error, spike, burst, peak)
                - fingerprint: str
                - error_count: int
                - ratio: float (pro spike/peak)
                - message: str
            trigger: Trigger incidentu (pro označení)
        
        Returns:
            Seřazený seznam TimelineEvent
        """
        if not events:
            return []
        
        timeline = []
        trigger_fp = trigger.fingerprint if trigger else None
        
        # Seřadit podle času
        sorted_events = sorted(events, key=lambda e: e.get('timestamp', datetime.min))
        
        # Vytvořit TimelineEvent pro každou událost
        for event in sorted_events:
            ts = event.get('timestamp')
            if not ts:
                continue
            
            te = TimelineEvent(
                timestamp=ts,
                event_type=event.get('event_type', 'error'),
                app=event.get('app', 'unknown'),
                namespace=event.get('namespace', ''),
                version=event.get('version', ''),
                description=self._build_description(event),
                fingerprint=event.get('fingerprint', ''),
                error_count=event.get('error_count', 0),
                ratio=event.get('ratio', 1.0),
                is_trigger=(event.get('fingerprint') == trigger_fp),
            )
            timeline.append(te)
        
        # Označit effects
        timeline = self._mark_effects(timeline, trigger)
        
        # Mergovat události ve stejném okně
        timeline = self._merge_window_events(timeline)
        
        return timeline
    
    def _build_description(self, event: Dict) -> str:
        """Vytvoří popis události"""
        event_type = event.get('event_type', 'error')
        app = event.get('app', 'unknown')
        
        if event_type == 'error':
            count = event.get('error_count', 0)
            msg = event.get('message', '')[:50]
            return f"Error in {app}: {msg}" if msg else f"{count} errors in {app}"
        
        elif event_type == 'spike':
            ratio = event.get('ratio', 1.0)
            return f"Spike {ratio:.1f}x in {app}"
        
        elif event_type == 'burst':
            count = event.get('error_count', 0)
            return f"Burst ({count} errors) in {app}"
        
        elif event_type == 'peak':
            ratio = event.get('ratio', 1.0)
            return f"Peak {ratio:.1f}x in {app}"
        
        elif event_type == 'recovery':
            return f"Recovery in {app}"
        
        else:
            return f"{event_type} in {app}"
    
    def _mark_effects(
        self,
        timeline: List[TimelineEvent],
        trigger: Optional[IncidentTrigger]
    ) -> List[TimelineEvent]:
        """Označí události jako effects (důsledky triggeru)"""
        if not trigger or not timeline:
            return timeline
        
        trigger_time = trigger.timestamp
        trigger_app = trigger.app
        
        for event in timeline:
            # Pokud je to po triggeru a v jiné app, je to effect
            if event.timestamp > trigger_time and event.app != trigger_app:
                event.is_effect = True
                event.caused_by = trigger.fingerprint
            
            # Pokud je to spike/peak po error triggeru, je to effect
            if (event.timestamp > trigger_time and 
                event.event_type in ('spike', 'peak', 'burst') and
                not event.is_trigger):
                event.is_effect = True
                event.caused_by = trigger.fingerprint
        
        return timeline
    
    def _merge_window_events(self, timeline: List[TimelineEvent]) -> List[TimelineEvent]:
        """Merguje události ve stejném časovém okně"""
        if len(timeline) <= 1:
            return timeline
        
        merged = []
        current_window = []
        window_start = timeline[0].timestamp
        
        for event in timeline:
            if (event.timestamp - window_start).total_seconds() <= self.window_sec:
                current_window.append(event)
            else:
                # Zpracovat okno
                if current_window:
                    merged.extend(self._process_window(current_window))
                current_window = [event]
                window_start = event.timestamp
        
        # Poslední okno
        if current_window:
            merged.extend(self._process_window(current_window))
        
        return merged
    
    def _process_window(self, window: List[TimelineEvent]) -> List[TimelineEvent]:
        """Zpracuje okno událostí - možná mergování"""
        if len(window) <= 1:
            return window
        
        # Gruppovat podle app + event_type
        groups: Dict[Tuple[str, str], List[TimelineEvent]] = defaultdict(list)
        for event in window:
            key = (event.app, event.event_type)
            groups[key].append(event)
        
        result = []
        for (app, event_type), events in groups.items():
            if len(events) == 1:
                result.append(events[0])
            else:
                # Merge - vezmi první, agreguj counts
                merged = events[0]
                merged.error_count = sum(e.error_count for e in events)
                if event_type in ('spike', 'peak'):
                    merged.ratio = max(e.ratio for e in events)
                merged.description = self._build_merged_description(events)
                result.append(merged)
        
        # Seřadit výsledek
        result.sort(key=lambda e: e.timestamp)
        return result
    
    def _build_merged_description(self, events: List[TimelineEvent]) -> str:
        """Popis pro mergované události"""
        if not events:
            return ""
        
        first = events[0]
        count = len(events)
        
        if first.event_type == 'error':
            total = sum(e.error_count for e in events)
            return f"{total} errors in {first.app} ({count} events)"
        elif first.event_type == 'spike':
            max_ratio = max(e.ratio for e in events)
            return f"Multiple spikes (max {max_ratio:.1f}x) in {first.app}"
        else:
            return f"{count} {first.event_type} events in {first.app}"
    
    def detect_trigger(
        self,
        events: List[Dict]
    ) -> Optional[IncidentTrigger]:
        """
        Detekuje trigger incidentu z událostí.
        
        Trigger je:
        - Nový error fingerprint
        - Spike/burst nad prahem
        - Cross-namespace event
        - První error před kaskádou
        """
        if not events:
            return None
        
        # Seřadit podle času
        sorted_events = sorted(events, key=lambda e: e.get('timestamp', datetime.min))
        
        # Hledat trigger
        for event in sorted_events:
            # Nový error s flagem
            if event.get('is_new') and event.get('event_type') == 'error':
                return IncidentTrigger(
                    trigger_type=TriggerType.NEW_ERROR,
                    app=event.get('app', 'unknown'),
                    namespace=event.get('namespace', ''),
                    fingerprint=event.get('fingerprint', ''),
                    error_type=event.get('error_type', 'Unknown'),
                    message=event.get('message', ''),
                    timestamp=event.get('timestamp'),
                    version=event.get('version', ''),
                )
            
            # Spike
            if event.get('event_type') == 'spike' and event.get('ratio', 1.0) >= 3.0:
                return IncidentTrigger(
                    trigger_type=TriggerType.SPIKE,
                    app=event.get('app', 'unknown'),
                    namespace=event.get('namespace', ''),
                    fingerprint=event.get('fingerprint', ''),
                    error_type=event.get('error_type', 'Unknown'),
                    message=event.get('message', ''),
                    timestamp=event.get('timestamp'),
                    version=event.get('version', ''),
                )
            
            # Burst
            if event.get('event_type') == 'burst':
                return IncidentTrigger(
                    trigger_type=TriggerType.BURST,
                    app=event.get('app', 'unknown'),
                    namespace=event.get('namespace', ''),
                    fingerprint=event.get('fingerprint', ''),
                    error_type=event.get('error_type', 'Unknown'),
                    message=event.get('message', ''),
                    timestamp=event.get('timestamp'),
                    version=event.get('version', ''),
                )
            
            # Cross-namespace
            if event.get('is_cross_namespace'):
                return IncidentTrigger(
                    trigger_type=TriggerType.CROSS_NAMESPACE,
                    app=event.get('app', 'unknown'),
                    namespace=event.get('namespace', ''),
                    fingerprint=event.get('fingerprint', ''),
                    error_type=event.get('error_type', 'Unknown'),
                    message=event.get('message', ''),
                    timestamp=event.get('timestamp'),
                    version=event.get('version', ''),
                )
        
        # Fallback: první událost
        first = sorted_events[0]
        return IncidentTrigger(
            trigger_type=TriggerType.NEW_ERROR,
            app=first.get('app', 'unknown'),
            namespace=first.get('namespace', ''),
            version=first.get('version', ''),
            fingerprint=first.get('fingerprint', ''),
            error_type=first.get('error_type', 'Unknown'),
            message=first.get('message', ''),
            timestamp=first.get('timestamp'),
        )
    
    def format_timeline_text(self, timeline: List[TimelineEvent]) -> str:
        """Formátuje timeline jako text"""
        if not timeline:
            return "No events"
        
        lines = []
        for event in timeline:
            time_str = event.timestamp.strftime("%H:%M:%S")
            marker = ""
            if event.is_trigger:
                marker = " [TRIGGER]"
            elif event.is_effect:
                marker = " [EFFECT]"
            
            lines.append(f"{time_str} {event.description}{marker}")
        
        return "\n".join(lines)
