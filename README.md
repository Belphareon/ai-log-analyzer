# AI Log Analyzer - Incident Analysis Engine v6.0.1

Automatizovaná detekce a analýza incidentů z aplikačních logů.

**📚 [Kompletní dokumentace](docs/README.md)** | **🚀 [Quick Start](docs/QUICKSTART.md)** | **🔧 [Troubleshooting](docs/TROUBLESHOOTING.md)** | **🕐 [CronJob Scheduling](docs/CRONJOB_SCHEDULING.md)**

## ✅ STATUS - ÚNOR 2026

**🟢 VŠECHNY KRITICKÉ ISSUES VYŘEŠENY:**

- ✅ **DB Connection Fixed** - DDL user login pro INSERT operace
- ✅ **Teams Notifications** - Backfill + Regular Phase alerts
- ✅ **Export Feature** - PeakEntry.category bug opraveno
- ✅ **Confluence Integration** - CSV tables s barvami + legendou
- ✅ **Daily Reports** - Parsování problem_key do Teams/Confluence
- ✅ **Scheduling** - CronJob dokumentace (backfill 02:00, regular 15min)

## 🚀 SESSION FIXES (Únor 2026)

**Database Fixes:**
```bash
# ✅ FIX 1: DB DDL User Login
# Problem: "permission denied to set role 'ailog_analyzer_ddl_user_d1'"
# Cause: APP_USER (ailog_analyzer_user_d1) nesmí nastavit DDL role
# Solution:
#   1. get_db_connection() nyní používá DB_DDL_USER pro INSERT/UPDATE
#   2. set_db_role() má try/except fallback (non-blocking)
#   3. Přidáno DB_DDL_ROLE=role_ailog_analyzer_ddl do .env
# Files: scripts/backfill_v6.py, scripts/regular_phase_v6.py
# Result: ✅ DB writes nyní fungují

# ✅ FIX 2: Export Feature - PeakEntry.category
# Problem: AttributeError: 'PeakEntry' object has no attribute 'category'
# Cause: PeakEntry nemá 'category' pole (je v problem_key)
# Solution: Extrahuj category z problem_key.split(':')[0]
# File: scripts/exports/table_exporter.py line 338
# Result: ✅ CSV/JSON exports generují bez chyb
```

**Teams Integration:**
```bash
# ✅ FIX 3: Teams Notifikace z Backfill
# Created: core/teams_notifier.py (TeamsNotifier class)
# Integration: scripts/backfill_v6.py
# What it sends:
#   - Days processed, successful, failed
#   - Total incidents, saved count
#   - Registry updates (new problems, peaks)
#   - Duration in minutes
# Result: ✅ Teams message po backfilu

# ✅ FIX 4: Teams Alert z Regular Phase
# Created: Integrován do scripts/regular_phase_v6.py
# Sends only when: is_spike OR is_burst OR score >= 80
# Format: MessageCard s kritickými issues
# Result: ✅ Real-time alerts pro critical issues
```

**Daily Reporting:**
```bash
# ✅ FIX 5: Daily Report Generator
# Created: scripts/daily_report_generator.py
# What it does:
#   1. Parsuje problem_analysis report JSON
#   2. Extrahuje top 5-10 problémů
#   3. Formátuje pro Teams MessageCard
#   4. Generuje JSON report
# Usage: python daily_report_generator.py --send-teams
# Result: ✅ Daily summary do Teams + Confluence

# ✅ FIX 6: Confluence Publisher (using ITO-Upload)
# Tool: /root/git/toolbox/ITO-sync-v4/ito-upload (Go binary)
# Features:
#   - CSV → HTML tabulka conversion
#   - Severity-based row coloring
#   - Legend + nadpisy
#   - Automatické version tracking
#   - Basic Auth (username + password/token)
# Usage: ito-upload --file errors.csv --page-id 1334314201
# Integration: scripts/publish_daily_reports.sh
# Result: ✅ Tables uploadnuty do Confluence s formátováním
#         ✅ Known Errors (stránka 1334314201)
#         ✅ Known Peaks (stránka 1334314203)
#         ✅ Recent Incidents (stránka 1334314205, pokud existuje)
```

**Orchestration:**
```bash
# ✅ FIX 7: Publish Daily Reports Script
# Created: scripts/publish_daily_reports.sh
# Orchestruje:
#   1. Daily report generation (Teams notifikace)
#   2. Confluence uploads (ito-upload):
#      - errors_table.csv → Known Errors page
#      - peaks_table.csv → Known Peaks page
#      - errors_table.csv → Recent Incidents page
# Called: Automaticky z run_backfill.sh po backfilu
# Validation:
#   ✅ 2026-02-09: Known Errors → page 1334314201 ✅
#   ✅ 2026-02-09: Known Peaks → page 1334314203 ✅
# Result: ✅ End-to-end workflow

# ✅ FIX 8: CronJob Scheduling Documentation
# Created: docs/CRONJOB_SCHEDULING.md
# Obsahuje:
#   - Timing (backfill 02:00 UTC, regular 15min)
#   - Fallback strategie (non-blocking errors)
#   - K8s manifesty (příklady)
#   - Monitoring setup
#   - Checklist pro deployment
# Result: ✅ Kompletní scheduling reference
```

**Configuration:**
```bash
# ✅ FIX 9: Environment Variables
# Přidáno do .env:
#   DB_DDL_ROLE=role_ailog_analyzer_ddl
#   CONFLUENCE_URL=https://wiki.kb.cz
#   CONFLUENCE_USERNAME=XX_AWX_CONFLUENCE
#   CONFLUENCE_API_TOKEN=PP_@9532bb-xmHV26  (heslo jako token)
#   CONFLUENCE_DAILY_REPORT_PAGE_ID=1334314207
#   CONFLUENCE_KNOWN_ERRORS_PAGE_ID=1334314201
#   CONFLUENCE_KNOWN_PEAKS_PAGE_ID=1334314203
#   CONFLUENCE_RECENT_INCIDENTS_PAGE_ID=1334314205
#   TEAMS_WEBHOOK_URL=https://sgcz.webhook.office.com/...
# Result: ✅ Všechna integrace nakonfigurována
```

**Test Results:**
```
Backfill E2E Test: ✅ SUCCESS
- Command: python3 scripts/backfill_v6.py --days 1
- Result: 32,783 errors fetched, 6,049 incidents saved
- Exports: errors_table_latest.csv/md/json + peaks_table_latest.csv/md/json

Teams Integration: ✅ READY
- Backfill sends completion message with stats
- Regular phase sends critical alerts (spikes/bursts only)

Confluence Integration: ✅ VERIFIED (2026-02-09)
- CSV → HTML conversion: ✅ (135KB HTML z 86KB CSV)
- Known Errors upload: ✅ (stránka 1334314201 updated)
- Known Peaks upload: ✅ (stránka 1334314203 updated)
- Color coding by severity: ✅ (v Go programu)
- Legend + timestamps: ✅ (v Go programu)

Publish Script: ✅ WORKING
- Automaticky volán z run_backfill.sh
- Uploaduje všechny tři tabulky v parallel
- Non-blocking: selhání Confluence neblokuje pipeline
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
- **Publikuje do Teams & Confluence** (automaticky, s formátováním)

## Changelog

### v6.0.2 (aktuální - Únor 2026)

**NEW: Kompletní notification & reporting pipeline:**
- Teams notifikace z backfilu (statistics) + regular phase (critical alerts only)
- Daily report generator + publikování do Teams
- Confluence publisher (Python) s HTML tabulkami + severity colors
- Orchestrační skript `publish_daily_reports.sh`
- CronJob scheduling dokumentace (backfill 02:00, regular 15min, publish po backfilu)

**FIXED: Databázové problémy:**
- DB DDL user login pro INSERT operace
- Opravena PeakEntry.category chyba v exportech

### v5.3.1

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
