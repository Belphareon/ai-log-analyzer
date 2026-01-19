# 🔄 Implementační Status - Peak Detection V2 (2026-01-13)

## ✅ HOTOVO

### Dokumentace
- [x] PEAK_DETECTION_REFACTOR.md - Kompletně přepsáno V2 architekturou
- [x] values.yaml - Konfigurace s dynamickými parametry
- [x] INDEX.md (scripts/) - Aktualizováno pro V2 dynamic thresholds
- [x] ingest_from_log_v2.py - Implementován DYNAMIC peak detection algoritmus

### Algoritmus Peak Detection
- [x] **DYNAMIC RATIO THRESHOLD** = baseline_mean × min_ratio_multiplier (z values.yaml)
- [x] **DYNAMIC MINIMUM** = 24h_avg × dynamic_min_multiplier
- [x] **DUAL CONDITION** = (ratio >= dynamic_ratio_threshold) AND (value >= dynamic_minimum)
- [x] Konfigurabilní přes values.yaml (easy tuning)

### Databázové schéma (V2)
- [x] peak_raw_data - Poslední 30 dní (s peak replacement)
- [x] aggregation_data - Týdenní baseline (Reference 1)
- [x] peak_investigation - Full context peaků (s baseline, thresholds, ratio)
- [x] known_issues - Databáze aktivních bugů
- [x] known_peaks - Vyřešené problémy se řešením
- [x] error_patterns - Tracking VŠECH errorů (NEW!)

### Scripty (V2)
- [x] setup_peak_db_v2_simple.py - Vytvořit všech 6 tabulek
- [x] ingest_from_log_v2.py - INIT + REGULAR s dynamickými prahy
- [x] calculate_aggregation_baseline.py - Compute baseline

---

## ⏳ TODO - DALŠÍ SCRIPTY

### Phase 3: Agregace & Maintenance
- [ ] update_aggregation.py - Rolling update baseline každých 15 min
- [ ] cleanup_old_raw_data.py - Auto-delete raw_data >30 dnů

### Phase 4: Pattern Matching
- [ ] track_all_errors.py - Sbírá VŠECHNY errory do error_patterns
- [ ] match_known_issues.py - Pattern matching (peak → known_issue)
- [ ] match_known_peaks.py - Pattern matching (peak → known_peak)

### Phase 5: AI Analysis
- [ ] ai_analyze_peaks.py - AI inference (mel by byt Github Copilot, ale nejasne)
- [ ] send_teams_notification.py - Teams alert po detekci

### Phase 6: Auto-fix
- [ ] create_fix_pr.py - GitHub Copilot auto-fix (pokud confidence > 0.8)

---

## 🚀 POSTUP IMPLEMENTACE

### KROK 1: Setup DB V2 (Dnes)
```bash
cd /home/jvsete/git/sas/ai-log-analyzer
python3 scripts/setup_peak_db_v2_simple.py
python3 scripts/grant_permissions.py
```

### KROK 2: INIT Phase (Zítřa) - 21 dní baseline
```bash
for day in {01..21}; do
  python3 scripts/ingest_from_log_v2.py --init /tmp/peak_fixed_2025_12_$day.txt
done

python3 scripts/calculate_aggregation_baseline.py

python3 scripts/verify_peak_data.py
# Expected: 24,192 rows (21 × 96 × 12)
```

### KROK 3: REGULAR Phase (Od 22.12+) - S peak detection
```bash
# Denně (nebo každých 15 minut v K8s):
python3 scripts/ingest_from_log_v2.py /tmp/peak_fixed_2025_12_22.txt

# Log je v: /tmp/peaks_replaced_v2.log
# Ukazuje všechny detekované peaky s detaily (ratio, baseline, thresholds)
```

---

## 🎯 KEY FEATURES V2

| Feature | V1 (Stará) | V2 (Nová) |
|---------|-----------|----------|
| Ratio Threshold | Hardcoded 15× | **DYNAMIC** (baseline × multiplier) |
| Minimum Value | Hardcoded 100 | **DYNAMIC** (24h_avg × multiplier) |
| Konfigurace | V kódu | **values.yaml** |
| Error Tracking | Jen peaky | **VŠECHNY errory** |
| Known Patterns | Jen known_issues | **known_issues + known_peaks** |
| Peak Investigation | Bez detailů | **Full context** (baseline, thresholds) |

---

## 📊 CONFIGURATION (values.yaml)

```yaml
peak_detection:
  min_ratio_multiplier: 3.0          # ratio_threshold = baseline × 3.0
  dynamic_min_multiplier: 2.5        # minimum = 24h_avg × 2.5
  min_absolute_value: 100            # Fallback když žádný baseline
  same_day_window_count: 3           # Počet okna zpět
  use_aggregation_baseline: true
  use_24h_trend: true
  log_path: "/tmp/peaks_replaced_v2.log"
  verbose: false
```

**Jak se to používá:**
- Script načte values.yaml na začátku
- Všechny thresholdy se počítají DYNAMICKY
- Když potřebuješ ladit: edituj values.yaml a restartuj
- Log soubor ukazuje co se deteklo a jaké parametry se používaly

---

## ✅ ÚSPĚŠNÉ KRITÉRIUM

- ✅ peak_raw_data: 24,192 řádků (21 × 96 × 12) po INIT phase
- ✅ aggregation_data: 8,064 řádků (všechny kombinace) s mean/stddev/samples
- ✅ peak_investigation: Logují se detekované peaky s full context
- ✅ error_patterns: Trackují se VŠECHNY errory
- ✅ known_issues + known_peaks: Tabulky existují a lze je naplnit
- ✅ values.yaml: Používá se pro dynamické parametry
- ✅ Log: Ukazuje detaily detekce (baseline, threshold, ratio)
- ✅ Dokumentace: Aktuální, kompletní, jasná

---

## 🔍 OVĚŘENÍ FUNKČNOSTI

```bash
# Ověř peak_raw_data
python3 << 'EOF'
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT')),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_raw_data;")
print(f"✅ peak_raw_data rows: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM ailog_peak.aggregation_data;")
print(f"✅ aggregation_data rows: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM ailog_peak.peak_investigation;")
print(f"✅ peak_investigation rows: {cur.fetchone()[0]}")
