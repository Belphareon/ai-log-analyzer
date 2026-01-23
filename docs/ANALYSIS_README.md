# AI Log Analyzer - Incident Analysis Engine v5.2

Automatizovaná detekce a analýza incidentů z aplikačních logů.

## Změny v v5.2

**Opravy kritických problémů:**

1. **Fingerprint** - nyní `category|subcategory|normalized_message` místo jen textu
   - Zamezuje falešným cross-app incidentům
   - Správné seskupování podle typu problému

2. **Baseline pro 15min mode** - nastaveno na `None`
   - Real-time analýza nepotřebuje baseline
   - Zabraňuje falešným spike detekcím

3. **Grouping podle mode** - `15min` vs `daily/backfill`
   - 15min: group by fingerprint
   - daily/backfill: group by (fingerprint, day)

4. **Priority přepočet** - po knowledge matching
   - KNOWN incidenty správně dostanou P3
   - NEW incidenty správně dostanou P1/P2

5. **Version extrakce** - explicitní regex
   - Nechytne `vault`, `vhost`
   - Chytne `v1.8.2`, `release-2026.01`

6. **Slack timeout** - 3s místo 10s
   - Neblokuje 15min cron

7. **Incident ID** - stabilní formát `INC-{date}-{fp[:6]}`
   - Jednoznačná identifikace mezi běhy

## Přehled systému

Systém analyzuje error logy z Elasticsearch/PostgreSQL a automaticky:
- Detekuje anomálie (spiky, bursty, nové errory)
- Seskupuje souvisejí události do incidentů
- Určuje root cause bez použití AI
- Navrhuje konkrétní opravy
- Rozlišuje známé vs nové incidenty
- Generuje operační reporty

## Architektura

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. DETECTION (fakta)                        │
│                                                                 │
│  Vstup: Peak investigation záznamy z DB                        │
│  Výstup: IncidentCollection (raw detekce)                      │
│                                                                 │
│  • Statistické výpočty (EWMA, MAD)                             │
│  • Detekce peaků, spiků, burstů                                │
│  • Fingerprinting errorů                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  2. INCIDENT ANALYSIS (kauzalita)               │
│                                                                 │
│  Vstup: IncidentCollection                                      │
│  Výstup: IncidentAnalysis[] (analyzované incidenty)            │
│                                                                 │
│  • TimelineBuilder - jak se problém šířil (FACTS)              │
│  • CausalInferenceEngine - proč (HYPOTHESIS)                   │
│  • FixRecommender - konkrétní opravy                           │
│  • Priority calculation (P1-P4)                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│               3. KNOWLEDGE MATCHING (known vs new)              │
│                                                                 │
│  Vstup: IncidentAnalysis[], KnowledgeBase                      │
│  Výstup: Enriched IncidentAnalysis[]                           │
│                                                                 │
│  • KnowledgeBase loader (YAML + MD)                            │
│  • KnowledgeMatcher (fingerprint → cluster → pattern)          │
│  • TriageReportGenerator (pro NEW incidenty)                   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   4. REPORTING (výstup)                         │
│                                                                 │
│  Vstup: Enriched IncidentAnalysis[]                            │
│  Výstup: Console, Markdown, JSON, Slack                        │
│                                                                 │
│  • 15min mode - operační (max 1 obrazovka)                     │
│  • Daily mode - přehled (trendy, agregace)                     │
│  • Report je ČISTÝ RENDERER - nic nepřepočítává!               │
└─────────────────────────────────────────────────────────────────┘
```

## Instalace

```bash
# Struktura souborů
project/
├── incident_analysis/          # Hlavní modul
│   ├── __init__.py
│   ├── models.py              # Datové modely
│   ├── analyzer.py            # IncidentAnalysisEngine
│   ├── timeline_builder.py    # TimelineBuilder
│   ├── causal_inference.py    # CausalInferenceEngine
│   ├── fix_recommender.py     # FixRecommender
│   ├── knowledge_base.py      # KnowledgeBase
│   ├── knowledge_matcher.py   # KnowledgeMatcher
│   └── formatter.py           # IncidentReportFormatter
├── knowledge/                  # Knowledge base (human-managed)
│   ├── known_errors.yaml
│   ├── known_errors.md
│   ├── known_peaks.yaml
│   └── known_peaks.md
├── analyze_incidents.py        # CLI skript
└── config/.env                 # Konfigurace DB
```

### Závislosti

```bash
pip install psycopg2-binary python-dotenv requests pyyaml
```

### Konfigurace

```bash
# config/.env
DB_HOST=your-db-host
DB_PORT=5432
DB_NAME=your-db
DB_USER=your-user
DB_PASSWORD=your-password
```

## Použití

### 15-minute operační mode

```bash
# Poslední 15 minut
python analyze_incidents.py --mode 15min

# Poslední 30 minut
python analyze_incidents.py --mode 15min --minutes 30

# S knowledge base
python analyze_incidents.py --mode 15min --knowledge-dir ./knowledge

# Jen critical/high
python analyze_incidents.py --mode 15min --only-critical

# S odesláním do Slacku
python analyze_incidents.py --mode 15min --slack-webhook https://hooks.slack.com/...
```

### Daily mode

```bash
# Včerejší den
python analyze_incidents.py --mode daily

# Konkrétní datum
python analyze_incidents.py --mode daily --date 2026-01-21
```

### Backfill mode

```bash
# Posledních 7 dní
python analyze_incidents.py --mode backfill --days 7

# Konkrétní rozsah
python analyze_incidents.py --mode backfill --date-from 2026-01-01 --date-to 2026-01-14
```

### Knowledge base

```bash
# Inicializace prázdné knowledge base
python analyze_incidents.py --init-knowledge --knowledge-dir ./knowledge

# Triage report pro NEW incidenty
python analyze_incidents.py --mode 15min --triage --knowledge-dir ./knowledge
```

## Klíčové koncepty

### Severity vs Priority

| Koncept | Význam | Hodnoty |
|---------|--------|---------|
| **Severity** | DOPAD (jak moc to bolí) | CRITICAL, HIGH, MEDIUM, LOW |
| **Priority** | AKČNOST (mám to řešit hned?) | P1, P2, P3, P4 |

### Priority pravidla

```
P1: NEW AND (CRITICAL OR cross-app ≥3)  → Řeš HNED (3 AM call)
P2: KNOWN AND worsening                 → Řeš dnes
P2: NEW AND not critical                → Řeš dnes
P3: KNOWN AND stable                    → Sleduj, naplánuj
P4: ostatní                             → Backlog
```

### FACT vs HYPOTHESIS

Report jasně odděluje:
- **FACTS** = detekované události (co se stalo)
- **HYPOTHESIS** = odvozený root cause (proč)

### Known vs New

- **KNOWN** = incident matchuje záznam v knowledge base
- **NEW** = incident vyžaduje triage (vytvoření Jira, přidání do KB)

## Výstup reportu (15min mode)

```
======================================================================
🔍 INCIDENT ANALYSIS - 15 MIN OPERATIONAL REPORT
======================================================================
Period: 09:00 - 09:15
Analysis time: 45ms

⚠️ 2 INCIDENT(S) DETECTED
   🆕 1 NEW | 📚 1 KNOWN
   🔴 1 CRITICAL | 🟠 1 HIGH

────────────────────────────────────────────────────────────
🔴 [P1] 🆕 NEW INCIDENT (09:01–09:06)
────────────────────────────────────────────────────────────

FACTS:
  • order-service: HikariPool-1 - Connection is not available
  • Affected: order-service, payment-service, gateway, notification
  • Errors: 1,234 | Peak: 15.2x baseline

HYPOTHESIS:
  [✓] Database connection pool exhausted in order-service

STATUS: NEW - requires triage

IMMEDIATE ACTIONS:
  1. Check DB connection pool on order-service
  2. Verify payment-service latency
  3. Prepare Jira ticket if persists >15 min

────────────────────────────────────────────────────────────
🟠 [P3] KNOWN INCIDENT (09:08–09:12) [KE-002]
────────────────────────────────────────────────────────────

FACTS:
  • auth-service: Token validation failed
  • Affected: auth-service, api-gateway
  • Errors: 234 | Peak: 3.1x baseline

HYPOTHESIS:
  [✓] External OAuth provider intermittent issues

STATUS: Known issue KE-002
  Jira: OPS-445

IMMEDIATE ACTIONS:
  1. Check OAuth provider status page
```

## Knowledge Base

### Struktura

```
knowledge/
├── known_errors.yaml    # Machine readable
├── known_errors.md      # Human readable
├── known_peaks.yaml
└── known_peaks.md
```

### Known Error (YAML)

```yaml
- id: KE-001
  fingerprint: abc123def456
  category: DATABASE
  description: Order-service DB connection pool exhaustion
  affected_apps:
    - order-service
    - payment-service
  first_seen: 2025-11-12
  jira: OPS-431
  status: OPEN
  owner: platform-team
  workaround:
    - Restart order-service pod
    - Scale up replicas temporarily
  permanent_fix:
    - Increase pool size to 25
    - Optimize slow queries
  error_pattern: "HikariPool.*Connection is not available"
  related_fingerprints:
    - def456abc123
```

### Known Error (Markdown)

```markdown
## KE-001 – Order-service DB pool exhaustion

**Category:** DATABASE  
**Affected apps:** order-service, payment-service  
**First seen:** 2025-11-12  
**Jira:** OPS-431  
**Status:** OPEN  
**Owner:** platform-team

### Description
Order-service exhausts DB connection pool during traffic spikes.

### Workaround
- Restart order-service pod
- Scale up replicas temporarily

### Permanent fix
- Increase pool size to 25
- Optimize slow queries
```

### Matching pravidla

1. **Exact fingerprint** → EXACT confidence
2. **Fingerprint ∈ related_fingerprints** → HIGH confidence
3. **Category + affected_apps** → HIGH confidence
4. **Pattern match (regex)** → MEDIUM confidence

### Workflow

```
1. Report označí incident jako NEW
2. Člověk:
   - Vyšetří root cause
   - Vytvoří Jira ticket
   - Zapíše do known_errors.yaml + known_errors.md
3. Další běhy hlásí KNOWN se statusem a workaroundem
```

**DŮLEŽITÉ:** Known errors NIKDY nevznikají automaticky. Vždy vyžadují lidské rozhodnutí.

## IncidentAnalysis objekt

```python
IncidentAnalysis:
  # Identity
  incident_id: str                    # "INC-00001"
  
  # Priority (klíčové pro operační použití!)
  priority: IncidentPriority          # P1, P2, P3, P4
  priority_reasons: List[str]         # ["new_incident", "cross_app_impact"]
  
  # Status
  status: IncidentStatus              # ACTIVE, RESOLVED, INVESTIGATING
  severity: SeverityLevel             # CRITICAL, HIGH, MEDIUM, LOW
  
  # Trigger (co to spustilo)
  trigger: IncidentTrigger
    trigger_type: TriggerType         # NEW_ERROR, SPIKE, BURST, CROSS_NAMESPACE
    app: str
    namespace: str
    fingerprint: str
    message: str
    timestamp: datetime
  
  # Scope (kde se to projevilo)
  scope: IncidentScope
    apps: List[str]
    namespaces: List[str]
    blast_radius: int                 # počet affected apps
  
  # Time
  started_at: datetime
  ended_at: datetime
  duration_sec: int
  
  # Timeline (FACTS - detekované události)
  timeline: List[TimelineEvent]
  
  # Causal chain (HYPOTHESIS - odvozený root cause)
  causal_chain: CausalChain
    root_cause_description: str
    root_cause_app: str
    root_cause_type: str
    confidence: ConfidenceLevel       # HIGH, MEDIUM, LOW
    effects: List[CausalLink]
  
  # Impact (FACTS)
  total_errors: int
  peak_error_rate: float
  
  # Knowledge matching (vyplňuje KnowledgeMatcher)
  knowledge_status: str               # "NEW" nebo "KNOWN"
  knowledge_id: str                   # "KE-001" nebo "KP-001"
  knowledge_jira: str
  knowledge_workaround: List[str]
  knowledge_permanent_fix: List[str]
  
  # Actions
  immediate_actions: List[str]        # 1-3 kroky pro SRE ve 3 ráno
  recommended_actions: List[RecommendedAction]  # Detailní doporučení
```

## Komponenty

| Soubor | Třída | Popis |
|--------|-------|-------|
| `models.py` | `IncidentAnalysis` | Hlavní datový model incidentu |
| `models.py` | `calculate_priority()` | Výpočet P1-P4 priority |
| `analyzer.py` | `IncidentAnalysisEngine` | Hlavní engine pro analýzu |
| `timeline_builder.py` | `TimelineBuilder` | Staví časovou osu (FACTS) |
| `causal_inference.py` | `CausalInferenceEngine` | Root cause inference (HYPOTHESIS) |
| `fix_recommender.py` | `FixRecommender` | Generuje konkrétní opravy |
| `knowledge_base.py` | `KnowledgeBase` | Loader pro YAML/MD |
| `knowledge_matcher.py` | `KnowledgeMatcher` | Matching KNOWN vs NEW |
| `knowledge_matcher.py` | `TriageReportGenerator` | Triage report pro NEW |
| `formatter.py` | `IncidentReportFormatter` | Výstupní formáty |

## Root Cause pravidla

Systém používá deterministická pravidla (bez AI):

```python
ROOT_CAUSE_RULES = {
    'database': {
        'connection_pool': {
            'evidence': ['hikaripool', 'connection pool', 'no available connection'],
            'root_cause': 'Database connection pool exhausted',
            'fix': {
                'immediate': 'Restart affected pods',
                'config': 'spring.datasource.hikari.maximum-pool-size: 25',
                'permanent': 'Optimize slow queries, increase pool size'
            }
        },
        'deadlock': {
            'evidence': ['deadlock', 'lock wait timeout'],
            'root_cause': 'Database deadlock detected',
            'fix': {...}
        }
    },
    'timeout': {...},
    'network': {...},
    'auth': {...},
    'external': {...},
    'memory': {...}
}
```

## Exporty

```bash
# Výstupní adresář
reports/
├── incident_analysis_20260123_091500.txt   # Console format
├── incident_analysis_20260123_091500.md    # Markdown
├── incident_analysis_20260123_091500.json  # JSON
└── triage_20260123_091500.txt              # Triage report
```

## Integrace

### Slack

```bash
python analyze_incidents.py --mode 15min \
  --slack-webhook https://hooks.slack.com/services/XXX/YYY/ZZZ \
  --slack-channel "#alerts"
```

### Cron (15min run)

```bash
*/15 * * * * cd /path/to/project && python analyze_incidents.py --mode 15min --knowledge-dir ./knowledge --slack-webhook $SLACK_WEBHOOK
```

### Cron (daily report)

```bash
0 8 * * * cd /path/to/project && python analyze_incidents.py --mode daily --knowledge-dir ./knowledge
```

## Principy návrhu

1. **Incident-centric** - analyzujeme problémy, ne jednotlivé errory
2. **FACT vs HYPOTHESIS** - jasně oddělujeme detekované vs odvozené
3. **Priority** - "mám to řešit hned?" (P1-P4)
4. **IMMEDIATE ACTIONS** - 1-3 kroky pro SRE ve 3 ráno
5. **Report = renderer** - nic nepřepočítává, jen zobrazuje
6. **Knowledge base = human-managed** - žádná automatická magie
7. **15min ready** - max 1 obrazovka, co dělat TEĎ

## Verze

- **v5.1** (aktuální) - Priority, IMMEDIATE ACTIONS, finální model
- v5.0 - FACT vs HYPOTHESIS oddělení
- v4.0 - Knowledge base layer
- v3.0 - Incident Analysis engine
- v2.0 - Root cause inference
- v1.0 - Basic timeline

## Licence

Internal use only.
