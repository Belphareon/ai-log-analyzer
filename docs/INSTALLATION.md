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

Požádat DBA o vytvoření:

| Položka | Popis |
|---------|-------|
| **Databáze** | `ailog_analyzer` |
| **Schéma** | `ailog_peak` (vytvoří K8s init job automaticky) |
| **DDL role** | `role_ailog_analyzer_ddl` — vlastní schéma, CREATE TABLE |
| **App role** | `role_ailog_analyzer_app` — SELECT/INSERT/UPDATE/DELETE |
| **DDL user** | Přiřazen do `role_ailog_analyzer_ddl` |
| **App user** | Přiřazen do `role_ailog_analyzer_app` |

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
3. **Uložit účty do safe** — čtyři DB účty D1/D2 a účty pro ES a Confluence. Každý účet musí mít v EPV vyplněný `username` a `password` atribut:

| `values.yaml` klíč (`conjur.accounts.*`) | Účet | Co to je | Jak získat | Secret klíče v podu |
|---|---|---|---|---|
| `database.d1/d2` | DB runtime účty | PostgreSQL účty pro SELECT/INSERT/UPDATE/DELETE | `DB_USER_D1` a `DB_USER_D2` získané při založení DB | `DB_USER`, `DB_PASSWORD` (aktuálně D1) |
| `database_ddl.d1/d2` | DB DDL účty | PostgreSQL účty pro CREATE/ALTER/DROP, používané init jobem | `DB_DDL_USER_D1` a `DB_DDL_USER_D2` získané při založení DB | `DB_DDL_USER`, `DB_DDL_PASSWORD` (aktuálně D1) |
| `elastic` | ES read user | Elasticsearch read-only | Založit technický účet (např. `XX_<TEAM>_ES_READ`), přidat do CyberArk | `ES_USER`, `ES_PASSWORD` |
| `confluence` | Confluence user | API přístup na wiki.kb.cz | Založit služební účet, nebo použít sdílený (např. `XX_AWX_CONFLUENCE` v safe `DAN_OCSS`) | `CONFLUENCE_USERNAME`, `CONFLUENCE_PASSWORD` |

**Formát EPV cesty** (jak ji Conjur/Secrets Provider očekává, viz `k8s/templates/secrets.yaml`):

```
epv/{lobUser}/{safeName}/{accountName}/username
epv/{lobUser}/{safeName}/{accountName}/password
```

kde `{lobUser}` = `conjur.lobUser` (např. `CAR_TA_LOBUser_PROD`/`_TEST`), `{safeName}` = `conjur.safeName` (např. `DAN_AI-LOG-ANALYZER`), `{accountName}` = hodnota z tabulky výše (např. `ailog_analyzer_user_d1`).

> **Důležité:** Každý účet musí být v CyberArk uložen se správným username a password. Conjur mapuje `username` a `password` atributy z EPV záznamu. Bez aktivních D1, ES a Confluence účtů se init job/CronJoby nespustí. D2 účty jsou zatím připravené pro pozdější dual-account přepínání.

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


### 1.5 Elasticsearch

ES cluster musí být dostupný z K8s. Ověřit:


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
| 2. INFRA-APPS | Repo a base branch pro každé prostředí |
| 3. POSTGRESQL | JDBC host/DB a názvy účtů `DB_DDL_USER_D1/D2`, `DB_USER_D1/D2` |
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



## 3. Instalace — install.sh

```bash
chmod +x install.sh

# Plná instalace
./install.sh

# Jen validace (bez změn)
./install.sh --dry-run

# Volitelně použít jiný konfigurační soubor
./install.sh --config /cesta/ke/config.env
```

### Co install.sh provede:

| Krok | Co dělá |
|------|---------|
| **1. Validace** | Ověří, že všechny povinné proměnné v `.env` jsou vyplněné |
| **2. Infra branch** | Oznámí a vytvoří novou branch z base branche zvoleného prostředí |
| **3. K8s struktura** | Vytvoří `infra-apps/ai-log-analyzer.yaml` a kompletní chart v `infra-apps/ai-log-analyzer/` |
| **4. Validace** | Ověří YAML, `helm lint` a `helm template` |
| **5. Git commit & push** | Commitne pouze oba AI Log Analyzer cíle a pushne branch |
| **6. Souhrn** | Deployment checklist + instrukce pro další kroky |

### Po install.sh:

Skript na konci vypíše přesné kroky — v souhrnu:

1. **Vytvořit PR** z branch `feat/ai-log-analyzer-<env>` v infra-apps repu
2. **Review a merge PR**
3. **ArgoCD sync** — po merge ArgoCD automaticky nasadí CronJoby, PVC, ServiceAccount, Secret


## 4. Init joby — bootstrap po ArgoCD sync

Po úspěšném ArgoCD sync (vše Synced & Healthy):

```bash
# Ověřit, že vše běží
kubectl get all -n ai-log-analyzer

# Spustit init job (backfill + threshold výpočet)
helm template <infra-apps-dir> | kubectl apply -f - -l job-type=init

# Sledovat průběh
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

Init job provede:
1. **DB migrations** — spustí SQL migrace přes `DB_DDL_USER`/`DB_DDL_PASSWORD` z CyberArku a nastaví oprávnění pro `role_ailog_analyzer_app`
2. **Backfill** — stáhne error logy z ES za posledních N dní (default: 21)
3. **Threshold calc** — vypočítá P93/CAP prahy z backfill dat
4. **Verify** — zobrazí vypočtené thresholdy

Po dokončení init jobu systém běží autonomně přes CronJoby.


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
SELECT COUNT(*) FROM ailog_peak.peak_raw_data;

SELECT namespace, COUNT(*) FROM ailog_peak.peak_thresholds GROUP BY namespace;
```

### Confluence

Po prvním backfill jobu by měly být aktualizované stránky Known Errors, Known Peaks, Recent Incidents.


## 6. Deployment checklist

`install.sh` vypíše checklist automaticky. Kompletní seznam:



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
