# AI Log Analyzer - Incident Analysis Engine v6.0.1

Automatizovaná detekce a analýza incidentů z aplikačních logů.

**📚 [Kompletní dokumentace](docs/README.md)** | **🚀 [Quick Start](docs/QUICKSTART.md)** | **🔧 [Troubleshooting](docs/TROUBLESHOOTING.md)**

## 🔴 KNOWN ISSUES (Únor 2026)

**Non-Critical Issues** (neblokují core funkcionalitu):
- ⚠️ **Teams notifications**: Module `core/teams_notifier.py` vytvořen, ale import fallback v `main()` nefunguje (ModuleNotFoundError)
  - Impact: Backfill běží, ale Teams notifikace se neposílají
  - Workaround: Backfill core functionality (DB save) funguje bez problémů
  
- ⚠️ **Export feature**: `table_exporter.py` error - `'PeakEntry' object has no attribute 'category'`
  - Impact: Export to CSV/JSON/Markdown nefunguje
  - Workaround: Core incident processing (Elasticsearch → DB) funguje
  
**Resolution Plan:**
- [ ] Vyřešit Teams import (move get_notifier() to module level?)
- [ ] Fix PeakEntry dataclass definition
- [ ] Test regular_phase v K8s

## 🚀 Recent Fixes (Únor 2026 - SESSION)

**Infrastructure Fixes:**
```bash
# ✅ FIX 1: PostgreSQL Driver
# Problem: ModuleNotFoundError: No module named 'psycopg2'
# Solution:
apt-get install python3-psycopg2  # Install system-wide
# Result: ✅ Backfill saves to DB successfully

# ✅ FIX 2: K8s Paths
# File: sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/templates/cronjob.yaml
# Changes:
#   - python → python3
#   - scripts/regular_phase_v6.py → /app/scripts/regular_phase_v6.py  
#   - Added TEAMS_WEBHOOK_URL env var

# ✅ FIX 3: Timezone Bugs
# File: scripts/exports/table_exporter.py
# Changes:
#   Line 118: datetime.now() → datetime.now(timezone.utc)
#   Line 127: datetime.now() → datetime.now(timezone.utc)
#   Line 556: Added .replace(tzinfo=timezone.utc)
# Result: ✅ Offset-naive/aware datetime errors fixed

# ✅ FIX 4: Teams Webhook Configuration  
# Files: .env, values.yaml, cronjob.yaml
# Added: TEAMS_WEBHOOK_URL environment variable
# Result: ✅ Config ready (import issue prevents testing)
```

**Test Results:**
```
Backfill E2E Test: ✅ SUCCESS
- Command: python3 scripts/backfill_v6.py --days 4 --workers 4
- Result: 236,419 incidents saved to DB
- Registry: 299 problems, 65 peaks updated

Single-day Test: ✅ SUCCESS  
- Command: python3 scripts/backfill_v6.py --days 1 --workers 1 --force
- Result: 58,692 incidents saved to DB
```

## Přehled

Systém analyzuje error logy z Elasticsearch/PostgreSQL a automaticky:
- Detekuje anomálie (spiky, bursty, nové errory) pomocí EWMA/MAD statistik
- Seskupuje související události do incidentů
- **Klasifikuje role aplikací** (root → downstream → collateral)
- **Sleduje propagaci** (jak rychle se incident šířil)
- Určuje root cause pomocí deterministických pravidel (bez LLM)
- Navrhuje konkrétní opravy s kontextovými akcemi
- Rozlišuje známé vs nové incidenty (knowledge base)
- **Aktualizuje append-only registry** (known_errors, known_peaks)
- Generuje operační reporty (15min / daily / backfill)

## Changelog

### v5.3.1 (aktuální)

**Architektonická oprava - oddělení Scope a Propagation:**
```python
# PŘED (špatně) - propagation bylo v scope
class IncidentScope:
    propagated: bool  # ❌ Propagation není Scope!

# PO (správně) - samostatné dataclasses
class IncidentScope:      # KDE se to projevilo
    apps, root_apps, downstream_apps, collateral_apps

class IncidentPropagation:  # JAK se to šířilo
    propagated, propagation_time_sec, propagation_path

class IncidentAnalysis:
    scope: IncidentScope
    propagation: IncidentPropagation  # ← nové pole
```

**Report generation fix:**
- Report se generuje VŽDY (i když nejsou incidenty)
- Odstraněna podmínka `total_incidents > 0`
- Přidán `output_dir` parametr
- Reporty se ukládají do `scripts/reports/`

**Append-only Registry:**
```
registry/
├─ known_errors.yaml    ← Strojový formát
├─ known_errors.md      ← Human-readable
├─ known_peaks.yaml
└─ known_peaks.md
```
- Nikdy se nemaže, pouze přidává
- Nový fingerprint → nový záznam
- Existující fingerprint → aktualizuje `last_seen`, `occurrences++`
- Řazení od nejnovějšího (`last_seen DESC`)

### v5.3

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

### v5.1

- Priority systém (P1-P4)
- IMMEDIATE ACTIONS (1-3 kroky pro SRE)
- FACT vs HYPOTHESIS oddělení

## Architektura

```
┌─────────────────────────────────────────────────────────────────┐
│                     1. DETECTION (fakta)                        │
│  • Statistické výpočty (EWMA, MAD)                             │
│  • Detekce peaků, spiků, burstů                                │
│  • Fingerprinting errorů                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  2. INCIDENT ANALYSIS (kauzalita)               │
│  • TimelineBuilder - jak se problém šířil (FACTS)              │
│  • ScopeBuilder - klasifikace rolí aplikací                    │
│  • PropagationTracker - sledování šíření                       │
│  • CausalInferenceEngine - proč (HYPOTHESIS)                   │
│  • FixRecommender - konkrétní opravy                           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│               3. KNOWLEDGE MATCHING (known vs new)              │
│  • KnowledgeBase loader (YAML + MD)                            │
│  • KnowledgeMatcher (fingerprint → cluster → pattern)          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              4. REGISTRY UPDATE (append-only)                   │
│  • Nový fingerprint → nový záznam                              │
│  • Existující → aktualizuj last_seen, occurrences++            │
│  • NIKDY se nic nemaže                                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   5. REPORTING (výstup)                         │
│  • 15min mode - operační (max 1 obrazovka)                     │
│  • Daily mode - přehled (trendy, agregace)                     │
│  • Report se generuje VŽDY (i prázdný)                         │
└─────────────────────────────────────────────────────────────────┘
```

## Struktura projektu

```
ai-log-analyzer/
├── analyze_incidents.py           # CLI vstupní bod
├── incident_analysis/             # Hlavní modul v5.3.1
│   ├── models.py                  # IncidentScope, IncidentPropagation
│   ├── analyzer.py                # IncidentAnalysisEngine
│   ├── formatter.py               # IncidentReportFormatter
│   └── ...
├── scripts/
│   ├── regular_phase_v5.3.py      # 15min orchestrace
│   ├── backfill_v5.3.py           # Daily orchestrace
│   └── reports/                   # Výstupní reporty
├── registry/                      # Append-only evidence
│   ├── known_errors.yaml
│   ├── known_errors.md
│   ├── known_peaks.yaml
│   └── known_peaks.md
├── config/known_issues/           # Knowledge base (manuální)
└── docs/
```

## Instalace

```bash
pip install psycopg2-binary python-dotenv requests pyyaml
cp config/.env.example config/.env
```

## Použití

```bash
# 15min cyklus (report se uloží do scripts/reports/)
python scripts/regular_phase_v5.3.py

# Backfill N dní
python scripts/backfill_v5.3.py --days 7

# Standalone analýza
python analyze_incidents.py --mode 15min --knowledge-dir config/known_issues
```

## Výstupní soubory

```
scripts/reports/incident_analysis_15min_*.txt   # Každých 15min
registry/known_errors.yaml                       # Aktualizováno při každém běhu
registry/known_errors.md                         # Human-readable verze
```

## Registry formát

```yaml
- id: KE-000001
  fingerprint: 9fa2c41e8c3a1b2d
  category: DATABASE
  first_seen: "2026-01-23T09:12:41"
  last_seen: "2026-01-27T14:55:02"
  occurrences: 187
  affected_apps: [order-service, payment-service]
  status: OPEN
  jira: null          # vyplňuje člověk
  notes: null         # vyplňuje člověk
```

## Klíčové koncepty

### Datový model (v5.3.1)

```python
class IncidentAnalysis:
    scope: IncidentScope          # KDE (apps, roles)
    propagation: IncidentPropagation  # JAK (šíření)
    priority: IncidentPriority    # P1-P4
```

### Priority pravidla

```
P1: NEW AND (CRITICAL OR cross-app ≥3 OR fast_propagation <30s)
P2: NEW AND not critical
P3: KNOWN AND stable
P4: ostatní
```

### Role aplikací

```
Root        = aplikace s první chybou
Downstream  = aplikace zasažené do 60s od root
Collateral  = aplikace zasažené po 60s
```

## Principy návrhu

1. **Report VŽDY** - i prázdný
2. **Registry = append-only** - nikdy se nemaže
3. **Scope ≠ Propagation** - oddělené koncepty
4. **FACT vs HYPOTHESIS** - jasně oddělené
5. **15min ready** - max 1 obrazovka

## Licence

Internal use only.
