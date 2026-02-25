# Peak Detection Issues Analysis - 2026-02-25

## Summary
Peak detection implementace v6.1.0 má **KRITICKÉ PROBLÉMY** s naplněním baseline_mean hodnot v DB. To vede k selhání spike detekce a částečným výsledkům burst detekce.

---

## Problem #1: baseline_mean se nevyplňuje do DB (28.5% pokrytí místo 100%)

### Symptomy
```
Detection Method | Total Rows | With BL | BL % | Avg BL | Spike % | Burst %
v6_regular      |     12,313 |   3,507 | 28.5% | 1.4    |    0.3% |    0.0%
v6_backfill     |      2,842 |       0 |  0.0% | NULL   |    0.0% |   14.9%
```

**Očekávaný výsledek**: 100% records by měly mít baseline_mean
**Skutečný výsledek**: Jen 28.5% v regular, 0% v backfill

### Root cause analýza

#### a) Regular Phase - omezené extrahování error_types

**Soubor**: `scripts/regular_phase_v6.py` (řádky ~200-220)

```python
# AKTUÁLNÍ KÓD - CHYBNÝ
from pipeline.phase_a_parse import PhaseA_Parser
parser = PhaseA_Parser()
sample_error_types = set()
for error in errors[:1000]:  # ❌ POUZE PRVNÍCH 1000!
    msg = error.get('message', '')
    error_type = parser.extract_error_type(msg)
    if error_type and error_type != 'Unknown':
        sample_error_types.add(error_type)

if sample_error_types:
    historical_baseline = baseline_loader.load_historical_rates(
        error_types=list(sample_error_types),
        lookback_days=7,
        min_samples=3
    )
```

**Problém**: Když má regular phase 419,688 záznamů, ale loop běží jen na prvních 1000, chybí mnoho error_types:
- Např. v testu: měl by 10 typů error_types, ale vybere jen ty které jsou v prvních 1000 řádcích
- Ostatní error_types nemají baseline_mean → zůstávají NULL

**Evidence z backfill testu**:
```
   📊 Loaded baseline for 10 error types (z 419,688 records!)
```

#### b) Backfill Phase - stejný problém, jiný kód

**Soubor**: `scripts/backfill_v6.py` (řádky ~450-470)

```python
# AKTUÁLNÍ KÓD - ZA POSLEDNÍCH COMMITŮ JE FIXNUTÝ
# Ale problém stále přetrvává v DB datech!
sample_error_types = set()
for error in errors[:1000]:  # ❌ OPĚT POUZE PRVNÍCH 1000!
    msg = error.get('message', '')
    error_type = parser.extract_error_type(msg)
    if error_type and error_type != 'Unknown':
        sample_error_types.add(error_type)
```

**Problém**: Stejný jako regular - extrahuje jen z prvních 1000 záznamů

**Ověření v DB**: Backfill inserty mají 0% baseline_mean - to znamená že `incident.stats.baseline_median` je 0 nebo NULL pro všechny backfill incidenty

---

## Problem #2: Spike detekce nefunguje (0.2% ze 15,155 bodů)

### Symptomy
```
Total detection points: 15,155
Can support spike detection (baseline > 0): 3,507 (23.1%)
Actual spikes detected: 31 (0.2%)
```

**Problém**: Jen 31 spikes z 15,155 bodů, zatímco burst detekce běží normálně

### Root cause

Spike detekce v `scripts/pipeline/phase_c_detect_v2.py` (řádky 150-180) používá:

```python
def _detect_spike(self, measurement: MeasurementResult, result: DetectionResult) -> bool:
    """Detekuje spike: current > baseline * threshold"""
    
    # EWMA test
    if measurement.baseline_ewma > 0:
        ratio = measurement.current_rate / measurement.baseline_ewma
        if ratio > self.spike_threshold:  # Default: 3.0
            result.flags.is_spike = True
            return True
    
    # MAD test  
    if measurement.baseline_mad > 0:
        mad_upper = measurement.baseline_median + (measurement.baseline_mad * self.spike_mad_threshold)
        if measurement.current_rate > mad_upper:
            result.flags.is_spike = True
            return True
    
    return False
```

**Problém je v pipeline.py** (řádky 307-310):

```python
inc.stats.baseline_rate = measurement.baseline_ewma  # ✅ Kopírován
inc.stats.baseline_median = measurement.baseline_median  # ✅ Přidán v poslední opravě
inc.stats.baseline_mad = measurement.baseline_mad  # ✅ Existuje
```

Ale v **regular_phase_v6.py INSERT** (řádky 358-374):

```python
data.append((
    ts,
    ts.weekday(),
    ts.hour,
    ts.minute // 15,
    incident.namespaces[0] if incident.namespaces else 'unknown',
    incident.stats.current_count,
    int(incident.stats.baseline_rate) if incident.stats.baseline_rate > 0 else incident.stats.current_count,  # ✅ baseline_mean
    incident.stats.baseline_median if incident.stats.baseline_median > 0 else None,  # ✅ baseline_mean (REPEAT?)
    # ❌ CHYBÍ: incident.stats.baseline_mad - potřebné pro MAD test spike detekce!
    incident.flags.is_new,
    incident.flags.is_spike,  # Tady je flag SET v phase_c, ale...
    ...
))

# INSERT
(timestamp, day_of_week, hour_of_day, quarter_hour, namespace,
 original_value, reference_value, baseline_mean,  # ✅ Ve sloupcích
 is_new, is_spike, is_burst, is_cross_namespace,  # Zde je is_spike flag
 error_type, error_message, detection_method, score, severity)
```

**Zjištění**: Flag `is_spike` se KOPÍRUJE ze phase_c výsledků do DB dobře. Ale:
1. `baseline_median` se zapisuje 2x (v datech na pozici 8)
2. `baseline_mad` se nezapisuje vůbec
3. Pokud baseline_median není vyplněn, spike test v phase_c vrátí False

---

## Problem #3: Backfill data mají podivné časy

### Symptomy

Z backfill reporte:
```
#19 🟢 BUSINESS: servererror
  Time: 2026-02-18 02:06 - 23:07 (162027s)
```

Backfill byl spuštěn s:
```
[2/7] 2026-02-19
```

**Otázka**: Proč jsou časy z 2026-02-18 (včerejšek) když Processing probíhá na 2026-02-19?

### Root cause

Časy NEJSOU problém - jsou to event timestamps z logů, ne run timestamps:
- `Time` v reportu = `first_seen ... last_seen` z incidentů
- To je správně
- Ale VŠECHNY problémy mají stejný časový rozsah - to je divné

**Ověření**: Pojďme zkontrolovat, zda se v DB zapisují správné event timestamps→

---

## Problem #4: Inconsistency v baseline polích

### Vytvoření vs. Zapis

**V incident.py (Stats dataclass)**:
```python
@dataclass
class Stats:
    baseline_rate: float = 0.0       # EWMA baseline
    baseline_median: float = 0.0     # Median baseline value (NOVĚ PŘIDÁNO)
    baseline_mad: float = 0.0        # Median Absolute Deviation
```

**V pipeline.py (kopírování do incident)**:
```python
inc.stats.baseline_rate = measurement.baseline_ewma
inc.stats.baseline_median = measurement.baseline_median  # ✅ Nově přidáno
inc.stats.baseline_mad = measurement.baseline_mad
```

**V regular_phase_v6.py (zapis do DB)**:
```python
data.append((
    ...
    incident.stats.baseline_rate,  # Pozice 7
    incident.stats.baseline_median,  # Pozice 8 - DUPLICATE VALUES?
    ...
))

# INSERT sloupce
baseline_mean,  # Pozice 7+1 ve sloupcích = baseline_rate
               # Pozice 8+1 = baseline_median (je to baseline_mean 2x?)
```

**V backfill_v6.py (zapis do DB)**:
```python
data.append((
    ...
    int(incident.stats.baseline_rate) if incident.stats.baseline_rate > 0 else incident.stats.current_count,
    incident.stats.baseline_median if incident.stats.baseline_median > 0 else None,
    ...
))
# Stejný INSERT statement
```

---

## Data Evidence

### Skutečné hodnoty z DB (poslední 24h):

```sql
SELECT detection_method, COUNT(*), 
       COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) as with_baseline,
       ROUND(100.0 * COUNT(CASE WHEN baseline_mean IS NOT NULL THEN 1 END) / COUNT(*), 1) as pct
FROM peak_investigation
WHERE timestamp >= NOW() - INTERVAL '24 hours'
GROUP BY detection_method
ORDER BY COUNT(*) DESC;

 detection_method | count | with_baseline | pct
------------------+-------+---------------+-----
 v6_regular       | 12313 |          3507 | 28.5%
 v6_backfill      |  2842 |             0 | 0.0%
```

### Spike vs Burst detekce:

```sql
SELECT 
  COUNT(*) as total,
  COUNT(CASE WHEN is_spike THEN 1 END) as spikes,
  COUNT(CASE WHEN is_burst THEN 1 END) as bursts,
  ROUND(100.0 * COUNT(CASE WHEN is_spike THEN 1 END) / COUNT(*), 1) as spike_pct,
  ROUND(100.0 * COUNT(CASE WHEN is_burst THEN 1 END) / COUNT(*), 1) as burst_pct
FROM peak_investigation
WHERE timestamp >= NOW() - INTERVAL '24 hours'
  AND detection_method != 'baseline_test';

 total | spikes | bursts | spike_pct | burst_pct
-------+--------+--------+-----------+-----------
 15155 |     31 |    172 |     0.2%  |     1.1%
```

**Očekávaný poměr**: Spikes a bursts by měly mít podobné procento (obě ~ 2-3%)
**Skutečný poměr**: Spikes = 0.2%, Bursts = 1.1%

---

## Recommended Actions

1. **FIX #1**: V regular_phase_v6.py - extrahovat error_types ze VŠECH records, ne jen prvních 1000
   - Soubor: `scripts/regular_phase_v6.py`
   - Řádky: ~200-220
   - Zmena: `for error in errors[:1000]:` → `for error in errors:`

2. **FIX #2**: V backfill_v6.py - totéž
   - Soubor: `scripts/backfill_v6.py`
   - Řádky: ~450-470
   - Zmena: `for error in errors[:1000]:` → `for error in errors:`

3. **FIX #3**: Ověřit, že baseline_mean a baseline_median nejsou duplicitní v INSERT datech
   - Soubor: `scripts/regular_phase_v6.py` a `scripts/backfill_v6.py`
   - Řádky: ~358-374 (regular) a ~250-273 (backfill)
   - Ověřit pořadí a počet polí ve `data.append()` vs INSERT statement

4. **FIX #4**: Ověřit, že baseline_mad se nikam nezapomíná
   - Pokud je potřebný pro spike detekci, měl by se psát do DB
   - Pokud ne, vyloučit z pipeline

5. **FIX #5**: Po opravách spustit testy znovu a ověřit:
   - baseline_mean by měl být 100% vyplněn
   - Spike detekce by měla vrátit lepší procento (1-3%)
   - Event timestamps by měly být korektní

---

## Test Commands

```bash
# Ověřit baseline_mean pokrytí
python3 verify_baseline_fix.py

# Spustit regular phase na 24h okně
python3 scripts/regular_phase_v6.py --window 1440

# Spustit backfill na 1 den
python3 scripts/backfill_v6.py --days 1

# Commit and push
git add -A
git commit -m 'Fix: Extract ALL error_types for baseline loading'
git push
```
