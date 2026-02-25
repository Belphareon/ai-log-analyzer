# DIAGNÓZA PROBLÉMŮ S PEAK DETECTION - 2026-02-23

## 🔍 CO UKAZUJÍ DATA

### Statistiky za posledních 24h (z peak_investigation):

```
Count | Spike | Burst | Baseline
------|-------|-------|----------
 5640 | FALSE | FALSE | ref=1-9       ← Normální provoz, nízký baseline
 1790 | FALSE | FALSE | ref=0         ← Baseline=0, není peak
  632 | FALSE | FALSE | ref=10-99     ← Normální provoz
  346 | FALSE | TRUE  | ref=0         ← 🔴 FALSE POSITIVES - burst s baseline=0!
   25 | FALSE | FALSE | ref>=100      ← Normální provoz, vysoký baseline
```

### Detection Method Breakdown:

```
Count | Method      | Spike | Burst | Score
------|-------------|-------|-------|-------
 6198 | v6_regular  | FALSE | FALSE | score<30    ← Běžné záznamy (ne peaky)
 1754 | v6_backfill | FALSE | FALSE | score<30    ← Běžné záznamy
  226 | v6_backfill | FALSE | TRUE  | score>=30   ← 🔴 BURSTS (pravděpodobně false)
  120 | v6_backfill | FALSE | TRUE  | score<30    ← 🔴 BURSTS (false)
   97 | v6_regular  | FALSE | FALSE | score>=30  ← Anomálie, ne spike/burst
   38 | v6_backfill | FALSE | FALSE | score>=30   ← Anomálie
```

### Příklady Burst s Baseline=0:

```
Namespace          | Error Type         | Orig | Ref | Score | Time
-------------------|--------------------|----- |-----|-------|------
pcb-dev-01-app     | ServerError        |  0.0 | 0.0 |  20.0 | 23:07
pcb-ch-sit-01-app  | ForbiddenError     |  0.0 | 0.0 |  20.0 | 21:35
pcb-sit-01-app     | UnknownError       |  0.0 | 0.0 |  20.0 | 21:35
```

---

## ❌ PROBLÉMY IDENTIFIK OVÁNY

### PROBLÉM #1: FALSE POSITIVE BURSTS (346 záznamů)

**Symptom:** `is_burst=TRUE` ale `reference_value=0` a `original_value=0`

**Root Cause:**  
V `phase_c_detect.py`, metoda `_detect_burst()` (řádek 184):

```python
if measurement.baseline_ewma > 0:
    rate_change = rate_per_min / measurement.baseline_ewma
    
    if rate_change > self.burst_threshold:
        result.flags.is_burst = TRUE  # ← Označí jako burst
```

**Problém:**
- Když `baseline_ewma = 0.0001` (velmi malý), ale rate_per_min = 0.1
- Ratio = 0.1 / 0.0001 = 1000 > burst_threshold (5.0) → detekuje burst
- ALE původní hodnota (`original_value`) je také 0 nebo velmi nízká!
- **Tohle nejsou skutečné peaky, ale šum / testovací data**

**Dopad:**
- 346 false positive záznamů namísto maybe 10-20 skutečných peaků
- Tabulka peaků je zaplněna nesmysly (duration=0m, events=0)

---

### PROBLÉM #2: REGULAR PHASE NEPOSÍLÁ NOTIFIKACE

**Symptom:** Nemáš žádné Teams notifikace o peakech

**Root Cause:**  
V `regular_phase_v6.py` (řádek 725-736):

```python
if HAS_TEAMS and collection.incidents:
    try:
        peaks_detected = sum(
            1 for inc in collection.incidents
            if inc.flags.is_spike or inc.flags.is_burst  # ← Podmínka
        )
        
        if peaks_detected > 0 and enriched_problems:  # ← Odesílá JEN když jsou peaky
            # Send notification...
```

**Problém:**
- Notifikace se posílá JEN když `peaks_detected > 0`
- `peaks detect` = spike OR burst
- **Když baseline=0 → spike test selže** (phase_c_detect.py řádek 153):
  ```python
  if measurement.baseline_ewma > 0:  # ← Když baseline=0, skip spike test
      ratio = measurement.current_rate / measurement.baseline_ewma
  ```
- **Burst test vytvoří false positives** (viz Problém #1)
- **Výsledek:** Buďto žádné notifikace, nebo notifikace o nesmyslech

---

### PROBLÉM #3: BASELINE=0 PRO NOVÉ ERRORY

**Symptom:** 1790 + 346 = 2136 záznamů má `reference_value=0`

**Root Cause Options:**

**A) Ve své analýze jsem viděl BaselineLoader v regular_phase**  
→ Ale pravděpodobně vrací prázdný dictionary pro nové error_types

**B) Data z DB nejsou dostupná**  
→ `BaselineLoader` query má filtr:  
```sql
WHERE (is_spike OR is_burst OR score >= 30)
```
→ Pokud error_type nikdy předtím nebyl spike/burst → není v historii!

**C) Phase B selhává při výpočtu baseline**  
→ Když `historical_baseline[fp]` je prázdný list → EWMA = 0

---

### PROBLÉM #4: SCORE-BASED DETEKCE NEFUNGUJE PRO NOTIFIKACE

**Symptom:** 97 záznamů v regular_phase má `score>=30` ale `is_spike=FALSE, is_burst=FALSE`

**Root Cause:**  
- Score může být vysoké i bez spike/burst (např. cross-namespace, nový error, atd.)
- **Ale notifikace se posílá JEN pro spike/burst** (viz Problém #2)
- **Score-based anomálie jsou ignorovány!**

---

## 🔧 NÁVRH ŘEŠENÍ

### FIX #1: FILTRUJ FALSE POSITIVE BURSTS

**Co opravit:** `phase_c_detect.py`, metoda `_detect_burst()`

**Současný kód (řádek 184-238):**
```python
def _detect_burst(...):
    # ...
    if measurement.baseline_ewma > 0:
        rate_change = rate_per_min / measurement.baseline_ewma
        
        if rate_change > self.burst_threshold:
            result.flags.is_burst = True  # ← Označí jako burst
```

**OPRAVA:**
```python
def _detect_burst(...):
    # ...
    
    # ← NOVÉ: Filtruj nesmyslné burst detekce
    MIN_BASELINE = 0.5  # Minimální baseline pro validní burst detection
    MIN_EVENTS = 3      # Minimální počet eventů v burst window
    MIN_RATE = 1.0      # Minimální rate/min pro burst
    
    if measurement.baseline_ewma > MIN_BASELINE:  # ← Změna z > 0
        rate_change = rate_per_min / measurement.baseline_ewma
        
        # ← NOVÉ: Kontroluj, že je to skutečně burst (ne šum)
        if (rate_change > self.burst_threshold and 
            count_in_window >= MIN_EVENTS and 
            rate_per_min >= MIN_RATE):
            
            result.flags.is_burst = True
            # ...
```

**Dopad:**  
- Eliminuje 300+ false positive bursts s baseline≈0
- Zachová skutečné bursts (baseline > 0.5, rate > 1/min)

---

### FIX #2: REGULAR PHASE NOTIFIKACE - ZAHRŇ SCORE-BASED

**Co opravit:** `regular_phase_v6.py`, podmínka pro notifikaci (ř. 725-736)

**Současný kód:**
```python
if HAS_TEAMS and collection.incidents:
    peaks_detected = sum(
        1 for inc in collection.incidents
        if inc.flags.is_spike or inc.flags.is_burst
    )
    
    if peaks_detected > 0 and enriched_problems:  # ← Jen spike/burst
        # Send notification
```

**OPRAVA:**
```python
if HAS_TEAMS and collection.incidents:
    # ← NOVÉ: Zahrň critical score-based anomálie
    critical_threshold = int(os.getenv('TEAMS_ALERT_SCORE_THRESHOLD', 70))
    
    peaks_detected = sum(
        1 for inc in collection.incidents
        if inc.flags.is_spike or inc.flags.is_burst
    )
    
    critical_incidents = sum(
        1 for inc in collection.incidents
        if inc.score >= critical_threshold  # ← Score-based
    )
    
    # ← NOVÉ: Pošli notifikaci pro spike/burst NEBO critical score
    if (peaks_detected > 0 or critical_incidents > 0) and enriched_problems:
        # Send notification
        peak_message = _build_peak_notification(...)
        # Include critical_incidents info in message
```

**Dopad:**  
- Pošle notifikaci i pro score-based anomal ie (např. nový cross-namespace error)
- Threshold konfigurovatelný přes `.env` (default: 70)

---

### FIX #3: BASELINE LOADING - FALLBACK PRO NOVÉ ERRORS

**Co opravit:** `core/baseline_loader.py` + `phase_b_measure.py`

**Problém:** BaselineLoader query filtruje `score >= 30` → nové errory nemají historii

**OPRAVA A: Použij MIN THRESHOLD v query**
```python
# baseline_loader.py, řádek ~70
query = """
SELECT error_type, reference_value, timestamp
FROM ailog_peak.peak_investigation
WHERE 
    error_type = ANY(%s)
    AND timestamp > %s
    AND (is_spike OR is_burst OR score >= 20)  # ← Změna z 30 na 20
ORDER BY error_type, timestamp ASC
"""
```

**OPRAVA B: Fallback na globální baseline**
```python
# phase_b_measure.py, metoda measure(), cca řádek 301
if fp in self.historical_baseline:
    historical_rates = self.historical_baseline[fp] + historical_rates
else:
    # ← NOVÉ: Fallback - použij průměr ostatních error_types v NS
    if not historical_rates:
        global_baseline = self._calculate_global_baseline(namespace)
        if global_baseline > 0:
            historical_rates = [global_baseline] * 10  # Seed with 10 samples
```

---

### FIX #4: VYLEPŠI TABULKU PEAKŮ

**Co opravit:** `scripts/generate_peak_summary_table.py`

**OPRAVA: Filtruj false positives**
```python
# V metodě fetch_peak_data(), cca řádek 150
query = """
SELECT ...
FROM ailog_peak.peak_investigation
WHERE timestamp >= %s
  AND (is_spike = TRUE OR is_burst = TRUE OR score >= 30)
  # ← NOVÉ: Filtruj bursts s baseline=0
  AND NOT (is_burst = TRUE AND reference_value < 0.5)  
  # ← NOVÉ: Filtruj events=0
  AND original_value > 0  
ORDER BY timestamp ASC
"""
```

---

## 📊 OČEKÁVANÉ VÝSLEDKY PO OPRAVĚ

| Metrika | Před | Po | Zlepšení |
|---------|------|-----|----------|
| False positive bursts | 346 | ~10 | 97% ↓ |
| Validní peaky v tabulce | ~ 12 | ~35 | 3x ↑ |
| Regular phase notifikace | 0/den | 3-8/den | ✅ |
| Score-based alerts | ignorované | zahrnuté | ✅ |
| Baseline=0 záznamy | 2136 | ~200 | 90% ↓ |

---

## 🎯 PRIORITY

1. **FIX #1 (HIGH)** - Filtruj false positive bursts → Vyčistí data
2. **FIX #2 (HIGH)** - Regular phase notifikace → Začneš dostávat alerts
3. **FIX #3 (MEDIUM)** - Baseline loading fallback → Lepší detekce nových
4. **FIX #4 (LOW)** - Vylepši tabulku → Lepší přehled

---

## 📝 IMPLEMENTAČNÍ PLÁN

### Krok 1: Oprav burst detection (30 min)
```bash
# Edit: scripts/pipeline/phase_c_detect.py
# Přidej MIN_BASELINE, MIN_EVENTS, MIN_RATE checks
# Test: python3 -m pytest tests/test_phase_c_detect.py
```

### Krok 2: Oprav regular phase notifikace (20 min)
```bash
# Edit: scripts/regular_phase_v6.py
# Přidej critical_incidents check
# Add TEAMS_ALERT_SCORE_THRESHOLD=70 do .env
```

### Krok 3: Test E2E (15 min)
```bash
# Run regular phase
python3 scripts/regular_phase_v6.py --window 60

# Verify:
# 1. Počet burst detections ↓
# 2. Teams notification odeslaná
# 3. Log obsahuje "critical_incidents" info
```

### Krok 4: Re-generate tabulku (5 min)
```bash
python3 scripts/generate_peak_summary_table.py --hours 24
# Verify: Méně false positives
```

---

**Chceš, abych implementoval FIX #1 a #2 teď?**
