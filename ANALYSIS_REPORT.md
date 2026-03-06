# ANALÝZA 3 ZBÝVAJÍCÍCH BODŮ - 2.3.2026

## 1️⃣ BASELINE LOADING: ALL ERROR_TYPES

### Status: ✅ HOTOVO (v regular_phase.py)

**Co se dělá:**
```python
# Lines 761-780 v regular_phase.py
all_error_types = set()
for error in errors:
    error_type = parser.extract_error_type_rich(error)
    if error_type and error_type != 'Unknown':
        all_error_types.add(error_type)

# Načti baseline pro ALL error_types
if all_error_types:
    historical_baseline = baseline_loader.load_historical_rates(
        error_types=list(all_error_types),
        lookback_days=7,
        min_samples=3
    )
    print(f"   📊 Loaded baseline for {len(historical_baseline)}/{len(all_error_types)} error types")
```

**Analýza:**
- ✅ Iteruje přes VŠECHNY errors (ne jen prvních 1000)
- ✅ Extrahuje ALL unique error_types 
- ✅ Loaduje baseline pro ALL error_types
- ✅ Loguje procento ké error_types se podařilo loadovat
- ✅ Stejná logika jako v backfill.py (konzistentní)

**Závěr:** BASELINE LOADING JE OK - není co řešit

---

## 2️⃣ CHYBÍ KNOWN PEAKS OD 27.2.

### Status: ⚠️ ZJIŠTĚNO - DATA JSOU POUZE DO 27.2.

**Aktuální stav registru:**
- Nejstarší peak: PK-000052, first_seen = 2026-02-23
- Poslední peak: PK-000060, last_seen = 2026-02-27
- CHYBÍ: nic od 28.2. do 2.3. (5 dní bez registru!)

**Registry struktura:**
- `registry/known_peaks.yaml` - seznam všech detekovaných peaků
- `registry/known_problems.yaml` - seznam všech problémů (lidská evidencia)
- `registry/fingerprint_index.yaml` - mapování fingerprint → problem_key

**Možné příčiny:**
1. Regular phase se neběžel od 27.2. 12:09:49 UTC
2. Nebo se běžel ale neprodukoval peaky
3. Nebo se neukládal update do registru (bug v save registry?)

**Jak si to ověřit:**
```bash
# 1. Check if regular_phase ran recently
tail -100 /tmp/regular_phase_test.log

# 2. Check database for recent data
psql -d ailog -c "SELECT DISTINCT DATE(timestamp) FROM ailog_peak.peak_investigation ORDER BY 1 DESC LIMIT 10;"

# 3. Check if registry save works
git log --oneline registry/ | head -5
```

**Závěr:** POTŘEBUJEŠ SPUSTIT RECENT DATA FETCH ABY SEN VĚDĚL CO SE DĚJE OD 27.2.

---

## 3️⃣ PEAK_COUNT vs OCCURRENCES_COUNT

### Status: ⚠️ ZJIŠTĚNO NEKONZISTENCE

**Struktura Problem objektu (z analysis/):**
- `problem.total_occurrences` - POČET všech incidentů pro daný problém
- `problem.incident_count` - POČET incidentů (mělo by se rovnat total_occurrences?)
- `problem.max_score` - maximální skóre incidentu

**Struktura Peak v registry:**
```yaml
PeakEntry:
  occurrences: int  # Počet výskytů v registry

Problem (z pipeline):
  total_occurrences: int  # Počet všech incidentů
  incident_count: int     # Počet incidentů?
```

**Možný problém:**
```python
# V _build_peak_notification():
lines.append(f"Occurrences: {problem.total_occurrences:,} across {problem.incident_count} incidents")

# Co znamená "total_occurrences" vs "incident_count"?
# Zdá se že:
# - total_occurrences = součet countu všech raw errors v problému
# - incident_count = počet unikátních incidentů (po agregaci)

# Příklad:
# 10 raw errors → aggregate do 3 incidentů
# total_occurrences = 10
# incident_count = 3
```

**V email notifikaci:**
```python
error_count=problem.total_occurrences,  # Raw error count
```

**Závěr:** LOGIKA VYPADÁ OK - total_occurrences = raw error count, incident_count = agregované incidenty
- Ale POTŘEBUJEŠ OVĚŘIT NA REÁLNÝCH DATECH, že se to chová jak se očekává

---

## AKČNÍ BODY 📋

### Pro tebe:
1. **Spust recent regular phase run** (např. posledních 24h)
2. **Zkontroluj výstup** abychom viděli:
   - Kolik error_types se loadilo pro baseline
   - Jestli se vytvořily nové peaky
   - Co se uložilo v registru

3. **Po spuštění se podíváme na:**
   - Obsahuje nový conhecido_peaks.yaml recent data?
   - Jsou tam nové peaky od 28.2 - 2.3?
   - Jaké jsou occurrence countů?

### Čekám na tvůj feedback:
```bash
# Spusť tohle a pošli mi output:
cd /home/jvsete/git/ai-log-analyzer
python3 scripts/regular_phase.py --window 1440 2>&1 | tail -100
```

---

## SHRNUTÍ

| Bod | Status | Akce |
|-----|--------|------|
| 1. Baseline loading | ✅ OK | Žádná akce potřebná |
| 2. Chybí peaks od 27.2 | ⚠️ POTŘEBUJEŠ DATA | Spusť recent run |
| 3. Peak count vs occurrences | ⏳ ČEKÁ NA OVĚŘENÍ | Po spuštění run |
| 4. Email template test | ⏳ PŘIPRAVENO | Po spuštění run |
