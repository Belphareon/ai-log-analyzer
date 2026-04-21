# AI Log Analyzer

Automatizovaný systém pro detekci, klasifikaci a eskalaci chybových incidentů z aplikačních logů v Kubernetes.

**[Jak to funguje](docs/HOW_IT_WORKS.md)** | **[Architektura](docs/ARCHITECTURE.md)** | **[Instalace](docs/INSTALLATION.md)** | **[Provoz](docs/OPERATIONS.md)** | **[Troubleshooting](docs/TROUBLESHOOTING.md)** | **[Telemetrie](docs/TELEMETRY.md)** | **[Testování](docs/TESTING.md)** | **[Changelog](CHANGELOG.md)**

---

## Co program dělá

Systém každých 15 minut načte error logy ze sledovaných Kubernetes namespace z Elasticsearch a automaticky:

1. **Detekuje anomálie** — porovní aktuální počty chyb s historickým P93/CAP prahem; odhalí spike, burst, nový typ chyby nebo regresi
2. **Identifikuje** — každá chyba dostane `fingerprint` (hash), je zařazena do kategorie a přiřazena k business flow
3. **Určí, co je nové vs. známé** — registry drží historii všech dříve viděných problémů
4. **Vyhodnotí závažnost** — deterministické bodování 0–100
5. **Notifikuje** — při peaku odešle digest email + volitelně Teams
6. **Aktualizuje Confluence** — Known Errors, Known Peaks a Recent Incidents tabulky
7. **Sbírá historická data** — ukládá surové počty chyb pro zpětný přepočet P93/CAP prahů

---

## Rychlý start

### Kubernetes (produkce)

```bash
# 1. Vyplnit .env.example → .env (credentials, registry, prostředí)
cp .env.example .env && vi .env

# 2. Spustit install.sh — validuje → DB migrace → Docker build+push → K8s manifesty → git branch+push
./install.sh

# 3. Po merge PR → ArgoCD sync → spustit init job
kubectl create job log-analyzer-init --from=cronjob/log-analyzer-backfill -n ai-log-analyzer
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

Kompletní postup → [docs/INSTALLATION.md](docs/INSTALLATION.md)

### Lokální testování

```bash
cp .env.example .env
# Vyplnit credentials (DB, ES, Confluence, Teams)

python3 scripts/regular_phase.py --window 15 --dry-run
```

---

## K8s CronJoby

| CronJob | Schedule | Popis |
|---------|----------|-------|
| `log-analyzer` | `*/15 * * * *` | Hlavní pipeline: fetch → detect → alert → export |
| `log-analyzer-backfill` | `0 9 * * *` | Denní backfill + Confluence publish |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP |

Detaily → [docs/OPERATIONS.md](docs/OPERATIONS.md)

---

## Konfigurace

### K8s deployment (produkce)

Hlavní konfigurace: `k8s/values.yaml` (šablona) → kopie v `k8s-infra-apps-<env>/infra-apps/ai-log-analyzer/values.yaml`.

Credentials: CyberArk (EPV) safe → Conjur secrets provider → K8s Secret.

### Lokální vývoj

`.env` soubor — šablona v `.env.example`. V K8s se nepoužívá.

| Skupina | Proměnné |
|---------|----------|
| Elasticsearch | `ES_HOST`, `ES_INDEX`, `ES_USER`, `ES_PASSWORD` |
| PostgreSQL | `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` |
| PostgreSQL DDL | `DB_DDL_USER`, `DB_DDL_PASSWORD`, `DB_DDL_ROLE` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `EMAIL_FROM`, `TEAMS_EMAIL` |
| Teams | `TEAMS_WEBHOOK_URL` |
| Confluence | `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_TOKEN` |
| Alertování | `ALERT_DIGEST_ENABLED`, `ALERT_COOLDOWN_MIN`, `ALERT_HEARTBEAT_MIN` |
| Detekce | `PERCENTILE_LEVEL`, `DEFAULT_THRESHOLD`, `EWMA_ALPHA` |

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
| Stav alertů | `registry/alert_state_regular_phase.json` | Cooldown, trend, počet alertů |
| Sledované namespace | `config/namespaces.yaml` | Seznam namespace pro monitoring |

---

## Struktura projektu

```
ai-log-analyzer/
├── scripts/
│   ├── regular_phase.py            # Hlavní 15min pipeline — entry point
│   ├── backfill.py                 # Historický backfill
│   ├── core/
│   │   ├── email_notifier.py       # Email notifikace (digest + detail)
│   │   ├── problem_registry.py     # Registry: problem + fingerprint index
│   │   ├── peak_detection.py       # P93/CAP spike detektor
│   │   ├── calculate_peak_thresholds.py  # Výpočet P93/CAP, zápis do DB
│   │   ├── baseline_loader.py      # Historický baseline z DB
│   │   ├── fetch_unlimited.py      # Elasticsearch fetcher
│   │   └── teams_notifier.py       # Microsoft Teams integrace
│   ├── pipeline/                   # Detection pipeline (6 fází: A–F)
│   ├── exports/
│   │   └── table_exporter.py       # CSV/MD/JSON export pro Confluence
│   └── analysis/                   # Agregace incidentů do problémů
├── incident_analysis/              # Kauzální analýza incidentů
├── registry/                       # Append-only YAML evidence (live data)
├── config/
│   ├── namespaces.yaml             # Sledované namespace
│   └── known_issues/               # Manuální knowledge base
├── docs/                           # Dokumentace
├── k8s/                            # Helm šablony pro K8s CronJoby
│   ├── values.yaml                 # Konfigurační šablona
│   └── templates/
│       ├── cronjob.yaml            # Regular + Backfill + Threshold CronJoby
│       ├── job-init.yaml           # Bootstrap job
│       ├── pvc.yaml                # Persistent Volume Claim
│       ├── secrets.yaml            # Conjur secret mapping
│       └── serviceaccount.yaml     # ServiceAccount + RBAC
├── .env.example                    # Template pro konfiguraci
└── install.sh                       # Instalační orchestrace (DB + Docker + K8s + git)
```

---

## Dokumentace

| Dokument | Popis |
|----------|-------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Komponenty, datové toky, DB schéma, integrace |
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Celý proces krok za krokem |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Prerekvizity, CyberArk, DB setup, K8s deployment |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | K8s CronJoby, alerting tuning, namespace management |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Řešení častých problémů |
| [docs/TELEMETRY.md](docs/TELEMETRY.md) | Telemetrie a metriky |
| [docs/TESTING.md](docs/TESTING.md) | Testovací průvodce |
| [CHANGELOG.md](CHANGELOG.md) | Historie všech verzí |

---

## Licence

Internal use only.
