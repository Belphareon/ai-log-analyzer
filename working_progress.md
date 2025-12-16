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

