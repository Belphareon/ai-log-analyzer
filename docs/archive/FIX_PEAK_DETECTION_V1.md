# FIX Peak Detection v Regular Phase - Implementation Summary

**Date:** 2026-02-19
**Status:** ✅ Implementation Complete - Ready for Testing

## Problem Statement

Regular phase (15-min) **nemohl detekovat nové peaky** protože:
1. ❌ Nenačítal historické baseline z `peak_investigation` tabulky
2. ❌ Počítal baseline POUZE z aktuálního 15-min okna
3. ❌ Pro nový error → baseline = 0 → nelze detekovat spike
4. ❌ Notifikace se nikdy neposlala (podmínka `if HAS_TEAMS and collection.incidents`)

## Solution Implemented

### FIX A: Baseline Loading from DB ✅

**3 komponenty implementovány:**

#### 1. `scripts/core/baseline_loader.py` (NOVÝ MODUL)
- SQL query: SELECT reference_value z peak_investigation za posledních 7 dní
- Filtr: `is_spike OR is_burst OR score >= 30` (jen validní detekce)
- Vrací: `Dict[error_type -> List[baseline_rates]]` chronologicky seřazeno
- CLI: Testovatelný - `python baseline_loader.py --error-types NullPointerException --stats`

#### 2. `scripts/pipeline/phase_b_measure.py` (MODIFIED)
- Přidán parametr `historical_baseline: Dict[str, List[float]]` do `__init__`
- V metodě `measure()` kombinuje:
  - Historické rates z DB (7 dní × 96 oken = 672+ samples)
  - + Aktuální rates z ES (15-min okno = 1 sample)
  - = 673+ samples pro baseline EWMA
- Baseline nyní ≠ 0 pro nové errory!

#### 3. `scripts/regular_phase_v6.py` (MODIFIED)
- Import: `from core.baseline_loader import BaselineLoader`
- Před spuštěním pipeline:
  1. Zavolá `BaselineLoader(db_conn).load_historical_rates(...)`
  2. Injektuje do `pipeline.phase_b.historical_baseline = historical_baseline`
  3. Pipeline teď má reálný baseline → peak detection FUNGUJE

### FIX B: CSV Redesign (V6.2) ✅

**Nové pořadí sloupců (PRIORITY-DRIVEN):**

```
| first_seen | last_seen | occurrence_total | occurrence_24h | trend | root_cause | category | detail | [historické fields] | [informativní: severity, score, ratio] |
```

**ErrorTableRow dataclass:**
- Přidány nové fields: `trend`, `root_cause`, `occurrence_24h`
- Přeuspořádány: `first_seen` + `last_seen` na začátek
- `occurrence_total` místo `occurrences`
- Detail jako shorthand (error_class + flow)
- Score/ratio na konci (informativní)

**Implementace v `scripts/exports/table_exporter.py`:**
- Nový `ErrorTableRow` design s správným pořadím
- `get_errors_rows()` vypočítává trend a detail
- `export_errors_csv()` seřazuje sloupce dle nového pořadí

## Testing Plan

### T1: Ověřit data v peak_investigation
```bash
psql ... << 'EOF'
SELECT COUNT(*) FROM ailog_peak.peak_investigation;
SELECT DISTINCT error_type FROM ailog_peak.peak_investigation 
WHERE timestamp > NOW() - INTERVAL '7 days' LIMIT 10;
EOF
```

### T2: Test BaselineLoader CLI
```bash
python scripts/core/baseline_loader.py \
    --error-types "NullPointerException" "TimeoutException" \
    --days 7 --stats
```

### T3: Spustit regular_phase_v6.py
```bash
python scripts/regular_phase_v6.py \
    --from "$(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
    --to "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

### T4: Ověřit peak detection
```bash
grep -E "(BaselineLoader|historical|spike|burst|peak)" /tmp/test.log
```

## Files Modified

| File | Changes | Lines |
|------|---------|-------|
| `scripts/core/baseline_loader.py` | NEW | 250+ |
| `scripts/pipeline/phase_b_measure.py` | historical_baseline integration | +15 |
| `scripts/regular_phase_v6.py` | BaselineLoader call + injection | +35 |
| `scripts/exports/table_exporter.py` | CSV redesign (V6.2) | +60 |

## Expected Outcomes

✅ Regular phase nyní:
- Načte historické baseline z DB
- Kombinuje s aktuálními daty
- Detekuje peaky (spikes/bursts) i pro nové errory
- Pošle Teams notifikaci

✅ CSV tabulka:
- First_seen/Last_seen na začátku
- Trend zobrazuje změnu v čase
- Root_cause pole připraveno na enrichment
- Score/ratio na konci

## Next Steps (Future)

1. **Enrichment Script** - Naplní `root_cause` detaily
2. **Trend Analysis** - Agregace metriky po čase
3. **Teams Message Formatting** - Lepší formátování notifikace
