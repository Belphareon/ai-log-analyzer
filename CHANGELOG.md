# Changelog

Veskere zmeny projektu AI Log Analyzer, serazeno od nejnovejsiho.

---

## v6.1.0 (2026-02-25) - Detection Pipeline Fixes

Analyza a oprava 5 kritickych problemu v detekci peaku a baseline vypoctu.

### Opraveno

**1. Peak Fingerprint Indexing (`core/problem_registry.py`)**
- Registry mel 42 znamych peaku, ale jejich fingerprinty nebyly indexovane
- Metoda `load()` indexovala pouze problem fingerprinty, ne peak fingerprinty
- Fix: Po nacteni peaku se jejich fingerprinty pridavaji do `self.fingerprint_index`
- Dopad: Phase C nyni spravne rozpozna zname peaky

**2. Known Peak Matching (`core/problem_registry.py`)**
- `is_problem_key_known()` kontrolovala pouze `self.problems`, ne `self.peaks`
- Navic format klicu se lisil: detekce generuje `CATEGORY:flow:error_class`, peaky pouzivaji `PEAK:category:flow:peak_type`
- Fix: Metoda ted kontroluje i `self.peaks` a provadi cross-format matching
- Dopad: Zname peaky uz nejsou oznacovany jako NEW

**3. BaselineLoader v Backfillu (`scripts/backfill_v6.py`)**
- Regular phase mel BaselineLoader implementovany (od v6.0.5), ale backfill ne
- Backfill pocital baseline pouze z aktualniho dne (max 96 oken)
- Pro nove error_type: baseline = 0 = spatna detekce
- Fix: Pridan import BaselineLoader a nacteni 7-denni historie pred pipeline.run()
- Dopad: Konzistentni detekce mezi backfill a regular phase

**4. BaselineLoader SQL Query Bias (`scripts/core/baseline_loader.py`)**
- SQL dotaz mel filtr `AND (is_spike OR is_burst OR score >= 30)` - nacital POUZE anomalni data
- Baseline pocitany z anomalnich dat je zkresleny (prilis vysoky)
- Fix: Odstranen filtr, nahrazen `AND reference_value IS NOT NULL`
- Dopad: Baseline nyni odpovida realnym hodnotam

**5. Duplicitni kod v Phase B (`scripts/pipeline/phase_b_measure.py`)**
- Funkce `progress_iter()` a importy byly v souboru dvakrat
- Druha kopie prepisovala prvni a nemela parametr `disable`
- Fix: Odstraneny duplicitni radky

### Zmenene soubory

| Soubor | Zmena |
|--------|-------|
| `core/problem_registry.py` | Peak fingerprint indexing + is_problem_key_known() rozsireni |
| `scripts/backfill_v6.py` | Pridan BaselineLoader import a pouziti |
| `scripts/core/baseline_loader.py` | Odstranen anomaly-only SQL filtr |
| `scripts/pipeline/phase_b_measure.py` | Odstranen duplicitni kod |

---

## v6.0.5 (2026-02-19) - Peak Detection Fix

Oprava detekce peaku v regular phase implementaci BaselineLoader.

### Opraveno

- **BaselineLoader** - Novy modul `scripts/core/baseline_loader.py` pro nacteni historickych baseline dat z DB
- **Phase B integrace** - `phase_b_measure.py` nyni kombinuje historicke + aktualni rates pro EWMA vypocet
- **Regular phase integrace** - `regular_phase_v6.py` nacita 7-denni historii pred spustenim pipeline
- **CSV Export opravy** - Opraveny reference na neexistujici pole v `table_exporter.py`:
  - `problem.root_cause` -> `problem.description`
  - `row.occurrences` -> `row.occurrence_total`
  - Odstraneny reference na `last_seen_days_ago` a `app_versions`

### Dopad
- Baseline nyni pouziva 600+ samplu misto 1
- Detekce peaku v regular phase plne funkcni
- Vsechny export formaty (CSV, MD, JSON) funguji

---

## v6.0.4 (2026-02-10) - DB Writing Fix

Oprava zapisu do PostgreSQL databaze.

### Opraveno

- **SET ROLE** - Obnoveny `set_db_role()` volani v backfill i regular phase
- **K8s Secrets** - `DB_DDL_USER`/`DB_DDL_PASSWORD` nyni mapuji na spravny DDL ucet
- **Dockerfile** - Aktualizovan na r9 (v6.0.5)

### Klicove zjisteni
Pro zapis do DB je nutna sekvence:
1. Pripojit se jako `ailog_analyzer_ddl_user_d1`
2. `SET ROLE role_ailog_analyzer_ddl`
3. Teprve pak INSERT/UPDATE operace

---

## v6.0.3 (2026-02-09) - Integrace a Notifikace

Kompletni notification a reporting pipeline.

### Pridano

- **Teams notifikace** - Backfill (statistiky) + Regular phase (kriticke alerty)
- **Confluence publisher** - CSV -> HTML tabulky s severity barvami
- **Daily report generator** - Top 5-10 problemu ve formatu MessageCard
- **Orchestracni skript** - `publish_daily_reports.sh`
- **CronJob dokumentace** - Backfill 02:00, Regular 15min

### Opraveno

- DB DDL user login pro INSERT operace
- PeakEntry.category chyba v exportech

---

## v6.0.0 (2026-01-26) - V6 Architecture

Kompletni prepis architektury na problem-centric pristup.

### Hlavni zmeny

- **Dvouurovnova identita**: Problem (stabilni, malo zaznamu) + Fingerprint Index (technicky, hodne zaznamu)
- **Problem Key format**: `CATEGORY:flow:error_class` (napr. `BUSINESS:card_servicing:validation_error`)
- **Peak Key format**: `PEAK:category:flow:peak_type` (napr. `PEAK:unknown:card_servicing:burst`)
- **Append-only registry** - Nikdy se nemaze, pouze pridava a aktualizuje
- **Event timestamps** misto run timestamps
- **Registry se nacita pred pipeline** - Phase C ma pristup ke znamym fingerprintum

### Opraveno z V5

- Duplicity v DB (backfill ukladal data opakovane)
- Registry lookup nefungoval (vse oznaceno jako NEW)
- known_peaks.yaml prazdne
- Chybejici detaily k errorům
- Verze aplikace = "v1" (deployment label)
- first_seen = last_seen (timestamp behu scriptu)
- Script neukoncil po reportu

---

## v5.3.1 - Scope a Propagation

- **Oddeleni Scope a Propagation** - Samostatne dataclasses misto smichani v IncidentScope
- **Report generace** - Generuje se VZDY (i bez incidentu)
- **Append-only Registry** - known_errors.yaml/md, known_peaks.yaml/md

---

## v5.3 - Strukturovane role

- **Role aplikaci**: root_apps, downstream_apps, collateral_apps
- **Propagation tracking**: propagated, propagation_time_sec, propagation_path
- **Context-aware actions**: ruzne akce podle typu incidentu
- **Semver sorting**: 1.10.0 > 1.9.0

---

## v5.2

- Fingerprint = `category|subcategory|normalized_message`
- Baseline = None pro 15min mode
- Grouping podle mode (15min vs daily)
- Priority prepocet po knowledge matching

---

## v5.1

- Priority system (P1-P4)
- IMMEDIATE ACTIONS (1-3 kroky pro SRE)
- FACT vs HYPOTHESIS oddeleni
