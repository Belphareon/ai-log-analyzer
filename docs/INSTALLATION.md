# Instalace — AI Log Analyzer

Kompletní průvodce: prerekvizity → příprava prostředí → deployment na K8s.

> **Konvence:** Dokument je obecný. Všude kde vidíte `<placeholder>`, doplňte hodnoty pro vaše prostředí.

---

## 1. Prerekvizity

### 1.1 Infrastrukturní služby

| Služba | Popis | Příklad (nprod) | Příklad (prod) |
|--------|-------|-----------------|----------------|
| **PostgreSQL** | DB pro historická data, thresholdy, investigace | `P050TD01.DEV.KB.CZ:5432` | `P050TD01.PROD.KB.CZ:5432` |
| **Elasticsearch** | Zdroj error logů z K8s clusterů | `https://elasticsearch-test.kb.cz:9500` | `https://elasticsearch.kb.cz:9500` |
| **SMTP** | Odesílání email notifikací | `css-smtp-prod-os.sos.kb.cz:25` | `css-smtp-prod-os.sos.kb.cz:25` |
| **Confluence** | Cílové stránky pro Known Errors/Peaks/Recent Incidents | `https://wiki.kb.cz` | `https://wiki.kb.cz` |
| **Docker Registry** | Úložiště Docker image | `dockerhub.kb.cz/<squad>/ai-log-analyzer` | `dockerhub.kb.cz/<squad>/ai-log-analyzer` |
| **CNTLM Proxy** | HTTP proxy v K8s pro přístup ke Confluence | `http://cntlm.speed-default:3128` | `http://cntlm.speed-default:3128` |

### 1.2 CyberArk / Conjur — uložení credentials

Všechny credentials jsou uloženy v CyberArk (EPV) safe a do K8s se injektují přes Conjur secrets provider.

**Registrace přes PSIAM portál:**

1. Požádat o **Application Identity** (např. `AI-LOG-ANALYZER`)
2. Vytvořit **Safe** (např. `DAN_AI-LOG-ANALYZER`)
3. Do safe uložit tyto účty:

| Účet v CyberArk | Popis | Kde se používá |
|------------------|-------|----------------|
| `<DB_DML_USER>` | PostgreSQL app user (SELECT, INSERT, UPDATE, DELETE) | Čtení/zápis dat v `ailog_peak` |
| `<DB_DDL_USER>` | PostgreSQL DDL user (CREATE TABLE, ALTER, GRANT) | Migrace schématu, SET ROLE |
| `<ES_READ_USER>` | Elasticsearch read-only user | Čtení error logů z ES indexů |
| `<CONFLUENCE_USER>` | Confluence service account | Publikace tabulek na wiki |

**Mapování v K8s Secret** viz sekce [3.3 Conjur konfigurace](#33-conjur-konfigurace).

### 1.3 PostgreSQL — založení databáze

Databáze musí existovat **před** prvním deplojem. Potřeba:

```sql
-- 1. Databáze (DBA požadavek)
CREATE DATABASE ailog_analyzer;

-- 2. Schéma
CREATE SCHEMA IF NOT EXISTS ailog_peak;

-- 3. Role (DBA požadavek)
CREATE ROLE role_ailog_analyzer_ddl;
CREATE ROLE role_ailog_analyzer_app;

-- 4. DDL user — pro migrace
CREATE USER <ddl_user> WITH PASSWORD '***';
GRANT role_ailog_analyzer_ddl TO <ddl_user>;
GRANT ALL ON SCHEMA ailog_peak TO role_ailog_analyzer_ddl;

-- 5. App user — pro runtime
CREATE USER <app_user> WITH PASSWORD '***';
GRANT role_ailog_analyzer_app TO <app_user>;
GRANT USAGE ON SCHEMA ailog_peak TO role_ailog_analyzer_app;
```

**Migrace schématu** (spouští se jako DDL user):

```bash
# Připojení k DB
export PGHOST=<db_host> PGPORT=5432 PGDATABASE=ailog_analyzer PGUSER=<ddl_user>

# Spuštění migrací (v pořadí)
psql -f scripts/migrations/000_create_base_tables.sql
psql -f scripts/migrations/001_create_peak_thresholds.sql
psql -f scripts/migrations/002_create_enhanced_analysis_tables.sql
psql -f scripts/migrations/003_remove_version_suffixes.sql

# Oprávnění pro app usera
psql -c "SET ROLE role_ailog_analyzer_ddl;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;"
```

**Ověření:**
```bash
psql -U <app_user> -d ailog_analyzer -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ailog_peak';"
# Očekáváno: 5+ tabulek
```

### 1.4 Confluence — vytvoření stránek

Vytvořit 3 stránky v příslušném Confluence space:

| Stránka | Proměnná | Popis |
|---------|----------|-------|
| Known Errors | `CONFLUENCE_KNOWN_ERRORS_PAGE_ID` | Tabulka známých chyb |
| Known Peaks | `CONFLUENCE_KNOWN_PEAKS_PAGE_ID` | Tabulka známých peaků |
| Recent Incidents | `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` | Denní report incidentů |

Po vytvoření poznamenat **Page ID** z URL (číslo na konci URL stránky).

### 1.5 Teams Webhook

Vytvořit Incoming Webhook v příslušném Teams kanálu a poznamenat URL + email adresu kanálu.

---

## 2. Konfigurace

### 2.1 Git repozitáře

Projekt využívá 2 repozitáře:

| Repozitář | Obsah | Cesta (nprod) | Cesta (prod) |
|-----------|-------|---------------|--------------|
| **ai-log-analyzer** | Zdrojový kód, Dockerfile, lokální `k8s/` šablony | `<git_root>/ai-log-analyzer` | `<git_root>/ai-log-analyzer` |
| **k8s-infra-apps** | Nasazené K8s manifesty (values.yaml s reálnými hodnotami) | `<git_root>/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer` | `<git_root>/k8s-infra-apps-prod/infra-apps/ai-log-analyzer` |

### 2.2 values.yaml — hlavní konfigurační soubor

Hlavní konfigurace pro K8s deployment je v `k8s/values.yaml`. Pro každé prostředí existuje kopie v příslušném infra-apps repozitáři.

**Povinné položky k úpravě:**

```yaml
# ---- Prostředí ----
namespace: ai-log-analyzer            # Název K8s namespace
environment: nprod                     # nprod | prod

# ---- Image ----
app:
  image: dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag>

# ---- Conjur (CyberArk) ----
conjur:
  applicationId: <PSIAM_APP_ID>       # Z PSIAM registrace
  lobUser: CAR_TA_LOBUser_<ENV>       # TEST nebo PROD
  safeName: DAN_<SAFE_NAME>           # Název safe v CyberArk
  accounts:
    confluence: <CONFLUENCE_USER>
    database: <DB_DML_USER>
    database_ddl: <DB_DDL_USER>
    elastic: <ES_READ_USER>

# ---- Database ----
env:
  DB_HOST: <db_hostname>              # Liší se prod/nprod
  DB_NAME: ailog_analyzer
  DB_PORT: "5432"

  # ---- Elasticsearch ----
  ES_HOST: <es_url>                   # Liší se prod/nprod
  ES_INDEX: "cluster-app_<prefix>-*"  # Vzor pro vaše namespace

  # ---- Confluence ----
  CONFLUENCE_URL: "https://wiki.kb.cz"
  CONFLUENCE_PROXY: "http://cntlm.speed-default:3128"
  CONFLUENCE_KNOWN_ERRORS_PAGE_ID: "<page_id>"
  CONFLUENCE_KNOWN_PEAKS_PAGE_ID: "<page_id>"

  # ---- Teams ----
teams:
  webhook_url: "<webhook_url>"
  email: "<teams_channel_email>"
```

Kompletní referenci všech parametrů najdete přímo v `k8s/values.yaml` (komentovaný s defaulty).

### 2.3 config/namespaces.yaml

Seznam Kubernetes namespace, které se budou monitorovat:

```yaml
namespaces:
  - <prefix>-dev-01-app
  - <prefix>-sit-01-app
  - <prefix>-uat-01-app
  # ... přidat dle potřeby
```

> **Tip:** Soubor je součástí Docker image — po změně nutný nový build+push image.

### 2.4 .env (pouze pro lokální vývoj/testování)

```bash
cp .env.example .env
# Vyplnit hodnoty — viz komentáře v .env.example
```

`.env` soubor se **nepoužívá** v K8s — tam jsou env vars předány přes `values.yaml` + Conjur Secret.

---

## 3. Deployment na Kubernetes

### 3.1 Docker build & push

```bash
# Build
docker build -t dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag> .

# Push
docker push dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag>

# Aktualizovat values.yaml
# app.image: dockerhub.kb.cz/<squad>/ai-log-analyzer:<tag>
```

### 3.2 Adresářová struktura v infra-apps

```
k8s-infra-apps-<env>/
└── infra-apps/
    └── ai-log-analyzer/
        ├── Chart.yaml
        ├── values.yaml           # ← Hlavní konfigurace pro dané prostředí
        └── templates/
            ├── cronjob.yaml      # Regular + Backfill + Threshold CronJoby
            ├── job-init.yaml     # Bootstrap job (jednorázový)
            ├── pvc.yaml          # Persistent Volume Claim
            ├── secrets.yaml      # Conjur secret mapping
            └── serviceaccount.yaml
```

### 3.3 Conjur konfigurace

Secret template (`templates/secrets.yaml`) mapuje CyberArk účty na K8s Secret klíče:

```yaml
stringData:
  conjur-map: |-
    DB_USER:             epv/<lobUser>/<safeName>/<db_account>/username
    DB_PASSWORD:         epv/<lobUser>/<safeName>/<db_account>/password
    DB_DDL_USER:         epv/<lobUser>/<safeName>/<ddl_account>/username
    DB_DDL_PASSWORD:     epv/<lobUser>/<safeName>/<ddl_account>/password
    ES_USER:             epv/<lobUser>/<safeName>/<es_account>/username
    ES_PASSWORD:         epv/<lobUser>/<safeName>/<es_account>/password
    CONFLUENCE_USERNAME: epv/<lobUser>/<safeName>/<confluence_account>/username
    CONFLUENCE_PASSWORD: epv/<lobUser>/<safeName>/<confluence_account>/password
```

Všechny `<lobUser>`, `<safeName>`, `<*_account>` hodnoty se berou z `values.yaml` → sekce `conjur`.

### 3.4 Deployment sekvence — nové prostředí

```bash
# 1. Namespace (pokud neexistuje)
kubectl create namespace ai-log-analyzer

# 2. PVC pro persistent storage
helm template k8s/ | kubectl apply -f - -l component=storage

# 3. ServiceAccount + RBAC
helm template k8s/ | kubectl apply -f - -l app=log-analyzer -l kind=serviceaccount

# 4. Secret (Conjur mapping)
helm template k8s/ | kubectl apply -f - -l app=log-analyzer -l kind=secret

# 5. Init Job — bootstrap (backfill + threshold calculation)
helm template k8s/ | kubectl apply -f - -l job-type=init
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer

# 6. Ověřit, že init proběhl
kubectl get job log-analyzer-init -n ai-log-analyzer
# STATUS: Complete

# 7. Deploy CronJoby (regular + backfill + thresholds)
helm template k8s/ | kubectl apply -f -
kubectl get cronjobs -n ai-log-analyzer

# 8. Ověřit první běh
kubectl get jobs -n ai-log-analyzer
kubectl logs job/<first-job-name> -n ai-log-analyzer
```

### 3.5 Init Job — co dělá

Init job je **jednorázový** bootstrap, definovaný v `templates/job-init.yaml`:

| Krok | Popis | Konfigurace |
|------|-------|-------------|
| 1. Backfill | Zpětně stáhne error logy z ES za posledních N dní | `init.backfillDays` (default: 21) |
| 2. Threshold calc | Vypočítá P93/CAP prahy z backfill dat | `init.thresholdWeeks` (default: 3) |
| 3. Verify | Zobrazí vypočtené thresholdy pro kontrolu | — |

**Parametry init jobu** (v `values.yaml`):

```yaml
init:
  backfillDays: 21          # Počet dní zpětně (min. 14 pro spolehlivé P93)
  backfillWorkers: 4        # Paralelní workery
  thresholdWeeks: 3         # Týdnů pro výpočet thresholdů
  activeDeadlineSeconds: 14400  # Max doba běhu (4h)
```

Po dokončení se job automaticky smaže po 24h (`ttlSecondsAfterFinished: 86400`).

---

## 4. CronJoby — přehled K8s jobů

Po úspěšném init jobu systém běží autonomně přes 3 CronJoby:

| CronJob | Schedule | Popis | Duration |
|---------|----------|-------|----------|
| `log-analyzer` | `*/15 * * * *` | Hlavní pipeline: fetch → detect → alert → export | 1–5 min |
| `log-analyzer-backfill` | `0 9 * * *` | Denní backfill + Confluence publish | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP | 1–5 min |

Detailní popis jobů a jejich parametrů → [OPERATIONS.md](OPERATIONS.md).

---

## 5. Ověření po instalaci

### 5.1 DB data

```sql
-- Počet raw data záznamů (po init jobu)
SELECT COUNT(*) FROM ailog_peak.peak_raw_data;

-- Thresholdy per namespace
SELECT namespace, COUNT(*) AS threshold_count
FROM ailog_peak.peak_thresholds GROUP BY namespace ORDER BY namespace;

-- CAP hodnoty
SELECT namespace, cap_value
FROM ailog_peak.peak_threshold_caps ORDER BY namespace;
```

### 5.2 K8s stav

```bash
# CronJoby existují a mají schedule
kubectl get cronjobs -n ai-log-analyzer

# Poslední joby proběhly úspěšně
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp

# Logy posledního jobu
kubectl logs job/<job-name> -n ai-log-analyzer
```

### 5.3 Confluence stránky

Po prvním backfill jobu by měly být aktualizované:
- Known Errors stránka
- Known Peaks stránka
- Recent Incidents stránka

---

## 6. Deployment checklist

- [ ] DB vytvořena, schéma migrováno, oprávnění nastavena
- [ ] CyberArk safe vytvořen, účty uloženy (DB DML, DB DDL, ES, Confluence)
- [ ] PSIAM registrace provedena (Application Identity)
- [ ] Confluence stránky vytvořeny, Page ID zaznamenány
- [ ] Teams webhook nastaven
- [ ] `values.yaml` vyplněn pro prostředí (nprod/prod)
- [ ] `config/namespaces.yaml` obsahuje správné namespace
- [ ] Docker image built & pushed
- [ ] K8s namespace existuje
- [ ] PVC, ServiceAccount, Secret, Init Job deployed
- [ ] Init job dokončen (backfill + thresholds)
- [ ] CronJoby deployed a běží
- [ ] První regular phase job proběhl úspěšně
- [ ] Email notifikace ověřena
- [ ] Confluence stránky aktualizovány

---

## 7. Lokální testování (volitelné)

Pro vývoj a debugging mimo K8s:

```bash
# 1. Vyplnit .env
cp .env.example .env
# Doplnit credentials (ES, DB, Confluence, Teams)

# 2. Ověřit konektivitu
python3 scripts/regular_phase.py --window 15 --dry-run

# 3. Test backfill (1 den)
python3 scripts/backfill.py --days 1 --dry-run

# 4. Test thresholdů
python3 scripts/core/calculate_peak_thresholds.py --dry-run --verbose
```

> **Poznámka:** Lokální testy vyžadují přímý přístup k DB a ES — v prod prostředí je to obvykle dostupné jen z K8s clusteru.
