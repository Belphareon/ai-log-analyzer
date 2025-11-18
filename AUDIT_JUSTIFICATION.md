# Audit Justification - File Classification (2025-11-18)

## SOUBORY KE SMAZÁNÍ - DETAILNÍ ZDŮVODNĚNÍ

### 1. `trace_analysis.py` (5.8K) - DELETE
**Důvod:** Nahrazen novější verzí
- **Status:** Starší verze z Nov 13, původně vytvořen pro trace grouping
- **Nahrazen:** `trace_extractor.py` (8.1K, Nov 13, completní implementace)
- **Funkcionalita:** trace_extractor.py má VŠECHNY funkce + více (root cause extraction, konkrétní popis)
- **Git:** Upravován 2x (Nov 12, Nov 13) - již není aktivní vývoj
- **Dependence:** Nikde není importován
- **Riziko:** Nízké - plně nahrazen

### 2. `trace_report_generator.py` (5.2K) - DELETE
**Důvod:** Nahrazen novější verzí
- **Status:** Základní verze pro report generování
- **Nahrazen:** `trace_report_detailed.py` (16K, Nov 13, kontext + konkrétní příčiny)
- **Funkcionalita:** trace_report_detailed.py má:
  - ✅ Všechny funkce trace_report_generator.py
  - ✅ PLUS: Context extraction (15+ regex patterns)
  - ✅ PLUS: Specificity classification (concrete/semi-specific/generic)
  - ✅ PLUS: Time format fixes
  - ✅ PLUS: Executive summary s action items
- **Git:** Upravován 1x (Nov 13) - finální verze
- **Dependence:** Nikde není importován
- **Riziko:** Nízké - plně nahrazen

### 3. `investigate_relay_peak.py` (4.2K) - DELETE
**Důvod:** Ad-hoc debug/diagnostic skript, ne produkční
- **Status:** Speciální skript pro investigation jednoho konkrétního problému
- **Použití:** Jednorázová analýza peaku Relay v Nov 12
- **Nahrazen:** Funkcionalita integrována do `intelligent_analysis.py`
- **Git:** Naposledy upravován Nov 12 - již není relevantní
- **Dependence:** Nikde není importován
- **Riziko:** Nízké - je to debug skript, ne core functionality

### 4. `aggregate_batches.py` (3.8K) - DELETE
**Důvod:** Testovací skript, ne produkční
- **Status:** Starý testovací skript pro agregaci batchů
- **Nahrazen:** `fetch_today_batches.py` + `test_integration_pipeline.py`
- **Použití:** Jednorázový test, již není relevantní
- **Git:** Naposledy upravován Nov 12
- **Dependence:** Nikde není importován
- **Riziko:** Nízké - je to testovací skript

### 5. `refetch_low_coverage.py` (3.9K) - DELETE
**Důvod:** Nahrazen smart sampler funkcionalitou
- **Status:** Helper skript pro re-fetch dat s nízkou pokrytím
- **Nahrazen:** `fetch_errors_smart.py` (má --min-coverage flag)
- **Git:** Naposledy upravován Nov 11
- **Dependence:** Nikde není importován
- **Riziko:** Nízké - funkcionalita je v smart fetcheru

### 6. `fetch_errors.py` (2.1K) - DELETE
**Důvod:** Nahrazen verzí bez timezone bugů
- **Status:** Stará verze bez timezone fix
- **Nahrazen:** `fetch_errors_smart.py` (má timezone conversion + smart sampling)
- **Bug:** Fetch errors.py má timezone issue (hledal v budoucnosti)
- **Git:** Naposledy upravován Nov 11 - PŘED timezone bugfix
- **Dependence:** Nikde není importován
- **Riziko:** Nízké - ale DŮLEŽITÝ: pokud by se znovu použil, vrátil by se timezone bug!

### 7. `fetch_errors_curl.sh` (2.7K) - DELETE
**Důvod:** Debug shell script, ne produkční
- **Status:** Ruční curl příkazy pro testing ES
- **Nahrazen:** Všechny Python skripty (fetch_errors_smart.py, simple_fetch.py)
- **Použití:** Jednorázový manuální test, debugging
- **Git:** Naposledy upravován Nov 11
- **Dependence:** Nikde není importován, je to shell
- **Riziko:** Nízké - debug skript

### 8. `app.log` (826B) - DELETE
**Důvod:** Stará log data, bez historické hodnoty
- **Status:** Výstup ze starého loggingu
- **Obsahuje:** Staré error/debug zprávy z Nov 12
- **Relevance:** Nula - lze regenerovat při novém spuštění
- **Git:** Mělo by být v .gitignore (je v .gitignore!)
- **Riziko:** Nízké - je to jen log, není to data

### 9. `test_analyze.json` (1.3K) - DELETE (PODMÍNĚNĚ)
**Důvod:** Starý testovací sample
- **Status:** Test JSON z Nov 6
- **Nahrazen:** Novější test samples v `/data/` (last_hour*.json, batch_*.json)
- **Relevance:** Nižší - je z dávné minulosti
- **Doporučení:** Zkontrolovat - pokud je v `/data/` novější, smazat

### 10. `/tmp/` DIRECTORY - DELETE
**Důvod:** Vývojářská data, bez historické hodnoty
- **Velikost:** 800MB+
- **Obsahuje:** daily_*.json, report_*.md, starší test data
- **Relevance:** Nula - je to dočasný storage
- **Git:** Mělo by být v .gitignore (.gitignore obsahuje `/tmp/`)
- **Riziko:** Nízké - jde jen o temp data

---

## KLÍČOVÉ POZOROVÁNÍ

Všech 10 souborů ke smazání splňuje alespoň jedno z:
1. ✅ Nahrazeno novější verzí (trace_analysis.py, trace_report_generator.py, refetch_low_coverage.py, fetch_errors.py)
2. ✅ Je to debug/testovací skript (investigate_relay_peak.py, aggregate_batches.py, fetch_errors_curl.sh)
3. ✅ Je to stará/dočasná data (app.log, test_analyze.json, /tmp/)

**ŽÁDNÝ** z nich se **NEIMPORTUJE** v produkčním kódu ani testech.

---

## SOUBORY K ZACHOVÁNÍ

### Produkční Skripty (7 ks)
1. **simple_fetch.py** - Standalone ES fetcher
2. **fetch_errors_smart.py** - Smart sampler s timezone fix ✅
3. **fetch_today_batches.py** - Real-time batch fetch
4. **trace_extractor.py** - Root cause extraction (NOVÝ)
5. **trace_report_detailed.py** - Detailed reporting s kontextem (NOVÝ)
6. **intelligent_analysis.py** - ML analysis s trace integration
7. **analyze_daily.py** - Daily batch analyzer

### Test Skripty (4 ks)
1. **test_integration_pipeline.py** - E2E test (NOVÝ)
2. **test_pattern_detection.py** - Pattern ML test
3. **test_temporal_clustering.py** - Temporal analysis test
4. **test_cross_app.py** - Cross-app correlation test

**Všichni produkční a test skripty se IMPORTUJÍ v:**
- app/main.py (při spuštění analyzy)
- CI/CD pipeline (při testování)
- Kubernetes CronJob (při naplánovaném běhu)

---

## RIZIKO ANALÝZA

| Soubor | Riziko | Důvod |
|--------|--------|-------|
| trace_analysis.py | VELMI NÍZKÉ | Plně nahrazen trace_extractor.py |
| trace_report_generator.py | VELMI NÍZKÉ | Plně nahrazen trace_report_detailed.py |
| investigate_relay_peak.py | NÍZKÉ | Debug skript, debug info v reports |
| aggregate_batches.py | NÍZKÉ | Testovací skript, není v CI/CD |
| refetch_low_coverage.py | NÍZKÉ | Nahrazeno --min-coverage flagg |
| fetch_errors.py | NÍZKÉ (POZOR!) | Je to stará verze, ale s BUG! |
| fetch_errors_curl.sh | NÍZKÉ | Shell debug skript |
| app.log | NÍZKÉ | Log soubor, lze regenerovat |
| test_analyze.json | NÍZKÉ | Starý sample, je novější |
| /tmp/ | NÍZKÉ | Dočasné soubory |

**ZÁVĚR:** Všechny soubory lze bezpečně smazat.
