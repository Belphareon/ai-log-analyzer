# Changelog

Všechny změny projektu AI Log Analyzer, seřazeno od nejnovějšího.

---

## r64 (2026-03-31) — Trace flow dedup, signal filtering, root cause detection

### Opraveno

- **Trace flow deduplikace** (`scripts/regular_phase.py`)
  - Vylepšená normalizace `_normalize_message_for_dedup()`: nově odstraňuje Java object adresy (`@4f97d62f` → `@<ADDR>`), UUIDs, hex IDs, a zkracuje na 200 znaků
  - Zprávy lišící se jen hex adresou se korektně deduplikují (např. 5× "Step processing failed" → 1 unikátní)

- **Výběr trace kroků** (`scripts/regular_phase.py`)
  - `_select_trace_steps()` nově preferuje high-signal kroky a odfiltruje low-signal (score ≤ 0)
  - Trackuje `_occurrence_count` pro každý deduplikovaný krok
  - Fallback: pokud není dost signal kroků, doplní low-signal (místo všeho)

- **Repetition count zobrazení** (`scripts/regular_phase.py`, `scripts/core/email_notifier.py`)
  - Text i HTML výstup zobrazuje `[x5]` u opakujících se kroků
  - Záhlaví: "N unique messages" místo "N messages"
  - Email notifier: normalizovaná deduplikace (nejen raw string match)

- **Root cause positive patterns** (`scripts/analysis/trace_analysis.py`, `scripts/regular_phase.py`)
  - Přidány nové detekční vzory: `is not filled`, `not all required data`, `required field`, `validation failed`, `invalid value`, `missing field`, `ServiceBusinessException`, `BusinessException`, `NullPointerException`
  - Root cause detekce nyní lépe identifikuje business chyby (např. "Field 'primaryAddress' is not filled")

### Důvod

Alert z 2026-03-31 07:30-07:45 zobrazil 11 trace zpráv místo 5 — duplikáty, low-signal noise.
Skutečný root cause ("Client has not all required data") se ztrácel pod závalem "Step processing failed".

### Změněné soubory

| Soubor | Změna |
|--------|-------|
| `scripts/regular_phase.py` | Normalizace, step selection, signal patterns, occurrence count |
| `scripts/analysis/trace_analysis.py` | Root cause positive patterns (+4 nové skupiny) |
| `scripts/core/email_notifier.py` | Normalized dedup, occurrence count display (text+HTML) |

## r62 (2026-03-26) — Dark mode, ratio rounding, structured behavior v Confluence

### Opraveno

- **Email dark mode** (`scripts/core/email_notifier.py`)
  - Odstraněny hardcoded barvy `#444`, `#666`, `#888` z HTML šablony — v dark mode byly nečitelné
  - Čísla trace kroků nyní zobrazena tučně (`<strong>`)
  - TraceID div používá `opacity: 0.75` místo fixed šedé barvy

- **Peak ratio zaokrouhlení** (`scripts/exports/table_exporter.py`)
  - `peak_ratio` zaokrouhlen na 2 desetinná místa při uložení: `round(float(peak.max_ratio or 0), 2)`
  - Formát v markdown tabulce: `{ratio:.2f}×` (např. `12.45×` místo `422.78057...×`)

- **Structured behavior v Confluence** (`scripts/regular_phase.py`, `scripts/exports/table_exporter.py`)
  - Write-back do `entry.behavior` nyní ukládá strukturovaný text s číslovanými trace kroky,
    inferred root cause a propagation info (stejný formát jako v email digestu)
  - Confluence Errors detail: přidány sekce Root Cause a Behavior (se splitlines zobrazením)
  - Confluence Peaks: přidána nová sekce Peak Details s detaily per peak (apps, NS, behavior)

### Změněné soubory

| Soubor | Změna |
|--------|-------|
| `scripts/core/email_notifier.py` | Dark mode fix, tučná čísla kroků |
| `scripts/exports/table_exporter.py` | ratio rounding, Errors/Peaks detail sekce |
| `scripts/regular_phase.py` | Structured behavior write-back |
| `Dockerfile` | r61 → r62 |

---

## r61 (2026-03-26) — Fix počtů app/NS, strukturovaný behavior v email digestu

### Opraveno

- **Duplicitní počty app a NS** (`scripts/regular_phase.py`)
  - Pokud incident pokrýval N aplikací, každá dostala stejný počet (celkový), místo primárního
  - Oprava: `app_counts[apps[0]] += count` — pouze primární app/NS získá počet;
    ostatní jsou zapsány do `affected_apps` bez duplikace
  - Výsledek: `bl-pcb-v1 (1,240), feapi-pca-v1 (89)` místo `bl-pcb-v1 (1,240), feapi-pca-v1 (1,240)`

- **Strukturovaný behavior v email digestu** (`scripts/core/email_notifier.py`, `scripts/regular_phase.py`)
  - Detail blok v HTML emailu zobrazuje číslované trace kroky s app názvem a zprávou
  - Detekce "same error" (stejná zpráva v jiné app ve stejném trace)
  - Confidence inferred root cause, propagation s typem a délkou trvání
  - Plain-text varianta emailu má identický strukturovaný formát

- **trace_steps vždy předávány** — odstraněna podmínka `if not is_continues`

### Změněné soubory

| Soubor | Změna |
|--------|-------|
| `scripts/regular_phase.py` | Count fix, trace_steps, root_cause confidence, propagation short_string |
| `scripts/core/email_notifier.py` | Strukturovaný HTML + plain-text detail blok |
| `Dockerfile` | r60 → r61 |

---

## r60 (2026-03-25) — Oprava regrese z r57 (NS sloupec, NameError)

### Opraveno

- **NS sloupec obnoven v souhrnné tabulce** (`scripts/core/email_notifier.py`)
  - r57 commit omylem odstranil `<th>NS</th>` z HTML hlavičky a odpovídající `<td>` z řádků
  - Obnoven; zobrazuje pouze jména namespace (bez duplicitních počtů)

- **NameError v plain-text detail bloku** (`scripts/core/email_notifier.py`)
  - Loop odkazoval na nedefinované proměnné `behavior` a `apps_display`
  - Způsoboval pád `send_regular_phase_peak_digest()` a fallback na starší single-alert šablonu
  - Opraveno definováním proměnných před jejich použitím

### Poznámka k r58/r59

r58 a r59 byly testovací builds vytvořené během iterace nad opravou r57 regrese. Neobsahují samostatné změny kódu.

### Změněné soubory

| Soubor | Změna |
|--------|-------|
| `scripts/core/email_notifier.py` | NS sloupec obnoven, NameError opraven |
| `Dockerfile` | r57 → r60 |

---

## v6.2.1 (2026-03-24) - r57 Peak Alerts opravy

### Peak Alerts digest email

- **Opraveny pocty NS a Apps** (`scripts/regular_phase.py`)
  - Pocty erroru se chybne duplikovaly: kdyz 1 incident pokryval N namespaaces/apps, pripisoval se stejny pocet vsem.
  - Oprava: `count_per_ns = count // len(ns_list)`, stejne pro apps. Kazdy NS/app dostane sve proporcionalni cislo.
  - Pridano `app_counts` field do payloadu alertu (dict serazeny podle poctu desc).

- **Trend: pouziva predchozi okno misto historickeho prumeru** (`scripts/regular_phase.py`)
  - Trend se pocital oproti historickemu prumeru vsech minulych vyskytu, coz vedlo k tomu ze 'rising' se temer neobjevovalo.
  - Oprava: Trend porovnava `current_window_errors` vs `last_error_count` z alertovacieho stavu (stavovy soubor).
  - Prvni vyskyt (bez predesleho okna) = 'stable'. Dalsi okno: >=1.2x = rising, <=0.8x = falling.

- **Behavior misto surove message** (`scripts/regular_phase.py`)
  - `detail_message` se plnilo prvni zprávou z trace kroků (surová zprava).
  - Oprava: pouziva `problem.trace_flow_summary` (max 3 kroky: app: zprava) = behavior jak je v Recent Incidents.

- **Email template** (`scripts/core/email_notifier.py`)
  - Odstranen sloupec 'NS (Raw)' z souhrnne tabulky (byl duplicitni s detailem nize).
  - Detail blok: Apps s pocty erroru: `bl-pcb-v1 (1,234), feapi-pca-v1 (567)` misto prostého výčtu.
  - Detail blok: Namespaces serazeny od nejvyssiho poctu, format `pcb-dev-01-app (1,234)`.
  - Prejmenovano 'Message' -> 'Behavior' v detailu alertu (HTML i text).

### Zmenene soubory

| Soubor | Zmena |
|--------|-------|
| `scripts/regular_phase.py` | NS/app count fix, trend, behavior, app_counts payload |
| `scripts/core/email_notifier.py` | Remove NS from table, apps s pocty, Behavior label |
| `Dockerfile` | r56 -> r57 |

---

## v6.2.0 (2026-03-23) - r56 Known Errors + Recent Incidents Quality

### Known Errors Report

- **Category backfill from error_class** (`scripts/exports/table_exporter.py`)
  - 135/346 problemu melo category=unknown. Nova metoda `_backfill_category()` odvodí kategorii z error_class (constraint_violation->business, access_denied->auth, gateway_error->external, atd.)
  - Pridana mapa `_ERROR_CLASS_TO_CATEGORY` s 25 mapovanimi.

- **Behavior sloupec presunut vedle Root Cause** (`scripts/exports/table_exporter.py`)
  - V CSV: `behavior` je nyní hned za `root_cause`, na viditelnem miste.
  - V Markdown tabulce All Problems: pridany sloupce Root Cause, Behavior a Age.
  - Opravena `_problem_behavior()` fallback kaskada: behavior -> trace_flow -> sample_messages -> description (odstraneno neuzitecne error_class/flow).

- **Age status indikator** (`scripts/exports/table_exporter.py`)
  - Nove pole `activity_status` v `ErrorTableRow`: ACTIVE (<7d) / STALE (7-30d) / OLD (>30d).
  - Zobrazeno v tabulce All Problems jako druhy sloupec.

- **Nova klasifikacni pravidla** (`scripts/pipeline/phase_e_classify.py`, `core/problem_registry.py`)
  - phase_e_classify: 6 novych pravidel (constraint_violation, json_deserialization, not_found, illegal_state, upstream_error, gateway_error).
  - problem_registry ERROR_CLASS_PATTERNS: +11 vzoru (ConstraintViolation, MismatchedInput, DataIntegrity, RestClient, atd.).

### Recent Incidents

- **Opraven unknownerror v Problem Key** (`scripts/analysis/problem_aggregator.py`)
  - `_extract_error_class()`: error_type UnknownError/unknown/error uz nevracejí `unknownerror`, ale `unclassified`.
  - Pridana konstanta `_UNKNOWN_ERROR_TYPES` pro centralni spravu.

- **Opraven bl fallback v Problem Key** (`scripts/analysis/problem_aggregator.py`)
  - `_extract_flow()`: kompletne prepsan s PCB-specifickymi vzory (card-servicing, click2pay, design-lifecycle, atd.) a spravnym meaningful-parts fallbackem (skip: bff, bl, feapi, pcb, pca).
  - 'bl' uz nebude v klici.

- **Pocty raw errors k NS a Apps** (`scripts/analysis/problem_aggregator.py`, `scripts/analysis/problem_report.py`)
  - `ProblemAggregate` ma nova pole `app_counts: Dict[str, int]` a `ns_counts: Dict[str, int]`.
  - Sekce Scope zobrazuje: `bl-pcb-v1 (1234), feapi-pca-v1 (567)` misto pouheho vyctu.

- **Orez trace flow messages** (`scripts/analysis/problem_report.py`)
  - Zpravy v trace flow kraceny na max 200 znaku, pridan '...' suffix.

- **Duration citelny format** (`scripts/analysis/problem_report.py`)
  - Pridany helper funkce `_format_duration_sec()` a `_format_duration_ms()`.
  - Time: `(83100s)` -> `(23h 5m 0s)` | `(45s)` -> `(45s)` | `(90s)` -> `(1m 30s)`
  - Propagation Duration: `20121656ms` -> `5h 35m 21s` | `500ms` -> `500ms` | `1500ms` -> `1s 500ms`

### Zmenene soubory

| Soubor | Zmena |
|--------|-------|
| `scripts/analysis/problem_report.py` | Duration helpers, trace msg crop, per-app/ns counts |
| `scripts/analysis/problem_aggregator.py` | unknownerror fix, flow fix, app_counts/ns_counts |
| `scripts/exports/table_exporter.py` | behavior order, MD table, behavior fallback, category backfill, activity_status |
| `scripts/pipeline/phase_e_classify.py` | +6 classification rules |
| `core/problem_registry.py` | +11 ERROR_CLASS_PATTERNS |
| `Dockerfile` | version r55 -> r56 |

---


## r45 (2026-03-06) — Email Template Redesign

- Kompletní redesign HTML email šablony pro peak alerty
- Nový formát subjektu: `ERROR_CLASS | Status | Trend`
- Strukturované sekce: Summary → Error Details → Affected Scope → Root Cause → Behavior → Propagation
- Opravena is_continues logika: peak "continued" jen pokud viděn v PŘEDCHOZÍM okně
- Opravena peak_window_start: nyní správně window_start místo first_seen
- Trend rozdělen na trend_2h a trend_24h

---

## r44 (2026-03-02) — Peak Continuation & Time Window Fixes

- Oprava time window calculation: peak time ranges ukazují aktuální detection window
- Oprava peak continuation logiky: jen peaky z PŘEDCHOZÍHO okna se značí "continued"
- Odstraněn UTC čas z email notifikací (jen CET)
- K8s job manifesty: oprava generateName → name

---

## r43 (2025-11-13) — Known Peaks Export & Root Cause

- Čisté exporty known peaks/errors
- Root cause a behavior tracking
- Dual-window trend analýza
- Known peaks wiki integrace

---

## r42 (2025-10-11) — CET Notifikace & Category Mapping

- CET timezone notifikace
- Continuation summary v alertech
- Peak key alignment
- 3-wave unknown error reduction
- r42b: Trace quality improvements
- r42c: Targeted category mapping pro unknown top signatures

---
## v6.1.2 (2026-03-02) - r41 Peak Detection Logic Fix + Notification Clarity

### Opraveno

- **Per-problem per-namespace spike detekce (`scripts/pipeline/phase_c_detect.py`)**
  - Spike se vyhodnoti pouze pokud count konkretniho fingerprintu v konkretnim namespace
    prekroci Pxx/CAP threshold tohoto namespace.
  - Odstraneno inheritovani peak stavu z jine chyby ve stejnem namespace.
  - Odstraneno duplicitni pricitani pri multi-namespace fingerprintu.
  - `spike_new_error_type` fallback je vypnuty, pokud je aktivni P93/CAP detector.
  - Do evidence je pridany jednoznacny `peak_id` (`SPIKE:<fingerprint>:<namespace>:<window_start>`).

- **Regular peak email readability (`scripts/core/email_notifier.py`, `scripts/regular_phase.py`)**
  - Odebrana `Category` z detailu emailu.
  - Pri `unknownerror` se zobrazi kontext: top `error_type` s pocty.
  - Pridano `Peak Type` (SPIKE/BURST), `Peak Key` a namespace breakdown s pocty.
  - Zjednoduseny vizual: bold/underline, bez barevnych blokovych panelu.

### Provozni konfigurace

- Helm values: `MIN_NAMESPACE_PEAK_VALUE: "1"` (prakticky bez extra absolutniho guardrailu).

---

## v6.1.1 (2026-03-02) - r40 Peak Notification and Counting Fixes

Zamereno na regular-phase peak notifikace, konzistenci threshold labelu a presnost metrik peaku.

### Opraveno

- **Detailed peak email template (`scripts/core/email_notifier.py`)**
  - Pridana metoda `send_regular_phase_peak_alert_detailed()` s HTML/text variantou.
  - Obsahuje pouze data konkretniho peaku: NEW/KNOWN status, time range, category/error_class,
    raw error count, affected apps/namespaces, behavior flow.
  - Root cause + propagation se posilaji pouze pro NEW peak.

- **Peak continuity time range (`scripts/regular_phase.py`)**
  - Pro `KNOWN (continued)` se zacatek intervalu bere z `known_peak.first_seen` zarovnaneho do okna.
  - V notifikaci je tedy skutecny rozsah peaku pres vice cron oken.

- **Known peaks occurrences semantics (`scripts/core/problem_registry.py`)**
  - `occurrences` je nyni pocet vyskytu peaku v case (per 15m bucket), ne soucet incidentu.
  - Pridano `raw_error_count` pro agregaci poctu raw error logu.

- **Peaks export metrics (`scripts/exports/table_exporter.py`)**
  - `peak_count` = raw error count (`raw_error_count`).
  - `occurrence_count` = frekvence vyskytu peaku (`occurrences`).
  - Opraven extraction category z `PEAK:category:flow:peak_type`.

- **Dynamic percentile labels (`scripts/core/calculate_peak_thresholds.py`, `scripts/core/peak_detection.py`)**
  - Textove vystupy uz nejsou hardcoded na `P93`.
  - Labely se odvozuji z `PERCENTILE_LEVEL` (napr. `P94`).

### Zmenene soubory

| Soubor | Zmena |
|--------|-------|
| `scripts/core/email_notifier.py` | Detailed HTML peak notifikace + optional HTML send |
| `scripts/regular_phase.py` | Peak continuity time range pro continued peaky |
| `scripts/core/problem_registry.py` | `raw_error_count`, occurrence counting per window |
| `scripts/exports/table_exporter.py` | Oddeleni `peak_count` vs `occurrence_count` |
| `scripts/core/calculate_peak_thresholds.py` | Dynamicky `Pxx` label ve summary |
| `scripts/core/peak_detection.py` | Dynamicky `Pxx` label v reason stringu |

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

**3. BaselineLoader v Backfillu (`scripts/backfill.py`)**
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
| `scripts/backfill.py` | Pridan BaselineLoader import a pouziti |
| `scripts/core/baseline_loader.py` | Odstranen anomaly-only SQL filtr |
| `scripts/pipeline/phase_b_measure.py` | Odstranen duplicitni kod |

---

## v6.0.5 (2026-02-19) - Peak Detection Fix

Oprava detekce peaku v regular phase implementaci BaselineLoader.

### Opraveno

- **BaselineLoader** - Novy modul `scripts/core/baseline_loader.py` pro nacteni historickych baseline dat z DB
- **Phase B integrace** - `phase_b_measure.py` nyni kombinuje historicke + aktualni rates pro EWMA vypocet
- **Regular phase integrace** - `regular_phase.py` nacita 7-denni historii pred spustenim pipeline
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
