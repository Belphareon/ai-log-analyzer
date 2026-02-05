# Pipeline Architecture v5.3.1

## Přehled

Systém se skládá ze dvou hlavních částí:

1. **Detection Pipeline (v6)** - statistická detekce anomálií
2. **Incident Analysis (v6.0.1)** - kauzální analýza a reporting

## Celková architektura

```
┌─────────────────────────────────────────────────────────────────┐
│                    ELASTICSEARCH                                │
│                    (aplikační logy)                            │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                DETECTION PIPELINE (v6)                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐           │
│  │ Phase A │→ │ Phase B │→ │ Phase C │→ │ Phase D │           │
│  │ Parse   │  │ Measure │  │ Detect  │  │ Score   │           │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘           │
│       ↓            ↓            ↓            ↓                  │
│  ┌─────────┐  ┌─────────┐                                      │
│  │ Phase E │→ │ Phase F │                                      │
│  │Classify │  │ Report  │                                      │
│  └─────────┘  └─────────┘                                      │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    IncidentCollection
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              INCIDENT ANALYSIS (v6.0.1)                         │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ TimelineBuilder│→ │  ScopeBuilder  │→ │ CausalInference│   │
│  │                │  │ + Propagation  │  │                │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
│           ↓                   ↓                   ↓            │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐   │
│  │ FixRecommender │→ │KnowledgeMatcher│→ │    Formatter   │   │
│  └────────────────┘  └────────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    OUTPUT (v6.0.1)                              │
│  ┌────────────────┐  ┌────────────────┐                        │
│  │ scripts/reports│  │   registry/    │                        │
│  │   (reporty)   │  │ (append-only)  │                        │
│  └────────────────┘  └────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

## Detection Pipeline (v6)

### Phase A: Parse

- Vstup: Raw logy z ES
- Výstup: Normalizované záznamy
- Činnost: Fingerprinting, kategorizace

### Phase B: Measure

- Vstup: Normalizované záznamy
- Výstup: Statistiky (EWMA baseline, MAD)
- Činnost: Výpočet baseline pro každý fingerprint

### Phase C: Detect

- Vstup: Statistiky + aktuální data
- Výstup: Detekované anomálie
- Činnost: Porovnání s baseline, detekce spiků/burstů

### Phase D: Score

- Vstup: Detekované anomálie
- Výstup: Scorované anomálie
- Činnost: Výpočet závažnosti

### Phase E: Classify

- Vstup: Scorované anomálie
- Výstup: Klasifikované incidenty
- Činnost: Seskupení do incidentů

### Phase F: Report

- Vstup: Klasifikované incidenty
- Výstup: IncidentCollection
- Činnost: Příprava pro analýzu

## Incident Analysis (v5.3.1)

### Datový model

```python
class IncidentAnalysis:
    incident_id: str
    
    # KDE se to projevilo
    scope: IncidentScope
        apps: List[str]
        root_apps: List[str]
        downstream_apps: List[str]
        collateral_apps: List[str]
    
    # JAK se to šířilo (v5.3.1 - odděleno od scope)
    propagation: IncidentPropagation
        propagated: bool
        propagation_time_sec: int
        propagation_path: List[str]
    
    # Časová osa (FACTS)
    timeline: List[TimelineEvent]
    
    # Root cause (HYPOTHESIS)
    causal_chain: CausalChain
    
    # Priorita
    priority: IncidentPriority  # P1-P4
    priority_reasons: List[str]
    recommended_actions: List[RecommendedAction]
```

|------------|-------|--------|
| TimelineBuilder | Events | Timeline (FACTS) |
| ScopeBuilder | Events | IncidentScope + IncidentPropagation |
| Formatter | IncidentAnalysis | Report string |

### Registry Update (v6.0.1)
  Pro každý incident:
    Pro každý fingerprint:
      IF fingerprint NOT IN registry:
        
  WRITE registry/known_errors.yaml
  WRITE registry/known_errors.md

### regular_phase_v6.py (15min)

```python
def run_regular_pipeline():
    # 1. Fetch z ES
    errors = fetch_unlimited(...)
    
    # 2. Detection pipeline
    pipeline = PipelineV6()
    collection = pipeline.run(errors)
    
    # 3. Save to DB
    save_incidents_to_db(collection)
    
    # 4. Incident Analysis (VŽDY - v6.0.1)
    report = run_incident_analysis(
        collection,
        output_dir="scripts/reports/"  # ← v6.0.1: explicitní path
    )
    # → report se uloží
    # → registry se aktualizuje
    
    # 5. Output
    print(report)
```

### backfill_v6.py (daily)

```python
def run_backfill():
    # Pro každý den:
    #   1. Fetch
    #   2. Pipeline
    #   3. DB save
    #   4. Aggregate
    
    # Na konci:
    #   Daily report + registry update
```

## Výstupní soubory

```
scripts/reports/
├── incident_analysis_15min_20260123_091500.txt
├── incident_analysis_15min_20260123_093000.txt
├── incident_analysis_daily_20260122_*.txt
└── ...

registry/
├── known_errors.yaml   # Strojový formát
├── known_errors.md     # Human-readable
├── known_peaks.yaml
└── known_peaks.md
```

## Klíčové principy v5.3.1

1. **Scope ≠ Propagation** - oddělené datové struktury
2. **Report VŽDY** - generuje se i prázdný
3. **Registry append-only** - nikdy se nemaže
4. **Output dir explicitní** - ne relativní cesty
5. **Traceback při chybě** - pro debugging
