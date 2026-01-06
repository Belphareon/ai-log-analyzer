# CONTEXT RETRIEVAL PROTOCOL
## AI Log Analyzer - Quick Reference

**Verze:** 2.2  
**Last Update:** 2025-12-17  
**Účel:** Rychlý přehled pro pokračování v práci

---

## 📋 CO TO JE

**AI Log Analyzer** - Automatická analýza errorů z Elasticsearch s AI doporučeními

- **Tech Stack:** Python + FastAPI + PostgreSQL + Elasticsearch + Ollama (optional)
- **Deployment:** Kubernetes (ArgoCD) + Harbor registry  
- **Current Phase:** Phase 5 (Peak Detection Baseline)

---

## 🎯 AKTUÁLNÍ STAV (2025-12-16 11:00 UTC - Phase 5 IN PROGRESS)

### ✅ HOTOVO (Phase 4 + 5 setup)
1. **Docker Image** ✅
   - Tag: `v0.4.0-docker-verified` + `latest`
   - Registry: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer`

2. **Database Schema** ✅
   - PostgreSQL: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
   - Schema: ailog_peak

3. **Phase 5: Peak Data Collection** ✅
   - ✅ collect_peak_detailed.py: 2025-12-01 (230K errors, ready for load)
   - ✅ Scripts reorganized do `scripts/` s `scripts/INDEX.md`
   - ✅ Workspace cleanup (6 archivů)
   - ⚠️ DB: testovací data (2025-12-05) - BUDOU SMAZANA

### 🔄 V PROCESU (Phase 5B - Priority: DATA INGESTION)

**Production Data Status:**
```
2025-12-01: ✅ 230,146 errors (4 namespaces: pcb-*)
            Lokace: /tmp/peak_data_2025_12_01.txt
            ⚠️ Chybí: pca-dev, pca-sit

2025-12-02 až 2025-12-15: ❌ CHYBÍ - Nutno stáhnout
2025-12-16: ⏳ TODAY - Ještě se sbírá
```

**DB Current State:**
```
❌ Testovací data (budou smazana):
   - 2,623 rows z 2025-12-05
   - 6 namespaces (pca-* + pcb-*)
   - Status: TO DELETE
```

**Next 5 Steps (PRIORITY ORDER):**
1. [ ] **Smazat** testovací data z DB
2. [ ] **Stáhnout** chybějící data 2025-12-02 až 2025-12-15
3. [ ] **Ověřit** formát dat z 2025-12-01
4. [ ] **Nataž** všech dat do DB (s smoothingem)
5. [ ] **Validovat** kompletní range 2025-12-01 až 2025-12-15

### 📋 NEXT (Priority Order)
1. ⏭️ Load data into DB - Phase 5B (THIS PRIORITY!)
2. ⏭️ Create ingest_peak_statistics.py
3. ⏭️ Deploy to K8s cluster (Phase 6)
4. ⏭️ Cluster automate (Phase 7)

---

## 🎯 PEAK DETECTION - KLÍČOVÉ POŽADAVKY

**PROČ:** Zjistit CO SE DĚJE při anomáliích, detekovat, analyzovat, vyřešit

**LOGIKA VKLÁDÁNÍ DAT:**
```
6 REFERENČNÍCH OKEN:
  - 3 okna PŘED (stejný den): time-45min, time-30min, time-15min
  - 3 okna stejný čas (jiný den): den-1, den-2, den-3

Kombinovaná reference:
  reference = (avg(3_pred) + avg(3_dny)) / 2

IF nova_hodnota >= 10× reference:
  → Označit jako PEAK
  → VYNECHAT z DB (nezapisovat)
  → Zapsat do LOG pro analýzu
  
ELSE:
  → Zapsat normálně do DB

Special cases:
  - Pokud reference < 10: threshold 50× (ne 10×)
  - Pokud hodnota < 10: NIKDY skip (baseline)
  - Není třeba více dní! Stačí i 2 dny (Thu+Fri) protože lze vždy najít 3 okna před + reference Den-1
```

**OUTPUT:**
1. **DB (peak_statistics):** Pouze normální provoz (bez peaks)
2. **LOG (peaks_analysis.log):** Všechny peaks s kontextem pro analýzu
   - Timestamp, namespace, hodnota, baseline, ratio
   - ± 30min kontext (co se dělo před/po)

**VERIFIKACE:**
- TOP 20 hodnot v DB < 1000 (peaks skipnuty)
- Baseline hodnoty (2-65) v DB přítomny
- Peaks (2890, 43000, atd.) v logu, NE v DB

---

## 📁 WORKSPACE STRUKTURA (2025-12-16)

```
ai-log-analyzer/
├── 📄 README.md                      # ⭐ Main documentation
├── 📄 CONTEXT_RETRIEVAL_PROTOCOL.md  # ⭐ This file - quick context
├── 📄 working_progress.md            # ⭐ Session log + tasks
├── 📄 HOW_TO_USE.md                  # ⭐ User guide + examples
│
├── 📂 scripts/                       # ALL PRODUCTION SCRIPTS
│   ├── INDEX.md                      # 📋 Script reference (START HERE!)
│   ├── collect_peak_detailed.py      # ⭐ CORE - Peak data collector
│   ├── fetch_unlimited.py            # Elasticsearch fetcher
│   ├── analyze_period.py             # Orchestrator
│   ├── export_peak_statistics.py     # CSV export
│   ├── verify_peak_data.py           # Data validation
│   ├── init_peak_statistics_db.py    # DB init (1x)
│   ├── setup_peak_db.py              # DB setup (1x)
│   ├── grant_permissions.py          # DB perms (1x)
│   ├── create_known_issues_registry.py # Known issues
│   └── workflow_manager.sh           # Shell wrapper
│
├── 📂 app/                           # FastAPI application
│   ├── main.py                       # Entry point
│   ├── routes/
│   ├── models/
│   ├── schemas/
│   └── utils/
│
├── 📂 alembic/                       # Database migrations
│   ├── versions/
│   └── env.py
│
├── 📂 _archive_md/                   # OLD Documentation (ignore)
│   ├── COMPLETED_LOG.md
│   ├── DEPLOYMENT.md
│   ├── HARBOR_DEPLOYMENT_GUIDE.md
│   ├── KNOWN_ISSUES_DESIGN.md
│   ├── PHASE_ROADMAP.md
│   └── README_SCRIPTS.md
│
├── 📂 _archive_scripts/              # OLD Scripts from Phase 1-3
│   └── (19 zastaralých skriptů)
│
├── 📂 _archive_old/                  # OLD Folders (cleanup 2025-12-16)
│   ├── k8s/                          # Zastaralé manifesty
│   ├── copilot-chat-backups/         # Chat backupy
│   ├── updates/                      # Staré session noty
│   ├── .backup_2025-11-18/           # Starý backup
│   └── tests/                        # Prázdný test folder
│
├── 🐳 Dockerfile                     # Current image build
├── 📦 requirements.txt               # Python dependencies
├── 📋 docker-compose.yml             # Dev environment
├── 🔑 .env                           # Configuration (git-ignored)
├── alembic.ini                       # DB migration config
├── pyproject.toml                    # Python project config
└── .gitignore                        # Git ignore rules
```

---

## 🔑 KLÍČOVÉ INFORMACE

### Database Connection
```
Host: P050TD01.DEV.KB.CZ
Port: 5432
Database: ailog_analyzer
Schema: ailog_peak (tables: peak_statistics, peak_raw_data, etc.)

USERS:
- ailog_analyzer_user_d1     → Data operations (SELECT, INSERT, UPDATE, DELETE)
- ailog_analyzer_ddl_user_d1 → DDL operations (CREATE, ALTER, DROP, GRANT)

ROLES:
- role_ailog_analyzer_ddl    → DDL role (SET ROLE před DDL operacemi)
```

**KRITICKY DŮLEŽITÉ - Jak se připojit k DB:**

**1. DATA OPERACE (SELECT, INSERT, UPDATE, DELETE):**
```python
from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()  # ⚠️ POVINNÉ! Načte .env soubor

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')  # Z .env souboru
}
conn = psycopg2.connect(**DB_CONFIG)
cursor = conn.cursor()

# Normální operace (INSERT/SELECT/UPDATE/DELETE)
cursor.execute("SELECT * FROM ailog_peak.peak_statistics LIMIT 10")
```

**2. DDL OPERACE (CREATE TABLE, ALTER, GRANT):**
```python
from dotenv import load_dotenv
import psycopg2
import os

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1'),  # DDL user!
    'password': os.getenv('DB_DDL_PASSWORD')  # Z .env souboru
}
conn = psycopg2.connect(**DB_CONFIG)
cursor = conn.cursor()

# ⚠️ POVINNÉ: SET ROLE před DDL operacemi
cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
print("✅ DDL role set")

# Nyní můžeš dělat DDL operace
cursor.execute("CREATE SCHEMA IF NOT EXISTS ailog_peak;")
cursor.execute("CREATE TABLE IF NOT EXISTS ailog_peak.peak_statistics (...);")
cursor.execute("GRANT SELECT ON ailog_peak.peak_statistics TO ailog_analyzer_user_d1;")
conn.commit()
```

**VŽDY kontroluj NEJDŘÍV:**
1. Existuje .env soubor? `ls -la .env`
2. Má DB_PASSWORD? `grep DB_PASSWORD .env` (bez zobrazení hodnoty)
3. Volej `load_dotenv()` PŘED `psycopg2.connect()`!
4. Pro DDL: použij DB_DDL_USER + SET ROLE!

**Všechny DB skripty používají tento přístup:**
- **Data skripty:** verify_peak_data.py, ingest_from_log.py, clear_peak_db.py
- **DDL skripty:** setup_peak_db.py, grant_permissions.py, init_peak_statistics_db.py

### Elasticsearch (FIXED VALUES)
```bash
# Stejné pro všechny - NEMĚNIT!
ES_URL=https://elasticsearch-test.kb.cz:9500
ES_VERIFY_CERTS=false

# Specifické pro vaši aplikaci:
ES_INDEX=cluster-app_<vase_aplikace>-*  # např. pcb-*, pca-*, relay-*
ES_USER=XX_<VASE_APP>_ES_READ            # z SMAX
ES_PASSWORD=<z_emailu>                   # z SMAX
```

### Environment Setup
```bash
# 1. Zkopírovat template
cp .env.example .env

# 2. Vyplnit své hodnoty
nano .env

# 3. Spustit skripty (načtou automaticky)
python scripts/analyze_period.py ...
```

**See:** [ENV_SETUP.md](ENV_SETUP.md) pro detaily

---

## 🛠️ WORKFLOW: Jak Pokračovat

### 1. START NOVÉ SESSION
```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# Zkontroluj git status
git status
git log --oneline -5

# Přečti poslední progress
cat working_progress.md | tail -100
```

### 2. SPUSŤ SCRIPT Z `scripts/` SLOŽKY
```bash
# Všechny scripty jsou teď v scripts/
cd scripts/

# Například: collect data
python collect_peak_detailed.py --from 2025-12-16T00:00:00Z --to 2025-12-17T00:00:00Z

# Nebo: verify data
python verify_peak_data.py

# Nebo: export to CSV
python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16

# HELP - co dělá každý script?
cat INDEX.md
```

### 3. COMMIT ZMĚNY
```bash
git add -A
git commit -m "Phase 5: [brief description]"
git push origin feature/ai-log-analyzer-v2
```

---

## 📚 ACTIVE DOCUMENTATION

### PRIMARY (aktuální, používej):
| Soubor | Obsah | Kdy |
|--------|-------|-----|
| **working_progress.md** | Session log + TODO | Každý den |
| **scripts/INDEX.md** | Script reference | Spouštění scripts |
| **README.md** | Project overview | First time |
| **CONTEXT_RETRIEVAL_PROTOCOL.md** | Tenhle soubor | Kontext přenosu |
| **HOW_TO_USE.md** | User guide | Development |

### ARCHIVED (zastaralé, ignoruj):
- `_archive_md/COMPLETED_LOG.md` - Starý session log
- `_archive_md/DEPLOYMENT.md` - Zastaralé deployment noty
- `_archive_md/PHASE_ROADMAP.md` - Starý roadmap
- → Viz `_archive_md/` pro úplný seznam

---

## 🎯 PHASE 5 WORKFLOW - Co Dělat Dnes

### Krok 1: Export Data (if needed)
```bash
cd scripts/
python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16
# Vytvoří: peak_statistics_export_YYYYMMDD_HHMMSS.csv
```

### Krok 2: Verify Current Data
```bash
python verify_peak_data.py
# Kontroluje: duplicates, NaN values, date ranges
```

### Krok 3: PHASE 5B - Load Production Data
```bash
# Step 1: DELETE testovací data
psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer_user_d1 -d ailog_analyzer
DELETE FROM ailog_peak.peak_statistics WHERE 1=1;

# Step 2: Prepare chybějící data (2025-12-02 až 2025-12-15)
# Ke každému dni:
python collect_peak_detailed.py --from "2025-12-02T00:00:00Z" --to "2025-12-03T00:00:00Z"
# Output: /tmp/peak_data_2025_12_02.txt

# Step 3: Load do DB (skript ingest_peak_statistics.py TBD)
# (zatím ručně, nebo skript který existuje)

# Step 4: Validate
python verify_peak_data.py
```

### Krok 4: Commit & Update
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
git add -A
git commit -m "Phase 5B: Production data ingestion (2025-12-01 to 2025-12-15)"
git push
```

---

## ✅ CHECKLIST - Návrat k Projektu

Standardní postup když začínáš:

- [ ] Zkontroluj poslední commit: `git log --oneline -3`
- [ ] Přečti progress: `cat working_progress.md | tail -50`
- [ ] Zkontroluj branchy: `git branch -v`
- [ ] Aktualizuj si kontext: `cat CONTEXT_RETRIEVAL_PROTOCOL.md`
- [ ] Spusť script z `scripts/` (viz `scripts/INDEX.md`)
- [ ] Loguj progress do `working_progress.md`
- [ ] Commit + push

---

## 📊 SCRIPTS QUICK REFERENCE

| Script | Typ | Popis | Last Run |
|--------|-----|-------|----------|
| **collect_peak_detailed.py** | ⭐ Core | Sbírá peak data z ES | 2025-12-15 |
| **fetch_unlimited.py** | Util | ES query helper | N/A |
| **analyze_period.py** | Util | Full pipeline | 2025-12-16 |
| **export_peak_statistics.py** | Export | Data → CSV | 2025-12-16 |
| **verify_peak_data.py** | Validation | DB checks | Pending |
| **init_peak_statistics_db.py** | Setup (1x) | Create tables | 2025-12-12 |

→ **FULL DETAILS:** `scripts/INDEX.md`

---

## 📦 ARCHIVE & CLEANUP (2025-12-16)

```
✅ DONE:
- Workspace cleanup: 6 archiv složek
- Scripts reorganizace: do scripts/ s INDEX.md
- MD soubory: archivovány do _archive_md/
- k8s/: archivován (zastaralé nasazení)

📊 SIZE REDUCTION:
- Původně: 618MB
- Nyní: ~404MB (200MB cleanup)
- Root: 4 MD + config files (čistý!)
```

---

**Version:** 2.1 (Updated 2025-12-16 11:00 UTC)  
**Status:** ✅ Phase 4 Complete | 🔄 Phase 5 - Peak Detection  
**Maintainer:** jvsete + AI Assistant  
**Branch:** `feature/ai-log-analyzer-v2` (k8s-infra-apps-nprod repo)

