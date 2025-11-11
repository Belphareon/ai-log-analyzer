# TODO List - AI Log Analyzer Report Generation

## ✅ HOTOVO:
- [x] Fetch data pro Nov 4-10 (7 dní)
- [x] Vytvořit fetch_errors.py a analyze_daily.py
- [x] Dokumentace README_SCRIPTS.md

## 📋 AKTUÁLNÍ ÚKOLY (v pořadí):

### 1. DOKONČIT SOUČASNÝ REPORT (Nov 4-10)
- [ ] **1.1** Vygenerovat denní reporty (7 reportů) - BĚŽÍ
- [ ] **1.2** Vytvořit týdenní summary report
- [ ] **1.3** Ukázat výsledky uživateli

### 2. VYLEPŠIT COVERAGE (75% pro daily, 95% pro 15-min)
- [ ] **2.1** Vytvořit script pro zjištění celkového počtu errorů
- [ ] **2.2** Automaticky vypočítat potřebný sample size pro 75% coverage
- [ ] **2.3** Re-fetch dny s nízkým coverage (Nov 9, 10 mají < 30%)
- [ ] **2.4** Připravit logiku pro 15-minutové běhy (95%+ coverage)

### 3. ROZŠÍŘIT ČASOVÉ OBDOBÍ
- [ ] **3.1** Zjistit nejstarší dostupná data v ES (říká user: od 30.10.)
- [ ] **3.2** Fetch Oct 30, 31, Nov 1, 2, 3
- [ ] **3.3** Vytvořit kompletní 2-týdenní report

### 4. CLEANUP /tmp/
- [ ] **4.1** Projít /tmp/ a identifikovat užitečné vs obsolete soubory
- [ ] **4.2** Přesunout užitečné soubory do repo (reports/, data/)
- [ ] **4.3** Smazat obsolete dočasné soubory
- [ ] **4.4** Commit a push užitečných souborů

## 🎯 POZNÁMKY:
- Coverage metrics z current fetch:
  - Nov 4: 47.4% ✅ (ok)
  - Nov 5: 54.8% ✅ (ok) 
  - Nov 6: 32.9% ⚠️ (re-fetch s větším sample)
  - Nov 7: 59.3% ✅ (ok)
  - Nov 8: 51.8% ✅ (ok)
  - Nov 9: 28.7% ⚠️ (re-fetch)
  - Nov 10: 22.6% ❌ (re-fetch s mnohem větším sample!)

- Nov 10 má 147M soubor → pravděpodobně > 200k errors → potřeba 150k+ sample

## 🚫 CO NEDĚLAT:
- ❌ Nezačínat sbírat data znovu dokud nedokončím reporty
- ❌ Nepřeskakovat kroky
- ❌ Nedělat víc věcí najednou
