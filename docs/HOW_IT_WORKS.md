# Jak to funguje — AI Log Analyzer

Detailní popis celého procesu: od načtení logů přes detekci anomálií až po odeslání notifikace.

---

## Obsah

1. [Spouštění a životní cyklus](#1-spouštění-a-životní-cyklus)
2. [Načítání logů z Elasticsearch](#2-načítání-logů-z-elasticsearch)
3. [Fingerprinting a normalizace](#3-fingerprinting-a-normalizace)
4. [Měření a baseline](#4-měření-a-baseline)
5. [Detekce anomálií — Pxx/CAP a cause-family gate](#5-detekce-anomálií--pxxcap-a-cause-family-gate)
6. [Ostatní detekční pravidla](#6-ostatní-detekční-pravidla)
7. [Skórování (0–100)](#7-skórování-0100)
8. [Klasifikace](#8-klasifikace)
9. [Registry — nové vs. známé problémy](#9-registry--nové-vs-známé-problémy)
10. [Incident Analysis](#10-incident-analysis)
11. [Rozhodování o alertu](#11-rozhodování-o-alertu)
12. [Email digest](#12-email-digest)
13. [Confluence export](#13-confluence-export)
14. [Write-back — zpětné obohacení dat](#14-write-back--zpětné-obohacení-dat)
15. [Backfill](#15-backfill)
16. [Přepočet thresholdů](#16-přepočet-thresholdů)

---

## 1. Spouštění a životní cyklus

Program `scripts/regular_phase.py` se spouští každých 15 minut jako Kubernetes CronJob.

Při každém spuštění proběhne tento cyklus:

```
 1. Načti konfiguraci (namespaces.yaml, .env)
 2. Načti YAML registry (known_problems, known_peaks, fingerprint_index)
 3. Načti stav alertů (alert_state_regular_phase.json)
 4. Načti historický baseline z DB (posledních 7 dní)
 5. Stáhni logy z Elasticsearch za aktuální okno (15 min)
 6. Spusť Detection Pipeline (fáze A→F) pro každý namespace
 7. Spusť Incident Analysis
 8. Ulož výsledky do DB (complete facts, peak_investigation)
 9. Ulož/aktualizuj YAML registry
10. Rozhodni, zda odeslat alert
11. Pokud ano — odešli email digest
```

---

## 2. Načítání logů z Elasticsearch

Modul `scripts/core/fetch_unlimited.py` načte **všechny** logy za aktuální 15min okno.

- Standardní ES limit 10 000 výsledků je obejit pomocí **stránkování přes `search_after`**
- Logy jsou filtrovány na sledované namespace (seznam z `config/namespaces.yaml`)
- Dotaz cílí na index `ES_INDEX` (např. `cluster-app_pcb-*`) — konfigurováno v `.env`
- Regular phase předá každou stránku okamžitě do `StreamingAggregator`; celý seznam raw JSON dokumentů se v RAM nevytváří
- Přesné per-fingerprint, aplikační, namespace a trace počty se agregují průběžně; detailní trace eventy se ukládají do dočasné SQLite databáze
- Streaming režim nepoužívá fetch cap k ořezání vstupu. Paměť proto neroste s počtem opakovaných zpráv, ale s počtem unikátních fingerprintů a trace ID
- Limity `TRACE_TIMELINE_MAX_EVENTS_PER_TRACE` a `TRACE_TIMELINE_MAX_TOTAL_EVENTS` chrání pouze volitelný detail reprezentativních trace timelines; neomezují počty ani peak detekci

---

## 3. Fingerprinting a normalizace

**Fáze A** (`phase_a_parse.py`) zpracuje každý raw log záznam:

### Co se extrahuje

| Pole | Zdroj v ES dokumentu |
|------|------|
| `namespace` | `kubernetes.namespace_name` |
| `app_name` | `kubernetes.labels.app` nebo `deployment_label` |
| `error_type` | `error_type`, `exception.type`, nebo odvozeno |
| `message` | `message` (raw) |
| `trace_id` | `traceId`, `trace.id` |
| `environment` | z namespace prefixu (dev/sit/uat/prod) |

### Normalizace message

Dynamické hodnoty se před fingerprinting nahradí zástupnými tokeny:
- `card_id=12345678` → `card_id=<NUM>`
- `traceId=abc-def-123` → `traceId=<UUID>`
- `192.168.1.1` → `<IP>`

Tím dostane stejný typ chyby stejný fingerprint bez ohledu na konkrétní data.

### Výpočet fingerprint

```python
fingerprint = MD5(f"{error_type}:{normalized_message}")[:16]
```

Fingerprint identifikuje **typ problému**, ne konkrétní výskyt.

---

## 4. Měření a baseline

**Fáze B** (`phase_b_measure.py`) vypočítá statistiky pro každý fingerprint:

### Baseline

- Načítá se z authoritative complete facts (`ailog_peak.v_complete_error_kind_counts`) — posledních 7 dní
- Baseline = EWMA (exponenciálně vážený klouzavý průměr, alfa default 0.3)
- Odráží, kolik chyb tohoto typu bylo *obvyklé* v tomto namespace v tuto dobu

### EWMA a MAD — informativní metriky

EWMA a MAD se **NEPOUŽÍVAJÍ pro spike detekci** (viz důvody níže). Zůstávají v Phase B jako informativní metriky:

- `trend_ratio` = `current_rate / baseline_ewma` → indikuje trend
- `trend_direction` = "increasing" / "stable" / "decreasing"
- `baseline_ewma` = exponenciálně vážený průměr historických rates
- `baseline_mad` = medián absolutních odchylek

Tyto metriky se ukládají do DB (`peak_investigation`) a používají v Phase D pro bonus scoring (`trend_ratio > 2.0` přidává body).

**Proč ne EWMA pro spike detekci:**
- EWMA produkuje více false positives než percentile gate
- EWMA se adaptuje na vysoké hodnoty a pak missí reálné peaky
- MAD test generuje masivní false positives u nízkých hodnot

---

## 5. Detekce anomálií — Pxx/CAP a cause-family gate

**Fáze C** (`phase_c_detect.py`) rozhoduje, zda je aktuální počet chyb anomální.

### Pxx/CAP metodika

Spike detekce má dvě samostatné podmínky. Namespace volume gate odpovídá na otázku, zda je celkový ERROR provoz neobvyklý; cause-family gate určuje, která konkrétní family smí spike vlastnit.

```
namespace_peak = (namespace_total > effective_Pxx_per_DOW) OR (namespace_total > CAP)
family_peak = contribution > max(20, median(namespace/fingerprint history) + 6 * 1.4826 * MAD)
is_spike = namespace_peak AND family_peak
```

**Pxx** = uživatelem zvolený percentil `PERCENTILE_LEVEL` historických aktivních 15min oken pro danou kombinaci `(namespace, day_of_week)`. Jeho efektivní hodnota je chráněna před opakovanou kontaminací incidenty:

```
effective_Pxx = min(configured_Pxx, median + 6 * 1.4826 * MAD)
```

Konfigurovaný Pxx zůstává hlavním ovladačem citlivosti. Robustní cap jej pouze sníží, když by opakované extrémní incidenty zvýšily práh natolik, že by se další incident ztratil.

**CAP** = `(median_Pxx + avg_Pxx) / 2` přes všechny dny týdne pro daný namespace.
- Záložní práh, pokud pro konkrétní den není dostatek historických dat.

**Cause-family gate** používá hustou, zero-inclusive sedmidenní historii stejného `(namespace, fingerprint)`. Family s historií musí překročit vlastní robustní práh. Nová family bez historie smí vlastnit namespace peak až od `new_error_min_count` (výchozí `50`). Pokud se authoritative family baseline nenačte, peak se fail-closed nepřiřadí žádné family.

### Jak to funguje v pipeline

1. **`detect_batch()`** agreguje total error count per namespace a contribution každého fingerprintu.
2. **`PeakDetector.is_peak()`** zkontroluje každý namespace proti efektivnímu Pxx/CAP ze kompatibilního snapshotu.
3. **`_fingerprint_peak_gate()`** porovná contribution s historií stejného `(namespace, fingerprint)`.
4. **`_detect_spike()`** označí pouze vítěznou kvalifikovanou family jako `is_spike=True`.

### Příklad

```
Namespace: pcb-sit-01-app, Pondělí
Effective P98 threshold: 360 errors/window
CAP threshold: 373 errors/window
Aktuální celkový count: 487 errors
Cause family contribution: 200 errors
Family threshold: 20 errors

487 > 360 (P98) a 200 > 20 → SPIKE (triggered_by=percentile)
```

### Jak se thresholdy počítají

```
Regular phase a backfill
  └─ ukládají úplná 15-min fakta

calculate_peak_thresholds.py (týdně)
  └─ čte complete namespace facts
  └─ počítá robustní Pxx per (namespace, DOW)
  └─ počítá CAP per namespace
  └─ ukládá → peak_thresholds + peak_threshold_caps

Pipeline (Phase C)
  └─ PeakDetector čte thresholdy z DB
  └─ porovnává aktuální namespace total vs Pxx/CAP a family contribution vs namespace/fingerprint historii
```

### DB tabulky pro spike detekci

| Tabulka | Účel | Kdo plní |
|---------|------|----------|
| `v_complete_namespace_error_counts` | Complete 15-min namespace facts | authoritative complete runs |
| `peak_thresholds` | Robust Pxx per (namespace, DOW) | calculate_peak_thresholds.py |
| `peak_threshold_caps` | CAP per namespace | calculate_peak_thresholds.py |
| `v_complete_error_kind_counts` | Zero-inclusive namespace/fingerprint facts | authoritative complete runs |

### Nová cause family

Nová `(namespace, fingerprint)` family bez historie může vlastnit namespace peak až od `new_error_min_count`:
```
namespace_peak AND contribution >= new_error_min_count
```

### Fail-closed baseline

Pokud nelze načíst kompatibilní DB threshold snapshot nebo authoritative namespace/fingerprint baseline, regular phase i backfill skončí s chybou. EWMA se pro spike rozhodování nepoužívá jako fallback.

---

## 6. Ostatní detekční pravidla

| Flag | Pravidlo | Popis |
|------|----------|-------|
| `is_burst` | Sliding window (60s), `max_count / avg_count > 5.0` | Náhlá lokální koncentrace chyb |
| `is_new` | Fingerprint/problem_key není v registry + count ≥ min | Nový typ chyby, dosud neviděný |
| `is_regression` | Fingerprint byl znám, zobrazoval se < lookback_min | Regrese — chyba se vrátila |
| `is_cross_namespace` | Fingerprint ve ≥ 2 namespace | Problém se šíří přes více prostředí |
| `is_silence` | `current_rate == 0 AND baseline_ewma > 5` | Očekávaný error se neobjevil |

---

## 7. Skórování (0–100)

**Fáze D** (`phase_d_score.py`) vypočítá numerické skóre:

```
score = min(count / 10, 30)     # základní skóre z počtu chyb (max 30)
      + 25 if is_spike
      + 20 if is_burst
      + 15 if is_new
      + 35 if is_regression
      + 20 if is_cascade
      + 15 if is_cross_namespace
      + (trend_ratio - 2.0) * 2.0    # bonus za trend nad 2.0×
      + (namespace_count - 2) * 3.0  # bonus za každý NS nad 2
```

Skóre je **deterministické** — stejný vstup vždy dá stejný výstup.

| Score | Severity |
|------:|----------|
| ≥ 80  | critical |
| ≥ 60  | high     |
| ≥ 40  | medium   |
| ≥ 20  | low      |
| < 20  | info     |

---

## 8. Klasifikace

**Fáze E** (`phase_e_classify.py`) přiřadí každému incidentu **kategorii** a **subcategory** pomocí regexových pravidel seřazených dle priority.

Kategorie: `MEMORY`, `DATABASE`, `NETWORK`, `AUTH`, `BUSINESS`, `INTEGRATION`, `CONFIGURATION`, `INFRASTRUCTURE`, `UNKNOWN`

---

## 9. Registry — nové vs. známé problémy

Problem Registry (`scripts/core/problem_registry.py`) zajišťuje identifikaci:

- **Nový problém**: fingerprint dosud neviděný → vytvoří se nový záznam, `is_new=True`
- **Známý problém**: fingerprint nalezen → aktualizuje se `last_seen`, `occurrences`, behavior, root_cause

Registry soubory (`registry/`) jsou append-only — nikdy se z nich nemaže.

---

## 10. Incident Analysis

Vrstva `incident_analysis/` poskytuje kauzální analýzu:

1. **TimelineBuilder** — sestaví chronologickou osu: kdy se co objevilo a v jakém pořadí
2. **ScopeBuilder + Propagation** — identifikuje root_apps, downstream_apps, detekuje propagaci
3. **CausalInferenceEngine** — deterministicky inferuje kořenovou příčinu z trace kroků (žádné ML)
4. **FixRecommender** — generuje konkrétní doporučené akce pro SRE

Report jasně odděluje **FACTS** (co se stalo) od **HYPOTHESIS** (možná příčina).

---

## 11. Rozhodování o alertu

Regular phase rozhoduje, zda odeslat notifikaci:

| Podmínka | Hodnota (default) | Popis |
|----------|--------------------|-------|
| `ALERT_COOLDOWN_MIN` | 45 | Min. interval mezi alerty pro stejný peak |
| `ALERT_HEARTBEAT_MIN` | 120 | Opakovaný alert i pro pokračující peak |
| `ALERT_MIN_DELTA_PCT` | 30 | Min. změna error_count pro znovu-odeslání |
| `MAX_PEAK_ALERTS_PER_WINDOW` | 3 | Max. počet peaků v jednom digest emailu |
| `ALERT_CONTINUATION_LOOKBACK_MIN` | 60 | Lookback pro detekci pokračujícího peaku |

Continuation: peak detekovaný v předchozím okně se považuje za pokračující. Potlačuje se, pokud nedošlo k materiální změně.

### Workflow lifecycle větev

Před ERROR fetch se volitelně spustí nezávislý probe raw INFO zpráv pro queue processing, blocking predecessor, návrat `PROCESSING -> REGISTERED` bez delay a completion predecessorů. Kandidátní scope se načítají přes PIT/search_after a každý root/predecessor query se počítá do completeness ledgeru.

`LIFECYCLE_ANALYSIS_ENABLED` a `LIFECYCLE_ALERT_ENABLED` jsou defaultně `false`. Alert je možný jen po úplném fetchi, high-confidence detekci a commitnutém `workflow_lifecycle_runs` záznamu. Probe cap, evidence cap, timeout nebo chybný fetch vytvoří pouze partial auditní run a žádný alert.

---

## 12. Email digest

Když jsou peaky k odeslání, `send_regular_phase_peak_digest()`:

1. **Souhrn** — raw ERROR logy, detekované peak problémy, počet unikátních aplikací a namespaces a počet odeslaných alertů
2. **Summary tabulka** — všechny odeslané alerty (error_class, type, status, NS, trend, count)
3. **Detail bloky** — různé logové projevy stejné události se korelují podle trace nebo konkrétního cause + shodného scope; aliasní zprávy se nezapočítávají vícekrát
4. **Behavior** — reprezentativní deduplikované message patterny s počtem eventů
5. **Inferred root cause** — s confidence labelem
6. **Propagation info** — počet services, typ propagace, délka trvání

Subject: `AI Log Analyzer | HH:MM - HH:MM | D.M.YYYY`

---

## 13. Confluence export

`table_exporter.py` generuje tabulky pro Confluence:

- **Known Errors** — `ErrorTableRow` s kategoriemi, root cause, behavior, activity status
- **Known Peaks** — `PeakTableRow` s peak_count, peak_ratio, occurrences, first/last seen, Peak Details

---

## 14. Write-back — zpětné obohacení dat

Regular phase po analýze zapíše zpět do registry:
- `entry.behavior` — strukturovaný text s trace kroky, root cause, propagation
- `entry.root_cause` — inferred root cause text

Toto obohacení se pak zobrazí v Confluence tabulkách.

---

## 15. Backfill

`scripts/backfill.py` zpracovává historická data:

```bash
# Zpracovat posledních 7 dní
python3 scripts/backfill.py --days 7

# Zpracovat konkrétní období
python3 scripts/backfill.py --from "2026-02-01" --to "2026-02-14" --workers 4
```

Pro každý den: fetch 24h dat po 15min oknech → pipeline → DB save → registry update.
Na konci: daily report + Teams notifikace.

---

## 16. Přepočet thresholdů

`scripts/core/calculate_peak_thresholds.py` přepočítá robustní Pxx/CAP z complete namespace facts:

```bash
# Přepočítat z posledních 4 týdnů
python3 scripts/core/calculate_peak_thresholds.py --weeks 4

# Dry-run (jen zobrazí, neuloží)
python3 scripts/core/calculate_peak_thresholds.py --weeks 4 --dry-run
```

V K8s běží automaticky jako CronJob `log-analyzer-thresholds` každou neděli 03:00 UTC.

### Edge cases

- **Nový namespace** (bez thresholdů): PeakDetector použije CAP (pokud existuje pro jiný DOW) nebo `default_threshold` (100)
- **Málo dat** (< 7 dní): Pxx bude méně přesný; CAP z kompatibilního snapshotu slouží jako namespace fallback
- **Víkend vs pracovní den**: thresholdy se liší per day_of_week
