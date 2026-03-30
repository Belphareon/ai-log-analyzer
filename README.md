# AI Log Analyzer

Automatizovaný systém pro detekci, klasifikaci a eskalaci chybových incidentů z aplikačních logů v Kubernetes.

**[Jak to funguje](docs/HOW_IT_WORKS.md)** | **[Architektura](docs/ARCHITECTURE.md)** | **[Instalace](docs/INSTALLATION.md)** | **[Provoz](docs/OPERATIONS.md)** | **[Troubleshooting](docs/TROUBLESHOOTING.md)** | **[Changelog](CHANGELOG.md)**

---

## Co program dělá

Systém každých 15 minut načte error logy ze všech sledovaných Kubernetes namespace z Elasticsearch a automaticky:

1. **Detekuje anomálie** — porovní aktuální počty chyb s historickým P93/CAP prahem; odhalí spike, burst, nový typ chyby nebo regresi
2. **Identifikuje** — každá chyba dostane `fingerprint` (hash), je zařazena do kategorie (BUSINESS, AUTH, DATABASE, NETWORK, TIMEOUT, MEMORY, EXTERNAL) a přiřazena k business flow
3. **Určí, co je nové vs. co je známé** — registry drží historii všech dříve viděných problémů; nová chyba = alert, opakující se = monitoring + aktualizace statistik
4. **Vyhodnotí závažnost** — deterministické bodování 0–100 (spike +25, burst +20, nový +15, regrese +35, cross-namespace +15)
5. **Notifikuje** — při peaku odešle digest email s přehledem všech aktivních incidentů a volitelně zprávu do Microsoft Teams
6. **Aktualizuje Confluence** — Known Errors a Known Peaks tabulky se průběžně aktualizují
7. **Sbírá historická data** — každý běh ukládá surové počty chyb do DB, ze kterých se zpětně přepočítávají P93/CAP prahy

---

## Rychlý start

```bash
# Kopie konfigurace
cp .env.example .env
# Vyplnit hodnoty v .env (ES_URL, DB_HOST, SMTP_HOST, ...)

# Jednorázové spuštění 15min cyklu
python3 scripts/regular_phase.py

# Backfill — zpracování historických dat
python3 scripts/backfill.py --days 7

# Přepočet P93/CAP thresholdů (po nahromadění ≥2 týdny dat)
python3 scripts/core/calculate_peak_thresholds.py
```

V produkci běží jako Kubernetes CronJob — viz [docs/INSTALLATION.md](docs/INSTALLATION.md).

---

## Konfigurace

Program je konfigurován přes `.env` soubor. Kompletní šablona je v `.env.example`.

| Skupina | Proměnné |
|---------|----------|
| Elasticsearch | `ES_URL`, `ES_INDEX`, `ES_USER`, `ES_PASSWORD`, `ES_VERIFY_CERTS` |
| PostgreSQL (čtení) | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| PostgreSQL (zápis) | `DB_DDL_USER`, `DB_DDL_PASSWORD`, `DB_DDL_ROLE` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM`, `TEAMS_EMAIL` |
| Teams | `TEAMS_WEBHOOK_URL` |
| Confluence | `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN` |
| Alertování | `ALERT_DIGEST_ENABLED`, `ALERT_COOLDOWN_MIN`, `ALERT_HEARTBEAT_MIN`, `MAX_PEAK_ALERTS_PER_WINDOW` |
| Detekce | `MIN_NAMESPACE_PEAK_VALUE`, `PERCENTILE_LEVEL`, `EWMA_ALPHA` |

---

## Kde jsou data uložena

| Typ dat | Uložiště | Popis |
|---------|----------|-------|
| Surové počty chyb | DB `ailog_peak.peak_raw_data` | Vstupní data pro výpočet P93/CAP |
| P93 prahy | DB `ailog_peak.peak_thresholds` | Per (namespace, day_of_week) |
| CAP prahy | DB `ailog_peak.peak_threshold_caps` | Per namespace |
| Evidované peaky | DB `ailog_peak.peak_investigation` | Pro Confluence reporty |
| Známé problémy | `registry/known_problems.yaml` | Append-only, nikdy se nemaže |
| Známé peaky | `registry/known_peaks.yaml` | Append-only, nikdy se nemaže |
| Index fingerprintů | `registry/fingerprint_index.yaml` | Lookup: fingerprint → problem_key |
| Stav alertů | `registry/alert_state_regular_phase.json` | Cooldown, trend, počet alertů per okno |
| Sledované namespace | `config/namespaces.yaml` | Seznam namespace pro monitoring |
| Manuální knowledge base | `config/known_issues/*.yaml` | Lidský kontext ke známým problémům |

---

## Struktura projektu

```
ai-log-analyzer/
├── scripts/
│   ├── regular_phase.py            # Hlavní 15min pipeline — entry point
│   ├── backfill.py                 # Historický backfill
│   ├── core/
│   │   ├── email_notifier.py       # Email notifikace (digest + detail)
│   │   ├── problem_registry.py     # Registry: problem + fingerprint index + klasifikace
│   │   ├── peak_detection.py       # P93/CAP spike detektor (čte z DB)
│   │   ├── calculate_peak_thresholds.py  # Výpočet P93/CAP, zápis do DB
│   │   ├── baseline_loader.py      # Načítání historického baseline z DB
│   │   ├── fetch_unlimited.py      # Elasticsearch fetcher (stránkovaný)
│   │   └── teams_notifier.py       # Microsoft Teams integrace
│   ├── pipeline/
│   │   ├── phase_a_parse.py        # Parse & Normalize, fingerprinting
│   │   ├── phase_b_measure.py      # EWMA/MAD statistiky, baseline
│   │   ├── phase_c_detect.py       # Detekce (spike/burst/new/regression)
│   │   ├── phase_d_score.py        # Skórování 0–100
│   │   ├── phase_e_classify.py     # Taxonomická klasifikace
│   │   └── phase_f_report.py       # Formátování výstupu
│   ├── exports/
│   │   └── table_exporter.py       # CSV/MD/JSON export pro Confluence
│   └── analysis/
│       ├── problem_aggregator.py   # Agregace incidentů do problémů
│       └── problem_report.py       # Formátování reportu
├── incident_analysis/
│   ├── analyzer.py                 # IncidentAnalysisEngine
│   ├── timeline_builder.py         # Časová osa incidentů
│   ├── causal_inference.py         # Kauzální dedukce (deterministická)
│   └── fix_recommender.py          # Doporučené akce pro SRE
├── registry/                       # Append-only YAML evidence (live data, není v gitu)
├── config/
│   ├── namespaces.yaml             # Sledované namespace
│   └── known_issues/               # Manuální knowledge base
├── docs/                           # Dokumentace
│   ├── ARCHITECTURE.md             # Technická architektura
│   ├── HOW_IT_WORKS.md             # Detailní popis procesu
│   ├── INSTALLATION.md             # Instalace a deployment
│   ├── OPERATIONS.md               # Provoz, CronJoby, tuning
│   ├── TROUBLESHOOTING.md          # Řešení problémů
│   ├── TELEMETRY.md                # Telemetrie a metriky
│   └── TESTING.md                  # Testovací průvodce
└── k8s/                            # Kubernetes CronJob manifesty
```

---

## Dokumentace

| Dokument | Popis |
|----------|-------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Komponenty, datové toky, DB schéma, integrace |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Celý proces krok za krokem: fetch → detect → alert |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Prerekvizity, krok za krokem, K8s deployment |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | CronJoby, alerting tuning, přidání namespace, přepočet thresholdů |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Řešení častých problémů |
| [docs/TELEMETRY.md](docs/TELEMETRY.md) | Telemetrie a metriky |
| [docs/TESTING.md](docs/TESTING.md) | Testovací průvodce |
| [CHANGELOG.md](CHANGELOG.md) | Historie všech verzí (r40–r62+) |

---

## Licence

Internal use only.
