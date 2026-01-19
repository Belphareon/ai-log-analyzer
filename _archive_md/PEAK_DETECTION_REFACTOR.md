# 🔄 Peak Detection Architecture V2 - COMPLETE SPECIFICATION

**Datum:** 2026-01-13  
**Verze:** 2.0 - DYNAMIC THRESHOLDS  
**Status:** 🔄 IMPLEMENTATION  
**Účel:** Implementovat korektní peak detection s dynamickými parametry z values.yaml

---

## 📋 ARCHITEKTURA - Přehled

### 🎯 Problém (Co jsme zjistili)

1. **Hardcoded thresholds jsou špatné:** Ratio 15× a minimum 100 se nehodí všem namespace
2. **Chybí trend tracking:** Nesledujeme všechny errory, jen agregované
3. **Bez context:** Nejsou uloženy detaily o peaku pro later investigation
4. **Bez known patterns:** Nemáme databázi vyřešených/očekávaných peaků

### ✅ ŘEŠENÍ - V2 Design

**6 Tabulek v PostgreSQL:**

| Tabulka | Účel | Lifetime | Key |
|---------|------|----------|-----|
| **peak_raw_data** | Surová data (s replacement) | 30 dní | timestamp + (day,hour,quarter,ns) |
| **aggregation_data** | Baseline (1 týden rolling) | Průběžně | (day,hour,quarter,ns) |
| **peak_investigation** | Log všech peaků | FOREVER | timestamp + namespace |
| **known_issues** | Databáze aktivních bugů | FOREVER | issue_name |
| **known_peaks** | Vyřešené problémy + řešení | FOREVER | peak_name |
| **error_patterns** | Tracking VŠECH errorů (NEW!) | 90 dní | pattern_hash |

---

## 🗄️ DATABÁZOVÉ SCHÉMA V2

Viz `scripts/setup_peak_db_v2_simple.py` pro kompletní SQL.

**Klíčové tabulky:**
- peak_raw_data: Všechny 15-min okna posledních 30 dnů (s peak replacement)
- aggregation_data: Týdenní baseline pro peak detection
- peak_investigation: Full context detekovaných peaků s AI analýzou
- known_issues: Databáze známých bugů pro pattern matching
- known_peaks: Vyřešené problémy se řešením pro auto-responses
- error_patterns: Tracking VŠECH errorů pro trend analýzu

---

## 🔧 PEAK DETECTION ALGORITMUS (DYNAMICKÝ)

### Klíčová logika

**DYNAMIC Peak Detection se 3 reference points + dynamickými prahy z values.yaml**

```
REFERENCE 1: baseline_mean z aggregation_data (1 týden)
REFERENCE 2: same_day windows (-15, -30, -45 min)
FINAL REFERENCE: průměr obou

DYNAMIC RATIO THRESHOLD = baseline_mean * min_ratio_multiplier (z values.yaml)
Příklad: baseline=100 → ratio_threshold = 100 * 3.0 = 300 (musí být 300× vyšší!)

DYNAMIC MINIMUM = 24h_avg * dynamic_min_multiplier
Příklad: 24h_avg=2500, multiplier=2.5 → dynamic_minimum = 6250

PEAK DECISION: (ratio >= dynamic_ratio_threshold) AND (error_count >= dynamic_minimum)
```

**Příklady:**

PCB (baseline=150, avg_24h=2500):
- ratio_threshold = 150 × 3.0 = 450
- dynamic_minimum = 2500 × 2.5 = 6250
- Peak jen pokud: ratio ≥ 150 AND value ≥ 6250

DCS (baseline=20, avg_24h=300):
- ratio_threshold = 20 × 3.0 = 60
- dynamic_minimum = 100 × 2.5 = 250
- Peak jen pokud: ratio ≥ 60 AND value ≥ 750

---

## 📊 FÁZE IMPLEMENTACE

### FÁZE 1: INIT (21 dní baseline - bez peak detection) hotova

```bash
# Setup
python3 scripts/setup_peak_db_v2.py
python3 scripts/grant_permissions.py

# Ingest 21 dní (1-21.12)
for day in {01..21}; do
  python3 scripts/ingest_from_log_v2.py --init /tmp/peak_fixed_2025_12_$day.txt
done

# Spočítej baseline
python3 scripts/calculate_aggregation_baseline.py

# Ověř
python3 scripts/verify_peak_data.py
# Expected: 24,192 rows (21 × 96 × 12)
```

### FÁZE 2: REGULAR (denní ingestion s peak detection)

```bash
# Denně (nebo každých 15 minut v K8s):
python3 scripts/ingest_from_log_v2.py /tmp/peak_fixed_2025_12_22.txt
```

---

## 🔧 KONFIGURAČNÍ SOUBOR (values.yaml)

Viz `values.yaml` v rootu projektu.

```yaml
peak_detection:
  min_ratio_multiplier: 3.0      # dynamic ratio threshold multiplier
  max_ratio_multiplier: 5.0
  dynamic_min_multiplier: 2.5    # dynamic minimum multiplier
  same_day_window_count: 3
  use_aggregation_baseline: true
  use_24h_trend: true
  log_path: "/tmp/peaks_replaced_v2.log"
  verbose: false
```

---

## 📝 SCRIPTY K IMPLEMENTACI

| Script | Účel | Status |
|--------|------|--------|
| `values.yaml` | Konfigurace | ✅ DONE |
| `setup_peak_db_v2.py` | Vytvořit schema | ⏳ TODO |
| `ingest_from_log_v2.py` | INIT + REGULAR | 🔄 UPDATE |
| `calculate_aggregation_baseline.py` | Baseline | ⏳ TODO |
| `update_aggregation.py` | Rolling update | ⏳ TODO |
| `track_all_errors.py` | Error patterns | ⏳ TODO |
| `match_known_issues.py` | Pattern matching | ⏳ TODO |

---

## ✅ ÚSPĚŠNÉ KRITÉRIUM

- ✅ peak_raw_data: 24,192 řádků (INIT)
- ✅ aggregation_data: 8,064 řádků
- ✅ peak_investigation: Logují se peaky
- ✅ error_patterns: Trackují se errory
- ✅ known_issues/peaks: Lze přiřazovat
- ✅ values.yaml: Používá se pro parametry
- ✅ Log: Ukazuje detaily detekce

---

**Version:** 2.0 DYNAMIC | **Last Updated:** 2026-01-13 | **Status:** 🔄 IMPLEMENTATION
