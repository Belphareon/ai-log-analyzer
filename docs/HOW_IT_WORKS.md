# Jak to funguje — AI Log Analyzer

Detailní popis celého procesu: od načtení logů přes detekci anomálií až po odeslání notifikace.

---

## Obsah

1. [Spouštění a životní cyklus](#1-spouštění-a-životní-cyklus)
2. [Načítání logů z Elasticsearch](#2-načítání-logů-z-elasticsearch)
3. [Fingerprinting a normalizace](#3-fingerprinting-a-normalizace)
4. [Měření a baseline](#4-měření-a-baseline)
5. [Detekce anomálií — P93/CAP](#5-detekce-anomálií--p93cap)
6. [Skórování (0–100)](#6-skórování-0100)
7. [Klasifikace](#7-klasifikace)
8. [Registry — nové vs. známé problémy](#8-registry--nové-vs-známé-problémy)
9. [Incident Analysis](#9-incident-analysis)
10. [Rozhodování o alertu](#10-rozhodování-o-alertu)
11. [Email digest](#11-email-digest)
12. [Confluence export](#12-confluence-export)
13. [Write-back — zpětné obohacení dat](#13-write-back--zpětné-obohacení-dat)
14. [Backfill](#14-backfill)
15. [Přepočet thresholdů](#15-přepočet-thresholdů)

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
8. Ulož výsledky do DB (peak_raw_data, peak_investigation)
9. Ulož/aktualizuj YAML registry
10. Rozhodni, zda odeslat alert
11. Pokud ano — odešli email digest
```

---

## 2. Načítání logů z Elasticsearch

Modul `scripts/core/fetch_unlimited.py` stáhne **všechny** logy za aktuální 15min okno.

- Standardní ES limit 10 000 výsledků je obejit pomocí **stránkování přes `search_after`**
- Logy jsou filtrovány na sledované namespace (seznam z `config/namespaces.yaml`)
- Dotaz cílí na index `ES_INDEX` (např. `cluster-app_pcb-*`) — konfigurováno v `.env`
- Výsledek: seznam raw JSON dokumentů z ES

---

## 3. Fingerprinting a normalizace

**Fáze A** (`phase_a_parse.py`) zpracuje každý raw log záznam:

### Co se extrahuje

| Pole           | Zdroj v ES dokumentu                              |
|----------------|---------------------------------------------------|
| `namespace`    | `kubernetes.namespace_name`                       |
| `app_name`     | `kubernetes.labels.app` nebo `deployment_label`   |
| `error_type`   | `error_type`, `exception.type`, nebo odvozeno     |
| `message`      | `message` (raw)                                   |
| `trace_id`     | `traceId`, `trace.id`                             |
| `environment`  | z namespace prefixu (dev/sit/uat/prod)            |

### Normalizace message

Dynamické hodnoty (ID, čísla, IP adresy, UUID) se před fingerprinting nahradí zástupnými tokeny:
- `card_id=12345678` → `card_id=<NUM>`
- `traceId=abc-def-123` → `traceId=<UUID>`
- `192.168.1.1` → `<IP>`

Tím dostane stejný typ chyby stejný fingerprint bez ohledu na konkrétní data.

### Výpočet fingerprint

```python
fingerprint = MD5(f"{error_type}:{normalized_message}")[:16]
```

Příklad:
```
error_type    = "ValidationException"
normalized    = "card number invalid, card_id=<NUM>"
fingerprint   = "a1b2c3d4e5f6a7b8"
```

Fingerprint identifikuje **typ problému**, ne konkrétní výskyt.

---

## 4. Měření a baseline

**Fáze B** (`phase_b_measure.py`) vypočítá statistiky pro každý fingerprint v každém namespace:

### Baseline

- Načítá se z DB (`ailog_peak.peak_raw_data`) — posledních 7 dní
- Baseline = EWMA (exponenciálně vážený klouzavý průměr, alfa default 0.3)
- Odráží, kolik chyb tohoto typu bylo *obvyklé* v tomto namespace v tuto dobu

### Trend ratio

```
trend_ratio = current_count / baseline
```

Pokud `trend_ratio > 3.0` — výrazný nárůst oproti normálu (threshold konfigurovatelný).

---

## 5. Detekce anomálií — P93/CAP

**Fáze C** (`phase_c_detect.py`) rozhoduje, zda je aktuální počet chyb anomální.

### P93/CAP metodika

Pro každý namespace a každý den v týdnu je spočítán **P93 threshold**:

```
is_spike = (current_count > P93_pro_tento_den_v_týdnu)
        OR (current_count > CAP_pro_tento_namespace)
```

**P93** = 93. percentil historických hodnot pro danou kombinaci `(namespace, day_of_week)`.
- Tzn. pokud je v pondělí v `pcb-sit-01-app` obvyklých maximálně 500 chyb, P93 = 500.
- Výskyt 600 chyb = spike.

**CAP** = `(median_P93 + avg_P93) / 2` přes všechny dny týdne pro daný namespace.
- Slouží jako záložní práh, pokud pro konkrétní den není dostatek historických dat.

### Jak se thresholdy počítají

1. Každý regular_phase běh uloží aktuální počty do `ailog_peak.peak_raw_data`
2. Příkaz `calculate_peak_thresholds.py` z těchto dat spočítá P93/CAP a uloží do `ailog_peak.peak_thresholds` a `ailog_peak.peak_threshold_caps`
3. Při detekci se thresholdy načtou z DB

Pro nový namespace (bez dat) je spike detekce neaktivní; P93/CAP jsou NULL a systém spadne na fallback (poměr vůči baseline).

### Ostatní detekční flagy

| Flag | Podmínka | Popis |
|------|----------|-------|
| `is_burst` | rate change > 5.0× | Náhlý nárůst v krátkém okně, i bez překročení P93 |
| `is_new` | fingerprint není v registry + count ≥ min | Nový typ chyby, dosud neviděný |
| `is_regression` | fingerprint byl znám, zobrazoval se < lookback_min | Regrese — chyba se vrátila |
| `is_cross_namespace` | fingerprint ve ≥ 2 namespace | Problém se šíří přes více prostředí |

---

## 6. Skórování (0–100)

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

### Severity mapping

| Score | Severity |
|------:|----------|
| ≥ 80  | 🔴 critical |
| ≥ 60  | 🟠 high |
| ≥ 40  | 🟡 medium |
| ≥ 20  | 🔵 low |
| < 20  | ⚪ info |

---

## 7. Klasifikace

**Fáze E** (`phase_e_classify.py`) přiřadí každému incidentu **kategorii** a **subcategory** pomocí regexových pravidel.

Pravidla jsou seřazena dle priority (vyšší = důležitější). Příklady:

```python
# Databázové chyby
ClassificationRule(
    category=DATABASE, subcategory="deadlock",
    patterns=[r'deadlock', r'Deadlock', r'lock timeout']
)

# Autentizace
ClassificationRule(
    category=AUTH, subcategory="token_expired",
    patterns=[r'token.expired', r'JWT.*expired', r'TokenExpired']
)
```

Pokud žádné pravidlo nesedí, kategorie je `UNKNOWN`.

Pravidla lze rozšiřovat přidáním do `DEFAULT_RULES` v `phase_e_classify.py` nebo `ERROR_CLASS_PATTERNS` v `core/problem_registry.py`.

---

## 8. Registry — nové vs. známé problémy

`core/problem_registry.py` udržuje dvouúrovňovou identitu:

### Jak funguje lookup

Před spuštěním pipeline se načte celý registr (`registry/known_problems.yaml`, `registry/known_peaks.yaml`) a sestaví se **in-memory fingerprint index**:

```
fingerprint_index: Dict[fingerprint, problem_key]
```

Fáze C se pak při detekci zeptá: **je tento fingerprint v indexu?**
- ✅ Ano → `is_new = False`, problém je KNOWN, aktualizuje se `last_seen` a `occurrences`
- ❌ Ne → `is_new = True`, vytvoří se nový záznam s `id: KP-XXXXXX`

### Problem Key

Skupinový identifikátor problémů ve formátu `CATEGORY:flow:error_class`:
- `BUSINESS:card_servicing:validation_error`
- `AUTH:pca:unauthorized`

Jeden problem_key může mít desítky fingerprintů (různé konkrétní zprávy, ale stejný typ problému).

**Flow** se extrahuje z názvu aplikace — např.:
- `bff-pcb-ch-card-servicing-v1` → `card_servicing`
- `bl-pcb-billing-v1` → `billing`
- Pro nerozpoznanou aplikaci fallback na prefix namespace nebo `unknown`

### Zápis do registry

Po každém běhu se registry **přepíše na disk** (atomic write):
1. Nové záznamy se přidají
2. Existující záznamy se aktualizují (`last_seen`, `occurrences`, `behavior`)
3. Záznamy se **nikdy nemažou** — registry je append-only

---

## 9. Incident Analysis

`incident_analysis/analyzer.py` zpracuje výsledky pipeline a sestaví strukturovanou analýzu:

1. **Timeline** — chronologická osa: kdy, kde, co se objevilo
2. **Scope** — které aplikace jsou `root`, `downstream`, `collateral`
3. **Causal chain** — kde problém začal a jak se šířil (dedukce z trace_id a časové posloupnosti)
4. **Root cause** — primární příčina (aplikace + chybová zpráva s nejvyšší korelací)
5. **Propagation** — za jak dlouho se chyba rozšířila do dalších aplikací (propagation_type: IMMEDIATE/GRADUAL/DELAYED)
6. **Recommended actions** — konkrétní kroky pro SRE

Výsledek (`trace_steps`, `root_cause`, `propagation_info`) se předává do email notifikace a Confluence exportu.

---

## 10. Rozhodování o alertu

`regular_phase.py` rozhoduje pro každý peak, zda odeslat alert:

### Cooldown

```
last_alert_time + ALERT_COOLDOWN_MIN (default 45 min) > now → přeskoč
```

Zabraňuje zahltění při opakujícím se peaku.

### Heartbeat

```
Pokud peak přetrvává déle než ALERT_HEARTBEAT_MIN (default 120 min)
→ odešli opakovaný alert (i přes cooldown)
```

Zajistí, že dlouhotrvající incident nezůstane bez upozornění.

### Continuation

Peak z předchozího 15min okna přetrvává → typ alertu je `CONTINUES` (ne `NEW` nebo `KNOWN`).

### Digest limit

```
MAX_PEAK_ALERTS_PER_WINDOW (default 3) peaků per cron okno
```

Pokud detekujeme např. 10 peaků najednou (cascáda), pošleme jen digest (1 email) s přehledem všech.

---

## 11. Email digest

Při detekci peaku se odešle **digest email** (`send_regular_phase_peak_digest`):

### Struktura emailu

**Souhrnná tabulka** (jeden řádek per peak):

| App | NS | Status | Errors | Trend |
|-----|----|--------|--------|-------|
| bl-pcb-v1 | pcb-sit | 🔴 NEW | 1,240 | ↑ rising |

**Detail blok** (per peak, rozbalený hned pod tabulkou):

```
bl-pcb-v1 (1,240 errors) — pcb-sit-01-app, pcb-dev-01-app
Trace ID: abc-123-def

Behavior:
  1) bff-pcb-ch-card-servicing-v1
     "ValidationException: card number invalid"
  2) bl-pcb-v1 (same error)
  3) feapi-pca-v1
     "ServiceUnavailable: upstream failed"

Inferred root cause (confidence: high):
  - bff-pcb-ch-card-servicing-v1: ValidationException

Propagation [GRADUAL]: 3 services, duration: 2m 15s
```

**Formát** je HTML s plain-text fallback. Dark-mode kompatibilní (žádné hardcoded tmavé barvy).

---

## 12. Confluence export

`scripts/exports/table_exporter.py` generuje markdown/CSV pro aktualizaci Confluence stránek:

### Known Errors

Tabulka všech chybových problémů z registru:
- **Activity status**: ACTIVE (< 7 dní), STALE (7–30 dní), OLD (> 30 dní)
- **Root cause** a **Behavior** ve formátu stručného trace flow
- **Kategorie** automaticky doplněna z error_class (pokud chybí)

### Known Peaks

Tabulka detekovaných peaků s metrikami:
- `peak_count` = počet raw error logů v peaku
- `peak_ratio` = aktuální/normální (zaokrouhleno na 2 des. místa, např. `12.45×`)
- `occurrence_count` = kolikrát byl peak detekován

---

## 13. Write-back — zpětné obohacení dat

Po každém běhu regular_phase systém zpětně obohacuje záznamy v registru:

```python
for entry in registry.problems:
    if entry.trace_flow_summary and not entry.behavior:
        # Sestav strukturovaný behavior popis z trace kroků
        blines = ["Behavior (trace flow): N messages"]
        for step in trace_steps:
            blines.append(f"  {i}) {app_name}")
            blines.append(f'     "{message}"')
        # ...přidej root cause a propagation
        entry.behavior = '\n'.join(blines)[:1000]
```

Tímto způsobem se `behavior` pole v `known_problems.yaml` postupně plní strukturovanými popisy, které se pak zobrazují v Confluence reportech. Záznam se obohacuje **pouze jednou** (pokud `behavior` ještě není vyplněno).

---

## 14. Backfill

`scripts/backfill.py` zpracuje historická data:

```bash
python3 scripts/backfill.py --days 14        # posledních 14 dní
python3 scripts/backfill.py --from "2026-01-06" --to "2026-01-20"
python3 scripts/backfill.py --days 14 --force  # přeprocesuj i zpracované dny
```

Backfill běží stejnou pipeline jako regular_phase, ale:
- Zpracovává data po celých dnech (ne 15min okna)
- Parallelně s `--workers N`
- Přeskakuje dny, které byly již zpracovány (detekce z DB záznamu)
- Ukládá stejná data do stejných DB tabulek a YAML registry

Primárně se spouští:
- Po inicializaci nové instance (backfill posledních N dní)
- Při obnovení po výpadku
- V produkci denně v 02:00 jako kontrolní/doplňovací krok

---

## 15. Přepočet thresholdů

`scripts/core/calculate_peak_thresholds.py` přepočítá P93/CAP prahy z nahromaděných dat:

```bash
python3 scripts/core/calculate_peak_thresholds.py           # z celé history
python3 scripts/core/calculate_peak_thresholds.py --weeks 4  # pouze poslední 4 týdny
python3 scripts/core/calculate_peak_thresholds.py --dry-run  # zobraz, nezapisuj
```

### Algoritmus

1. Načti všechna data z `ailog_peak.peak_raw_data`
2. Pro každou kombinaci `(namespace, day_of_week)`:
   - Seřad hodnoty
   - Spočítej 93. percentil (nebo jiný dle `PERCENTILE_LEVEL`)
   - Ulož do `ailog_peak.peak_thresholds`
3. Pro každý namespace:
   - Z P93 hodnot přes všechny dny spočítej `CAP = (median + avg) / 2`
   - Ulož do `ailog_peak.peak_threshold_caps`

**Doporučeno spouštět** min. po 2 týdnech provozu, pak pravidelně (měsíčně nebo při výrazné změně provozu).

---

## Principy návrhu

| Princip | Popis |
|---------|-------|
| **Report VŽDY** | Pipeline vždy vyprodukuje report, i když není žádný incident |
| **Registry = append-only** | Data se nikdy nemažou; každý problém má historii od `first_seen` |
| **FACT vs HYPOTHESIS** | Timeline obsahuje pouze fakta; root cause je explicitně označen jako hypotéza |
| **Deterministická logika** | Žádné ML modely; všechna rozhodnutí jsou transparentní a reprodukovatelná |
| **Non-blocking integrace** | Výpadek Teams nebo Confluence nezastaví pipeline ani nedojde ke ztrátě dat |
| **Scope ≠ Propagation** | Scope = které aplikace jsou zapojeny; Propagation = jak rychle se šíření dělo |
