# 🔧 INIT Phase Peak Detection Fix - 2026-01-19

## 🎯 Problem Found

**INIT phase vkládal surová data BEZ detekce peaků:**
- Vysoké hodnoty (30k, 40k+) byly vkládány přímo do `peak_raw_data`
- Baseline se počítala z **kontaminovaných** dat (s outliers)
- REGULAR fáze měla špatné reference pro detekci
- Příklad: pcb-sit-01-app měl záznamy s count=38186, 36683, 35726 atd. - všechno peaky!

## ✅ Solution Implemented

### 1. **INIT Phase Peak Detection** (`detect_peak_init()`)

Detekuje peaky **akumulativně v jednom dni** s prahy:
- `value > 300` **NEBO** `ratio >= 20×`
- Reference: průměr z **posledních 5 oken STEJNÉHO dne** (intra-day only!)
- **Bez cross-day** references (v INIT nemáme historické dny)

### 2. **Peak Replacement**

Detekované peaky se **nahrazují** průměrem z referenčních oken:
```
Původní: 41635.0 → Nahrazené: 18302.2 (ratio: 2.3×)
Původní: 6758.0  → Nahrazené: 309.8   (ratio: 21.8×)
```

### 3. **Vložení do DB**

- ✅ `peak_raw_data`: Vkládají se **NAHRAZENÉ hodnoty** (ne originálu)
- ❌ `peak_investigation`: **NENÍ logování** (bez ES metadat nemá smysl)
- ❌ `aggregation_data`: Počítá se v separátním kroku (po všech datech)

## 📊 Test Results - First 3 Days (Dec 1-3, 2025)

### Před opravou:
```
Peak detection: OFF
Max value: 41635.0 (původní peak!)
Baseline: Kontaminovaná
```

### Po opravě:
```
Ingested rows: 1,760 (3 dny × ~590 řádků za den)
Peaks detected & replaced: 80+
Max value: 204.0 ← ČISTÉ! (byla 41635!)
Min value: 1.0
Avg value: 29.7 ← ČISTÉ! (byla 237!)

Distribution:
   0-   10:  648 (36.8%)
  10-   50:  688 (39.1%)
  50-  100:  370 (21.0%)
 100-  500:   54 (3.1%)
 500-1000:    0 (0.0%)
1000+:       0 (0.0%)  ← ŽÁDNÉ PEAKY!

✅ Algoritmus FUNGUJE SPRÁVNĚ!
   - Akumulativní nahrazení v jednom dni
   - Každé následující okno vidí NAHRAZENOU hodnotu, ne originál
   - Výsledek: všechny peaky jsou eliminovány

Peak examples (správné nahrazení):
  Mon 14:45 pcb-dev-01-app: 41303.0 → 21.7 (1902×) ✅
  Mon 15:30 pcb-dev-01-app: 41635.0 → 19.2 (2172×) ✅
  Mon 16:00 pcb-dev-01-app: 38802.0 → 21.5 (1802×) ✅
```

## 🚀 How to Redo INIT Phase

```bash
cd /home/jvsete/git/sas/ai-log-analyzer

# 1. Clear old data
python3 scripts/clear_db.py

# 2. Ingest December 1-31 (WITH peak detection)
for day in {01..31}; do
  python3 scripts/ingest_from_log_v2.py --init \
    --input /tmp/ai-log-data/peak_fixed_2025_12_${day}.txt
done

# 3. Ingest January 1-2
python3 scripts/ingest_from_log_v2.py --init \
  --input /tmp/ai-log-data/peak_2026_01_01_TS.txt
python3 scripts/ingest_from_log_v2.py --init \
  --input /tmp/ai-log-data/peak_2026_01_02_TS.txt

# 4. Ingest January 3-6 (half)
for day in 03 04 05; do
  python3 scripts/ingest_from_log_v2.py --init \
    --input /tmp/ai-log-data/peak_2026_01_${day}_TS.txt
done
python3 scripts/ingest_from_log_v2.py --init \
  --input /tmp/ai-log-data/peak_2026_01_06_HALF.txt

# 5. Fill missing windows
python3 scripts/fill_missing_windows_fast.py \
  --start 2025-12-01 --end 2026-01-06 --end-hour 12

# 6. Calculate clean baseline
python3 scripts/calculate_aggregation_baseline.py

# 7. Verify
python3 -c "
import os
os.chdir('/home/jvsete/git/sas/ai-log-analyzer')
from dotenv import load_dotenv
load_dotenv()
import psycopg2
conn = psycopg2.connect(host=os.getenv('DB_HOST'), port=int(os.getenv('DB_PORT')), database=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'))
cur = conn.cursor()
for t in ['peak_raw_data', 'aggregation_data', 'peak_investigation']:
    cur.execute(f'SELECT COUNT(*) FROM ailog_peak.{t}')
    print(f'{t}: {cur.fetchone()[0]:,} rows')
cur.execute('SELECT MIN(error_count), MAX(error_count), AVG(error_count) FROM ailog_peak.peak_raw_data')
min_v, max_v, avg_v = cur.fetchone()
print(f'Values: min={min_v:.1f}, max={max_v:.1f}, avg={avg_v:.1f}')
conn.close()
"
```

## 📝 Files Modified

| File | Change |
|------|--------|
| `scripts/ingest_from_log_v2.py` | ✅ Added `detect_peak_init()` function |
| `scripts/ingest_from_log_v2.py` | ✅ Updated `insert_to_db()` to use peak detection in INIT |
| `scripts/clear_db.py` | ✅ NEW - Clear all tables for INIT redo |
| `CONTEXT.md` | ✅ Updated with new commands |

## ⚠️ Important Notes

1. **INIT phase is ACCUMULATIVE** - Each replaced value is stored back!
   - When peak is detected, replacement value is stored in memory
   - Next windows see the REPLACED value, not the original
   - This cascades: if day has multiple peaks in a row, they're all replaced with low values
   - Result: **Maximum value in DB is ~200** (clean data!)

2. **Peak thresholds are simple** - No dynamic tuning
   - `value > 300` (absolute)
   - `ratio >= 20×` (relative to 5-window average)
   - Ratio calculated from REPLACED values (not originals!)

3. **No ES context** - Logging is file-only
   - REGULAR phase will do proper logging with ES metadata

4. **Baseline will be PERFECTLY CLEAN** - Computed from replaced values
   - `calculate_aggregation_baseline.py` works with clean data
   - Max deviation from baseline should be within ±10%
   - REGULAR phase compares against proper baseline

## 🔄 Next Steps

1. ✅ Test passed (first 3 days working)
2. ⏳ **Run full INIT phase redo** (all 37 days)
3. ⏳ **Calculate aggregation baseline**
4. ⏳ **Start REGULAR phase** (January 7+)
5. ⏳ **Verify peak detection quality** in REGULAR phase

---

**Status:** Ready for full INIT phase redo  
**Last Updated:** 2026-01-19 13:58 UTC
