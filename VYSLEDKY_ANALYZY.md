# VÝSLEDKY ANALÝZY DETEKCE PEAKŮ - 2026-02-23

## 🔍 CO JSEM ZJISTIL

### 1. REGULAR PHASE - ✅ SPRÁVNĚ IMPLEMENTOVÁNO

**Regular phase (`scripts/regular_phase_v6.py`) má FIX A implementovaný podle dokumentu FIX_PEAK_DETECTION_V1.md:**

✅ **Import BaselineLoader** (řádek 37)
✅ **Načtení historického baseline z DB** (řádky 553-582) - načítá 7 dní historie z `peak_investigation`
✅ **Injekce do pipeline.phase_b** (řádek 593)
✅ **Použití v Phase B measure** (phase_b_measure.py, řádky 301-303) - kombinuje historické + aktuální rates

**Výsledek:** Regular phase **FUNGUJE SPRÁVNĚ** - má reálný baseline z historických dat!

---

### 2. BACKFILL - ❌ CHYBÍ BASELINE LOADING

**Backfill (`scripts/backfill_v6.py`) NEPOUŽÍVÁ BaselineLoader!**

**Co chybí:**

❌ **Import BaselineLoader** - není v souboru  
❌ **Načtení historického baseline** - neprovádí se  
❌ **Injekce do pipeline.phase_b** - řádky 427-437 vytváří pipeline BEZ historical_baseline

**Problematický kód v backfill_v6.py:**
```python
# Řádek 427-437
pipeline = PipelineV6(
    spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
    ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
)

# Inject registry into Phase C (critical for is_problem_key_known() lookup!)
if registry:
    pipeline.phase_c.registry = registry
pipeline.phase_c.known_fingerprints = known_fps.copy()

# ❌ CHYBÍ: pipeline.phase_b.historical_baseline = historical_baseline

collection = pipeline.run(errors, run_id=f"backfill-{date.strftime('%Y%m%d')}")
```

**Důsledky:**
- Backfill počítá baseline POUZE z aktuálního dne (max 96 oken)
- Pro nové error_type → baseline = 0 → špatná detekce
- Nižší kvalita než regular phase
- Nekonzistence mezi backfill a regular phase

---

### 3. DATA Z POSLEDNÍCH 24H - ANALÝZA

**Vygeneroval jsem tabulku peaků pomocí nového skriptu `generate_peak_summary_table.py`:**

**Statistiky:**
- 📊 **481 záznamů** v peak_investigation (za 24h)
- 🎯 **42 různých peaků** (seskupeno podle namespace + error_type)
- 📈 **8,403 celkových events** v peakech
- ⚠️ **0 známých peaků** - všechny jsou NEW
- 🔥 **0 spikes, 36 bursts**

**Příklady z tabulky:**

| Peak | Time Range | Duration | NS | Error Type | Events | Peak/Baseline | Status |
|------|-----------|----------|-----|-----------|--------|--------------|--------|
| #1 | 02-22 14:05 → 02-23 13:35 | 23h 30m | pcb-dev-01-app | ServiceBusinessException | 310 | 99.0 / 10.3 | NEW |
| #8 | 02-22 17:00 → 02-23 09:15 | 16h 14m | pcb-fat-01-app | UnknownError | 1,431 | 477.0 / 204.4 | NEW |
| #20 | 02-22 18:21 → 02-23 11:54 | 17h 32m | pcb-dev-01-app | UnknownError | 2,853 | 530.0 / 92.0 | NEW |
| #30 | 02-22 19:33 → 02-23 06:00 | 10h 26m | pcb-sit-01-app | AccessDeniedException | 1,100 | 612.0 / 157.1 | NEW |

**Problémy v datech:**

❌ **Všechny peaky jsou NEW** - žádný není rozpoznán jako známý  
❌ **Většina má baseline = 0** - pro krátké peaky (např. #5-16, duration=0m)  
❌ **Root causes jsou prázdné** - pole `suspected_root_cause` je NULL  
❌ **App name často "unknown"** - není správně extrahováno  

---

## 📋 CO NEFUNGUJE A PROČ

### Problem #1: Backfill nemá BaselineLoader
**Symptom:** Baseline hodnoty jsou nízké nebo 0  
**Root cause:** backfill_v6.py nepoužívá BaselineLoader  
**Impact:** Špatná detekce nových peaků, mnoho false positives

### Problem #2: Root Cause Analysis není implementována
**Symptom:** Všechna `suspected_root_cause` pole jsou NULL  
**Root cause:** Není skript/komponenta, která by analyzovala trace a doplnila root cause  
**Impact:** Nelze zjistit, co peak způsobilo

### Problem #3: Enrichment chybí
**Symptom:** App name "unknown", chybí detaily o flow  
**Root cause:** Není enrichment pipeline, která by doplnila metadata  
**Impact:** Špatná lokalizace problému

### Problem #4: Known Peak Matching nefunguje
**Symptom:** Všechny peaky jsou NEW (0 známých)  
**Root cause:** Registry má 42 známých peaků, ale matching selhává  
**Impact:** Nelze rozeznat, zda jde o nový nebo známý problém

---

## ✅ CO FUNGUJE DOBŘE

✅ **Regular phase detekce** - správně implementovaný BaselineLoader  
✅ **Peak Investigation tabulka** - ukládá peak data správně  
✅ **Seskupování peaků** - nový skript správně agreguje data  
✅ **Časové rozsahy** - first_seen/last_seen jsou přesné  
✅ **Detection method tracking** - v6_regular vs v6_backfill

---

## 🔧 PRIORITIZOVANÉ OPRAVY

### 1️⃣ VYSOKÁ PRIORITA: Přidat BaselineLoader do backfill

**Do `backfill_v6.py` přidat:**

```python
# A) Import (začátek souboru)
from core.baseline_loader import BaselineLoader

# B) V process_day_worker(), před pipeline.run() (cca řádek 427):

# Load historical baseline from DB
historical_baseline = {}
try:
    db_conn = get_db_connection()
    baseline_loader = BaselineLoader(db_conn)
    
    # Zjisti error_types z aktuálních dat
    from pipeline.phase_a_parse import PhaseA_Parser
    parser = PhaseA_Parser()
    sample_error_types = set()
    for error in errors[:1000]:
        msg = error.get('message', '')
        error_type = parser.extract_error_type(msg)
        if error_type and error_type != 'Unknown':
            sample_error_types.add(error_type)
    
    # Načti baseline pro tyto error_types
    if sample_error_types:
        historical_baseline = baseline_loader.load_historical_rates(
            error_types=list(sample_error_types),
            lookback_days=7,
            min_samples=3
        )
    
    db_conn.close()
except Exception as e:
    safe_print(f"⚠️ Baseline loading failed: {e}")
    historical_baseline = {}

# C) Před pipeline.run():
pipeline.phase_b.historical_baseline = historical_baseline
```

### 2️⃣ STŘEDNÍ PRIORITA: Root Cause Enrichment

**Vytvořit skript:**
- Načte peaks z peak_investigation (kde suspected_root_cause IS NULL)
- Pro každý peak:
  - Načte reprezentativní traces z Elasticsearch
  - Analyzuje stack traces a error messages
  - Identifikuje root cause (např. který service/endpoint selhal)
  - UPDATE peak_investigation SET suspected_root_cause = ...

### 3️⃣ NÍZKÁ PRIORITA: App Name Enrichment

**Vytvořit:**
- Mapping NS → default app name
- Extrakce z log messages (patterns)
- Fallback na "unknown"

---

## 📊 NOVÝ SKRIPT: generate_peak_summary_table.py

**Vytvořil jsem skript pro generování přehledné tabulky:**

```bash
# Použití:
python scripts/generate_peak_summary_table.py                  # Poslední 24h
python scripts/generate_peak_summary_table.py --hours 48       # Poslední 48h
python scripts/generate_peak_summary_table.py --output table.md
```

**Výstup obsahuje:**
1. ✅ **Peak odkud do kdy** - time range + duration
2. ✅ **Kolik výskytů** - total events, peak value, baseline
3. ✅ **Namespace a aplikace** - NS + app/component
4. ✅ **Známý status** - NEW/KNOWN
5. ⚠️ **Root cause** - zatím prázdné (čeká na implementaci)

**Vygenerovaný soubor:**
`ai-data/peak_summary_24h_20260223_135100.md` (38KB)

---

## 🎯 ZÁVĚR

### Současný stav:
- ✅ **Regular phase:** FIX A implementován → **FUNGUJE**
- ❌ **Backfill:** FIX A CHYBÍ → **NEFUNGUJE** správně
- ⚠️ **Root Cause:** Není implementováno
- ⚠️ **Enrichment:** Není implementováno

### K ověření detekce je potřeba:
1. **Opravit backfill** - přidat BaselineLoader (viz bod 1️⃣)
2. **Implementovat Root Cause Analysis** - skript na analýzu traces
3. **Re-run backfill** - pro poslední X dní s opravenou detekcí
4. **Porovnat výsledky** - před/po opravě

### Doporučení:
**Nejdřív oprav backfill (1️⃣)**, pak až implementuj enrichment. Bez správného baseline je detekce nespolehlivá.

---

**Soubory vytvořené:**
- ✅ `PEAK_DETECTION_STATUS.md` - technická analýza implementace
- ✅ `scripts/generate_peak_summary_table.py` - skript pro generování tabulek
- ✅ `ai-data/peak_summary_24h_20260223_135100.md` - vygenerovaná tabulka peaků
