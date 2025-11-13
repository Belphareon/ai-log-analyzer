#!/usr/bin/env python3
"""
TRACE-BASED ROOT CAUSE ANALYSIS PROCEDURE
=========================================

Postup analýzy error logů podle trace_id:

1. VIZUÁLNÍ ANALÝZA - Peak Detection
   - Zobrazit timeline errorů (počet errors v čase)
   - Identifikovat peaky (náhlé nárůsty)
   - V tomto případě: nejdriv maly peak kolem cca 9:36 (dobre zkontrolovat 10s pred zacatkem peaku jestli to nesouvisi) peak 10:08-10:28 ( velka anomálie na tu se rozhodne primarne zamerit)

2. APP IMPACT DISTRIBUTION
   - Kolik % errors má která aplikace?
   - V tomto případě:
     * bl-pcb-token-v1: 62% (primary issue)
     * bl-pcb-v1: 26% (secondary, pravdepodobne affected by primary)
     * Ostatní: zbývajících % (side effects, ale nevynechat, dost pravdepodobne souvisi)
   - Detekujeme PRIMARY app (pcb-token-v1) a SECONDARY apps (pcb-v1)

3. NAMESPACE DISTRIBUTION
   - Všechny namespaces gleichně postižené?
   - V tomto případě: cca 25% každý namespace
   - Znamená to že jde o systémový problém (ne environment-specific)
   - na zaver jen porovnat jestli je to opravdu stejne cross ns

4. ERROR MESSAGE ANALYSIS
   - Najit prvni error message cim dany problem zacal
   - Overit jaké jsou TOP messages? Muze tam byt jasny identifikator spolecneho problemu.
   - V tomto případě: "Error handler threw an exception"
   - PROBLÉM: To je generic message, neříká co se stalo!
   - Řešení: Musíme jít na TRACE_ID level první error message daneho peaku

5. TRACE_ID DEEP DIVE - Klíčový krok!
   - Vybrat PRVNI error z PRIMARY app (bl-pcb-token-v1)
   - Získat jeho trace_id (~360 errors s tímto trace_id)
   - Vyhledat VŠECHNY logy se stejným trace_id (ERROR + WARN + INFO) - advanced, nechat na pozdeji, az bude funkcni prototyp
   - Najít PRVNÍ log v chain (nejstarší timestamp)
   - V tomto případě ROOT CAUSE v bl-pcb-v1:
     "ServiceBusinessException: Resource not found. Card with id 91732..."
   - Nyní víme: Root cause je na bl-pcb-v1, pak se propaguje na token-v1

6. ERROR CHAIN RECONSTRUCTION
   - Časová posloupnost všech logů s daným trace_id
   - Ukázat flow: 
     * 10:08 bl-pcb-v1 ServiceBusinessException
     * 10:08 bl-pcb-v1 Error handling
     * 10:08 bl-pcb-token-v1 Error propagation
   - IMPACT: Vidíme jak se error šíří cross-app

7. DEDUPLICATION & CATEGORIZATION
   - Všechny "Error handler threw an exception" s tímto trace_id → TAG: DERIVATIVE
   - ROOT exception → TAG: ROOT_CAUSE
   - Opakující se ROOT causes → Sepsat do "Known Issues"
   - Nové ROOT causes → Sepsat do "New Issues"
   - Errory mimo peaky prověřit a 

8. ITERATION
   - Vybrat další trace_id s NEW root cause
   - Opakovat kroky 5-7
   - Pokračovat dokud neopakujeme jen známé chyby, ze kterych bude seznam s oznacenim dne a poctem

VÝSTUP:
========
- Timeline s peaky a jejich root causes
- Root causes seřazeny po výskytu (nejčastější první)
- Trace chains pro každý root cause
- Affected apps a namespaces per root cause
- Recommendations co opravit

IMPLEMENTACE:
==============
1. trace_extractor.py - Extract trace_id ze všech errors
2. trace_analyzer.py - Analyzovat trace_id Deep Dive
3. root_cause_detector.py - Najít root cause v trace chain
4. trace_report_generator.py - Generovat readable report

PŘÍKLAD OUTPUT:
================

# Trace-Based Root Cause Analysis
Period: 2025-11-13 09:30-10:30

## Timeline Analysis
```
09:30 |     ▁▂▃▂▁
10:00 |     ▃▄▅▆█████▆▄▂▁
10:30 |     ▁
```
Peak: 10:08-10:28 = 4,890 errors (PRIMARY)

## Root Causes Found: 3

### 1. Resource not found - Card 91732 (2,847 errors, 62%)
**First seen:** 10:08:01
**Last seen:** 10:28:15
**Source App:** bl-pcb-v1 (ServiceBusinessException)
**Propagated to:** bl-pcb-token-v1 (2,760 errors, 97%)
**Trace IDs:** 360 unique
**Affected Namespaces:** pcb-sit, pcb-dev, pcb-uat, pcb-fat (25% each)

Trace Example (trace_id: abc-123-def):
```
10:08:01.234 [bl-pcb-v1:pcb-sit] ServiceBusinessException: Card 91732 not found
10:08:01.245 [bl-pcb-v1:pcb-sit] Error: java.lang.NullPointerException in handler
10:08:01.256 [bl-pcb-token-v1:pcb-sit] Error: Cannot process token, upstream failed
```

**Impact:** 
- bl-pcb-v1: 2,847 errors (100%)
- bl-pcb-token-v1: 2,760 errors (97%)
- Total affected: 2,847 (unique)

**Recommendation:** Check why Card 91732 is missing from database

### 2. Connection timeout to external service (890 errors, 19%)
...

### 3. Authorization error (153 errors, 3%)
...

"""

import json
from collections import defaultdict
from datetime import datetime

class TraceBasedAnalyzer:
    """Analyze errors using trace_id as primary key"""
    
    def __init__(self, errors):
        self.errors = errors
        self.trace_groups = defaultdict(list)
        self._group_by_trace_id()
    
    def _group_by_trace_id(self):
        """Group all errors by trace_id"""
        for error in self.errors:
            trace_id = error.get('trace_id', 'NO_TRACE')
            self.trace_groups[trace_id].append(error)
    
    def find_root_causes(self):
        """Find root cause for each trace_id group"""
        root_causes = {}
        
        for trace_id, errors_in_trace in self.trace_groups.items():
            # Sort by timestamp to find first error
            sorted_errors = sorted(errors_in_trace, key=lambda e: e.get('timestamp', ''))
            
            if sorted_errors:
                # First error is likely root cause
                first_error = sorted_errors[0]
                
                # Extract cause from message
                msg = first_error.get('message', '')
                app = first_error.get('app', 'unknown')
                
                # Create cause key
                cause_key = f"{app}: {msg[:100]}"
                
                if cause_key not in root_causes:
                    root_causes[cause_key] = {
                        'trace_ids': [],
                        'errors': [],
                        'apps': set(),
                        'first_seen': sorted_errors[0].get('timestamp'),
                        'last_seen': sorted_errors[-1].get('timestamp'),
                    }
                
                root_causes[cause_key]['trace_ids'].append(trace_id)
                root_causes[cause_key]['errors'].extend(errors_in_trace)
                root_causes[cause_key]['apps'].add(app)
        
        return root_causes
    
    def get_trace_chain(self, trace_id):
        """Get full error chain for given trace_id"""
        errors = self.trace_groups.get(trace_id, [])
        return sorted(errors, key=lambda e: e.get('timestamp', ''))

if __name__ == '__main__':
    print(__doc__)
