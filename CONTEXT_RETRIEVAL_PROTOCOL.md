# CONTEXT RETRIEVAL PROTOCOL
## AI Log Analyzer Project - Kontext pro Kontinuitu Práce

**Verze:** 2.0  
**Datum vytvoření:** 2025-12-12  
**Poslední update:** 2025-12-16  
**Účel:** Rychlé načtení kontextu pro pokračování v práci na projektu

---

## 📋 PROJEKT OVERVIEW

### Co je AI Log Analyzer?
- **Účel:** Automatická analýza logů z Elasticsearch (K8s aplikace)
- **Funkce:** Detekce anomálií, clustering chybových vzorů, temporální analýza
- **Technologie:** FastAPI + PostgreSQL + Elasticsearch + Ollama (optional)
- **Deployment:** Kubernetes (ArgoCD) + Harbor registry
- **Stav:** Phase 4 COMPLETE ✅ | Phase 5 IN PROGRESS 🔄 - Peak Detection Baseline

---

## 🎯 AKTUÁLNÍ STAV (2025-12-16 - Phase 5 IN PROGRESS)

### ✅ HOTOVO (Phase 4 + 5 start)
1. **Docker Image** ✅
   - Tag: `v0.4.0-docker-verified` + `latest`
   - Registry: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer`

2. **K8s Manifests** ✅
   - Location: `/home/jvsete/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/`

3. **Database Schema** ✅
   - PostgreSQL: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
   - Schema: ailog_peak

4. **Phase 5: Peak Collection Started** ✅
   - ✅ collect_peak_detailed.py spuštěn pro 2025-12-15 (163,847 errors)
   - ✅ collect_peak_detailed.py spuštěn pro 2025-12-01 (16 dní zpátky - CRITICAL)
   - ✅ Archivovány staré scripty (19 v _archive_scripts/)
   - ✅ Smazány test_*.py scripty (8 testů)
   - ✅ Aktualizován README_SCRIPTS.md

### 🔄 V PROCESU (Phase 5 - Current)
1. **Data Ingestion Pipeline**
   - [ ] Exportovat data do CSV tabulky
   - [ ] Vyčistit DB (DELETE staré záznamy)
   - [ ] Nahrát nová data do peak_statistics
   - [ ] Verifikace přes verify_peak_data.py

2. **Documentation Cleanup**
   - [x] Archivovat staré scripty
   - [x] Aktualizovat README_SCRIPTS.md
   - [ ] Aktualizovat CONTEXT_RETRIEVAL_PROTOCOL.md (TEN SOUBOR - IN PROGRESS)
   - [ ] Archivovat staré MD soubory

### 📋 TODO (Next Priority)
1. Vytvořit `ingest_peak_statistics.py` skript
2. Dokumentovat nový script
3. Deploy to K8s
4. Test integration

---

## 📁 STRUKTURA PROJEKTU

### Klíčové Soubory (Phase 5)
```
ai-log-analyzer/
├── collect_peak_detailed.py          # ⭐ CORE - Sbírá peak data
├── fetch_unlimited.py                # ⭐ CORE - ES fetcher
├── analyze_period.py                 # Orchestrator
├── export_peak_statistics.py         # Export do CSV
├── init_peak_statistics_db.py        # DB init (1x)
├── setup_peak_db.py                  # DB setup (1x)
├── verify_peak_data.py               # Verifikace
├── grant_permissions.py              # DB perms (1x)
├── create_known_issues_registry.py   # Registry
├── working_progress.md               # ✅ SESSION LOG
├── CONTEXT_RETRIEVAL_PROTOCOL.md     # ✅ REFERENCE
├── README_SCRIPTS.md                 # ✅ SCRIPT DOCS
├── PHASE_ROADMAP.md                  # ✅ ROADMAP
├── HOW_TO_USE.md                     # ✅ USER GUIDE
├── requirements.txt                  # Python dependencies
├── Dockerfile                        # Docker build
└── docker-compose.yml                # Local dev
```

### Git Struktura
```
/home/jvsete/git/sas/
├── ai-log-analyzer/                           # Development workspace
└── k8s-infra-apps-nprod/                      # Production K8s manifests
    └── infra-apps/ai-log-analyzer/            # ← Deploy location
        └── feature/ai-log-analyzer-v2         # ← Active branch
```

---

## 🔑 KLÍČOVÉ INFORMACE

### Credentials (Cyberark)
- **Elasticsearch:** XX_PCBS_ES_READ (elastic user)
- **Database:** DAP_PCB safe (ailog_analyzer_user_d1)
- **URL:** elasticsearch-test.kb.cz:9500

### Network Config
- **DNS (Prod):** ai-log-analyzer.sas.kbcloud
- **DNS (Test):** ai-log-analyzer-test.sas.kbcloud
- **Tenant Network:** 10.85.88.128/25
- **DNS Resolver:** 10.85.88.1

### Database Connection
- **Host:** P050TD01.DEV.KB.CZ (TODO: verify NPROD host)
- **Port:** 5432
- **Database:** ailog_analyzer
- **Schema:** public (tables: known_errors, analysis_runs, etc.)

### Elasticsearch Indices (Phase 5 - AKTUÁLNÍ)
- **Active:** `cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*`
- ~~Old~~ `logstash-kb-k8s-apps-nprod-*`, ~~`logstash-kb-k8s-apps-prod-*`~~
- **Env var:** `ES_INDEX` (POZOR: byl chybně `ES_INDICES`!)
- **Fields:** message, app_name, level, @timestamp, kubernetes.namespace

---

## 🛠️ WORKFLOW: Jak Pokračovat

### 1. Před Začátkem Práce
```bash
# Načti aktuální stav
cat /home/jvsete/git/sas/ai-log-analyzer/working_progress.md

# Zkontroluj git branch
cd /home/jvsete/git/sas/k8s-infra-apps-nprod
git status
git branch  # Měl bys být na feature/ai-log-analyzer-v2

# Zkontroluj Docker image v Harbor
# (pokud potřebuješ rebuild)
```

### 2. Práce na Změnách
```bash
# Development workspace
cd /home/jvsete/git/sas/ai-log-analyzer

# Testování lokálně (pokud potřeba)
python -m pytest tests/

# Build nového image (pokud změny v Dockerfile)
podman build -t ai-log-analyzer:latest .
```

### 3. Update K8s Manifests
```bash
# Copy změněné manifesty
cp k8s-manifests-v2/* /home/jvsete/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/

# Git commit
cd /home/jvsete/git/sas/k8s-infra-apps-nprod
git add infra-apps/ai-log-analyzer/
git commit -m "Update: [popis změny]"
git push origin feature/ai-log-analyzer-v2
```

### 4. Deployment (ArgoCD)
```bash
# ArgoCD automaticky detekuje změny v gitu
# Manual sync (pokud potřeba):
argocd app sync ai-log-analyzer

# Monitor deployment
kubectl get pods -n ai-log-analyzer -w
kubectl logs -n ai-log-analyzer deployment/ai-log-analyzer -f
```

### 5. Update Progress Log
```bash
# Vždy aktualizuj working_progress.md s timestampem
echo "## 📋 $(date +%Y-%m-%d) - [Popis práce]" >> working_progress.md
echo "" >> working_progress.md
echo "### Co bylo uděláno" >> working_progress.md
echo "- [ ] Todo item 1" >> working_progress.md
```

---

## 📝 KONVENCE PRO LOGGING

### Timestamp Format
```
## 📋 YYYY-MM-DD HH:MM UTC - [Titulek session]
```

### Session Structure
```markdown
## 📋 2025-12-12 14:30 UTC - Feature X Implementation

### 🎯 Cíl
- Co chci udělat

### ✅ Hotovo
- [x] Item 1 (14:35 UTC)
- [x] Item 2 (14:42 UTC)

### 🔄 V Procesu
- [ ] Item 3 (started 14:50 UTC)

### ⚠️ Problémy
- Popis problému + jak byl vyřešen

### 📊 Výsledek
- Stav po ukončení session
```

---

## 🚨 ZNÁMÉ PROBLÉMY & ŘEŠENÍ

### Problem 1: Docker Hub Rate Limit
**Symptom:** `You have reached your pull rate limit`  
**Solution:** Počkat 6 hodin nebo použít Docker auth token  
**Workaround:** `podman build --network=host`

### Problem 2: WSL2 Docker Network Corruption
**Symptom:** `netavark: unable to append rule`  
**Solution:** `sudo nft flush ruleset` + delete orphaned chains  
**Workaround:** `docker run --network none` pro lokální testy

### Problem 3: Database Host DEV vs NPROD
**Symptom:** ConfigMap has `P050TD01.DEV.KB.CZ`  
**Status:** TODO - verify correct NPROD host  
**Action:** Check with DevOps if DEV host is correct for NPROD cluster

### Problem 4: Soteri PASSWORD_IN_URL
**Symptom:** Secret obsahuje password v URL stringu  
**Solution:** ✅ RESOLVED - Build connection string v Pythonu, ne v ENV  
**Status:** Clean scan ✅

---

## 📚 ACTIVE DOCUMENTATION (Updated 2025-12-16)

### ⭐ POUŽÍVEJ TYTO (PRIMARY):
1. **working_progress.md** - Session log + TODO (MAIN!)
2. **CONTEXT_RETRIEVAL_PROTOCOL.md** - Ten soubor (reference)
3. **README_SCRIPTS.md** - 8 core skriptů (UPDATED 2025-12-16!)
4. **HOW_TO_USE.md** - User guide

### 🗂️ ARCHIVED / ZASTARALÉ (IGNORUJ):
- MASTER.md (2025-12-02)
- README_v2.md
- ORCHESTRATION_PROGRESS.md (2025-12-08)
- working_progress_backup_* (nepoužívej!)
- Viz: **MD_REGISTRY.md** pro úplný seznam

### 📖 Pro Development:
- **HARBOR_DEPLOYMENT_GUIDE.md** - K8s deployment
- **KNOWN_ISSUES_DESIGN.md** - Known issues design

---

## 🎯 NEXT STEPS - Phase 5 Workflow (Priority)

**IMMEDIATE (TODAY - 2025-12-16):**
1. [ ] Exportovat výstupy collect_peak_detailed.py do CSV tabulky
2. [ ] Vyčistit DB - DELETE staré záznamy z peak_statistics
3. [ ] Nahrát nová data do DB (INSERT)
4. [ ] Verifikovat přes verify_peak_data.py

**NEXT SESSION:**
5. [ ] Vytvořit `ingest_peak_statistics.py` skript (JSON → DB loader)
6. [ ] Dokumentovat v README_SCRIPTS.md
7. [ ] Archivovat staré MD soubory (_archive_md/)

**FINAL (Deployment):**
8. [ ] Deploy to K8s cluster nprod-3100
9. [ ] Test health endpoint
10. [ ] Verify integration

---

## ✅ CHECKLIST: Návrat k Projektu

Když začínáš novou session:

- [ ] Přečti poslední entry v `working_progress.md`
- [ ] Zkontroluj git branch: `feature/ai-log-analyzer-v2`
- [ ] Ověř aktuální stav K8s deploymentu (pokud nasazeno)
- [ ] Načti tento CONTEXT_RETRIEVAL_PROTOCOL.md
- [ ] Vytvoř nový entry v progress s timestampem
- [ ] Postupuj po malých krocích, loguj průběžně

---

## 📊 Scripts Registry (2025-12-16)

**8 CORE SCRIPTS (v root - AKTIVNÍ):**
- `collect_peak_detailed.py` ⭐ - Sbírá peak data z ES
- `fetch_unlimited.py` ⭐ - ES fetcher (dependency)
- `analyze_period.py` - Full orchestrator A-Z
- `init_peak_statistics_db.py` - DB init (1x setup)
- `setup_peak_db.py` - DB setup helper (1x)
- `verify_peak_data.py` - DB verification
- `grant_permissions.py` - DB permissions (1x)
- `create_known_issues_registry.py` - Known issues

**19 ARCHIVED (v _archive_scripts/ - NEPOUŽÍVEJ):**
- Staré fetch family (fetch_errors.py, fetch_simple.py, atd.)
- Zastaralé analyzery (analyze_daily.py, intelligent_analysis.py)
- Staré peak collection (collect_historical_peak_data.py, atd.)
- Diagnostic scripty (diagnose_es_data.py, check_es_indices.py, atd.)
- Trace legacy (trace_extractor.py, trace_report_detailed.py)

→ **Detaily:** Viz `README_SCRIPTS.md`

---

**Last Updated:** 2025-12-16 10:30 UTC  
**Maintainer:** AI Assistant + jvsete  
**Status:** ✅ Phase 4 Complete | 🔄 Phase 5 IN PROGRESS - Peak Detection Baseline Collection
