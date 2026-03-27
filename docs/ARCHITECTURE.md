# Architektura — AI Log Analyzer

Tento dokument popisuje technickou strukturu systému: komponenty, datové toky, persistence a integrační body.

---

## Přehled

Systém se skládá ze čtyř hlavních vrstev:

```
┌─────────────────────────────────────────────────────────────────┐
│  ZDROJ DAT              │  Elasticsearch (aplikační error logy)  │
├─────────────────────────┼─────────────────────────────────────────┤
│  DETEKCE                │  Detection Pipeline (fáze A–F)          │
├─────────────────────────┼─────────────────────────────────────────┤
│  ANALÝZA                │  Incident Analysis Engine               │
├─────────────────────────┼─────────────────────────────────────────┤
│  VÝSTUP                 │  Email / Teams / Confluence             │
└─────────────────────────┴─────────────────────────────────────────┘
```

Dva vstupní body:
- **`scripts/regular_phase.py`** — spouštěn každých 15 minut jako Kubernetes CronJob; čte logy za poslední okno, běží pipeline, případně odesílá alert
- **`scripts/backfill.py`** — zpracovává historická data po dnech; slouží k doplnění chybějících dat nebo inicializaci nové instance

---

## Datový tok (regular phase)

```
Elasticsearch
      │  fetch_unlimited() — stránkované, bez limitu
      ▼
[ FÁZE A: Parse & Normalize ]
      │  NormalizedRecord: timestamp, namespace, app_name, error_type,
      │  normalized_message, fingerprint, trace_id, environment
      ▼
[ FÁZE B: Measure ]
      │  MeasurementResult: current_count, baseline, ewma, mad, trend_ratio
      │  (baseline se načítá z DB peak_raw_data — 7 dní historie)
      ▼
[ FÁZE C: Detect ]
      │  DetectionResult: is_spike, is_burst, is_new, is_regression,
      │  is_cross_namespace + evidence (proč byl flag nastaven)
      │  (spike detekce: P93/CAP z DB ailog_peak.peak_thresholds)
      ▼
[ FÁZE D: Score ]
      │  score 0–100 (váhový součet flagů + škálovací bonusy)
      ▼
[ FÁZE E: Classify ]
      │  category (BUSINESS, AUTH, DATABASE, ...) + subcategory
      ▼
[ FÁZE F: Report ]
      │  IncidentCollection — strukturovaná kolekce incidentů
      ▼
[ Incident Analysis Engine ]
      │  IncidentAnalysis: timeline, scope, causal_chain, recommended_actions
      ▼
[ Persistence ]
      ├── DB: peak_raw_data (surové počty → vstup pro P93/CAP výpočet)
      ├── DB: peak_investigation (evidované peaky pro Confluence)
      ├── YAML: registry/known_problems.yaml + known_peaks.yaml (append-only)
      └── JSON: registry/alert_state_regular_phase.json (stav alertů)
      ▼
[ Notifikace ]
      ├── Email digest (SMTP)
      └── Teams webhook
      ▼
[ Confluence export ]
      └── table_exporter.py → Known Errors + Known Peaks stránky
```

---

## Komponenty

### `scripts/regular_phase.py`

Hlavní orchestrátor 15min cyklu. Zodpovídá za:
- načtení konfigurace a registru před pipeline
- spuštění pipeline pro každý namespace/okno
- rozhodnutí, zda odeslat alert (cooldown, digest limit, continuation)
- zápis výsledků do DB a aktualizaci YAML registru
- write-back behavior popisu ke známým problémům

### `scripts/core/fetch_unlimited.py`

Stránkovaný Elasticsearch fetcher. Obchází limit 10 000 výsledků pomocí `search_after`. Vrací raw logy jako seznam dictu.

### `scripts/pipeline/phase_a_parse.py`

Normalizuje raw log záznamy:
- extrahuje strukturovaná pole (app_name, namespace, trace_id, environment, ...)
- normalizuje message (odstraňuje dynamické hodnoty: ID, timestamp, IP)
- generuje **fingerprint** = `MD5(error_type:normalized_message)[:16]`
  - fingerprint identifikuje *typ* chyby, ne konkrétní instanci
  - dvě chyby se stejným typem a stejnou (normalizovanou) zprávou dostanou stejný fingerprint

### `scripts/pipeline/phase_b_measure.py`

Počítá statistiky:
- **baseline** — historický průměr z DB (7 dní, EWMA)
- **current_count** — počet výskytů v aktuálním okně
- **trend_ratio** — aktuální / baseline
- EWMA s konfigurovatelným alpha (default 0.3)

### `scripts/pipeline/phase_c_detect.py`

Detekuje anomálie pro každý fingerprint:

| Flag | Podmínka |
|------|----------|
| `is_spike` | `value > P93_DOW` NEBO `value > CAP` |
| `is_burst` | rate change > 5.0× (konfigurováno `burst_threshold`) |
| `is_new` | fingerprint nenalezen v registry + `count >= new_error_min_count` |
| `is_regression` | fingerprint byl znám, dlouho neviděn, nyní znovu se objevil |
| `is_cross_namespace` | fingerprint nalezen ve ≥ 2 namespace |

P93 a CAP se čtou z DB (viz sekce Databáze). Pokud DB data nejsou k dispozici, použije se fallback na poměr vůči baseline.

### `scripts/pipeline/phase_d_score.py`

Deterministická váhová funkce:

```
score = base_score + Σ(flag_bonus)

base_score = min(count / 10, 30)
```

| Flag        | Bonus |
|-------------|------:|
| spike       |  +25  |
| burst       |  +20  |
| new         |  +15  |
| regression  |  +35  |
| cascade     |  +20  |
| cross-ns    |  +15  |

Výsledný score se mapuje na severity:

| Score    | Severity |
|----------|----------|
| ≥ 80     | critical |
| ≥ 60     | high     |
| ≥ 40     | medium   |
| ≥ 20     | low      |
| < 20     | info     |

### `scripts/pipeline/phase_e_classify.py`

Klasifikuje incidenty do taxonomie pomocí explicitních regexových pravidel (žádné ML):

| Kategorie  | Příklady subcategory                                     |
|------------|----------------------------------------------------------|
| BUSINESS   | not_found, validation, constraint_violation, not_found   |
| AUTH       | unauthorized, forbidden, token_expired                   |
| DATABASE   | connection, deadlock, constraint_violation, query_error  |
| NETWORK    | connection_refused, connection_reset, dns, ssl           |
| TIMEOUT    | read_timeout, connect_timeout, request_timeout           |
| MEMORY     | out_of_memory, memory_leak                               |
| EXTERNAL   | api_error, service_unavailable, gateway_error            |

Pravidla jsou definována v `phase_e_classify.py` (DEFAULT_RULES, 30+ pravidel) a `core/problem_registry.py` (ERROR_CLASS_PATTERNS, 40+ vzorů).

### `core/problem_registry.py`

Dvouúrovňová identita problémů:

```
PROBLEM REGISTRY (stabilní, málo záznamů)     1:N     FINGERPRINT INDEX (technický)
  problem_key                              ◄────────   fingerprint → problem_key
  first_seen / last_seen                               sample_messages
  occurrences, behavior, root_cause
```

**Problem Key** — trvalý identifikátor ve formátu `CATEGORY:flow:error_class`
- např. `BUSINESS:card_servicing:validation_error`

**Peak Key** — identifikátor v formátu `PEAK:category:flow:peak_type`
- např. `PEAK:business:card_servicing:spike`

**Flow** se extrahuje z názvu aplikace pomocí FLOW_PATTERNS:
- `bff-pcb-ch-card-servicing-v1` → `card_servicing`
- `bl-pcb-billing-v1` → `billing`
- 14 definovaných flow vzorů v kódu; pro neznámé aplikace fallback na první část jména

### `incident_analysis/`

Vrstva kauzální analýzy nad výsledky pipeline:
- **`analyzer.py`** — `IncidentAnalysisEngine`: grupuje incidenty do událostí, stavební timeline, spouští kauzální dedukci
- **`timeline_builder.py`** — sestavuje chronologickou osu: kdy se co objevilo a v jakém pořadí
- **`causal_inference.py`** — deterministicky inferuje kořenovou příčinu z trace kroků (žádné ML)
- **`fix_recommender.py`** — generuje konkrétní doporučené akce pro SRE na základě kategorie a severity

### `scripts/core/email_notifier.py`

Dvě varianty notifikace (řízeno `ALERT_DIGEST_ENABLED`):

- **Digest** (`send_regular_phase_peak_digest`) — jeden email per cron okno s přehlednou HTML tabulkou všech aktivních peaků; obsahuje NS sloupec, counts per app, strukturovaný trace flow, inferred root cause
- **Detail** (`send_regular_phase_peak_alert_detailed`) — jeden email per peak; používá se jako fallback nebo pro specifické případy

### `scripts/exports/table_exporter.py`

Generuje exporty pro Confluence:
- **Known Errors** — tabulka `ErrorTableRow` s kategoriemi, root cause, behavior, activity status (ACTIVE/STALE/OLD)
- **Known Peaks** — tabulka `PeakTableRow` s peak_count, peak_ratio (zaokrouhleno na 2 desetinná místa), occurrences, first/last seen, status + Peak Details sekce

---

## Databáze

Schema: `ailog_peak`

### `peak_raw_data`

```sql
(namespace, window_start, window_end, error_count, day_of_week)
```

Surové počty chyb per namespace per 15min okno. Každý regular_phase běh zde ukládá výsledky. Tato data jsou vstupem pro výpočet P93/CAP thresholdů.

### `peak_thresholds`

```sql
(namespace, day_of_week, percentile_value, sample_count)
```

P93 (nebo jiný percentil dle `PERCENTILE_LEVEL`) pro každou kombinaci `(namespace, den_v_týdnu)`. Přepočítává se příkazem `calculate_peak_thresholds.py`.

### `peak_threshold_caps`

```sql
(namespace, cap_value)
```

CAP = `(median_P93 + avg_P93) / 2` per namespace. Funguje jako zastropování pro namespace s málo daty.

### `peak_investigation`

```sql
(peak_key, problem_key, namespace, first_seen, last_seen, peak_type, ...)
```

Evidence jednotlivých peaků pro Confluence export a historii.

### Zápis do DB

Pro zápis je nutná sekvence:
1. Připojit se jako DDL user (`DB_DDL_USER`)
2. `SET ROLE role_ailog_analyzer_ddl` (viz `set_db_role()` v `regular_phase.py`)
3. Teprve pak `INSERT / UPDATE`

---

## YAML Registry (persistence)

Adresář `registry/` — **nikdy se z něj nemaže**, pouze se přidává a aktualizuje.

### `registry/known_problems.yaml`

Seznam všech dříve viděných problémů. Každý záznam:
```yaml
- id: KP-000123
  problem_key: BUSINESS:card_servicing:validation_error
  category: business
  flow: card_servicing
  error_class: validation_error
  first_seen: '2026-01-14T10:01:54+00:00'
  last_seen: '2026-03-26T09:15:00+00:00'
  occurrences: 1842
  behavior: |
    Behavior (trace flow): 3 messages
      1) bff-pcb-ch-card-servicing-v1
         "ValidationException: card number invalid"
      2) bl-pcb-v1 (same error)
    Inferred root cause: bff-pcb-ch-card-servicing-v1: ValidationException
```

### `registry/known_peaks.yaml`

Seznam všech detekovaných peaků:
```yaml
- id: PK-000042
  problem_key: PEAK:business:card_servicing:spike
  peak_type: SPIKE
  first_seen: '2026-03-01T08:00:00+00:00'
  last_seen: '2026-03-01T09:15:00+00:00'
  occurrences: 4
  affected_apps: [bff-pcb-ch-card-servicing-v1, bl-pcb-v1]
  affected_namespaces: [pcb-dev-01-app, pcb-sit-01-app]
```

### `registry/fingerprint_index.yaml`

Inverzní index pro rychlý lookup:
```yaml
BUSINESS:card_servicing:validation_error:
  - a1b2c3d4e5f6a7b8
  - 9f8e7d6c5b4a3f2e
```

### `registry/alert_state_regular_phase.json`

Stavový soubor pro řízení alertů:
```json
{
  "peaks": {
    "PK-000042": {
      "last_alert_sent": "2026-03-26T09:00:00+00:00",
      "alert_count": 2,
      "last_error_count": 1540
    }
  }
}
```

Slouží pro:
- **Cooldown** — default 45 min (`ALERT_COOLDOWN_MIN`)
- **Heartbeat** — opakovaný alert i pro pokračující peak po 120 min (`ALERT_HEARTBEAT_MIN`)
- **Trend** — porovnání s předchozím oknem (rising/falling/stable)
- **Continuation** — detekce zda peak přetrvává z předchozího okna (`ALERT_CONTINUATION_LOOKBACK_MIN=60`)

---

## Konfigurační soubory

### `config/namespaces.yaml`

Seznam Kubernetes namespace, které jsou monitorovány:
```yaml
namespaces:
  - pca-dev-01-app
  - pcb-dev-01-app
  - pcb-sit-01-app
  - pcb-uat-01-app
  # ...
```

### `config/known_issues/known_errors.yaml`

Manuální knowledge base — lidský kontext ke známým fingerprintům:
```yaml
a1b2c3d4e5f6a7b8:
  description: "ValidationException při zadání neplatného čísla karty"
  first_seen: 2026-01-10
  workaround: "Ověřit formát vstupu na frontend straně"
  fix_status: in_progress  # open | in_progress | fixed | wont_fix
  jira_ticket: "PCBS-1234"
```

---

## Integrace

| Systém        | Typ             | Použití                                              |
|---------------|-----------------|------------------------------------------------------|
| Elasticsearch | HTTP REST (čtení)| Zdrojová data — error logy aplikací                  |
| PostgreSQL    | psycopg2        | Persistence thresholdů, raw dat, peaků              |
| SMTP / Teams  | HTTP/email (zápis) | Notifikace při detekci peaku                      |
| Confluence    | HTTP REST (zápis) | Known Errors a Known Peaks stránky                 |

Všechny integrace jsou **non-blocking** — selhání Teams nebo Confluence neblokuje pipeline, pouze se loguje chyba.

---

## Kubernetes nasazení

Dva CronJoby:

| Job              | Schedule        | Skript                          |
|------------------|-----------------|---------------------------------|
| `log-analyzer-regular` | `*/15 * * * *` | `scripts/regular_phase.py` |
| `log-analyzer-backfill` | `0 2 * * *`   | `scripts/backfill.py --days 1` |

Image: `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:<tag>`

K8s manifesty: `k8s/` v tomto repozitáři.
Helm values pro nasazení: `~/git/sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/values.yaml`
