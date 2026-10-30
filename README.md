# AI Log Analyzer

Automatizovaný systém pro detekci, klasifikaci a eskalaci chybových incidentů z aplikačních logů v Kubernetes.

**[Jak to funguje](docs/HOW_IT_WORKS.md)** | **[Architektura](docs/ARCHITECTURE.md)** | **[Instalace](docs/INSTALLATION.md)** | **[Provoz](docs/OPERATIONS.md)** | **[Troubleshooting](docs/TROUBLESHOOTING.md)** | **[Telemetrie](docs/TELEMETRY.md)** | **[Testování](docs/TESTING.md)** | **[Changelog](CHANGELOG.md)**

---

## Co program dělá

Systém každých 15 minut načte error logy ze sledovaných Kubernetes namespace z Elasticsearch a automaticky:

1. **Detekuje anomálie** — porovná namespace total s vlastním P95/MAD prahem přesného UTC týdenního 15min slotu bez globálního CAP a peak přiřadí pouze anomální cause family; odhalí spike, burst, nový typ chyby nebo regresi
2. **Identifikuje** — každá chyba dostane `fingerprint` (hash), je zařazena do kategorie a přiřazena k business flow
3. **Určí, co je nové vs. známé** — registry drží historii všech dříve viděných problémů
4. **Vyhodnotí závažnost** — deterministické bodování 0–100
5. **Koreluje** — různé logové projevy stejné události se sloučí do jednoho alertu
6. **Notifikuje** — při peaku odešle digest přes nakonfigurovaný Teams webhook, email, nebo oba kanály
7. **Aktualizuje Confluence** — samostatny DB-only reporter publikuje Known Errors, Known Peaks a Recent Incidents z autoritativnich faktu a katalogovych metadat
8. **Sbírá historická data** — ukládá úplná 15min fakta včetně skutečných nul pro zpětný přepočet slotových prahů a namespace/fingerprint baseline; chybějící běhy nejsou nuly

---

## Prerekvizity

| Prerekvizita | Popis |
|-------------|-------|
| **PostgreSQL** | Databáze `ailog_analyzer`, schéma `ailog_peak`, DDL+App user/role |
| **Elasticsearch** | Read-only přístup k aplikačním logům (`cluster-app_*`) |
| **CyberArk (SPEED)** | Safe s credentials (DB, ES, Confluence) + Application Identity v PSIAM |
| **Confluence** | Služební účet + 3 stránky (Known Errors, Known Peaks, Recent Incidents) |
| **Email/SMTP** | SMTP relay dostupný z K8s clusteru |
| **K8s namespace** | `ai-log-analyzer` namespace se ServiceAccount a RBAC; r111 PostgreSQL rezim pravidelneho sberu a reporter nepotrebuji PVC mount |

Kompletní postup založení → [docs/INSTALLATION.md](docs/INSTALLATION.md)

### r111: Ochrana proti cekani na PVC

Nasazeny nprod pouziva `runtimeState.backend=postgres`: migrace 013 uchovava registry i alert cooldowny v DB, kazdy regular pod je obnovi do lokalniho `/data` a zmeny synchronne checkpointuje. DB advisory lock brani soubeznym writerum; chybejici nebo poskozeny checkpoint zastavi beh misto resetu na prazdnou registry. Regular nema PVC mount a ma deadline 900 s. Puvodni PVC je zachovane pouze pro legacy data, nikoli jako aktualni autorita. Zdrojovy chart a instalator maji kvuli zpetne kompatibilite stale explicitne volitelny `filesystem` default.

r110/r111 omezuji Confluence nahled na 100 radku v tabulce, 192 znaku v bunce a 128 Ki znaku denniho uvodu; skryta data jsou oznacena, uplna DB fakta a lokalni CSV zustavaji zachovana. Uploader meri cely serializovany UTF-8 request a odmitne PUT nad 4 MiB. Prechod, fail-closed handoff, rollback a casove oznacene overeni nasazeni jsou v [provoznim navodu](docs/OPERATIONS.md#r111-runtime-bez-pvc).

---

## Rychlý start

### Kubernetes deployment (produkce)

```bash
# 1. Vyplnit konfiguraci
cp config/install.conf.example .env && vi .env

# 2. Instalační skript — validuje konfiguraci → vygeneruje kompletní infra-apps strukturu → commitne instalační branch
./install.sh

# 3. Po merge PR → ArgoCD sync; init Job je součástí chartu
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

### Lokální testování

```bash
cp config/install.conf.example .env
# Vyplnit credentials (potřeba přímý síťový přístup k DB a ES)

python3 scripts/regular_phase.py --window 15 --dry-run
python3 scripts/backfill.py --days 1 --dry-run
```

---

## K8s CronJoby

| CronJob | Schedule | Popis | Typická doba |
|---------|----------|-------|-------------|
| `log-analyzer` | `5,20,35,50 * * * *` UTC | Live ES sber, detekce, alert; pak facts-only doplneni mezer a pozdnich dat | 1–10 min |
| `log-analyzer-reports` | `10 */2 * * *` UTC | DB-only trendy kazde 2 h; denni Known Peaks a Recent Incidents, bez PVC a ES credentials | 1–15 min |
| `log-analyzer-backfill` | pozastaven (`suspend: true`) | Legacy manualni maintenance, nikoli zdroj pravidelne publikace | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet slotového P95/MAD z 12 týdnů úplných fact rows | 1–5 min |
| `log-analyzer-maintenance` | `30 2 * * *` | Denní rollup a retention jemnozrnných faktů | 1–30 min |

### Manuální spuštění

V PostgreSQL rezimu nespoustejte legacy backfill jako druheho registry writera. Historicke opravy zajistuje scheduled regular bez alert replay; explicitni init bootstrap pouziva facts-only rezim. Postup maintenance a rollbacku je v provoznim navodu.

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
| **Instalace** | `.env` soubor (šablona: `config/install.conf.example`) |

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
| `CONFLUENCE_USERNAME` / `CONFLUENCE_PASSWORD` | Confluence služební účet; token je uložený v CyberArku jako password atribut a publisher ho posílá přes Bearer auth | CyberArk |
| `CONFLUENCE_TOKEN` | Volitelný přímý token pro lokální běh; má přednost před `CONFLUENCE_PASSWORD` a používá stejný Bearer auth | Secret mimo standardní prod/nprod chart |
| `CONFLUENCE_KNOWN_ERRORS_PAGE_ID` | ID stránky Known Errors | z URL stránky |
| `CONFLUENCE_KNOWN_PEAKS_PAGE_ID` | ID stránky Known Peaks | z URL stránky |
| `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` | ID stránky Recent Incidents | z URL stránky |
| `CONFLUENCE_PROXY` | HTTP proxy pro Confluence z K8s | `http://cntlm.speed-default:3128` |
| `SMTP_HOST` | SMTP relay | `css-smtp-prod-os.sos.kb.cz` |
| `SMTP_PORT` | SMTP port | `25` |
| `EMAIL_FROM` | Odesílatel emailů | `ai-log-analyzer@kb.cz` |
| `TEAMS_WEBHOOK_URL` | Volitelný Teams incoming webhook; defaultně vypnutý, primární je `TEAMS_EMAIL` | URL webhooku |
| `TEAMS_EMAIL` | Email adresa Teams kanálu (primární doručení notifikací) | email |
| `MONITORED_NAMESPACES` | K8s namespace pro monitoring | `pcb-dev-01-app,pca-sit-01-app` |

### Peak detection a alerting

| Proměnná | Default | Popis |
|----------|---------|-------|
| `PERCENTILE_LEVEL` | `0.95` | Percentil pro každý UTC slot samostatně |
| `MIN_SAMPLES_FOR_THRESHOLD` | `10` | Minimum pro mature profil, nelze snížit pod 10; méně vzorků je použitelný init |
| `DEFAULT_THRESHOLD` | `100` | Legacy proměnná, slotový model ji nepoužívá; missing profil se nevyhodnotí |
| `FINGERPRINT_SPIKE_MIN_COUNT` | `20` | Absolutní minimum pro historickou cause family |
| `FINGERPRINT_SPIKE_MAD_MULTIPLIER` | `6` | MAD násobek pro namespace/fingerprint family gate |
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
| `init.thresholdWeeks` | `12` | DB historie pro init i týdenní přepočet, požadavek nejméně 10 týdnů; kratší dostupná historie vytvoří init |
| `init.activeDeadlineSeconds` | `14400` | Max doba běhu init jobu (4h) |

### CyberArk/Conjur

| Proměnná | Popis |
|----------|-------|
| `CONJUR_APP_ID` | Application Identity z PSIAM |
| `CONJUR_LOB_USER` | nprod: `CAR_TA_LOBUser_TEST`, prod: `CAR_TA_LOBUser_PROD` |
| `CONJUR_SAFE_NAME` | Název SPEED safe |
| `PROD_DB_USER_D1/D2`, `NPROD_DB_USER_D1/D2` | Názvy runtime DB účtů získané při založení DB |
| `PROD_DB_DDL_USER_D1/D2`, `NPROD_DB_DDL_USER_D1/D2` | Názvy DDL DB účtů získané při založení DB |
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
| Úplná namespace fakta | DB `ailog_peak.v_complete_namespace_error_counts` | Vstupní data pro slotové P95/MAD, včetně pozorovaných nul |
| Slotové prahy | DB `ailog_peak.threshold_slot_values` | Per (snapshot, namespace, UTC weekday, hour, quarter), počet vzorků a init/mature |
| Metadata snapshotů | DB `ailog_peak.threshold_snapshot_runs` | Verze 5.0 a grain; staré denní tabulky zůstávají jen pro historii |
| Evidované peaky | DB `ailog_peak.peak_investigation` | Pro Confluence reporty |
| Registry a stav alertu (r111 PostgreSQL) | DB `ailog_peak.runtime_state` | Scoped checkpoint obou registry YAML a alert cooldown JSON, autorita prezivajici vymenu podu |
| Katalog pro DB reporter | DB `ailog_peak.report_knowledge` | Kopie problem/peak metadat; vstup prvniho runtime bootstrapu |
| Publication ledger | DB `ailog_peak.report_publications` | Doruceni kazdeho reportovaciho cile, oddelene partial/final verze |
| Registry soubory v podu | `/data/registry` v `emptyDir` | Pracovni kopie z DB; fingerprint index a ID countery se obnovi z registry |
| Legacy filesystem registry | `/data/registry` na PVC | Pouze `runtimeState.backend=filesystem`; po DB cutoveru neni zachovane PVC aktualni zalohou |
| Sledované namespace | `config/namespaces.yaml` | Seznam namespace pro monitoring |

> Nprod r111 drzi trvaly runtime stav v PostgreSQL. Pod-local YAML a CSV/MD/JSON exporty nejsou trvale zalohy. Prepnuti tagu zpet na starou filesystem image bez exportu aktualniho DB stavu neni bezpecny rollback.

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
│   │   ├── peak_detection.py       # UTC slot P95/MAD spike detektor
│   │   ├── calculate_peak_thresholds.py  # Slotové prahy včetně nul, zápis do DB
│   │   ├── baseline_loader.py      # Historický baseline z DB
│   │   ├── fetch_unlimited.py      # Elasticsearch fetcher (search_after paging)
│   │   ├── teams_notifier.py       # Microsoft Teams integrace
│   │   └── telemetry_context.py    # Telemetrie a runtime metriky
│   ├── pipeline/                   # Detection pipeline (6 fází: A→F)
│   │   ├── phase_a_parse.py        # Parsování a normalizace ES dokumentů
│   │   ├── phase_b_measure.py      # Měření a baseline porovnání
│   │   ├── phase_c_detect.py       # UTC slot + family-gate detekce anomálií
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
│       ├── secrets.yaml            # Conjur secret mapping (conjur-map, centrální Secrets Provider)
│       └── serviceaccount.yaml     # ServiceAccount + RBAC
├── wheels/                         # Pre-stažené Python wheels (offline Docker build)
├── docs/                           # Rozšířená dokumentace
├── requirements.txt                # Python závislosti
├── install.sh                      # Instalační orchestrace (profil + K8s + git)
├── run_regular.sh                  # Shell wrapper pro regular phase
├── run_backfill.sh                 # Shell wrapper pro backfill
├── run_init.sh                     # Shell wrapper pro init phase
├── config/install.conf.example     # Prod/nprod instalační profily bez hesel
└── CHANGELOG.md                    # Historie verzí
```

---

## Image pro instalaci

Instalator pouziva explicitni `IMAGE_TAG` z `.env`, ale image nebuildi ani nepushuje. Release se sestavi z commitnuteho aplikacniho stromu s offline wheels, publikuje do registry a overi pullnutim zpet pred zmenou GitOps image. V manifestu nepouzivejte implicitni `latest` ani existujici tag neprepisujte. Nprod r111 byl overen z aplikacniho commitu `41d1a12`; dokumentacni commity nevyzaduji novou image.

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
| `401/403 (Confluence)` | Neplatný token nebo chybějící edit oprávnění | Ověřit Bearer token z CyberArk password atributu a oprávnění cílové stránky |
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
