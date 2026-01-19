# 🚀 GETTING STARTED - AI Log Analyzer

**Phase 5B: INIT Phase 3 Weeks - Complete Setup and Execution Guide**

**Version:** 2.0 | **Updated:** 2026-01-12 | **Target:** 24,192 rows baseline

---

## 📋 What You'll Do

1. ✅ Verify database connection
2. ✅ Setup DB schema (one-time)
3. ✅ Ingest all 14 data files (21 days)
4. ✅ Fill missing windows (complete grid)
5. ✅ Verify success (24,192 rows)
6. ✅ Create backup

**Estimated Time:** 30-45 minutes

---

## ⚠️ Prerequisites

- ✅ Access to database: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
- ✅ `.env` file with DB credentials
- ✅ All 14 peak_fixed_*.txt files in `/tmp/`
- ✅ Python 3.8+
- ✅ psycopg2 and python-dotenv installed

---

## 🚀 STEP-BY-STEP EXECUTION

### 1.2 Výsledek

- ✅ Po schválení obdržíte **credentials** na svůj mail
- ✅ Poznamenejte si: **username** a **password**
- ✅ Formát účtu: `XX_<NAZEV>_ES_READ`

**Příklad emailu s credentials:**
```
Subject: Tech účet vytvořen - XX_PCB_ES_READ

Username: XX_PCB_ES_READ
Password: ************
Domain: DS

Účet byl vytvořen a je připraven k použití.
```

---

## STEP 1: Verify Database Connection

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

python3 << 'EOF'
import os, psycopg2
from dotenv import load_dotenv

load_dotenv()
try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST'),
        port=int(os.getenv('DB_PORT')),
        database=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
    print("✅ Database connection successful!")
    conn.close()
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print("   Check: .env file exists and DB_HOST/DB_PORT/DB_PASSWORD are correct")
EOF
```

---

## STEP 2: Setup Database (One-Time)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer/scripts

# Create schema and tables
echo "Creating schema..."
python3 setup_peak_db.py

# Grant permissions
echo "Granting permissions..."
python3 grant_permissions.py

echo "✅ Database setup complete!"
```

---

## STEP 3: Ingest All 21 Days (Main Work)

```bash
cd /home/jvsete/git/sas/ai-log-analyzer/scripts

echo "📊 Starting INIT Phase ingestion (3 weeks, no peak detection)..."

# Process all 14 files sequentially
for file in /tmp/peak_fixed_2025_12_01.txt \
            /tmp/peak_fixed_2025_12_02_03.txt \
            /tmp/peak_fixed_2025_12_04_05.txt \
            /tmp/peak_fixed_2025_12_06_07.txt \
            /tmp/peak_fixed_2025_12_08_09.txt \
            /tmp/peak_fixed_2025_12_10_11.txt \
            /tmp/peak_fixed_2025_12_12_13.txt \
            /tmp/peak_fixed_2025_12_14_15.txt \
            /tmp/peak_fixed_2025_12_16.txt \
            /tmp/peak_fixed_2025_12_17.txt \
            /tmp/peak_fixed_2025_12_18.txt \
            /tmp/peak_fixed_2025_12_19.txt \
            /tmp/peak_fixed_2025_12_20.txt \
            /tmp/peak_fixed_2025_12_21.txt
do
  echo "Processing: $(basename $file)"
  python3 ingest_from_log_v2.py --init "$file"
  if [ $? -eq 0 ]; then
    echo "  ✅ Success"
  else
    echo "  ⚠️ Warning - check output above"
  fi
done

echo "✅ All files processed!"
```

**What happens:**
- Reads each file's 1,918 patterns (96 windows × 12 namespaces + variations)
- NO peak detection (--init flag disables it)
- Aggregates duplicates using weighted average
- Inserts to peak_statistics

---

## STEP 4: Fill Missing Windows

```bash
cd /home/jvsete/git/sas/ai-log-analyzer/scripts

echo "Completing the grid..."
python3 fill_missing_windows.py

echo "✅ Grid completed!"
```

**Result:** All 24,192 combinations present (21 days × 96 windows × 12 namespaces)

---

## STEP 5: Verify Success

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

python3 << 'EOF'
import os, psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cursor = conn.cursor()

# Checks
cursor.execute("SELECT COUNT(*) FROM peak_statistics;")
total = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(DISTINCT day_of_week) FROM peak_statistics;")
days = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(DISTINCT namespace) FROM peak_statistics;")
namespaces = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM peak_statistics WHERE mean_errors = 0.0;")
zeros = cursor.fetchone()[0]

# Results
print(f"📊 INIT PHASE COMPLETE!")
print(f"✅ Rows: {total}/24192 {'✅' if total == 24192 else '❌'}")
print(f"✅ Days: {days}/7 {'✅' if days == 7 else '❌'}")
print(f"✅ Namespaces: {namespaces}/12 {'✅' if namespaces == 12 else '❌'}")
print(f"✅ Zero rows (OK status): {zeros}")
print(f"✅ Error rows: {total - zeros}")

success = (total == 24192 and days == 7 and namespaces == 12)
if success:
    print(f"\n🎉 READY FOR PHASE 6 (Regular Phase with peak detection)!")
else:
    print(f"\n⚠️ INCOMPLETE - Check counts above")

conn.close()
EOF
```

---

## STEP 6: Create Backup

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

python3 << 'EOF'
import os, psycopg2, csv
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cursor = conn.cursor()

# Export
cursor.execute("""
    SELECT day_of_week, hour_of_day, quarter_hour, namespace,
           mean_errors, stddev_errors, samples_count
    FROM peak_statistics
    ORDER BY day_of_week, hour_of_day, quarter_hour, namespace;
""")

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"/tmp/backup_INIT_3WEEKS_{timestamp}.csv"

with open(filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['day_of_week', 'hour_of_day', 'quarter_hour', 'namespace',
                     'mean_errors', 'stddev_errors', 'samples_count'])
    writer.writerows(cursor.fetchall())

print(f"✅ Backup: {filename}")
conn.close()
EOF
```

---

## ✅ Checklist: Ready for Phase 6?

After completing all 6 steps:

- [ ] Step 1: DB connection works
- [ ] Step 2: Schema created
- [ ] Step 3: All 14 files processed
- [ ] Step 4: Grid filled
- [ ] Step 5: Verification shows 24,192 rows + 7 days + 12 namespaces
- [ ] Step 6: Backup created
- [ ] Update [working_progress.md](working_progress.md)

**When all ✅ → Ready for Phase 6: REGULAR Phase (Day 22 onwards)**

---

## 📖 Archive (Older Content)

See `_archive_md/` for older documentation on:
- Elasticsearch setup
- Technical accounts
- Part 2 (Full K8s deployment)
- And more...

---

**Version:** 2.0 | **Updated:** 2026-01-12 | **Phase:** 5B (INIT 3 Weeks)  
# =============================================================================

ES_URL=https://elasticsearch-prod.kb.cz:9200
ES_INDEX=cluster-app_sas-relay-*
ES_USER=XX_RELAY_ES_READ
ES_PASSWORD=your_password_here
ES_VERIFY_CERTS=false
```

**To je vše!** Pro lightweight nepotřebujete databázi, API settings, SECRET_KEY, Ollama, Redis, atd.

---

## Krok 5: První analýza (Lightweight)

### 5.1 Ověření připojení k Elasticsearch

#### Test 1: Základní připojení

```bash
# Jednoduchý test pomocí curl
curl -u "XX_VASE_APP_ES_READ:vase_heslo" \
  -X GET "https://elasticsearch-test.kb.cz:9500/_cat/indices/cluster-app_vase_aplikace-*?v" \
  --insecure
```

**Příklad pro PCB aplikaci:**
```bash
curl -u "XX_PCB_ES_READ:your_password_here" \
  -X GET "https://elasticsearch-test.kb.cz:9500/_cat/indices/cluster-app_pcb-*?v" \
  --insecure
```

**Očekávaný výstup:**
```
health status index                                    uuid                   pri rep docs.count docs.deleted store.size pri.store.size
green  open   cluster-app_pcb-api-2025.12.16          xY9kL2mPQR-Tg4nV8fA7Bw   5   1   1234567          0      2.5gb          1.2gb
green  open   cluster-app_pcb-worker-2025.12.16       aB3cD4eF5G-H6iJ7kL8mN9   5   1    987654          0      1.8gb          900mb
green  open   cluster-app_pcb-scheduler-2025.12.16    pQ2rS3tU4V-W5xY6zA7bC8   5   1     45678          0      120mb           60mb
```

#### Test 2: Kontrola dat (počet errorů)

```bash
# Počet errorů za poslední hodinu pro PCB
curl -u "XX_PCB_ES_READ:your_password_here" \
  -X GET "https://elasticsearch-test.kb.cz:9500/cluster-app_pcb-*/_count" \
  -H 'Content-Type: application/json' \
  -d '{
    "query": {
      "bool": {
        "must": [
          {"match": {"log.level": "ERROR"}},
          {"range": {"@timestamp": {"gte": "now-1h"}}}
        ]
      }
    }
  }' \
  --insecure
```

**Očekávaný výstup:**
```json
{
  "count": 2543,
  "_shards": {
    "total": 15,
    "successful": 15,
    "skipped": 0,
    "failed": 0
  }
}
```

✅ Pokud vidíte počet > 0, máte data a můžete pokračovat!

### 5.2 První spuštění analýzy (READY!)

Lightweight setup **NEPOTŘEBUJE** databázi ani API! Rovnou spusťte analýzu:

```bash
# Aktivujte venv (pokud není aktivní)
source venv/bin/activate

# Spusťte analýzu poslední hodiny
python scripts/analyze_period.py \
  --from "$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')" \
  --to "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --output first_analysis.json
```

**Příklad s konkrétním časem:**
```bash
# Analýza dnes ráno 8:00-10:00 (UTC čas!)
python scripts/analyze_period.py \
  --from "2025-12-16T06:00:00Z" \
  --to "2025-12-16T08:00:00Z" \
  --output morning_analysis.json
```

**Co uvidíte během běhu:**
```
🔍 Fetching errors from Elasticsearch...
⏳ Progress: 5000/15234 errors (32.8%) | Batch 1/4
⏳ Progress: 10000/15234 errors (65.6%) | Batch 2/4  
⏳ Progress: 15000/15234 errors (98.5%) | Batch 3/4
✅ Fetched 15234 errors in 12.3s

📊 Extracting root causes...
✅ Found 156 unique traces
✅ Identified 23 root causes

📝 Generating report...
✅ Analysis complete! Saved to: morning_analysis.json

Summary:
  Total Errors: 15234
  Root Causes: 23
  Top Issue: ConnectionTimeout (4521 errors - 29.7%)
```

**To je vše!** Žádné databáze, žádné migrace, žádná komplexní infrastruktura. 🎉

---

## Krok 6: Použití (Lightweight)

### 6.1 Denní analýza

```bash
# Analýza celého včerejšího dne
python scripts/analyze_period.py \
  --from "2025-12-15T00:00:00Z" \
  --to "2025-12-15T23:59:59Z" \
  --output daily_2025-12-15.json
```

### 6.2 Analýza konkrétního časového okna

```bash
# Analýza špičky dnes ráno 8-10h
python scripts/analyze_period.py \
  --from "2025-12-16T06:00:00Z" \
  --to "2025-12-16T08:00:00Z" \
  --output morning_peak_2025-12-16.json
```

### 6.3 Real-time analýza (poslední hodina)

```bash
# Poslední hodina
python scripts/analyze_period.py \
  --from "$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%SZ')" \
  --to "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  --output recent_errors.json
```

### 6.4 Prohlížení výsledků

```bash
# JSON výstup obsahuje:
cat first_analysis.json

# Zobrazí markdown report:
jq -r '.report' first_analysis.json

# Statistiky:
jq '.statistics' first_analysis.json
```

**Příklad kompletního JSON výstupu:**

```json
{
  "metadata": {
    "analysis_type": "Complete Trace-Based Root Cause Analysis",
    "period_start": "2025-12-16T06:00:00Z",
    "period_end": "2025-12-16T08:00:00Z",
    "duration_seconds": 18.7,
    "timestamp": "2025-12-16T10:23:45Z",
    "total_errors_fetched": 15234,
    "unique_traces": 156,
    "root_causes_identified": 23
  },
  "statistics": {
    "trace_id_coverage_percent": 78.5,
    "app_distribution": {
      "pcb-api": 8234,
      "pcb-worker": 3421,
      "pcb-scheduler": 888,
      "pcb-notification": 691
    },
    "namespace_distribution": {
      "prod-pcb": 12543,
      "prod-pcb-batch": 2691
    },
    "top_root_causes": [
      {
        "issue": "ConnectionTimeout to external API",
        "count": 4521,
        "percentage": 29.7,
        "apps": ["pcb-api", "pcb-worker"]
      },
      {
        "issue": "Database deadlock detected",
        "count": 2134,
        "percentage": 14.0,
        "apps": ["pcb-api"]
      },
      {
        "issue": "Redis connection pool exhausted",
        "count": 1876,
        "percentage": 12.3,
        "apps": ["pcb-worker", "pcb-scheduler"]
      }
    ]
  },
  "report": "# AI Log Analysis Report\n\n## Period: 2025-12-16 06:00 - 08:00 UTC\n\n### Summary\n- Total Errors: 15,234\n- Root Causes: 23\n..."
}
```

**Zobrazení markdown reportu:**
```bash
# Extrahujte a zobrazte markdown report
jq -r '.report' morning_analysis.json

# Nebo uložte do souboru
jq -r '.report' morning_analysis.json > report.md
cat report.md
```

### 6.5 Automatizace (Cron)

Pro denní automatické analýzy:

```bash
# Editujte crontab
crontab -e

# Přidejte (denně ve 2:00 analyzuje předchozí den)
0 2 * * * cd /home/your-user/git/ai-log-analyzer && \
  ./venv/bin/python scripts/analyze_period.py \
  --from "$(date -u -d 'yesterday 00:00' '+\%Y-\%m-\%dT\%H:\%M:\%SZ')" \
  --to "$(date -u -d 'yesterday 23:59' '+\%Y-\%m-\%dT\%H:\%M:\%SZ')" \
  --output "/var/log/ai-analyzer/daily_$(date -d yesterday '+\%Y-\%m-\%d').json" \
  >> /var/log/ai-analyzer/cron.log 2>&1
```

---

## ✅ Lightweight Setup Complete!

**Gratulujeme!** Máte fungující lightweight setup. 🎉

### Co máte:
- ✅ CLI analýzy kdykoliv potřebujete
- ✅ JSON + Markdown reporty
- ✅ Žádná infrastruktura k údržbě
- ✅ Rychlé a jednoduché

### Co NEMÁTE (a nepotřebujete pro lightweight):
- ❌ REST API
- ❌ PostgreSQL databáze
- ❌ Self-learning
- ❌ Historická data
- ❌ Redis caching

### 🚀 Chcete více? Pokračujte na [Part 2: Full Kubernetes](#part-2-full-kubernetes-deployment)!

---
---

# Part 2: Full (Kubernetes Deployment)

**Production-ready setup s REST API, databází a automatizací**

---

## 📋 Obsah - Part 2

1. [Prerekvizity (Full)](#prerekvizity-full)
2. [Tech účet](#tech-účet-stejné-jako-part-1)
3. [Instalace (Full)](#krok-3-instalace-projektu-full)
4. [Konfigurace (Full)](#krok-4-konfigurace-full)
5. [Lokální testování](#krok-5-lokální-testování-full)
6. [K8s Deployment](#krok-6-kubernetes-deployment)
7. [Monitoring & Alerting](#krok-7-monitoring--alerting)

---

## Prerekvizity (Full)

### Co potřebujete pro full setup:

**Stejné jako Part 1:**
- ✅ **Přístup k SMAX** - pro vytvoření technického účtu
- ✅ **JIRA přístup** - pro povolení ES přístupu
- ✅ **Python 3.11+** - nainstalovaný na lokálním stroji
- ✅ **Git** - pro klonování repositáře
- ✅ **Elasticsearch cluster** - znalost názvu vašeho indexu
- ✅ **Znalost jména vaší aplikace** - např. `pcb`, `sas-relay`, atd.

**NAVÍC pro full:**
- ✅ **PostgreSQL 16+** - produkční databáze
- ✅ **Docker & Docker Compose** - pro lokální vývoj
- ✅ **Kubernetes cluster** - pro deployment
- ✅ **kubectl** - konfigurovaný přístup do K8s
- ✅ **Harbor registry** - pro Docker images
- ✅ **CyberArk** - pro ukládání credentials (optional)
- ✅ **Ollama** - pro LLM analýzu (optional)
- ✅ **Redis** - pro caching (optional)

---

## Tech účet (Stejné jako Part 1)

Pokud jste již vytvořili tech účet v **Part 1**, můžete tento krok přeskočit.

Jinak postupujte podle **[Krok 1](#krok-1-vytvoření-technického-účtu)** a **[Krok 2](#krok-2-povolení-přístupu-do-elasticsearch)** z Part 1.

---

## Krok 3: Instalace projektu (Full)

### 3.1 Klonování repositáře

```bash
cd ~/git
git clone <url-repositare> ai-log-analyzer
cd ai-log-analyzer
```

### 3.2 Vytvoření virtuálního prostředí

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# nebo
venv\Scripts\activate  # Windows
```

### 3.3 Instalace VŠECH závislostí

Pro full setup instalujeme vše:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4 Spuštění lokální infrastruktury (Docker)

```bash
# Spustí PostgreSQL + Ollama + Redis
docker-compose up -d
```

Ověření:

```bash
docker-compose ps
# Měli byste vidět: postgres, ollama, redis (všechny "Up")
```

---

## Krok 4: Konfigurace (Full)

### 4.1 Vytvoření `.env` souboru (KOMPLETNÍ)

```bash
# Zkopírujte template s příklady
cp .env.example .env

# Upravte všechny hodnoty podle vašeho prostředí
nano .env
```

**DŮLEŽITÉ:** Soubor `.env` je v `.gitignore` a NEBUDE nahrán do gitu. Vaše credentials jsou v bezpečí!

### 4.2 Kompletní konfigurace `.env`

```bash
# =============================================================================
# AI LOG ANALYZER - FULL CONFIGURATION
# =============================================================================
# Production-ready setup s databází, API, LLM
# =============================================================================

# -----------------------------------------------------------------------------
# DATABASE - PostgreSQL
# -----------------------------------------------------------------------------
DATABASE_URL=postgresql://ailog:ailog_dev_pass@localhost:5432/ailog_analyzer

# -----------------------------------------------------------------------------
# ELASTICSEARCH - VAŠE HODNOTY!
# -----------------------------------------------------------------------------
# URL vašeho Elasticsearch clusteru
ES_URL=https://elasticsearch.vase-domena.cz:9200

# Název vašeho indexu (pattern)
ES_INDEX=cluster-app_<VASE_APLIKACE>-*

# Technický účet z SMAX (Krok 1)
ES_USER=XX_<VASE_APLIKACE>_ES_READ
ES_PASSWORD=<heslo_z_emailu>

# SSL/TLS nastavení
ES_VERIFY_CERTS=false

# -----------------------------------------------------------------------------
# API SETTINGS
# -----------------------------------------------------------------------------
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# -----------------------------------------------------------------------------
# SECURITY
# -----------------------------------------------------------------------------
# Vygenerujte vlastní secret key:
# python -c "import secrets; print(secrets.token_urlsafe(32))"
SECRET_KEY=<vygenerovany_secret_key>
ALGORITHM=HS256

# -----------------------------------------------------------------------------
# OLLAMA LLM (Optional - pro AI analýzu)
# -----------------------------------------------------------------------------
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=mistral:latest

# -----------------------------------------------------------------------------
# REDIS (Optional - pro caching)
# -----------------------------------------------------------------------------
REDIS_URL=redis://localhost:6379

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------
LOG_LEVEL=INFO
LOG_FORMAT=json

# -----------------------------------------------------------------------------
# ANALYSIS SETTINGS
# -----------------------------------------------------------------------------
LEARNING_ENABLED=true
AUTO_ADJUST_THRESHOLDS=true
MIN_SAMPLES_FOR_LEARNING=10
```

### 4.3 Generování SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Zkopírujte výstup do `.env` jako hodnotu `SECRET_KEY`.

---

## Krok 5: Lokální testování (Full)

### 5.1 Inicializace databáze

```bash
# Spusťte Alembic migrace
alembic upgrade head
```

### 5.2 Test ES připojení

```bash
curl -u "$ES_USER:$ES_PASSWORD" "$ES_URL/_cluster/health" --insecure
```

### 5.3 Spuštění API serveru

```bash
# Development mode
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Otevřete: http://localhost:8000/docs (Swagger UI)

### 5.4 Test API

```bash
# Health check
curl http://localhost:8000/health

# Analyze endpoint
curl -X POST http://localhost:8000/api/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "time_from": "2025-12-16T07:00:00Z",
    "time_to": "2025-12-16T08:00:00Z",
    "app_filter": "<vase-aplikace>-*"
  }'
```

---

## Krok 6: Kubernetes Deployment

### 6.1 Příprava Docker image

```bash
# Build image
docker build -t harbor.vase-domena.cz/ai-log-analyzer:v1.0.0 .

# Push to Harbor
docker push harbor.vase-domena.cz/ai-log-analyzer:v1.0.0
```

### 6.2 Vytvoření K8s Secret s credentials

```bash
# ES credentials
kubectl create secret generic ai-log-analyzer-es-creds \
  --from-literal=ES_USER='XX_VASE_APP_ES_READ' \
  --from-literal=ES_PASSWORD='vase_heslo' \
  -n your-namespace

# Database credentials (pro prod PostgreSQL)
kubectl create secret generic ai-log-analyzer-db-creds \
  --from-literal=DATABASE_URL='postgresql://user:pass@postgres-host:5432/ailog_analyzer' \
  -n your-namespace
```

### 6.3 Úprava K8s manifestů

```bash
# Upravte ConfigMap
vim k8s/configmap.yaml

# Změňte hodnoty:
# - ES_URL
# - ES_INDEX
# - OLLAMA_URL (pokud máte)
```

### 6.4 Deploy do K8s

```bash
# Deploy všechny manifesty
kubectl apply -f k8s/ -n your-namespace

# Ověření
kubectl get pods -n your-namespace
kubectl get svc -n your-namespace
```

### 6.5 Ověření deploymentu

```bash
# Logy
kubectl logs -f deployment/ai-log-analyzer -n your-namespace

# Port-forward pro testování
kubectl port-forward svc/ai-log-analyzer 8000:8000 -n your-namespace

# Test API
curl http://localhost:8000/health
```

---

## Krok 7: Monitoring & Alerting

### 7.1 Prometheus metriky

API automaticky exportuje metriky na `/metrics`:

```bash
curl http://localhost:8000/metrics
```

### 7.2 Grafana dashboard

Import dashboard z `k8s/grafana-dashboard.json` (pokud existuje).

### 7.3 Alerty

Nakonfigurujte alerty pro:
- ✅ API response time > 5s
- ✅ Error rate > 1%
- ✅ Database connection errors
- ✅ ES query failures

---

## ✅ Full Setup Complete!

**Gratulujeme!** Máte plně funkční production-ready deployment. 🚀

### Co máte:
- ✅ REST API s Swagger dokumentací
- ✅ PostgreSQL databáze s historií
- ✅ Self-learning z feedback
- ✅ Automatizované denní analýzy
- ✅ K8s deployment s HA
- ✅ Monitoring & alerting
- ✅ Redis caching (pokud nakonfigurován)
- ✅ LLM analýza (pokud Ollama nakonfigurován)

---
---

# Společné sekce pro obě varianty

---

## 📚 Další dokumentace

### Pro obě varianty (Lightweight i Full):

- **[HOW_TO_USE.md](HOW_TO_USE.md)** - Detailní operační příručka
- **[README.md](README.md)** - Přehled projektu a features
- **[CONTEXT_RETRIEVAL_PROTOCOL.md](CONTEXT_RETRIEVAL_PROTOCOL.md)** - Quick reference
- **[scripts/INDEX.md](scripts/INDEX.md)** - Dokumentace všech skriptů

---

## 🔧 Customizace pro vaši aplikaci

### Upravte prahy detekce (optional)

```python
# app/services/analysis.py
ERROR_THRESHOLD = 100  # minimální počet errorů pro alert
SPIKE_MULTIPLIER = 2.5  # kolikrát víc než baseline = spike
```

### Upravte seznam monitorovaných aplikací (optional)

```python
# app/core/config.py
MONITORED_APPS = [
    "vase-aplikace-api",
    "vase-aplikace-worker",
    "vase-aplikace-scheduler"
]
```

---

## 🔍 Troubleshooting

### Problem: Nelze se připojit k Elasticsearch

**Řešení:**

```bash
# 1. Ověřte credentials
echo $ES_USER
echo $ES_PASSWORD

# 2. Test připojení
curl -u "$ES_USER:$ES_PASSWORD" "$ES_URL/_cluster/health" --insecure

# 3. Zkontrolujte firewall/VPN
ping elasticsearch-test.kb.cz
```

### Problem: "Permission denied" na indexech

**Řešení:**

- ✅ Ověřte JIRA ticket (Krok 2) - je schválený?
- ✅ Zkontrolujte pattern indexu: `cluster-app_<app>-*`
- ✅ Kontaktujte ES admin team

### Problem: Žádná data v analýze

**Řešení:**

```bash
# 1. Ověřte, že index obsahuje data
curl -u "$ES_USER:$ES_PASSWORD" \
  "$ES_URL/cluster-app_vase-aplikace-*/_count" --insecure

# 2. Zkontrolujte časové rozmezí
# ES používá UTC! Přepočítejte lokální čas na UTC

# 3. Ověřte filtr v ES query
# Zkontrolujte log.level: ERROR vs error vs Error
```

### Problem: Database connection failed

**Řešení:**

```bash
# 1. Je PostgreSQL spuštěný?
docker-compose ps postgres
# nebo
systemctl status postgresql

# 2. Ověřte DATABASE_URL v .env
echo $DATABASE_URL

# 3. Test připojení
psql "$DATABASE_URL"
```

### Problem: Ollama LLM nedostupný

**Řešení:**

```bash
# 1. Spusťte Ollama
docker-compose up -d ollama

# 2. Stáhněte model
docker exec -it ai-log-analyzer-ollama-1 ollama pull mistral

# 3. Nebo použijte mock mode
# V .env nastavte:
OLLAMA_URL=mock://localhost
```

---

## 📞 Podpora

### Dokumentace
- **GitHub Wiki:** [Link na wiki]
- **JIRA:** [Link na JIRA projekt]
- **Confluence:** [Link na confluence]

### Kontakty
- **DevOps Team:** devops@vase-domena.cz
- **ES Admin:** elasticsearch-admin@vase-domena.cz
- **Slack:** #ai-log-analyzer

---

## ✅ Checklist pro go-live

Před nasazením do produkce ověřte:

- [ ] ✅ Tech účet vytvořen a credentials uloženy bezpečně
- [ ] ✅ ES přístup povolen přes JIRA
- [ ] ✅ Projekt nainstalován a závislosti nainstalovány
- [ ] ✅ `.env` soubor nakonfigurován s vašimi hodnotami
- [ ] ✅ PostgreSQL databáze běží a migrace aplikovány
- [ ] ✅ Test připojení k ES úspěšný
- [ ] ✅ První analýza proběhla bez chyb
- [ ] ✅ Výstup analýzy zkontrolován a validní
- [ ] ✅ Cron job nebo K8s deployment nastaven
- [ ] ✅ Monitoring a alerting nakonfigurován
- [ ] ✅ Dokumentace přečtena a pochopena

---

**Gratulujeme! 🎉**

Váš AI Log Analyzer je připraven k použití. Začněte s denními analýzami a nechte AI pomoci objevovat patterns ve vašich logách.

**Happy analyzing! 🚀**
