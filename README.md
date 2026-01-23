# AI Log Analyzer - Incident Analysis Engine v5.3

Automatizovaná detekce a analýza incidentů z aplikačních logů.

## Přehled

Systém analyzuje error logy z Elasticsearch/PostgreSQL a automaticky:
- Detekuje anomálie (spiky, bursty, nové errory) pomocí EWMA/MAD statistik
- Seskupuje související události do incidentů
- **Klasifikuje role aplikací** (root → downstream → collateral)
- **Sleduje propagaci** (jak rychle se incident šířil)
- Určuje root cause pomocí deterministických pravidel (bez LLM)
- Navrhuje konkrétní opravy s kontextovými akcemi
- Rozlišuje známé vs nové incidenty (knowledge base)
- Generuje operační reporty (15min / daily / backfill)

## Changelog

### v5.3 (aktuální)

**Strukturované role aplikací:**
- `IncidentScope.root_apps` - aplikace která je příčinou
- `IncidentScope.downstream_apps` - aplikace ovlivněné do 60s
- `IncidentScope.collateral_apps` - vedlejší poškození (po 60s)

**Propagation tracking:**
- `propagated` - incident se rozšířil?
- `propagation_time_sec` - jak rychle?
- `propagation_path` - cesta šíření
- Rychlá propagace (<30s) automaticky eskaluje na P1

**Context-aware actions:**
- Lokální incident → jednodušší diagnostika
- Fast propagation → URGENT akce
- Version change → review deployment
- KNOWN incident → "No immediate action - known stable issue"

**Opravy:**
- Semver-aware version sorting (1.10.0 > 1.9.0 správně)
- HYPOTHESIS zobrazena jen při confidence ≥ MEDIUM

### v5.2

- Fingerprint = `category|subcategory|normalized_message`
- Baseline = None pro 15min mode
- Grouping podle mode (15min vs daily)
- Priority přepočet po knowledge matching
- Duplicitní TOP INCIDENTS → agregace do Operational Incidents
- Rozšířená kategorizace (~30 nových pattern rules)

### v5.1

- Priority systém (P1-P4)
- IMMEDIATE ACTIONS (1-3 kroky pro SRE)
- FACT vs HYPOTHESIS oddělení

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
│  • ScopeBuilder - klasifikace rolí aplikací (v5.3)             │
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

## Struktura projektu

```
ai-log-analyzer/
├── analyze_incidents.py           # CLI vstupní bod
├── incident_analysis/             # Hlavní modul v5.3
│   ├── __init__.py
│   ├── models.py                  # Datové modely, calculate_priority()
│   ├── analyzer.py                # IncidentAnalysisEngine
│   ├── timeline_builder.py        # TimelineBuilder
│   ├── causal_inference.py        # CausalInferenceEngine
│   ├── fix_recommender.py         # FixRecommender
│   ├── knowledge_base.py          # KnowledgeBase loader
│   ├── knowledge_matcher.py       # KnowledgeMatcher
│   └── formatter.py               # IncidentReportFormatter
├── scripts/
│   ├── regular_phase_v5.3.py      # 15min orchestrace s analysis
│   ├── backfill_v5.3.py           # Daily orchestrace s analysis
│   ├── regular_phase.py           # Legacy (bez analysis)
│   ├── backfill.py                # Legacy (bez analysis)
│   └── v4/                        # Pipeline (detekce)
├── config/
│   ├── known_issues/              # Knowledge base (YAML)
│   │   ├── known_errors.yaml
│   │   ├── known_peaks.yaml
│   │   └── known_issues.yaml
│   └── namespaces.yaml
├── knowledge/                     # Templates pro KB
├── docs/
│   ├── ADD_APPLICATION_VERSION.md
│   ├── PIPELINE_V4_ARCHITECTURE.md
│   └── ...
└── requirements.txt
```

## Instalace

```bash
# Závislosti
pip install psycopg2-binary python-dotenv requests pyyaml

# Konfigurace
cp config/.env.example config/.env
# Upravit DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
```

## Použití

### Standalone analýza

```bash
# 15min mode (default)
python analyze_incidents.py --mode 15min --knowledge-dir config/known_issues

# Daily mode
python analyze_incidents.py --mode daily --date 2026-01-22

# Backfill
python analyze_incidents.py --mode backfill --days 7

# Jen critical/high
python analyze_incidents.py --mode 15min --only-critical

# S odesláním do Slacku
python analyze_incidents.py --mode 15min --slack-webhook https://hooks.slack.com/...
```

### Orchestrovaný běh (s pipeline)

```bash
# 15min cyklus (fetch → pipeline → DB → analysis → report)
python scripts/regular_phase_v5.3.py

# Backfill N dní
python scripts/backfill_v5.3.py --days 7

# Bez analýzy (jen pipeline)
python scripts/regular_phase_v5.3.py --no-analysis
```

### Cron

```bash
# 15min operační report
*/15 * * * * cd /path/to/project && python scripts/regular_phase_v5.3.py

# Daily report (8:00)
0 8 * * * cd /path/to/project && python analyze_incidents.py --mode daily
```

## Formát reportu (v5.3)

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
  • Root: order-service
  • Downstream: payment-service, gateway
  • Collateral: notification-service
  • Errors: 1,234 | Peak: 15.2x baseline
  • ⚡ PROPAGATED in 25s across 4 apps
  • ⚠️ VERSION CHANGE: order-service (1.8.3 → 1.8.4)

HYPOTHESIS:
  [?] Insufficient data for reliable root cause inference

STATUS: NEW - requires triage

IMMEDIATE ACTIONS:
  1. URGENT: Fast propagation detected (25s) - check order-service
  2. Review recent deployment of order-service (1.8.3 → 1.8.4)
  3. Check DB connection pool on order-service

────────────────────────────────────────────────────────────
🟠 [P3] 📚 KNOWN INCIDENT (09:05–09:10) [KE-002]
────────────────────────────────────────────────────────────

FACTS:
  • auth-service: Token validation failed
  • Root: auth-service
  • Errors: 234 | Peak: 3.1x baseline
  • ✓ Localized (single app)

HYPOTHESIS:
  [✓] External OAuth provider intermittent issues

STATUS: Known issue KE-002
  Jira: OPS-445

IMMEDIATE ACTIONS:
  1. No immediate action - known stable issue
```

## Klíčové koncepty

### Priority vs Severity

| Koncept | Význam | Hodnoty |
|---------|--------|---------|
| **Severity** | DOPAD (jak moc to bolí) | CRITICAL, HIGH, MEDIUM, LOW |
| **Priority** | AKČNOST (mám to řešit hned?) | P1, P2, P3, P4 |

### Priority pravidla (v5.3)

```
P1: NEW AND (CRITICAL OR cross-app ≥3 OR fast_propagation <30s)
P2: KNOWN AND worsening
P2: NEW AND not critical
P3: KNOWN AND stable
P4: ostatní
```

### Role aplikací (v5.3)

```
Root        = aplikace s první chybou (nebo nejvíc errory při shodném čase)
Downstream  = aplikace zasažené do 60s od root
Collateral  = aplikace zasažené po 60s (vedlejší poškození)
```

### FACT vs HYPOTHESIS

- **FACTS** = detekované události (co se stalo) - vždy zobrazeny
- **HYPOTHESIS** = odvozený root cause (proč) - jen při confidence ≥ MEDIUM

### Known vs New

- **KNOWN** = incident matchuje záznam v knowledge base → P3
- **NEW** = incident vyžaduje triage → P1/P2

## Knowledge Base

### Struktura

```yaml
# config/known_issues/known_errors.yaml
- id: KE-001
  fingerprint: database|connection_pool|hikaripool.*connection
  category: DATABASE
  description: Order-service DB connection pool exhaustion
  affected_apps:
    - order-service
    - payment-service
  jira: OPS-431
  status: OPEN
  workaround:
    - Restart order-service pod
```

### Workflow

```
1. Report označí incident jako NEW → P1/P2
2. Člověk vyšetří, vytvoří Jira, zapíše do KB
3. Další běhy hlásí KNOWN → P3
```

## Komponenty

| Soubor | Třída | Popis |
|--------|-------|-------|
| `models.py` | `IncidentAnalysis` | Hlavní datový model |
| `models.py` | `IncidentScope` | Scope s rolemi (v5.3) |
| `models.py` | `calculate_priority()` | Výpočet P1-P4 |
| `analyzer.py` | `IncidentAnalysisEngine` | Hlavní engine |
| `timeline_builder.py` | `TimelineBuilder` | Staví časovou osu |
| `causal_inference.py` | `CausalInferenceEngine` | Root cause inference |
| `fix_recommender.py` | `FixRecommender` | Generuje opravy |
| `knowledge_base.py` | `KnowledgeBase` | YAML/MD loader |
| `knowledge_matcher.py` | `KnowledgeMatcher` | KNOWN vs NEW |
| `formatter.py` | `IncidentReportFormatter` | Výstupní formáty |

## Známé limity

| Limit | Důvod | Workaround |
|-------|-------|------------|
| Hypothesis je slabá | Chybí traceID, dependency graph | Zobrazuj jen při confidence ≥ MEDIUM |
| Score není v reportu | Záměrně - je jen ordering hint | Používej priority místo score |
| Chybí application.version | Pole není v ES | Viz `docs/ADD_APPLICATION_VERSION.md` |

## Principy návrhu

1. **Incident-centric** - analyzujeme problémy, ne jednotlivé errory
2. **FACT vs HYPOTHESIS** - jasně oddělujeme detekované vs odvozené
3. **Priority** - "mám to řešit hned?" (P1-P4)
4. **IMMEDIATE ACTIONS** - 1-3 kroky pro SRE ve 3 ráno, context-aware
5. **Report = renderer** - nic nepřepočítává, jen zobrazuje
6. **Knowledge base = human-managed** - žádná automatická magie
7. **15min ready** - max 1 obrazovka, co dělat TEĎ
8. **Role clarity** - kdo je root, kdo je downstream, kdo collateral

## Licence

Internal use only.
