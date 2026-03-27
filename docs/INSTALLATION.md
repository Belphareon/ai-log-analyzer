# Instalační příručka — AI Log Analyzer

**Aktualizováno:** 2026-03-27

---

## Obsah

1. [Předpoklady](#1-předpoklady)
2. [Konfigurace prostředí (.env)](#2-konfigurace-prostředí-env)
3. [Databáze — schema a oprávnění](#3-databáze--schema-a-oprávnění)
4. [Python závislosti](#4-python-závislosti)
5. [Registry adresář](#5-registry-adresář)
6. [Inicializace dat (backfill)](#6-inicializace-dat-backfill)
7. [Přepočet thresholdů](#7-přepočet-thresholdů)
8. [Ověření funkčnosti](#8-ověření-funkčnosti)
9. [Kubernetes CronJob nasazení](#9-kubernetes-cronjob-nasazení)

---

## 1. Předpoklady

### Software

- Python 3.9+
- PostgreSQL 12+ (schema `ailog_peak`)
- Elasticsearch 7.x+
- Docker + Kubernetes (pro produkční nasazení)

### Credentials

| Systém | Potřeba |
|--------|---------|
| Elasticsearch | URL, username, password (read-only ES user) |
| PostgreSQL (čtení) | DB host, port, database, user, password |
| PostgreSQL (zápis) | DDL user + DDL role (`SET ROLE`) |
| SMTP | Host, port, `from` adresa, cílová `teams_email` adresa |
| Teams (optional) | Webhook URL |
| Confluence (optional) | URL, username, API token |

---

## 2. Konfigurace prostředí (.env)

```bash
# V kořeni repozitáře
cp .env.example .env
```

Vyplnit všechny hodnoty:

```bash
# ── Elasticsearch ───────────────────────────────────────────────────────────
ES_URL=https://elasticsearch.kb.cz:9500
ES_INDEX=cluster-app_your-app-*
ES_USER=your_es_read_user
ES_PASSWORD=your_es_password
ES_VERIFY_CERTS=false

# ── PostgreSQL (čtení) ──────────────────────────────────────────────────────
DB_HOST=your-db-host.example.com
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_read_user
DB_PASSWORD=your_read_password

# ── PostgreSQL (zápis — DDL) ────────────────────────────────────────────────
# Nutné pro INSERT/UPDATE do ailog_peak.*
DB_DDL_USER=ailog_ddl_user
DB_DDL_PASSWORD=your_ddl_password
DB_DDL_ROLE=role_ailog_analyzer_ddl      # Výchozí, změnit pokud se liší

# ── Email notifikace ────────────────────────────────────────────────────────
SMTP_HOST=smtp.kb.cz
SMTP_PORT=25
EMAIL_FROM=ai-log-analyzer@kb.cz
TEAMS_EMAIL=your-teams-channel@your-tenant.teams.ms.com

# ── Teams webhook (optional) ────────────────────────────────────────────────
TEAMS_WEBHOOK_URL=https://your-teams-webhook-url

# ── Confluence (optional) ───────────────────────────────────────────────────
CONFLUENCE_URL=https://wiki.kb.cz
CONFLUENCE_USERNAME=your_confluence_user
CONFLUENCE_API_TOKEN=your_confluence_token

# ── Alertování (volitelné — výchozí hodnoty jsou v pořádku) ─────────────────
ALERT_DIGEST_ENABLED=true          # true = 1 souhrnný email; false = 1 email per peak
ALERT_COOLDOWN_MIN=45              # Minimální interval mezi alerty pro stejný peak
ALERT_HEARTBEAT_MIN=120            # Opakovat alert pokud peak přetrvává déle
MAX_PEAK_ALERTS_PER_WINDOW=3       # Max peaků v 1 cron okně (zbytek -> digest)

# ── Detekce (volitelné) ──────────────────────────────────────────────────────
MIN_NAMESPACE_PEAK_VALUE=1         # Absolutní minimum pro spike detekci
PERCENTILE_LEVEL=0.93              # P93 (93. percentil) — změnit na 0.90 pro citlivější detekci
EWMA_ALPHA=0.3                     # EWMA alpha pro baseline výpočet
```

---

## 3. Databáze — schema a oprávnění

### Schema

Systém potřebuje schema `ailog_peak` v PostgreSQL databázi. Vytvoření:

```sql
CREATE SCHEMA ailog_peak;

CREATE TABLE ailog_peak.peak_raw_data (
    id           SERIAL PRIMARY KEY,
    namespace    VARCHAR(128) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end   TIMESTAMPTZ NOT NULL,
    error_count  INTEGER NOT NULL,
    day_of_week  SMALLINT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ailog_peak.peak_thresholds (
    namespace        VARCHAR(128) NOT NULL,
    day_of_week      SMALLINT NOT NULL,
    percentile_value FLOAT NOT NULL,
    sample_count     INTEGER,
    updated_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (namespace, day_of_week)
);

CREATE TABLE ailog_peak.peak_threshold_caps (
    namespace  VARCHAR(128) PRIMARY KEY,
    cap_value  FLOAT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ailog_peak.peak_investigation (
    id         SERIAL PRIMARY KEY,
    peak_key   VARCHAR(256) NOT NULL,
    problem_key VARCHAR(256),
    namespace  VARCHAR(128),
    peak_type  VARCHAR(32),
    first_seen TIMESTAMPTZ,
    last_seen  TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Oprávnění

```sql
-- Čtecí user (pro pipeline)
GRANT USAGE ON SCHEMA ailog_peak TO ailog_read_user;
GRANT SELECT ON ALL TABLES IN SCHEMA ailog_peak TO ailog_read_user;

-- DDL user (pro zápis)
GRANT USAGE ON SCHEMA ailog_peak TO ailog_ddl_user;
GRANT ALL ON ALL TABLES IN SCHEMA ailog_peak TO role_ailog_analyzer_ddl;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ailog_peak TO role_ailog_analyzer_ddl;

-- Role pro SET ROLE mechanismus
GRANT role_ailog_analyzer_ddl TO ailog_ddl_user;
```

> **Pozor:** Systém se při zápisu připojí jako `DB_DDL_USER` a před každou INSERT/UPDATE operací
> zavolá `SET ROLE DB_DDL_ROLE`. Bez tohoto mechanismu zápis selže.

---

## 4. Python závislosti

Závislosti jsou v `requirements.txt`:

```bash
pip install -r requirements.txt
```

Nebo z lokálních wheels (pro air-gapped prostředí):

```bash
pip install --no-index --find-links=wheels/ -r requirements.txt
```

Závislosti: `psycopg2-binary`, `python-dotenv`, `requests`, `pyyaml`

---

## 5. Registry adresář

Systém potřebuje zapisovatelný adresář `registry/` v kořeni repozitáře. Vytvoří se automaticky, ale musí být persistentní mezi běhy (v Kubernetes: PersistentVolumeClaim).

Adresář obsahuje:
- `known_problems.yaml` — append-only evidence všech problémů
- `known_peaks.yaml` — append-only evidence peaků
- `fingerprint_index.yaml` — lookup index fingerprintů
- `alert_state_regular_phase.json` — stav alertů (cooldown, trend)

Konfigurováno proměnnou `REGISTRY_DIR` (výchozí: `<repo_root>/registry`).

---

## 6. Inicializace dat (backfill)

Před prvním regular-phase během je nutné naplnit registry a DB historickými daty.

```bash
# Zpracuj posledních 14 dní
python3 scripts/backfill.py --days 14

# Nebo konkrétní rozsah
python3 scripts/backfill.py --from "2026-03-01" --to "2026-03-14"

# S paralelismem (rychlejší)
python3 scripts/backfill.py --days 14 --workers 4
```

Backfill:
1. Načte logy z ES pro každý den
2. Spustí detekci pipeline
3. Zapíše výsledky do `ailog_peak.peak_raw_data`
4. Naplní YAML registry (`known_problems.yaml`, `known_peaks.yaml`)

---

## 7. Přepočet thresholdů

Po backfillu je nutné spočítat P93/CAP prahy (doporučeno po min. 2 týdnech dat):

```bash
python3 scripts/core/calculate_peak_thresholds.py

# Ověření bez zápisu
python3 scripts/core/calculate_peak_thresholds.py --dry-run

# Pouze z posledních 4 týdnů dat
python3 scripts/core/calculate_peak_thresholds.py --weeks 4
```

Bez vypočítaných thresholdů spike detekce funguje pouze v fallback módu (poměr vůči baseline).

---

## 8. Ověření funkčnosti

```bash
# Test pipeline běhu (bez zápisu alertů)
python3 scripts/regular_phase.py

# Ověření DB připojení
python3 test_db_connection.py

# Ověření Confluence připojení
python3 test_confluence_connection.py
```

Očekávaný výstup regular_phase:

```
✅ Registry loaded: 42 problems, 18 peaks
✅ Baseline loaded: 7 days
Fetching logs from ES...
Running pipeline...
✅ 3 incidents detected
✅ Saved 12 namespace totals to peak_raw_data
📧 Peak digest sent to teams@...
```

---

## 9. Kubernetes CronJob nasazení

### Docker image

```bash
docker build -t dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:<tag> .
docker push dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:<tag>
```

### Helm values

Aktualizovat tag v Helm values souboru:

```
~/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/values.yaml
```

```yaml
regular:
  image: dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:<tag>
  imagePullPolicy: IfNotPresent
```

### CronJob harmonogram

| Job | Schedule | Skript |
|-----|----------|--------|
| `log-analyzer-regular` | `*/15 * * * *` | `python3 scripts/regular_phase.py` |
| `log-analyzer-backfill` | `0 2 * * *` | `python3 scripts/backfill.py --days 1` |

Viz `k8s/` pro úplné manifesty.

### PersistentVolumeClaim

Registry adresář musí být persistentní! V Kubernetes je namountovaný jako PVC.
Bez PVC se při každém restartu CronJobu zahodí celá knowledge base.
