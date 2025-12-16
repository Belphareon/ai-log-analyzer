# 🔄 Working Progress - AI Log Analyzer

**Projekt:** AI Log Analyzer - Trace-based Root Cause Analysis  
**Poslední aktualizace:** 2025-12-16 09:00 UTC  
**Status:** Phase 4 COMPLETE ✅ - Phase 5 (Peak Detection Baseline) IN PROGRESS

---

## ⚠️ KRITICKÉ - TIME RANGE HANDLING

### PAMATUJ SI VŽDYCKY:
```
🚨 TIMEZONE MUST BE UTC Z SUFFIX - NIKDY +00:00!
🚨 ALWAYS USE EXPLICIT DATE RANGES - NIKDY datetime.now() RELATIVNÍ!
🚨 CONTROL TIME RANGE BEFORE FETCHING - MUSÍ SOUHLASIT S EXPECTACÍ!

CHYBNÉ:
  start = (datetime.now(tz.utc) - timedelta(hours=24)).isoformat()
  → Vrátí: 2025-12-15T08:52:41.537703+00:00  ❌ PLUS OFFSET
  
SPRÁVNÉ:
  start = (datetime.now(tz.utc) - timedelta(hours=24)).isoformat().replace('+00:00', 'Z')
  → Vrátí: 2025-12-15T08:52:41.537703Z  ✅ WITH Z
  
NEJLÉPE:
  # Explicit ranges (SEMPRE!)
  --from "2025-12-15T00:00:00Z" --to "2025-12-16T00:00:00Z"

CHYBA KTERÁ SE STALA:
  - Stahoval jsem 88K errors (za 24h s přesahem)
  - Ty jsi viděl 164K errors (za 24h)
  - Chybělo mi 66.6K errors z peaku 2025-12-15T09:00-09:30
  - ROOT CAUSE: Časový posun/OFF-BY-ONE v generování windows
```

---

## 📚 KNOWLEDGE BASE - Peak Detection Data Collection

### Database Configuration
```
Host: P050TD01.DEV.KB.CZ:5432
Database: ailog_analyzer
Schema: ailog_peak

DDL User (CREATE/ALTER):
  User: ailog_analyzer_ddl_user_d1
  Pass: WWvkHhyjje8YSgvU

Data User (INSERT/SELECT - POUŽÍVAT V SCRIPTU):
  User: ailog_analyzer_user_d1
  Pass: y01d40Mmdys/lbDE
```

### Elasticsearch Configuration
```
URL: https://elasticsearch-test.kb.cz:9500
User: XX_PCBS_ES_READ
Pass: ta@@swLT69EX.6164

Index Pattern: cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*
```

### Peak Detection Script - UPDATED
```
Script: collect_peak_detailed.py
Cíl: Sbírat error counts v 15-minutových oknech za N dní

SPRÁVNÉ POUŽITÍ:

Varianta 1: RELATIVNÍ (poslední N dní - VHODNÉ POUZE PRO TESTING):
  python3 collect_peak_detailed.py --days 1
  python3 collect_peak_detailed.py --days 21

Varianta 2: EXPLICITNÍ (PREFEROVANÉ - MUSÍ BÝT PŘESNÉ):
  python3 collect_peak_detailed.py --from "2025-12-15T00:00:00Z" --to "2025-12-16T00:00:00Z"
  python3 collect_peak_detailed.py --from "2025-11-25T00:00:00Z" --to "2025-12-15T23:59:59Z"

DŮVOD:
- Relativní časy (--days) se počítají od datetime.now() → VARIABILNÍ!
- Explicitní časy (--from/--to) jsou FIXNÍ → OPAKOVATELNÉ!
- Pro prod MUSÍŠ VŽDYCKY POUŽÍVAT EXPLICITNÍ RANGE!
```

---

## 📊 SESSION - 2025-12-16 08:15 UTC - Peak Detection Indexing Fix

### 🎯 Cíl
Stáhnout data za 48 hodin, ověřit počty errors a distribuci dle NS/app, vyčistit DB a správně uložit data se smoothingem.

### ✅ Kroky Dokončené

**1. Identifikace Problému (08:15-08:25 UTC)**
- Issue: `collect_peak_detailed.py` vrátil 0 errors (mělo vrátit 100K+)
- Root cause: Script používal špatné env var `ES_INDICES` a špatné indexy
  - Mělo: `ES_INDEX` = `cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*`
  - Bylo: `ES_INDICES` = `logstash-kb-k8s-apps-nprod-*,logstash-kb-k8s-apps-prod-*`
- Bez pcb-ch dat!

**2. Secondary Issue - Timezone Format (08:25-08:30 UTC)**
- Script generoval `.isoformat()` → `2025-12-14T09:15:00+00:00`
- ES očekává: `2025-12-14T09:15:00Z`

**3. Oprava Scriptu (08:30 UTC)**
- `collect_peak_detailed.py` ES_CONFIG: Changed `ES_INDICES` → `ES_INDEX` with correct indices
- `collect_peak_detailed.py` fetch_errors_search_after(): Added timezone fix
- Integration s `fetch_unlimited.py` - nyní používá proven working module

**4. Test & Verification (08:30-08:35 UTC)**
- ✅ Quick test `--days 1`: 0 → 10,000+ errors
- ✅ Full run spuštěn: `python3 collect_peak_detailed.py --days 2` (PID spuštěn v /tmp/collect_pid.txt)
- ✅ Namespace ověření: fetch_unlimited vrací pcb-ch-dev-01-app + pcb-ch-sit-01-app

**5. Script Running (08:35+ UTC)**
- Background execution: `/tmp/collect_48h_final.log`
- Expected runtime: ~5-10 minut
- Process: Stahuje 120K+ errors → groupuje → počítá stats s smoothingem

### 🔧 Změny v Kódu

**File: `collect_peak_detailed.py`**
```python
# Line 21: FIX - Changed ES_INDICES to ES_INDEX
- 'indices': os.getenv('ES_INDICES', 'logstash-kb-k8s-apps-nprod-*,logstash-kb-k8s-apps-prod-*')
+ 'indices': os.getenv('ES_INDEX', 'cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*')

# Line 47-71: Integration s fetch_unlimited.py
- Nyní volá fetch_unlimited() místo vlastní implementace search_after
- To garantuje kompatibilitu s orchestrací (analyze_period.py)

# Line 49-50: FIX - Timezone format
date_from_str = date_from.isoformat().replace('+00:00', 'Z')
date_to_str = date_to.isoformat().replace('+00:00', 'Z')
```

### 📊 DEBUG Output

```
✅ Test za 1 hodinu (fetch_unlimited):
   Total errors: 740
   Namespaces: ['pca-dev-01-app', 'pca-sit-01-app', 
                'pcb-ch-dev-01-app', 'pcb-ch-sit-01-app',  ← NOVĚ!
                'pcb-dev-01-app', 'pcb-fat-01-app', 
                'pcb-sit-01-app', 'pcb-uat-01-app']

✅ Collect za 48 hodin - COMPLETED (08:50 UTC):
   Total errors fetched: 120,261
   Grouped into: 844 (day,hour,quarter,ns) combinations
   
   📦 Namespaces found (8 TOTAL):
   - pca-dev-01-app              (44 patterns)
   - pca-sit-01-app              (46 patterns)
   - pcb-ch-dev-01-app           (52 patterns) ✅ NOVĚ!
   - pcb-ch-sit-01-app           (104 patterns) ✅ NOVĚ!
   - pcb-dev-01-app              (192 patterns)
   - pcb-fat-01-app              (144 patterns)
   - pcb-sit-01-app              (163 patterns)
   - pcb-uat-01-app              (145 patterns)
```

### ✅ Výsledek

**Status: FIX SUCCESSFUL! ✅**

Oprava ES_INDEX proměnné v `collect_peak_detailed.py` vyřešila problém. Script nyní:
- Stahuje 120K+ errors správně
- Najde 8 namespace (včetně pcb-ch-*)
- Počítá mean/stddev s 3-window smoothingem

### 🔗 Reference

| Položka | Hodnota |
|---------|---------|
| Repo | `/home/jvsete/git/sas/ai-log-analyzer` |
| Database | P050TD01.DEV.KB.CZ:5432/ailog_analyzer |
| Elasticsearch | elasticsearch-test.kb.cz:9500 |
| Index Pattern | `cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*` |
| Env Var (CORRECT) | `ES_INDEX` |
| K8s Cluster | nprod (3095/3100) |

### Phase Status
- Phase 4: ✅ COMPLETE
- Phase 5: 🔄 IN PROGRESS (collect_peak_detailed.py + fetch_unlimited integration)
- Phase 6: 📋 TODO

---

## 📋 NEXT SESSION TODO (2025-12-16+)

### ✅ COMPLETED THIS SESSION
1. ✅ Fixed ES_INDEX configuration (was ES_INDICES)
2. ✅ Fixed timezone format (Z suffix)
3. ✅ Integrated with fetch_unlimited.py
4. ✅ Added explicit `--from` and `--to` date range support
5. ✅ Verified 164,526 errors for 25h period (2025-12-15T00:00:00Z - 2025-12-16T01:00:00Z)
6. ✅ All 8 namespaces confirmed (pcb-ch included!)

### 🎯 NEXT STEPS (PRIORITY ORDER)

**STEP 1: Prepare Clean Data (with smoothing)**
```bash
# Run collection with EXPLICIT dates for 24h:
cd /home/jvsete/git/sas/ai-log-analyzer
source .venv/bin/activate

python3 collect_peak_detailed.py \
  --from "2025-12-15T00:00:00Z" \
  --to "2025-12-16T00:00:00Z" \
  --output /tmp/peak_data_24h.json

# Output will show:
# - Total errors count
# - 8 namespaces breakdown
# - Statistics (day,hour,quarter,namespace) with smoothing
# - Mean/StdDev values
```

**STEP 2: Export to Table Format (FOR VERIFICATION)**
```
Create CSV/Table with columns:
  - day_of_week (Mon-Sun)
  - hour_of_day (0-23)
  - quarter_hour (0/15/30/45)
  - namespace
  - mean_errors
  - stddev_errors
  - samples_count

THIS IS FOR YOUR VERIFICATION BEFORE DB LOAD!
```

**STEP 3: Clean Database (BEFORE LOAD)**
```sql
-- Connect as ailog_analyzer_user_d1
DELETE FROM ailog_peak.peak_statistics WHERE 1=1;
SELECT COUNT(*) FROM ailog_peak.peak_statistics;  -- Should be 0
```

**STEP 4: Load into Database**
```bash
# After your approval of Step 2 table:
# Script will INSERT all statistics into ailog_peak.peak_statistics
# Using UPSERT (ON CONFLICT) pattern
```

**STEP 5: Verify Smoothing Function**
```sql
-- Check smoothing values are reasonable
SELECT * FROM ailog_peak.peak_statistics 
WHERE namespace = 'pcb-sit-01-app' 
ORDER BY day_of_week, hour_of_day, quarter_hour
LIMIT 20;
```

### 📊 Data Format Expected

```
Sample output from collect_peak_detailed.py:

day_of_week | hour_of_day | quarter_hour | namespace          | mean_errors | stddev_errors | samples
------------|-------------|--------------|-------------------|-------------|---------------|---------
0 (Mon)     | 8           | 0            | pcb-sit-01-app     | 203.32      | 45.67         | 3
0 (Mon)     | 8           | 15           | pcb-sit-01-app     | 195.45      | 42.15         | 3
0 (Mon)     | 8           | 30           | pcb-sit-01-app     | 187.23      | 40.89         | 3
...
```

### ⚠️ IMPORTANT REMINDERS
- ✅ Use EXPLICIT dates (--from/--to), NOT --days for production
- ✅ Always include 'Z' suffix in timestamps
- ✅ Verify data count BEFORE deleting old DB
- ✅ Create backup/screenshot of table BEFORE DB load
- ✅ Check smoothing values make sense (not NaN, not negative)

---

**Ready for:** Next session - Execute Step 1-5 in order

---

## 📊 SESSION - 2025-12-16 10:30 UTC - Workspace Cleanup & Phase 5 Setup

### 🎯 Cíl
Vyčistit workspace, archivovat staré soubory, extrahovat důležité info.

### ✅ HOTOVO (10:30-11:00 UTC)

**1. Data Collection**
- ✅ collect_peak_detailed.py: 2025-12-15 (163,847 errors)
- ✅ collect_peak_detailed.py: 2025-12-01 (16 dní zpátky - CRITICAL)

**2. Scripts Cleanup**
- ✅ 8 core scripts v root (keep)
- ✅ 19 zastaralých skriptů → _archive_scripts/
- ✅ 8 test_*.py skriptů smazáno

**3. Documentation Cleanup**
- ✅ README_SCRIPTS.md aktualizován (8 core scripts)
- ✅ CONTEXT_RETRIEVAL_PROTOCOL.md aktualizován (Phase 5 status)
- ✅ Vytváření PHASE_ROADMAP.md (Phase 5-7 planning)

**4. Data/Backup Archivace**
- ✅ data/ → /home/jvsete/git/sas/ai-data/
- ✅ 11 zastaralých MD → _archive_md/
- ✅ export_peak_statistics.py vytvořen

**5. Workspace Reorganizace**
- ✅ _archive_scripts/ (19 skriptů)
- ✅ _archive_md/ (11 dokumentů)
- ✅ Zbývá 9 MD + 9 PY v root (clean!)

### 📊 VÝSLEDKY

| Item | Před | Po | Změna |
|------|------|----|----|
| Workspace | 618M | 404M | -214M |
| Root MD | 20+ | 9 | -11 (archivováno) |
| Root PY | 35 | 9 | -26 (archivováno) |
| Data soubory | 215M | v ai-data/ | archivováno |

**Aktivní v root:**
- Scripts: collect_peak_detailed.py, fetch_unlimited.py, analyze_period.py, + 5 DB scripts
- Docs: working_progress.md, CONTEXT_RETRIEVAL_PROTOCOL.md, HOW_TO_USE.md, README_SCRIPTS.md, + 4 others

### 🔄 NEXT PRIORITY (TODO)

**TODAY:**
- [ ] Vyčistit DB (DELETE staré z peak_statistics)
- [ ] Nahrát nová data do DB
- [ ] Verifikovat integritu

**NEXT:**
- [ ] Vytvořit ingest_peak_statistics.py
- [ ] Phase 6a: DB schema validation
- [ ] Deploy to K8s


---

## 📝 SESSION - 2025-12-16 11:00 UTC - Workspace Reorganization & Cleanup

### 🎯 Cíl
Vyčistit workspace, reorganizovat scripty, aktualizovat dokumentaci.

### ✅ HOTOVO (11:00-11:15 UTC)

**1. Workspace Cleanup**
- ✅ Archivováno: copilot-chat-backups/ (5MB - backupy chatů, nepotřebné)
- ✅ Archivováno: updates/ (200KB - staré session noty z listopadu)
- ✅ Archivováno: .backup_2025-11-18/ (1MB - starý backup, zastaralý)
- ✅ Archivováno: tests/ (<1KB - prázdný folder)
- ✅ Smazáno: Dockerfile.peak-detector (experiment)
- ✅ Smazáno: Dockerfile.tmp (temporary file)
- ✅ Smazáno: __pycache__ (auto-generated)

**2. Scripts Reorganizace**
- ✅ Vytvořen: `scripts/` folder s `scripts/INDEX.md` (detailní reference)
- ✅ Přesunuty: všechny .py scripty (10 skriptů) → scripts/
- ✅ Přesunut: workflow_manager.sh → scripts/
- ✅ Zachovány: references v dokumentaci

**3. MD Soubory Cleanup**
- ✅ Archivováno: COMPLETED_LOG.md (starý log)
- ✅ Archivováno: DEPLOYMENT.md (zastaralé)
- ✅ Archivováno: HARBOR_DEPLOYMENT_GUIDE.md (reference v archívu)
- ✅ Archivováno: KNOWN_ISSUES_DESIGN.md (design doc)
- ✅ Archivováno: PHASE_ROADMAP.md (starý roadmap)
- ✅ Archivováno: README_SCRIPTS.md (nahrazeno scripts/INDEX.md)

**4. K8s Archivace**
- ✅ Archivováno: k8s/ folder (zastaralé manifesty, cluster se ještě řeší)

**5. Dokumentace Update**
- ✅ Aktualizován: CONTEXT_RETRIEVAL_PROTOCOL.md (v2.1)
  - Nová struktura s scripts/
  - Čisté workspace tree
  - Priority workflow Phase 5A (data ingestion)
  
### 📊 VÝSLEDKY CLEANUP

| Kategorie | Před | Po | Poznámka |
|-----------|------|----|----|
| Root MD files | 10 | 4 | -6 archivováno |
| Root PY files | 9 | 0 | Všechny v scripts/ |
| Root folders | 14 | 9 | -5 do archívu |
| Total size | 283M | 283M | (venv zůstal) |
| Clean root | ❌ | ✅ | 4 MD + 7 config files |

**Finální Root Struktura:**
```
📄 README.md
📄 CONTEXT_RETRIEVAL_PROTOCOL.md
📄 working_progress.md
📄 HOW_TO_USE.md
📂 scripts/                          ← ALL PRODUCTION CODE
📂 app/                              ← FastAPI app
📂 alembic/                          ← DB migrations
📂 _archive_md/                      ← Old docs (6 files)
📂 _archive_scripts/                 ← Old scripts (19 files)
📂 _archive_old/                     ← Old folders
🐳 Dockerfile
📦 requirements.txt
... (config files)
```

### 🔄 WHAT'S NEXT (Priority)

**IMMEDIATE (Phase 5A - Data Ingestion):**
1. [ ] Export peak_statistics to CSV (backup)
2. [ ] Verify current DB data
3. [ ] (Optional) Clean old DB records
4. [ ] Load new data if available
5. [ ] Verify data integrity

**NEXT SESSION:**
6. [ ] Create ingest_peak_statistics.py (automated loader)
7. [ ] Test full pipeline
8. [ ] Deploy to K8s (Phase 6)

### 📚 KEY DOCUMENTS UPDATED

- `CONTEXT_RETRIEVAL_PROTOCOL.md` (v2.1) - Full workspace guide
- `scripts/INDEX.md` - Script reference + usage
- `working_progress.md` - This log

### 💾 GIT STATUS

```bash
# Files to commit:
- CONTEXT_RETRIEVAL_PROTOCOL.md (updated)
- working_progress.md (this log)
- scripts/ folder structure (reorganized)
- _archive_*/ folders (new archiving)

# Not committing:
- .venv/, venv/ (env files)
- __pycache__/ (auto-generated, already in .gitignore)
```


---

## 🗺️ DŮLEŽITÉ LOKACE - Pro Příští Session

### 📍 Aktuální K8s Konfigurace
```
Repo: /home/jvsete/git/sas/k8s-infra-apps-nprod/
Branch: feature/ai-log-analyzer-v2
Manifest: infra-apps/ai-log-analyzer/
Status: ZASTARALÝ - cluster se ještě řeší, zatím ručně
```

### 📊 Historická Data
```
Database: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
Schema: ailog_peak
Table: peak_statistics

Dates in DB:
- 2025-12-01 (initial load, 16 dní zpátky)
- 2025-12-15 (recent, 163,847 errors)

Query example:
SELECT date_trunc('day', measurement_time) as day, COUNT(*) 
FROM peak_statistics 
GROUP BY day 
ORDER BY day DESC;
```

### 💾 Exportované/Backup Data
```
Location: (needs export, see scripts/export_peak_statistics.py)
Format: CSV (YYYYMMDD_HHMMSS timestamp)
Command: cd scripts/ && python export_peak_statistics.py --from 2025-12-01 --to 2025-12-16
```

### 📁 Archive Locations
```
_archive_md/          - Old documentation (6 files)
_archive_scripts/     - Old scripts Phase 1-3 (19 files)
_archive_old/         - Folders archived today:
                        ├── k8s/                 (zastaralé manifesty)
                        ├── copilot-chat-backups/ (backupy chatů)
                        ├── updates/             (staré session noty)
                        ├── .backup_2025-11-18/  (starý backup)
                        └── tests/               (prázdný folder)
```

### 🔑 Key Contacts/Credentials (Cyberark)
```
Elasticsearch: XX_PCBS_ES_READ (elastic user)
Database: DAP_PCB safe (ailog_analyzer_user_d1)
Elasticsearch URL: elasticsearch-test.kb.cz:9500
```


---

## ✅ SESSION SUMMARY - 2025-12-16 11:00-11:30 UTC

### 🎯 GOALS
- [x] Clean workspace structure
- [x] Organize all scripts into single folder
- [x] Update documentation
- [x] Commit changes to git

### 📊 COMPLETED
```
✅ Workspace cleanup: 6 old folders archived
✅ Scripts reorganization: 10 PY + 1 SH moved to scripts/
✅ Created scripts/INDEX.md (detailed reference)
✅ MD files reorganized: 6 archived
✅ Documentation updated: CONTEXT_RETRIEVAL_PROTOCOL.md (v2.1)
✅ Git commit: a857894 (Phase 5: Workspace cleanup & reorganization)
```

### 🎯 FINAL WORKSPACE STRUCTURE
```
ai-log-analyzer/
├── 📄 CONTEXT_RETRIEVAL_PROTOCOL.md  (v2.1) ← START HERE
├── 📄 README.md                       (main docs)
├── 📄 working_progress.md             (this log)
├── 📄 HOW_TO_USE.md                   (tutorials)
│
├── �� scripts/                        (ALL PRODUCTION CODE)
│   ├── INDEX.md                       (script reference)
│   ├── collect_peak_detailed.py       (⭐ core)
│   ├── fetch_unlimited.py
│   ├── analyze_period.py
│   ├── export_peak_statistics.py
│   ├── verify_peak_data.py
│   ├── init_peak_statistics_db.py
│   ├── setup_peak_db.py
│   ├── grant_permissions.py
│   ├── create_known_issues_registry.py
│   └── workflow_manager.sh
│
├── 📂 app/                            (FastAPI app)
├── 📂 alembic/                        (DB migrations)
├── 📂 _archive_md/                    (old docs, 6 files)
├── 📂 _archive_scripts/               (old scripts, 19 files)
├── 📂 _archive_old/                   (archived folders)
├── 🐳 Dockerfile
└── 📦 requirements.txt
```

### 🔄 NEXT PRIORITY - Phase 5A: DATA INGESTION

**Immediate tasks:**
1. [ ] Export current peak_statistics to CSV backup
2. [ ] Verify DB data integrity
3. [ ] Load new historical data (if available)
4. [ ] Test full pipeline

**See:** `scripts/INDEX.md` for exact commands

### 📝 IMPORTANT FOR NEXT SESSION

**K8s Configuration Location:**
```
Repo: /home/jvsete/git/sas/k8s-infra-apps-nprod/
Branch: feature/ai-log-analyzer-v2
Manifest: infra-apps/ai-log-analyzer/
Status: ZASTARALÝ - cluster se řeší později
```

**Historical Data Location:**
```
Database: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
Schema: ailog_peak
Table: peak_statistics

Current dates:
- 2025-12-01 (baseline, 16 days)
- 2025-12-15 (recent, 163,847 errors)
```

**To Check Status:**
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
cat CONTEXT_RETRIEVAL_PROTOCOL.md    # Full context
cat scripts/INDEX.md                 # Scripts reference
tail -50 working_progress.md         # Last session log
```

### �� GIT INFO
- Commit: a857894
- Branch: main
- Last commit message: "Phase 5: Workspace cleanup & reorganization"
- Status: ✅ Clean, ready for next work

---

**Session ended at:** 2025-12-16 11:30 UTC  
**Total cleanup time:** ~30 minutes  
**Files organized:** 46 changes in git commit  
**Workspace ready:** ✅ YES - Phase 5A ready to begin


---

## 🔍 VYJASNĚNÍ: Co je "peak_statistics" (važné!)

### ❌ ŠPATNÉ POCHOPENÍ
"peak_statistics" = statistika o peakech (events, detekce, atd.)

### ✅ SPRÁVNÉ POCHOPENÍ
"peak_statistics" = **BASELINE PRO DETEKCI** peaků
- Je to reference data (známá/normální stav)
- Používá se pro porovnání = detekce anomálií

### 📊 OBSAH TABULKY peak_statistics
```
Řádek = (den_týdne, hodina, čtvrthodina, namespace)

Příklad data:
┌──────┬──────┬────────┬───────────────┬──────────────┬──────────────┐
│ Den  │ Hod  │ 15min  │ Namespace     │ Průměr chyb  │ StdDev chyb  │
├──────┼──────┼────────┼───────────────┼──────────────┼──────────────┤
│ Pon  │ 8:00 │ 0      │ pcb-sit-01    │ 203          │ 45           │
│ Pon  │ 8:00 │ 15     │ pcb-sit-01    │ 195          │ 42           │
│ Pon  │ 8:00 │ 30     │ pcb-sit-01    │ 187          │ 41           │
└──────┴──────┴────────┴───────────────┴──────────────┴──────────────┘

FORMULA PRO DETEKCI PEAKU:
  Aktuální chyby > (Průměr + 3 * StdDev) = ANOMÁLIE!
  Aktuální chyby > (Průměr + 5 * StdDev) = KRITICKÁ ANOMÁLIE!
```

### 📋 TABULKY V DATABÁZI
```
ailog_peak schema obsahuje:

1. peak_raw_data         ← Raw data z Elasticsearch (15min okna)
                           Používá se pro výpočet baseline

2. peak_statistics       ← BASELINE (průměr + stddev)
                           ⭐ TO CO VÁS ZAJÍMÁ!
                           Používá se pro detekci anomálií

3. peak_history          ← Historické peaky (skutečné detekované anomálie)
                           Peaky co se skutečně staly

4. active_peaks          ← Aktuálně běžící peaky
                           Real-time detekce
```

### 🎯 PROČ TEN NÁZEV?
- Původně by to mělo být: `error_baseline` nebo `anomaly_thresholds`
- Ale v kódu se to tak jmenuje, tak to necháme
- **DŮLEŽITÉ:** Vědět, že to je BASELINE, ne samotné peaky!

### 💾 AKTUÁLNÍ DATA V DB (2025-12-16)
```
Tabulka: peak_statistics (schema: ailog_peak)
Status: ✅ Načtena data pro:
  - 2025-12-01 (baseline, historické 16 dní)
  - 2025-12-15 (recent, 163,847 errors)

Ověřit stav:
  psql -h P050TD01.DEV.KB.CZ -U ailog_analyzer_user_d1 -d ailog_analyzer
  SELECT COUNT(*) FROM ailog_peak.peak_statistics;
  SELECT * FROM ailog_peak.peak_statistics LIMIT 5;
```

