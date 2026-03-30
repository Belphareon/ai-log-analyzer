# Instalace — AI Log Analyzer

Kompletní průvodce od prerekvizit po běžící systém v K8s.

---

## Přehled procesu

```
1. Prerekvizity (manuální)       — DB, CyberArk, Confluence, Teams
2. Konfigurace (.env)            — vyplnit .env.example → .env
3. Instalační skript (install.sh) — automatická DB migrace, Docker build, K8s manifesty, git push
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
| **Schéma** | `ailog_peak` (vytvoří install.sh automaticky) |
| **DDL role** | `role_ailog_analyzer_ddl` — vlastní schéma, CREATE TABLE |
| **App role** | `role_ailog_analyzer_app` — SELECT/INSERT/UPDATE/DELETE |
| **DDL user** | Přiřazen do `role_ailog_analyzer_ddl` |
| **App user** | Přiřazen do `role_ailog_analyzer_app` |

Hostnames se liší podle prostředí:

| Prostředí | DB Host |
|-----------|---------|
| nprod | `P050TD01.DEV.KB.CZ` |
| prod | `<prod_db_host>` (dle DBA) |

> **Tabulky a oprávnění vytváří `install.sh` automaticky** — stačí mít DB, schéma a uživatele.

### 1.2 CyberArk (SPEED) — uložení credentials

Všechny credentials jsou uloženy v CyberArk SPEED safe a do K8s se injektují přes Conjur secrets provider.

**Kroky v PSIAM portálu:**

1. **Registrovat Application Identity** — unikátní identifikátor aplikace v Conjur (např. `AI-LOG-ANALYZER`). Slouží pro autentizaci podu vůči Conjur API.
2. **Vytvořit SPEED Safe** — úložiště pro credentials (např. `DAN_AI-LOG-ANALYZER`).
3. **Uložit účty do safe:**

| Účet | Co to je | Jak získat |
|------|----------|-----------|
| **DB DML user** | PostgreSQL app user | Viz 1.1 — založit u DBA |
| **DB DDL user** | PostgreSQL DDL user | Viz 1.1 — založit u DBA |
| **ES read user** | Elasticsearch read-only | Založit technický účet (např. `XX_<TEAM>_ES_READ`), přidat do CyberArk |
| **Confluence user** | API přístup na wiki.kb.cz | Založit služební účet, nebo použít sdílený (např. `XX_AWX_CONFLUENCE` v safe `DAN_OCSS`) |

> **Důležité:** Každý účet musí být v CyberArk uložen se správným username a password. Conjur mapuje `username` a `password` atributy z EPV záznamu.

### 1.3 Confluence — vytvoření stránek

Vytvořit 3 stránky v příslušném Confluence space:

| Stránka | Proměnná v .env |
|---------|-----------------|
| Known Errors | `CONFLUENCE_KNOWN_ERRORS_PAGE_ID` |
| Known Peaks | `CONFLUENCE_KNOWN_PEAKS_PAGE_ID` |
| Recent Incidents | `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` |

Page ID je číslo na konci URL stránky. Zapsat do `.env`.

### 1.4 Teams — webhook

Vytvořit Incoming Webhook v cílovém Teams kanálu. Zapsat URL a email adresu kanálu do `.env`.

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
cp .env.example .env
```

Otevřít `.env` a vyplnit **všechny** sekce. Soubor je komentovaný s příklady pro nprod i prod.

Klíčové sekce:

| Sekce | Co vyplnit |
|-------|-----------|
| 1. PROSTŘEDÍ | `nprod` nebo `prod` |
| 2. DOCKER IMAGE | Squad a tag (např. `pccm-sq016`, `r63`) |
| 3. GIT REPOZITÁŘE | Cesta k tomuto repu + k infra-apps repu |
| 4. POSTGRESQL | Host, uživatelé (z prerekvizit) |
| 5. ELASTICSEARCH | URL, index pattern, účet |
| 6. CONFLUENCE | Token, page IDs (z prerekvizit) |
| 7–8. TEAMS & EMAIL | Webhook, email kanálu |
| 9. CYBERARK | App ID, safe, názvy účtů |
| 10. NAMESPACES | Čárkou oddělený seznam K8s namespace k monitoringu |
| 11–12. DETEKCE | Defaulty — většinou není třeba měnit |

### 2.2 Poznámka k values.yaml

`install.sh` **automaticky vygeneruje** `values.yaml` z `.env` a uloží ho do infra-apps repozitáře. Na konci instalace skript vypíše cestu — zkontroluj a dolad, pokud je třeba.

---

## 3. Instalace — install.sh

```bash
chmod +x install.sh

# Plná instalace
./install.sh

# Jen validace (bez změn)
./install.sh --dry-run

# Přeskočit DB (už existuje z dřívějška)
./install.sh --skip-db

# Přeskočit Docker build (image už existuje)
./install.sh --skip-docker
```

### Co install.sh provede:

| Krok | Co dělá |
|------|---------|
| **1. Validace** | Ověří, že všechny povinné proměnné v `.env` jsou vyplněné |
| **2. DB migrace** | Připojí se jako DDL user, spustí SQL migrace, nastaví oprávnění, ověří tabulky |
| **3. Docker build & push** | Buildne image a pushne do registru |
| **4. K8s manifesty** | Vygeneruje `values.yaml`, zkopíruje/aktualizuje Helm templates do infra-apps repu |
| **5. Git commit & push** | Vytvoří branch `feat/ai-log-analyzer-<env>-<tag>`, commitne, pushne |
| **6. Souhrn** | Deployment checklist + instrukce pro další kroky |

### Po install.sh:

Skript na konci vypíše přesné kroky — v souhrnu:

1. **Vytvořit PR** z branch `feat/ai-log-analyzer-<env>-<tag>` v infra-apps repu
2. **Review a merge PR**
3. **ArgoCD sync** — po merge ArgoCD automaticky nasadí CronJoby, PVC, ServiceAccount, Secret

---

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
1. **Backfill** — stáhne error logy z ES za posledních N dní (default: 21)
2. **Threshold calc** — vypočítá P93/CAP prahy z backfill dat
3. **Verify** — zobrazí vypočtené thresholdy

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

Po prvním backfill jobu by měly být aktualizované stránky Known Errors, Known Peaks, Recent Incidents.

---

## 6. Deployment checklist

`install.sh` vypíše checklist automaticky. Kompletní seznam:

- [ ] **Prerekvizity:** DB existuje, uživatelé založeni
- [ ] **Prerekvizity:** CyberArk safe vytvořen, účty uloženy
- [ ] **Prerekvizity:** Confluence stránky vytvořeny, Page IDs zaznamenány
- [ ] **Prerekvizity:** Teams webhook nastaven
- [ ] **Prerekvizity:** ES účet založen a v CyberArk
- [ ] `.env` vyplněn a validován (`install.sh` krok 1)
- [ ] DB migrace provedena (`install.sh` krok 2)
- [ ] Docker image built & pushed (`install.sh` krok 3)
- [ ] K8s manifesty vygenerovány a v infra-apps (`install.sh` krok 4)
- [ ] Branch pushed (`install.sh` krok 5)
- [ ] PR vytvořen a mergnout
- [ ] ArgoCD sync proběhl — Synced & Healthy
- [ ] Init job dokončen (backfill + thresholds)
- [ ] CronJoby běží (regular, backfill, thresholds)
- [ ] Email/Teams notifikace ověřena
- [ ] Confluence stránky aktualizovány

---

## 7. Lokální testování (volitelné)

Pro vývoj/debugging bez K8s:

```bash
cp .env.example .env
# Doplnit credentials (potřeba přímý přístup k DB a ES)

# Dry-run regular phase
python3 scripts/regular_phase.py --window 15 --dry-run

# Dry-run backfill
python3 scripts/backfill.py --days 1 --dry-run

# Zobrazit thresholdy
python3 scripts/core/peak_detection.py --show-thresholds
```

> **Pozor:** Lokální testy vyžadují síťový přístup k DB a ES — v prod prostředí je to obvykle dostupné jen z K8s clusteru.
