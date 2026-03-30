# Instalace — AI Log Analyzer

Kompletní průvodce instalací: od prerekvizit přes konfiguraci až po K8s deployment.

---

## Prerekvizity

### Runtime

- Python 3.11+
- PostgreSQL (schema `ailog_peak`)
- Elasticsearch (zdroj error logů)
- SMTP server (pro email notifikace)

### Python balíčky

```bash
pip install psycopg2-binary python-dotenv requests pyyaml
```

Nebo offline (Docker):
```bash
pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt
```

### Databáze

Dva uživatelé:
- **App user** (`DB_USER`) — `SELECT, INSERT, UPDATE, DELETE` na tabulkách v `ailog_peak`
- **DDL user** (`DB_DDL_USER`) — pro migraci schématu a `SET ROLE`

---

## Krok za krokem

### 1. Konfigurace

```bash
cp .env.example .env
# Vyplnit:
#   ES_URL, ES_INDEX, ES_USER, ES_PASSWORD
#   DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
#   DB_DDL_USER, DB_DDL_PASSWORD, DB_DDL_ROLE
#   SMTP_HOST, SMTP_PORT, EMAIL_FROM, TEAMS_EMAIL
#   ALERT_DIGEST_ENABLED=true
```

Sledované namespace:
```bash
vi config/namespaces.yaml
# namespaces:
#   - pcb-dev-01-app
#   - pcb-sit-01-app
#   - pcb-uat-01-app
```

### 2. Databáze — vytvoření schématu

```bash
# Spustit migrace (jako DDL user)
psql -h $DB_HOST -p $DB_PORT -U $DB_DDL_USER -d $DB_NAME \
  -f scripts/migrations/000_create_base_tables.sql
psql -h $DB_HOST -p $DB_PORT -U $DB_DDL_USER -d $DB_NAME \
  -f scripts/migrations/001_create_peak_thresholds.sql
psql -h $DB_HOST -p $DB_PORT -U $DB_DDL_USER -d $DB_NAME \
  -f scripts/migrations/002_create_enhanced_analysis_tables.sql
```

### 3. Oprávnění

```sql
SET ROLE role_ailog_analyzer_ddl;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ailog_peak TO role_ailog_analyzer_app;
```

### 4. Ověření DB

```bash
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -c \
  "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='ailog_peak';"
# Očekáváno: 4+ tabulek
```

### 5. Adresářová struktura

```bash
mkdir -p registry scripts/reports scripts/exports/latest /var/log/ailog
```

### 6. First run (test)

```bash
# Jednorázové spuštění
python3 scripts/regular_phase.py

# Ověření výstupu
ls scripts/reports/
cat registry/known_problems.yaml
```

---

## Bootstrap — naplnění historických dat

Pro fungování P93/CAP spike detekce je potřeba minimálně 2 týdny historických dat.

### Varianta A: Automatický init (K8s)

```bash
helm template k8s/ | kubectl apply -f - -l job-type=init
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

Konfigurace v `k8s/values.yaml`:
```yaml
init:
  backfillDays: 21
  backfillWorkers: 4
  thresholdWeeks: 3
  activeDeadlineSeconds: 14400  # max 4 hodiny
```

### Varianta B: Manuální bootstrap

```bash
# 1. Backfill 21 dní — plní peak_raw_data + peak_investigation
python3 scripts/backfill.py --days 21 --workers 4

# 2. Vypočítat P93/CAP thresholdy
python3 scripts/core/calculate_peak_thresholds.py --weeks 3

# 3. Ověřit thresholdy
python3 scripts/core/peak_detection.py --show-thresholds

# 4. Otestovat konkrétní hodnotu
python3 scripts/core/peak_detection.py --check 500 pcb-sit-01-app 0
#                                              ^value ^namespace    ^DOW(0=Po)
```

### Ověření dat po bootstrap

```sql
-- Počet raw data záznamů
SELECT COUNT(*) FROM ailog_peak.peak_raw_data;

-- Thresholdy per namespace
SELECT namespace, COUNT(*) as threshold_count
FROM ailog_peak.peak_thresholds GROUP BY namespace ORDER BY namespace;

-- CAP hodnoty
SELECT namespace, cap_value FROM ailog_peak.peak_threshold_caps ORDER BY namespace;
```

---

## Kubernetes deployment

### Docker build

```bash
docker build -t dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r63 .
docker push dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r63
```

### CronJob manifesty

V `k8s/` jsou Helm šablony pro:

| CronJob | Schedule | Popis |
|---------|----------|-------|
| `ai-log-analyzer-regular` | `*/15 * * * *` | Hlavní 15min pipeline |
| `ai-log-analyzer-backfill` | `0 2 * * *` | Denní backfill |
| `ai-log-analyzer-thresholds` | `0 3 * * 0` | Týdenní přepočet P93/CAP |

### Resource požadavky

| Job | CPU request | Memory request | CPU limit | Memory limit |
|-----|-------------|----------------|-----------|--------------|
| Regular | 500m | 1Gi | 1000m | 2Gi |
| Backfill | 1000m | 2Gi | 2000m | 4Gi |

### Env vars (K8s Secret)

Všechny proměnné z `.env` se předají jako K8s Secret → `envFrom` v CronJob spec.

```yaml
envFrom:
  - secretRef:
      name: ai-log-analyzer-config
```

---

## Deployment checklist

- [ ] `.env` vyplněn a ověřen
- [ ] DB schéma migrace proběhla
- [ ] DB oprávnění nastavena
- [ ] Backfill testován lokálně (1 den)
- [ ] Regular phase testován (15 min okno)
- [ ] P93/CAP thresholds naplněny (backfill ≥14 dní + `calculate_peak_thresholds.py`)
- [ ] PeakDetector ověřen (`--show-thresholds`)
- [ ] Email/Teams notifikace testovány
- [ ] Confluence credentials ověřeny
- [ ] Docker image built & pushed
- [ ] K8s manifesty deployed
- [ ] Resource limits nastaveny
- [ ] Monitoring/alerting setup
- [ ] Backup strategie pro registry YAML
