# 🔍 CODE ANALYSIS - ingest_from_log.py - 2025-12-18 16:00 UTC

## 📋 Jak funguje AKTUÁLNÍ logika

### 1️⃣ PARSING DAT (řádky 1-98)
```python
def parse_peak_statistics_from_log(file_path):
    statistics = {}  # dict: (day, hour, qtr, ns) → {mean, stddev, samples}
    
    # Čte soubor řádek po řádku
    # Formát: "Day=Friday Hour=07:00 Quarter=0 Namespace=pcb-ch-sit-01-app Mean=2890.5 StdDev=..." 
    
    # Grupuje data do dict se UNIQUE KEY:
    # (day_of_week, hour_of_day, quarter_hour, namespace) → stats
    
    return statistics  # {(4, 7, 0, 'pcb-ch-sit'): {'mean': 2890.5, 'stddev': ..., 'samples': 1}}
```

✅ **TADY FUNGUJE SPRÁVNĚ** - Data se čtou a grupují

---

### 2️⃣ PEAK DETECTION - detect_and_skip_peaks() (řádky 99-202)

**TEORIE - Co by mělo dělat:**
```
REFERENCE OKNA:
1. PŘED (stejný den):
   - 45 minut před: hour-1, qtr 3 (nebo hour:45)
   - 30 minut před: hour-0, qtr 2 (nebo hour:30)
   - 15 minut před: hour-0, qtr 1 (nebo hour:15)

2. STEJNÝ ČAS (jiné dny):
   - Včera (day-1)
   - Předvčera (day-2)
   - 3 dny zpět (day-3)

KOMBINACE:
- avg_before_windows = (mean1 + mean2 + mean3) / 3 (tři okna PŘED)
- avg_prev_days = (mean_yesterday + mean_prev2 + mean_prev3) / 3 (3 dny zpět)
- combined_reference = (avg_before_windows + avg_prev_days) / 2

THRESHOLD:
- IF original_mean >= 15 × combined_reference:
    PEAK! → return (True, ratio, reference, debug_info)
- ELSE:
    Normal → return (False, None, None, {})

SPECIAL CASE:
- IF reference < 10: Use 50× threshold instead (avoid false positives)
```

✅ **LOGIKA JE SPRÁVNÁ V TEORII** - Koncept je správný

---

### 3️⃣ KRITICKÁ CHYBA - Řádek 252 v insert_statistics_to_db()

```python
def insert_statistics_to_db(statistics, conn):
    peaks_detected = 0
    inserted = 0
    
    # ... setup ...
    
    for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
        try:
            original_mean = stats['mean']
            
            # ⚠️ ŘÁDEK 252 - VOLÁNÍ:
            is_peak, ratio, reference, debug_info = detect_and_skip_peaks(
                day_of_week, hour_of_day, quarter_hour, namespace,
                original_mean, 
                statistics,           # ✅ Existuje
                all_stats             # ❌ UNDEFINED! Nikdy se nevytvoří!
            )
```

🔴 **PROBLÉM: `all_stats` se NIKDY nedefiniuje v insert_statistics_to_db()!**

---

## 🔴 ROOT CAUSE - PEAK DETECTION NEBEŽÍ!

### Řetězec chyb:

1. **Řádek 203** - Definice funkce:
   ```python
   def insert_statistics_to_db(statistics, conn):
       peaks_detected = 0
       inserted = 0
       # ...
   ```
   ➜ Parametry: `statistics` (dict s parsovanými daty) a `conn` (DB connection)
   ➜ ALE NIKDE se nevytvoří `all_stats`!

2. **Řádek 252** - Volání detect_and_skip_peaks s undefined `all_stats`:
   ```python
   is_peak, ratio, reference, debug_info = detect_and_skip_peaks(
       ..., statistics, all_stats  # ← all_stats NEEXISTUJE!
   )
   ```

3. **Výsledek:**
   - Python by měl vyhodit: `NameError: name 'all_stats' is not defined`
   - ALE na řádku 327 je `except Exception as e` blok! ⚠️
   - Chyba se pravděpodobně CHYTÁ a IGNORUJE!

4. **Důsledek:**
   ```python
   except Exception as e:
       print(f"⚠️  Failed to insert ({day_of_week},...): {e}")
       failed += 1  # Počítá se jako failed, ne jako peak!
   ```
   - Všechny záznamy s undefined `all_stats` se markují jako FAILED
   - Peak detection se NEBĚŽÍ
   - Žádné peaks se nedetekují = 28 peaks v DB!

---

## 🔧 CO JE POTŘEBA UDĚLAT

**KROK 1: Ověřit chybu přímo**
- Spustit `ingest_from_log.py` na testovacích datech
- Podívat se na stderr/stdout - je tam NameError?

**KROK 2: Opravit `all_stats`**

Správná logika by měla být:
```python
def insert_statistics_to_db(statistics, conn):
    peaks_detected = 0
    inserted = 0
    
    # ✅ FIX: Vytvořit all_stats - komplexní struktura pro hledání referenčních oken
    all_stats = {}
    for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
        if namespace not in all_stats:
            all_stats[namespace] = {}
        all_stats[namespace][(day_of_week, hour_of_day, quarter_hour)] = stats
    
    # Nyní se all_stats používá pro hledání referenčních oken
    for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
        is_peak, ratio, reference, debug_info = detect_and_skip_peaks(
            day_of_week, hour_of_day, quarter_hour, namespace,
            original_mean,
            statistics,  # Všechna data
            all_stats    # ✅ Nyní existuje!
        )
```

---

## 📊 RESUMÉ

| Aspekt | Status | Poznámka |
|--------|--------|----------|
| **Parsing dat** | ✅ OK | Data se čtou správně |
| **Peak Detection logika** | ✅ OK (v teorii) | Koncept je správný |
| **`all_stats` parametr** | 🔴 BROKEN | Nikdy se nevytvoří |
| **Error handling** | 🔴 SKRÝVÁ CHYBY | `except Exception` chytá NameError |
| **Výsledek** | 🔴 0 PEAKS SKIPNUTO | Všechny peak se vloží do DB |

---

---

## 🔴 OPRAVNÁ ANALÝZA - ROOT CAUSE NALEZEN! 2025-12-18 16:15 UTC

### ❌ PROBLÉM SE NACHÁZÍ V detect_and_skip_peaks()!

**Signatura funkce (řádek 105):**
```python
def detect_and_skip_peaks(cur, day_of_week, hour_of_day, quarter_hour, namespace, mean_val):
    """
    CLEAN IMPLEMENTATION - Peak Detection with Combined References
    
    Algorithm:
    1. Get 3 previous 15-min windows (same day): -15min, -30min, -45min
    2. Get 3 previous days (same time): day-1, day-2, day-3
    3. Combine: reference = (avg_windows + avg_days) / 2
    4. Calculate ratio = current / reference
    5. If ratio >= 15× AND current >= 10 → SKIP (it's a peak)
    """
    
    # STEP 1-2: Query DB for previous windows (same day)
    refs_windows = []
    if prev_windows:
        cur.execute(sql, params)  # ← HLEDÁ V DB!
        refs_windows = [row[0] for row in cur.fetchall()]
    
    # STEP 3: Query DB for previous days (same time)
    refs_days = []
    cur.execute(sql_days, (namespace, hour_of_day, quarter_hour, day_minus_1, day_minus_2, day_minus_3))
    refs_days = [row[0] for row in cur.fetchall()]  # ← HLEDÁ V DB!
    
    # STEP 4-5: Calculate reference
    if avg_windows is not None and avg_days is not None:
        reference = (avg_windows + avg_days) / 2.0
    ...
    
    return (is_peak, ratio, reference, debug_info)
```

---

## 🔴 ROOT CAUSE - CIRCULAR DEPENDENCY!

**PROBLÉM:**

Peak detection funguje takto:

1. **Čte parsovaná data** z `statistics` dict (ze souboru):
   - 2025-12-04 (Thu) + 2025-12-05 (Fri) = 946 řádků

2. **Pro KAŽDÝ řádek** volá `detect_and_skip_peaks()`:
   ```python
   for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
       is_peak, ratio, reference, debug_info = detect_and_skip_peaks(cur, ...)
   ```

3. **detect_and_skip_peaks() HLEDÁ V DB:**
   ```python
   cur.execute(sql_days, (namespace, hour_of_day, quarter_hour, day_minus_1, day_minus_2, day_minus_3))
   refs_days = [row[0] for row in cur.fetchall()]
   ```
   - Hledá `day_of_week IN (Thu-1, Thu-2, Thu-3)` = `(Wed, Tue, Mon)`
   - Hledá `day_of_week IN (Fri-1, Fri-2, Fri-3)` = `(Thu, Wed, Tue)`

**PROBLÉM:**

- Když ingestionujeme **PRVNÍHO DNEHO (Thu 04)**:
  - DB je prázdná!
  - Hledá Wed, Tue, Mon v DB → NIČEMU NEODPOVÍDÁ
  - `refs_days = []` (prázdné!)
  - `reference = None` nebo jen `avg_windows`
  - `ratio` se nepočítá správně
  - **Peak detection NEFUNGUJE!**

- Když ingestionujeme **DRUHÉHO DNEHO (Fri 05)**:
  - DB má data z Thu 04
  - Hledá Thu, Wed, Tue v DB
  - NAJDE Thu z předchozího ingestionu ✅
  - ALE Ten Thu byl s PEAKS v DB (nebyly skipnuty!) 🔴
  - Takže reference je NESPRÁVNÁ (obsahuje peaks)
  - **Peak detection pracuje s korrumpovanými referenčními daty!**

---

## 📊 DŮSLEDEK - Proč máme 28 peaks v DB:

```
DNEŠEK: Čtvrtek (Day 1 ingestion)
├─ Ingestionujeme Thu + Fri data
├─ detect_and_skip_peaks() hledá v PRÁZDNÉ DB
├─ Vrací reference = None (nebo jen 3 okna PŘED)
├─ Peaks se NEDETEKUJÍ (všechny jdou do DB) 🔴
└─ Výsledek: 28 PEAKS v DB

PŘÍŠTÍ DEN: Pátek (Day 2 ingestion)
├─ Ingestionujeme nová Fri data
├─ detect_and_skip_peaks() hledá v DB s KORRUMPOVANÝMI Thu referenčnímy daty
├─ Reference obsahuje ještě PEAKS ze včerejšího ingestionu
├─ Peaks se počítají vůči CHYBNÝM referencím
├─ Výsledek: Ještě více peaks v DB 🔴
```

---

## ✅ SPRÁVNÉ ŘEŠENÍ

**OPRAVA: Peak detection musí hledat reference z PARSOVANÝCH DAT, ne z DB!**

```python
def insert_statistics_to_db(statistics, conn):
    """
    Insert statistics into PostgreSQL peak_statistics table
    WITH PROPER PEAK DETECTION using PARSED DATA references
    """
    
    # ✅ FIX: Vytvořit indexovanou strukturu pro hledání referenčních oken
    # Tímto způsobem budeme hledat v PARSOVANÝCH DATECH, ne v DB
    stats_by_ns_day_time = {}
    for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
        key = (namespace, day_of_week, hour_of_day, quarter_hour)
        stats_by_ns_day_time[key] = stats
    
    # Nyní iterujeme a detekujeme peaks
    for (day_of_week, hour_of_day, quarter_hour, namespace), stats in statistics.items():
        original_mean = stats['mean']
        
        # ✅ NOVÁ LOGIKA: Hledej v parsovaných datech, ne v DB!
        is_peak = detect_and_skip_peaks_from_parsed_data(
            day_of_week, hour_of_day, quarter_hour, namespace,
            original_mean,
            stats_by_ns_day_time  # ← Parsovaná data, ne DB!
        )
        
        if is_peak:
            # Skip - don't insert
            continue
        
        # Insert normally
        cur.execute(sql, ...)
```

---

## 🎯 DŮVOD PROČ CURRENT LOGIKA SELHÁVÁ:

| Fáze | Logika | Status |
|------|--------|--------|
| **Parsing** | Data se čtou ze souboru ✅ | ✅ OK |
| **References lookup** | Hledají se v **DB** 🔴 | ❌ WRONG |
| **Detection** | Počítá se ratio s DB references 🔴 | ❌ FAILS |
| **Insertion** | Data se vloží bez detekce | ❌ 28 PEAKS V DB |

---

## ✅ PŘÍŠTÍ KROK:

1. **Opravit detect_and_skip_peaks()** aby hledal v parsovaných datech
2. Nebo vytvořit **novou funkci** `detect_and_skip_peaks_from_parsed_data()`
3. Testu na single-day ingestion (pouze Thu nebo Fri)
4. Ověřit že peaks NEJSOU v DB po ingestionu
