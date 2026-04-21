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
5. **Clusteruje** — problémy se stejným trace flow nebo error class se sloučí do jednoho alertu
6. **Notifikuje** — při peaku odešle digest email + volitelně Teams
7. **Aktualizuje Confluence** — Known Errors, Known Peaks a Recent Incidents tabulky
8. **Sbírá historická data** — ukládá surové počty chyb pro zpětný přepočet P93/CAP prahů

---

## Prerekvizity

| Prerekvizita | Popis |
|-------------|-------|
| **PostgreSQL** | Databáze `ailog_analyzer`, schéma `ailog_peak`, DDL+App user/role |
| **Elasticsearch** | Read-only přístup k aplikačním logům (`cluster-app_*`) |
| **CyberArk (SPEED)** | Safe s credentials (DB, ES, Confluence) + Application Identity v PSIAM |
| **Confluence** | Služební účet + 3 stránky (Known Errors, Known Peaks, Recent Incidents) |
| **Email/SMTP** | SMTP relay dostupný z K8s clusteru |
| **K8s namespace** | `ai-log-analyzer` namespace s ServiceAccount a PVC |

Kompletní postup založení → [docs/INSTALLATION.md](docs/INSTALLATION.md)

---

## Rychlý start

### Kubernetes deployment (produkce)

```bash
# 1. Vyplnit konfiguraci
cp .env.example .env && vi .env

# 2. Instalační skript — validuje → DB migrace → Docker build+push → K8s manifesty → git branch+push
./install.sh

# 3. Po merge PR → ArgoCD sync → spustit init job
kubectl create job log-analyzer-init --from=cronjob/log-analyzer-backfill -n ai-log-analyzer
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

### Lokální testování

```bash
cp .env.example .env
# Vyplnit credentials (potřeba přímý síťový přístup k DB a ES)

python3 scripts/regular_phase.py --window 15 --dry-run
python3 scripts/backfill.py --days 1 --dry-run
```

---

## K8s CronJoby

| CronJob | Schedule | Popis | Typická doba |
|---------|----------|-------|-------------|
| `log-analyzer` | `*/15 * * * *` | Hlavní pipeline: ES fetch → detect peaks → alert → export | 1–5 min |
| `log-analyzer-backfill` | `0 9 * * *` | Denní backfill + Confluence publish | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP z peak_raw_data | 1–5 min |

### Manuální spuštění

```bash
kubectl create job manual-regular --from=cronjob/log-analyzer -n ai-log-analyzer
kubectl create job manual-backfill --from=cronjob/log-analyzer-backfill -n ai-log-analyzer
kubectl create job manual-thresholds --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer

# Úklid
kubectl delete job manual-regular manual-backfill manual-thresholds -n ai-log-analyzer --ignore-not-found
```

Detaily → [docs/OPERATIONS.md](docs/OPERATIONS.md)

---

## Konfigurace

### Zdroj konfigurace

| Prostředí | Kde |
|-----------|-----|
| **K8s (produkce)** | `values.yaml` v infra-apps repu → env vars v CronJob template |
| **Lokální vývoj** | `.env` soubor (šablona: `.env.example`) |

Credentials v K8s se injektují přes **CyberArk/Conjur** secrets provider → K8s Secret. Nikdy se nepíšou do values.yaml.

### Integrační proměnné

| Proměnná | Popis | Příklad |
|----------|-------|---------|
| `ES_HOST` | Elasticsearch URL | `https://elasticsearch-test.kb.cz:9500` |
| `ES_INDEX` | Index pattern | `cluster-app_pcb-*,cluster-app_pca-*` |
| `ES_USER` / `ES_PASSWORD` | ES read-only účet | CyberArk |
| `DB_HOST` | PostgreSQL hostname | nprod: `P050TD01.DEV.KB.CZ` |
| `DB_PORT` | PostgreSQL port | `5432` |
| `DB_NAME` | Název databáze | `ailog_analyzer` |
| `DB_USER` / `DB_PASSWORD` | DB app user | CyberArk |
| `DB_DDL_USER` / `DB_DDL_PASSWORD` | DB DDL user (migrace) | CyberArk |
| `CONFLUENCE_URL` | Confluence base URL | `https://wiki.kb.cz` |
| `CONFLUENCE_USERNAME` / `CONFLUENCE_TOKEN` | Confluence služební účet | CyberArk |
| `CONFLUENCE_KNOWN_ERRORS_PAGE_ID` | ID stránky Known Errors | z URL stránky |
| `CONFLUENCE_KNOWN_PEAKS_PAGE_ID` | ID stránky Known Peaks | z URL stránky |
| `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` | ID stránky Recent Incidents | z URL stránky |
| `CONFLUENCE_PROXY` | HTTP proxy pro Confluence z K8s | `http://cntlm.speed-default:3128` |
| `SMTP_HOST` | SMTP relay | `css-smtp-prod-os.sos.kb.cz` |
| `SMTP_PORT` | SMTP port | `25` |
| `EMAIL_FROM` | Odesílatel emailů | `ai-log-analyzer@kb.cz` |
| `TEAMS_WEBHOOK_URL` | Teams incoming webhook | URL webhooku |
| `TEAMS_EMAIL` | Email adresa Teams kanálu | email |
| `MONITORED_NAMESPACES` | K8s namespace pro monitoring | `pcb-dev-01-app,pca-sit-01-app` |

### Peak detection a alerting

| Proměnná | Default | Popis |
|----------|---------|-------|
| `PERCENTILE_LEVEL` | `0.93` | Percentil pro P93 threshold |
| `MIN_SAMPLES_FOR_THRESHOLD` | `10` | Min vzorků pro spolehlivý threshold |
| `DEFAULT_THRESHOLD` | `100` | Fallback pokud chybí P93/CAP data |
| `SPIKE_THRESHOLD` | `3.0` | Násobek P93 pro spike detekci |
| `EWMA_ALPHA` | `0.3` | EWMA vyhlazovací faktor |
| `WINDOW_MINUTES` | `15` | Velikost detekčního okna (min) |
| `MAX_PEAK_ALERTS_PER_WINDOW` | `3` | Max peaků v jednom digest emailu |
| `ALERT_DIGEST_ENABLED` | `true` | Digest místo individuálních emailů |
| `ALERT_COOLDOWN_MIN` | `45` | Min. interval mezi alerty pro stejný peak |
| `ALERT_HEARTBEAT_MIN` | `120` | Opakovat alert pro trvající peak |
| `ALERT_MIN_DELTA_PCT` | `30` | Min. % změna pro znovu-odeslání |
| `ALERT_CONTINUATION_LOOKBACK_MIN` | `60` | Lookback pro pokračující peak |

### Init job

| Proměnná (values.yaml) | Default | Popis |
|------------------------|---------|-------|
| `init.backfillDays` | `21` | Dní zpětně pro bootstrap backfill |
| `init.backfillWorkers` | `4` | Paralelní workery |
| `init.thresholdWeeks` | `3` | Týdnů pro výpočet thresholdů |
| `init.activeDeadlineSeconds` | `14400` | Max doba běhu init jobu (4h) |

### CyberArk/Conjur

| Proměnná | Popis |
|----------|-------|
| `CONJUR_APP_ID` | Application Identity z PSIAM |
| `CONJUR_LOB_USER` | nprod: `CAR_TA_LOBUser_TEST`, prod: `CAR_TA_LOBUser_PROD` |
| `CONJUR_SAFE_NAME` | Název SPEED safe |
| `CONJUR_ACCOUNT_DB` | Název DB DML účtu v safe |
| `CONJUR_ACCOUNT_DB_DDL` | Název DB DDL účtu v safe |
| `CONJUR_ACCOUNT_ES` | Název ES read účtu v safe |
| `CONJUR_ACCOUNT_CONFLUENCE` | Název Confluence účtu v safe |

### Alerting profily

**Méně emailů:**
```yaml
env:
  ALERT_COOLDOWN_MIN: "90"
  ALERT_HEARTBEAT_MIN: "180"
  ALERT_MIN_DELTA_PCT: "50"
```

**Citlivější:**
```yaml
env:
  ALERT_COOLDOWN_MIN: "30"
  ALERT_HEARTBEAT_MIN: "60"
  ALERT_MIN_DELTA_PCT: "20"
```

---

## Datové úložiště

| Typ dat | Uložiště | Popis |
|---------|----------|-------|
| Surové počty chyb | DB `ailog_peak.peak_raw_data` | Vstupní data pro výpočet P93/CAP |
| P93 prahy | DB `ailog_peak.peak_thresholds` | Per (namespace, day_of_week) |
| CAP prahy | DB `ailog_peak.peak_threshold_caps` | Per namespace |
| Evidované peaky | DB `ailog_peak.peak_investigation` | Pro Confluence reporty |
| Známé problémy | `registry/known_problems.yaml` (PVC) | Append-only, nikdy se nemaže |
| Známé peaky | `registry/known_peaks.yaml` (PVC) | Append-only, nikdy se nemaže |
| Index fingerprintů | `registry/fingerprint_index.yaml` (PVC) | Lookup: fingerprint → problem_key |
| Stav alertů | `registry/alert_state_regular_phase.json` (PVC) | Cooldown, trend, počet alertů |
| Sledované namespace | `config/namespaces.yaml` | Seznam namespace pro monitoring |

> V K8s jsou YAML registry soubory na PVC (`/data/registry`), ne v kontejneru.

---

## Struktura projektu

```
ai-log-analyzer/
├── scripts/
│   ├── regular_phase.py            # Hlavní 15min pipeline — entry point
│   ├── backfill.py                 # Historický backfill + Confluence publish
│   ├── core/
│   │   ├── email_notifier.py       # Email notifikace (digest + individuální)
│   │   ├── problem_registry.py     # Registry: problem + fingerprint index + peaks
│   │   ├── peak_detection.py       # P93/CAP spike detektor
│   │   ├── calculate_peak_thresholds.py  # Výpočet P93/CAP, zápis do DB
│   │   ├── baseline_loader.py      # Historický baseline z DB
│   │   ├── fetch_unlimited.py      # Elasticsearch fetcher (search_after paging)
│   │   ├── teams_notifier.py       # Microsoft Teams integrace
│   │   └── telemetry_context.py    # Telemetrie a runtime metriky
│   ├── pipeline/                   # Detection pipeline (6 fází: A→F)
│   │   ├── phase_a_parse.py        # Parsování a normalizace ES dokumentů
│   │   ├── phase_b_measure.py      # Měření a baseline porovnání
│   │   ├── phase_c_detect.py       # P93/CAP detekce anomálií
│   │   ├── phase_d_score.py        # Skórování závažnosti (0–100)
│   │   ├── phase_e_classify.py     # Klasifikace typu chyby
│   │   ├── phase_f_report.py       # Report a export
│   │   ├── incident.py             # Incident model a kolekce
│   │   └── pipeline.py             # Pipeline orchestrátor
│   ├── analysis/
│   │   ├── trace_analysis.py       # Trace flow analýza, behavior extraction, root cause
│   │   ├── problem_aggregator.py   # Agregace incidentů → problémy
│   │   ├── problem_report.py       # Problem report generátor
│   │   └── propagation.py          # Propagační analýza
│   ├── exports/
│   │   └── table_exporter.py       # CSV/MD/JSON export pro Confluence
│   └── test_pipeline.sh            # Integrační test (backfill + export + notify)
├── incident_analysis/              # Kauzální analýza incidentů
│   ├── analyzer.py                 # Hlavní analyzátor
│   ├── causal_inference.py         # Odvozování příčin
│   ├── timeline_builder.py         # Časová osa incidentu
│   ├── knowledge_base.py           # Knowledge base lookups
│   └── models.py                   # Datové modely + prioritizace
├── registry/                       # Append-only YAML evidence (live runtime data)
├── config/
│   ├── namespaces.yaml             # Sledované K8s namespace
│   └── known_issues/               # Manuální knowledge base (known errors/peaks)
├── k8s/                            # Helm šablony — VZOROVÉ
│   ├── Chart.yaml
│   ├── values.yaml                 # Konfigurační šablona (viz sekce Konfigurace)
│   └── templates/
│       ├── cronjob.yaml            # Regular + Backfill + Threshold CronJoby
│       ├── job-init.yaml           # Bootstrap job (jednorázový)
│       ├── pvc.yaml                # Persistent Volume Claim
│       ├── secrets.yaml            # Conjur secret mapping
│       ├── serviceaccount.yaml     # ServiceAccount + RBAC
│       └── _conjur.tpl             # Conjur init container helper
├── wheels/                         # Pre-stažené Python wheels (offline Docker build)
├── docs/                           # Rozšířená dokumentace
├── Dockerfile                      # Multi-stage offline build
├── requirements.txt                # Python závislosti
├── install.sh                      # Instalační orchestrace (DB + Docker + K8s + git)
├── run_regular.sh                  # Shell wrapper pro regular phase
├── run_backfill.sh                 # Shell wrapper pro backfill
├── run_init.sh                     # Shell wrapper pro init phase
├── .env.example                    # Template konfigurace — kompletní popis všech proměnných
└── CHANGELOG.md                    # Historie verzí
```

---

## Docker build

Dockerfile používá **offline build** — Python wheels jsou v `wheels/` a instalují se bez přístupu k internetu:

```bash
docker build -t dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag> .
docker push dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag>
```

> `install.sh` automatizuje build+push na základě `.env` (`DOCKER_REGISTRY`, `DOCKER_SQUAD`, `IMAGE_TAG`).

---

## Monitoring

### Stav CronJobů

```bash
kubectl get cronjobs -n ai-log-analyzer
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp | tail -10
kubectl logs job/<job-name> -n ai-log-analyzer
```

### Failed joby

```bash
kubectl get jobs -n ai-log-analyzer --field-selector=status.successful=0
kubectl logs job/<failed-job> -n ai-log-analyzer
```

### DB diagnostika

```sql
-- Poslední zapsaná data
SELECT MAX(created_at) FROM ailog_peak.peak_raw_data;

-- Thresholdy per namespace
SELECT namespace, COUNT(*) FROM ailog_peak.peak_thresholds GROUP BY namespace;

-- Peaky za posledních 24h
SELECT COUNT(*) FROM ailog_peak.peak_investigation WHERE created_at > NOW() - INTERVAL '24 hours';
```

### Typické chyby

| Chyba | Příčina | Řešení |
|-------|---------|--------|
| `connection refused DB_HOST` | DB nedostupná z K8s | Ověřit DB_HOST, network policy |
| `ES connection timeout` | ES nedostupný | Ověřit ES_HOST, proxy |
| `401 Unauthorized (Confluence)` | Neplatný token | Obnovit credentials v CyberArk |
| `No thresholds found` | Prázdná DB | Spustit init job |
| `SMTP connection refused` | Mail server | Ověřit SMTP_HOST z K8s |

Detaily → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)

---

## Dokumentace

| Dokument | Popis |
|----------|-------|
| [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) | Celý proces krok za krokem — od ES fetch po email digest |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Komponenty, datové toky, DB schéma, integrace |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Prerekvizity, CyberArk, DB setup, K8s deployment |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | K8s CronJoby, alerting tuning, namespace management |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Řešení častých problémů |
| [docs/TELEMETRY.md](docs/TELEMETRY.md) | Telemetrie a runtime metriky |
| [docs/TESTING.md](docs/TESTING.md) | Testovací průvodce |
| [CHANGELOG.md](CHANGELOG.md) | Historie všech verzí |

---

## Licence

Internal use only.
