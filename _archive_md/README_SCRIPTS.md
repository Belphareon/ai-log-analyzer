# AI Log Analyzer - Active Scripts Documentation

**Poslední aktualizace:** 2025-12-16  
**Status:** Phase 5 - Peak Detection Baseline Collection

---

## 🎯 Overview - Active Scripts

Projekt teď používá **8 core skriptů** pro peak detection pipeline. Všechny ostatní jsou archivovány v `_archive_scripts/`.

---

## ⭐ CORE SCRIPTS (POUŽÍVÁME)

### 1. `collect_peak_detailed.py` - Peak Data Collector

**Hlavní skript pro sbírání peak detection baseline dat.**

Sbírá error counts z Elasticsearch v 15-minutových oknech, počítá mean/stddev s 3-window smoothingem.

**Usage:**
```bash
# Explicitní datumový rozsah (PREFEROVANÉ):
python3 collect_peak_detailed.py --from "2025-12-15T00:00:00Z" --to "2025-12-16T00:00:00Z"

# Relativní (posledních N dní):
python3 collect_peak_detailed.py --days 1
python3 collect_peak_detailed.py --days 21
```

**Output:**
- Console: Detailní statistiky (mean/stddev/samples)
- Log: `/tmp/collect_peak_*.log` (dle redirect)

**Interní workflow:**
1. Generuje 15-minutová okna
2. Volá `fetch_unlimited.py` (stahuje z ES)
3. Grupuje chyby do windows
4. Počítá statistiky (mean, stddev, samples)
5. Aplikuje 3-window smoothing

**Důležité:**
- ✅ Vždycky používej `--from` a `--to` s Z suffixem
- ✅ 24h rozsah ≈ 160K errors
- ✅ Script běží 5-10 minut

---

### 2. `fetch_unlimited.py` - Elasticsearch Fetcher

**Dependency scriptu `collect_peak_detailed.py`.**

Implementuje search_after paginaci pro neomezené stahování.

**Konfigurace:**
- Index pattern: `cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*`
- Batch size: 5,000 (default)
- Credentials: Čítá z `.env`

---

### 3. `analyze_period.py` - Full Pipeline Orchestrator

**Komplexní orchestrační nástroj - A-Z analýza.**

Kombinuje všechny kroky: fetch → group → analyze → output.

**Usage:**
```bash
python3 analyze_period.py \
  --from "2025-12-15T00:00:00Z" \
  --to "2025-12-16T00:00:00Z" \
  --output /tmp/analysis_result.json
```

---

### 4. `init_peak_statistics_db.py` - Database Initialization

**ONE-TIME setup - vytvoří DB schema a tabulky.**

Vytvoří:
- Schema `ailog_peak`
- Table `peak_statistics` (baseline)
- Table `peak_raw_data` (raw collection)
- Indexy

**Usage:**
```bash
python3 init_peak_statistics_db.py
```

**Kdy:** Pouze při první inicializaci (1x)

---

### 5. `setup_peak_db.py` - Database Setup Helper

**Setup skript - přípravuje DB environment.**

Similar k `init_peak_statistics_db.py` ale lightweight.

---

### 6. `verify_peak_data.py` - Database Verification

**Kontrola dat v `peak_statistics` tabulce.**

Zobrazuje:
- Počet řádků
- Distinct namespaces
- Sample statistiky
- Stats by day of week

**Usage:**
```bash
python3 verify_peak_data.py
```

---

### 7. `grant_permissions.py` - DB Permissions Setup

**ONE-TIME setup - nastavuje DB permissions.**

**Usage:**
```bash
python3 grant_permissions.py
```

**Kdy:** Pouze při první inicializaci (1x)

---

### 8. `create_known_issues_registry.py` - Known Issues Registry

**Inicializace registry pro known issues.**

**Usage:**
```bash
python3 create_known_issues_registry.py
```

---

## 🗂️ Archived Scripts

Všechny staré/legacy/test scripty jsou v `_archive_scripts/` (19 skriptů).

Zahrnují:
- Staré fetch family (fetch_errors.py, fetch_simple.py, atd.)
- Zastaralé analyzery (analyze_daily.py, intelligent_analysis.py)
- Staré peak collection (collect_historical_peak_data.py, atd.)
- Diagnostické scripty (diagnose_es_data.py, check_es_indices.py)
- Legacy trace analysis (trace_extractor.py, trace_report_detailed.py)

---

## 🔄 Typical Workflow

### Phase 5 - Collect Peak Baseline

```bash
# 1. Sbírání dat (24h)
python3 collect_peak_detailed.py --from "2025-12-15T00:00:00Z" --to "2025-12-16T00:00:00Z"

# 2. Verifikace
python3 verify_peak_data.py

# 3-5. (TODO) Export, cleanup, insert do DB
```

---

## 📝 Environment Setup

**Vyžadovaný `.env` soubor:**
```
# Elasticsearch
ES_HOST=elasticsearch-test.kb.cz
ES_PORT=9500
ES_USER=XX_PCBS_ES_READ
ES_PASSWORD=<cyberark_password>
ES_INDEX=cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb-ch-*

# PostgreSQL
DB_HOST=P050TD01.DEV.KB.CZ
DB_PORT=5432
DB_NAME=ailog_analyzer
DB_USER=ailog_analyzer_user_d1
DB_PASSWORD=<cyberark_password>
```

---

## 🚨 Common Issues

### "0 errors fetched"
- Kontrola: ES_INDEX obsahuje všechny clustery?
- Kontrola: Jsou credentials v `.env`?

### Timezone errors
- Vždycky `Z` suffix (ne `+00:00`)
- ✅ Správně: `2025-12-15T00:00:00Z`
- ❌ Chybně: `2025-12-15T00:00:00+00:00`

---

## 📖 Related Documentation

- **CONTEXT_RETRIEVAL_PROTOCOL.md** - Kontext + kredenciály
- **working_progress.md** - Session log
- **HOW_TO_USE.md** - User guide
- **_archive_scripts/** - Legacy scripty (reference only)

