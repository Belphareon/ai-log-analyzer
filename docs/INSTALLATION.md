# Instalace — AI Log Analyzer

Kompletní průvodce od prerekvizit po běžící systém v K8s.

---

## Přehled procesu

```
1. Prerekvizity (manuální)       — DB, CyberArk, Confluence, email kanál
2. Konfigurace (.env)            — non-secret instalační vstup + názvy CyberArk účtů
3. Instalační skript (install.sh) — Docker build, values.yaml, K8s manifesty, git push
4. PR & ArgoCD sync              — merge PR, ArgoCD nasadí
5. Init joby                     — bootstrap historických dat (kubectl)
6. Ověření                       — CronJoby běží, Confluence aktualizován
```

---

## 1. Prerekvizity

Tyto kroky je třeba provést **manuálně** před spuštěním `install.sh`.

### 1.1 PostgreSQL databáze

Vytvorit v MIQ nebo požádat DBA o vytvoření:

| Položka | Popis |
|---------|-------|
| **Databáze** | `ailog_analyzer` |
| **Schéma** | `ailog_peak` (vytvoří K8s init job automaticky) |
| **DDL role** | `role_ailog_analyzer_ddl` — vlastní schéma, CREATE TABLE |
| **App role** | Role z `DB_APP_ROLE` (prod typicky `role_ai_log_analyzer_user`) — SELECT/INSERT/UPDATE/DELETE |
| **DDL user** | Přiřazen do `role_ailog_analyzer_ddl` |
| **App user** | Přiřazen do role z `DB_APP_ROLE` |

Hostnames se liší podle prostředí:

| Prostředí | DB Host |
|-----------|---------|
| nprod | `P050TD01.DEV.KB.CZ` |
| prod | `<prod_db_host>` (dle DBA) |

> **Tabulky a oprávnění vytváří K8s init job automaticky** pomocí DDL účtu dotaženého z CyberArku. `install.sh` lokálně negeneruje ani nevyžaduje DB hesla pro standardní prod/nprod deploy.

### 1.2 CyberArk (SPEED) — uložení credentials

Všechny credentials jsou uloženy v CyberArk SPEED safe a do K8s se injektují přes Conjur (annotation-based Secrets Provider — Secret `log-analyzer-secrets` je labelovaný `conjur.org/managed-by-provider: "true"` a obsahuje `conjur-map` s cestami k EPV záznamům; runtime hodnoty doplňuje centrální Secrets Provider, žádný per-pod init container není potřeba).

**Kroky v PSIAM portálu:**

1. **Registrovat Application Identity** — unikátní identifikátor aplikace v Conjur (např. `AI-LOG-ANALYZER`). Slouží pro autentizaci podu vůči Conjur API.
2. **Vytvořit SPEED Safe** — úložiště pro credentials (např. `DAN_AI-LOG-ANALYZER`).
3. **Uložit účty do safe** — DB runtime a DDL účty (v produkci typicky CyberArk virtual dual accounts) a účty pro ES a Confluence. Každý účet musí poskytovat `username` a `password` atribut:

| `values.yaml` klíč (`conjur.accounts.*`) | Účet | Co to je | Jak získat | Secret klíče v podu |
|---|---|---|---|---|
| `database` | DB runtime účet | PostgreSQL účet nebo CyberArk virtual dual account pro SELECT/INSERT/UPDATE/DELETE | Název aktivního EPV/virtual accountu | `DB_USER`, `DB_PASSWORD` |
| `database_ddl` | DB DDL účet | PostgreSQL účet nebo CyberArk virtual dual account pro CREATE/ALTER/DROP, používaný init jobem | Název aktivního EPV/virtual accountu | `DB_DDL_USER`, `DB_DDL_PASSWORD` |
| `elastic` | ES read user | Elasticsearch read-only | Založit technický účet (např. `XX_<TEAM>_ES_READ`), přidat do CyberArk | `ES_USER`, `ES_PASSWORD` |
| `confluence` | Confluence user | API přístup na wiki.kb.cz | Založit služební účet, nebo použít sdílený (např. `XX_AWX_CONFLUENCE` v safe `DAN_OCSS`) | `CONFLUENCE_USERNAME`, `CONFLUENCE_PASSWORD` |

**Formát EPV cesty** (jak ji Conjur/Secrets Provider očekává, viz `k8s/templates/secrets.yaml`):

```
epv/{lobUser}/{safeName}/{accountName}/username
epv/{lobUser}/{safeName}/{accountName}/password
```

kde `{lobUser}` = `conjur.lobUser` (např. `CAR_TA_LOBUser_PROD`/`_TEST`), `{safeName}` = `conjur.safeName` (např. `DAN_AI-LOG-ANALYZER`), `{accountName}` = hodnota z tabulky výše (např. `ailog_analyzer_user_d1`).

> **Důležité:** Každý účet musí v CyberArku poskytovat správný username a password. Conjur mapuje tyto atributy z EPV záznamu. U virtual dual accountu zajišťuje aktivního člena CyberArk; chart vždy odkazuje na jediný `database` a jediný `database_ddl` název.

Confluence publishery používají `CONFLUENCE_USERNAME` + `CONFLUENCE_PASSWORD` jako Basic auth. Volitelný explicitní `CONFLUENCE_TOKEN` používá Bearer auth a má před Basic auth přednost; standardní prod/nprod chart injektuje username/password z CyberArku.

### 1.3 Confluence — vytvoření stránek

Vytvořit 3 stránky v příslušném Confluence space:

| Stránka | Proměnná v .env |
|---------|-----------------|
| Known Errors | `CONFLUENCE_KNOWN_ERRORS_PAGE_ID` |
| Known Peaks | `CONFLUENCE_KNOWN_PEAKS_PAGE_ID` |
| Recent Incidents | `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` |

Page ID je číslo na konci URL stránky. Zapsat do `.env`.

### 1.4 Notifikace — webhook a/nebo email

Aplikace umí posílat notifikace přes Teams Incoming Webhook, e-mail (na adresu Teams kanálu nebo distribuční schránku), nebo oba kanály zároveň — každý zapnutý kanál dostane notifikaci nezávisle.

- `TEAMS_ENABLED` — master switch, musí být `true`, jinak se neposílá nic.
- `TEAMS_WEBHOOK_URL` — nastav pro doručení přes Teams Incoming Webhook.
- `TEAMS_EMAIL` — nastav pro doručení e-mailem (vyžaduje i `SMTP_HOST`/`SMTP_PORT`/`EMAIL_FROM`).
- Musí být vyplněný alespoň jeden z `TEAMS_WEBHOOK_URL`/`TEAMS_EMAIL` — `install.sh` to validuje.

### 1.5 Elasticsearch

ES cluster musí být dostupný z K8s. Ověřit:
- ES URL (liší se nprod/prod)
- ES index pattern (např. `cluster-app_pcb-*,cluster-app_pca-*`)
- Read-only technický účet (viz 1.2)

---

## 2. Konfigurace

### 2.1 Vyplnění .env

```bash
cd ai-log-analyzer/
cp config/install.conf.example .env
```

Otevřít `.env` a vyplnit non-secret sekce. Soubor je komentovaný s příklady pro nprod i prod.

Do `.env` pro prod/nprod deploy **nepatří runtime hesla ani tokeny** (`DB_PASSWORD`, `ES_PASSWORD`, `CONFLUENCE_TOKEN`, ...). Místo nich se v sekci CyberArk vyplní názvy účtů v safe. Runtime credentials se do podů injektují přes Conjur secrets provider do K8s Secretu `log-analyzer-secrets`.

Klíčové sekce:

| Sekce | Co vyplnit |
|-------|-----------|
| 1. PROSTŘEDÍ | `nprod` nebo `prod`; vybere celý `NPROD_*`/`PROD_*` profil |
| 2. INFRA-APPS | Repo a referenční base branch pro ruční checkout každého prostředí |
| 3. POSTGRESQL | JDBC host/DB, DB role a názvy runtime/DDL účtů nebo virtual dual accounts |
| 4. DB ROLE | Předvyplněná oprávnění `DB_DDL_ROLE` a `DB_APP_ROLE`; obvykle se nemění |
| 5. ELASTICSEARCH | URL a index pattern |
| 6. CONFLUENCE | URL, proxy, page IDs |
| 7–8. NOTIFIKACE & EMAIL | Email cíle, SMTP relay, webhook jen volitelně |
| 9. CYBERARK | App ID, safe a názvy účtů pro ES a Confluence; DB účty jsou v PostgreSQL sekci |
| 10. NAMESPACES | Čárkou oddělený seznam K8s namespace k monitoringu |
| 11–12. DETEKCE | Defaulty — většinou není třeba měnit |

### 2.2 Poznámka k values.yaml

`install.sh` **automaticky vygeneruje** `values.yaml` z `.env` a uloží ho do infra-apps repozitáře. Do `values.yaml` se zapisují non-secret hodnoty a názvy CyberArk účtů, ne hesla.

Vygenerovaný `values.yaml` je autoritativní konfigurace pro K8s prostředí. Na konci instalace skript vypíše cestu — zkontroluj hlavně:

- `conjur.applicationId`, `conjur.lobUser`, `conjur.safeName`
- `conjur.accounts.database`, `database_ddl`, `elastic`, `confluence`
- `env.DB_HOST`, `env.ES_HOST`, `env.ES_INDEX`, Confluence page IDs
- `teams.email`, `teams.enabled`, `email.smtpHost`

---

## 3. Instalace — install.sh

```bash
chmod +x install.sh

# Plná instalace
./install.sh

# Náhled bez Docker build/push, DB migrací a git změn.
# Pozor: values.yaml a chart se i v dry-run režimu přegenerují v INFRA_APPS_DIR.
./install.sh --dry-run

```

### Co install.sh provede:

| Krok | Co dělá |
|------|---------|
| **1. Validace** | Ověří, že všechny povinné proměnné v `.env` jsou vyplněné |
| **2. Databáze** | Standardně přeskočí lokální migrace; s `--run-db-migrations` je spustí pomocí lokálních DB credentials |
| **3. Docker image** | Sestaví a pushne image; `--skip-docker` tento krok přeskočí |
| **4. K8s chart** | Přegeneruje `values.yaml` a zkopíruje `templates/` a `Chart.yaml` do existujícího `infra-apps/ai-log-analyzer/` |
| **5. Git commit & push** | Z aktuálního checkoutu infra repa vytvoří feature branch, commitne chart a pushne ji |
| **6. Souhrn** | Deployment checklist + instrukce pro další kroky |

Před spuštěním musí být infra repo checkoutnuté na správné base branchi pro cílové prostředí. `install.sh` hodnotu `*_INFRA_APPS_BASE_BRANCH` nepoužívá a base branch sám nepřepíná.

Argo Application manifest `infra-apps/ai-log-analyzer.yaml` musí v infra repu existovat a spravuje se samostatně; installer vytváří nebo aktualizuje pouze chart v adresáři `infra-apps/ai-log-analyzer/`.

### Po install.sh:

Skript na konci vypíše přesné kroky — v souhrnu:

1. **Vytvořit PR** z branch `feat/ai-log-analyzer-<env>` v infra-apps repu
2. **Review a merge PR**
3. **ArgoCD sync** — po merge ArgoCD automaticky nasadí CronJoby, PVC, ServiceAccount, Secret a init Job

Argo Application nesmí mít globální `Replace=true`: Kubernetes nedovolí replace bound PVC. `Force=true,Replace=true` patří pouze na immutable init Job a `ApplyOutOfSyncOnly=true` zajistí, že se Job znovu vytvoří jen při skutečné změně jeho manifestu. Před syncem proto není potřeba Job ručně mazat.

---

## 4. Init joby — bootstrap po ArgoCD sync

Po úspěšném ArgoCD sync (vše Synced & Healthy):

```bash
# Ověřit, že vše běží
kubectl get all -n ai-log-analyzer

# Sledovat průběh
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

Init job provede:
1. **DB migrations** — spustí SQL migrace přes `DB_DDL_USER`/`DB_DDL_PASSWORD` z CyberArku a nastaví oprávnění pro roli z `DB_APP_ROLE`
2. **Backfill** — stáhne error logy z ES za posledních N dní (default: 21)
3. **Threshold calc** — vypočítá P93/CAP prahy z backfill dat
4. **Verify** — zobrazí vypočtené thresholdy

Po dokončení init jobu systém běží autonomně přes CronJoby.

---

## 5. Ověření

### K8s stav

```bash
# CronJoby existují
kubectl get cronjobs -n ai-log-analyzer

# První job proběhl
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp

# Logy posledního jobu
kubectl logs job/<job-name> -n ai-log-analyzer
```

### DB data

```sql
-- Počet raw dat (po init jobu)
SELECT COUNT(*) FROM ailog_peak.peak_raw_data;

-- Thresholdy per namespace
SELECT namespace, COUNT(*) FROM ailog_peak.peak_thresholds GROUP BY namespace;
```

### Confluence

Po prvním úspěšném backfill jobu mají být aktualizované všechny tři stránky. `backfill.py` publikuje Recent Incidents z `problem_report_*.txt` na `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID`; následný `confluence_csv_uploader.py` publikuje Known Errors a Known Peaks z registry CSV exportů.

---

## 6. Deployment checklist

`install.sh` vypíše checklist automaticky. Kompletní seznam:

- [ ] **Prerekvizity:** DB existuje, uživatelé založeni
- [ ] **Prerekvizity:** CyberArk safe vytvořen, účty uloženy
- [ ] **Prerekvizity:** Confluence stránky vytvořeny, Page IDs zaznamenány
- [ ] **Prerekvizity:** Email cíle pro notifikace ověřený
- [ ] **Prerekvizity:** ES účet založen a v CyberArk
- [ ] `.env` vyplněn bez runtime hesel a validován (`install.sh` krok 1)
- [ ] CyberArk account names zapsané do `values.yaml`
- [ ] `IMAGE_TAG` je explicitní a image s tímto tagem je dostupná v registry
- [ ] Kompletní K8s chart vygenerován v infra-apps (`install.sh` krok 4)
- [ ] Chart validován pomocí `helm lint <chart-dir>` a `helm template <release> <chart-dir>`
- [ ] Branch pushnuta (`install.sh` krok 5)
- [ ] PR vytvořen a mergnut
- [ ] ArgoCD sync proběhl — Synced & Healthy
- [ ] Argo Application nemá globální `Replace=true`; init Job má resource-level `Force=true,Replace=true`
- [ ] Init job dokončen (DB migrations + backfill + thresholds)
- [ ] CronJoby běží (regular, backfill, thresholds)
- [ ] Email/Teams notifikace ověřena
- [ ] Confluence stránky aktualizovány

---

## 7. Lokální testování (volitelné)

Pro vývoj/debugging bez K8s:

```bash
cp config/install.conf.example .env
# Lokálně doplnit credentials jen pro vývoj/debugging mimo K8s.
# Prod/nprod runtime je bere z CyberArku přes Conjur.

# Dry-run regular phase
python3 scripts/regular_phase.py --window 15 --dry-run

# Dry-run backfill
python3 scripts/backfill.py --days 1 --dry-run

# Zobrazit thresholdy
python3 scripts/core/peak_detection.py --show-thresholds
```

> **Pozor:** Lokální testy vyžadují síťový přístup k DB a ES — v prod prostředí je to obvykle dostupné jen z K8s clusteru.
