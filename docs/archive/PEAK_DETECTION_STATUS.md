# Peak Detection Implementation Status

**Datum analýzy:** 2026-02-23  
**Analyzováno:** regular_phase.py, backfill.py, pipeline/phase_b_measure.py

---

## ✅ REGULAR PHASE - SPRÁVNĚ IMPLEMENTOVÁNO

### FIX A: Baseline Loading from DB ✅

**Regular phase (`scripts/regular_phase.py`) má FIX implementovaný správně:**

1. **Import BaselineLoader** (řádek 37):
   ```python
   from core.baseline_loader import BaselineLoader
   ```

2. **Načtení historického baseline** (řádky 553-582):
   ```python
   baseline_loader = BaselineLoader(db_conn)
   historical_baseline = baseline_loader.load_historical_rates(
       error_types=list(sample_error_types),
       lookback_days=7,
       min_samples=3
   )
   ```

3. **Injekce do pipeline** (řádek 593):
   ```python
   pipeline.phase_b.historical_baseline = historical_baseline
   ```

4. **Použití v Phase B** (phase_b_measure.py, řádky 301-303):
   ```python
   if fp in self.historical_baseline:
       # Přidej DB historii před aktuální okno
       historical_baseline = self.historical_baseline[fp] + historical_rates
   ```

### Výsledek:
✅ Regular phase **FUNGUJE SPRÁVNĚ** - načítá historické baseline z DB (7 dní × 96 oken = ~672 samples) a kombinuje s aktuálním oknem → peak detection má reálný baseline!

---

## ❌ BACKFILL - CHYBÍ BASELINE LOADING

### Problém:

**Backfill (`scripts/backfill.py`) NEPOUŽÍVÁ BaselineLoader!**

**Co chybí:**

1. ❌ **Import BaselineLoader** - není importován
2. ❌ **Načtení historického baseline** - neprovádí se
3. ❌ **Injekce do pipeline.phase_b** - backfill nikdy nevolá:
   ```python
   pipeline.phase_b.historical_baseline = historical_baseline
   ```

### Současný kód v backfill.py (řádky 427-437):

```python
pipeline = Pipeline(
    spike_threshold=float(os.getenv('SPIKE_THRESHOLD', 3.0)),
    ewma_alpha=float(os.getenv('EWMA_ALPHA', 0.3)),
)

# Inject registry into Phase C (critical for is_problem_key_known() lookup!)
if registry:
    pipeline.phase_c.registry = registry
pipeline.phase_c.known_fingerprints = known_fps.copy()

collection = pipeline.run(errors, run_id=f"backfill-{date.strftime('%Y%m%d')}")
```

### Důsledky:

1. **Backfill počítá baseline POUZE z aktuálních dat** (1 den = max 96 oken)
2. **Pro nové error_type → baseline = 0** → nemůže detekovat spike
3. **Nižší kvalita detekce** než v regular phase
4. **Nekonzistence** mezi backfill a regular phase detekcí

---

## 📊 SOUČASNÝ STAV DAT

Ze souboru `ai-data/peaks_detected_last_24h_strict_summary.json`:

- **Total events:** 346
- **Total groups:** 36
- **Known groups:** 0 (všechny jsou NEW)
- **Detection method:** v6_backfill

### Formát dat z JSON:
```json
{
  "namespace": "pcb-sit-01-app",
  "error_type": "UnknownError",
  "detection_method": "v6_backfill",
  "count": 104,
  "known_status": "NEW",
  "spikes": 0,
  "bursts": 104,
  "first_seen": "2026-02-22T15:35:41.923000",
  "last_seen": "2026-02-22T21:04:01.931000",
  "duration": "5h 28m",
  "max_score": 35.0,
  "root_causes": []
}
```

### Co CHYBÍ v současných datech:
1. ❌ **Root cause details** - pole `root_causes` je prázdné
2. ❌ **Link na peak_investigation** - nelze dohledat původní detekci
3. ❌ **Original/reference values** - kolik výskytů bylo a jaký byl baseline
4. ❌ **App/component** - není vidět konkrétní aplikace
5. ✅ **Namespace** - je přítomen
6. ✅ **Duration** - je spočítán
7. ✅ **Known status** - je označen (ale všechny jsou NEW)

---

## 🔧 DOPORUČENÉ OPRAVY

### 1. FIX BACKFILL - Přidat BaselineLoader (PRIORITY: HIGH)

Do `backfill.py` přidat stejnou logiku jako v `regular_phase.py`:

**A) Import:**
```python
from core.baseline_loader import BaselineLoader
```

**B) Před spuštěním pipeline (v `process_day_worker`):**
```python
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
    print(f"⚠️ Baseline loading failed: {e}")
    historical_baseline = {}

# Injektuj do pipeline
pipeline.phase_b.historical_baseline = historical_baseline
```

### 2. ENRICH PEAK DATA - Doplnit chybějící informace

Do tabulky peaků přidat:
- Original value (kolik výskytů)
- Reference value (baseline)
- Ratio (original/reference)
- App name
- Root cause (z peak_investigation nebo trace analysis)

---

## 📋 ZÁVĚR

| Komponenta | FIX A (BaselineLoader) | Status |
|------------|------------------------|--------|
| `regular_phase.py` | ✅ Implementováno | ✅ Funguje |
| `backfill.py` | ❌ CHYBÍ | ❌ **Potřebuje opravu** |
| `core/baseline_loader.py` | ✅ Existuje | ✅ Funkční |
| `pipeline/phase_b_measure.py` | ✅ Podporuje | ✅ Funkční |

**Regular phase detekuje peaky správně, ale backfill NE!**

Pro konzistenci je nutné přidat BaselineLoader do backfill.py podle stejného vzoru jako v regular_phase.py.
