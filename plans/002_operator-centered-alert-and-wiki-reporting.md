# Plan 002: Operator-centered alert and wiki reporting

Návrh odděluje detekci zvýšeného namespace provozu od diagnostiky konkrétní příčiny. Alert má odpovědět na otázky „proč teď“, „co skutečně selhalo“, „kolika operací se to týká“ a „co má operátor udělat“, nikoli opakovat stejné logové řádky v několika sekcích.

## Problem

Současný 15min digest správně upozorní na zvýšený objem ERROR logů, ale jeho obsah míchá několik různých veličin:

- celkový počet ERROR řádků v namespace,
- počet řádků vybraného fingerprintu nebo error class,
- počet business operací reprezentovaných unikátními trace,
- historické Known Errors patterns,
- current-window scope a historický scope.

Výsledkem jsou opakované nebo vzájemně neslučitelné údaje. Operátor vidí například `servicebusinessexception`, wrapper `ServiceBusinessException error handled` a stejný text v Root cause i Behavior, ale ne konkrétní business příčinu.

Daily/backfill notifikace má podobný problém: `294 problems` a lifetime occurrence counts neříkají, co bylo 25. 8. nové, co se zhoršilo a co vyžaduje zásah.

## CAP lifecycle

### Proč CAP počítá init Job i CronJob

- Init Job je bootstrap. Po historickém backfillu vytvoří první `complete` threshold snapshot z `init.thresholdWeeks` (aktuálně tři týdny), aby první regular job měl co načíst.
- `log-analyzer-thresholds` je týdenní refresh. Každou neděli ve 03:00 UTC vytvoří nový snapshot z posuvných posledních čtyř týdnů.
- Regular job nic nepřepočítává. Z `v_latest_threshold_values` čte poslední atomicky dokončený snapshot.
- Nejde tedy o dvojí detekci v jednom běhu. Jde o stejný trainer spuštěný ze dvou důvodů: `bootstrap` a `scheduled_refresh`.

### Co zlepšit

Init Job dnes threshold vždy přepočítá. Při běžném redeployi je to zbytečné a mění auditní snapshot bez změny modelu. Doplnit guard:

1. Pokud neexistuje `complete` snapshot, vytvořit bootstrap snapshot.
2. Pokud se změnilo `calculation_version`, `percentile_level`, population grain nebo monitored namespaces, vytvořit nový snapshot.
3. Jinak threshold krok přeskočit, pokud není explicitní `FORCE_THRESHOLD_REFRESH=true`.
4. Do snapshot run uložit reason: `bootstrap`, `weekly_refresh`, `manual_refresh`, `model_change`.

### Důležitá statistická poznámka

Lokální rozpracovaná změna v `calculate_peak_thresholds.py` vyřazuje nuly přes `active_values = [value for value in values if value > 0]`. To práh nesnižuje. U sparse namespace naopak P93 i CAP obvykle zvýší a alertů bude méně.

- Snížení `PERCENTILE_LEVEL` z `0.93` na nižší hodnotu obvykle sníží threshold a zvýší citlivost.
- Vyřazení nul počítá „P93 aktivních oken“, což obvykle threshold zvýší.
- Současné pravidlo je `(namespace_total > Pxx) OR (namespace_total > CAP)`, takže efektivní trigger je nižší z `Pxx` a `CAP`.
- CAP není hard maximum. Je to vyhlazený fallback `(median daily Pxx + average daily Pxx) / 2`.

V alertu proto vždy zobrazit přesnou použitou metriku, oba prahy, efektivní práh, snapshot ID/age a population label, například `P93 active windows` místo neurčitého `P93`.

## Empirical analysis

### Zdroje

- Přiložené digesty z 25. 8. 2026.
- Produkční Elasticsearch `https://elasticsearch.kb.cz:9500`.
- Index contract `cluster-app_pcb-*,cluster-app_pca-*,cluster-app_pcb_ch-*`.
- Scope `pca-prod-01-app`, `pcb-prod-01-app`, `pcb-ch-prod-01-app`.
- Half-open 15min UTC okna.
- ERROR fetch přes repository PIT/search-after klienta.
- All-level context přes konkrétní trace IDs.
- Source pipeline a renderery v `regular_phase.py`, `trace_analysis.py`, `trace_timeline.py` a `email_notifier.py`.

### Reprodukovatelný postup

1. Převést čas digestu z Europe/Prague na UTC a použít interval `[from, to)`.
2. Stáhnout všechny ERROR eventy s PIT a ověřit `expected == fetched`.
3. Rozdělit eventy podle operation occurrence:
   - primárně `trace_id + root span/request`,
   - fallback samotný trace ID,
   - dlouhé session/mega-trace segmentovat request boundary nebo time gapem,
   - bez trace použít fingerprint s nižší confidence.
4. V každé operation occurrence označit role eventů:
   - concrete cause,
   - technical wrapper,
   - transport/downstream symptom,
   - business outcome.
5. Ignorovat jako root cause wrappery `* error handled`, `Handle fault`, generic `General error`, downstream URL/status a SPEED/ITO kód, pokud v trace existuje konkrétnější příčina.
6. Sestavit cause signature: root app + canonical cause + operation + outward status.
7. Agregovat dvě oddělené metriky:
   - unique operations,
   - raw ERROR lines a amplification `raw lines / operations`.
8. Pro reprezentanta top cause families dotáhnout INFO/WARN kontext. Ten rozhoduje například mezi technickým selháním a očekávaným CANCELLED flow.
9. Připojit detector evidence z `detection_events` a `threshold_snapshot_values`.
10. Vynutit auditní rovnice před renderem.

Výzkumný read-only probe je v `tmp/aug25_alert_report_probe.py`. Fail-closed vyžaduje complete PIT fetch a sanitizuje numeric IDs, UUID i long hex hodnoty.

### Ověřený výsledek: 10:00-10:15 CEST

Elasticsearch fetch byl complete: `393/393` ERROR eventů.

| Metrika | Hodnota |
|---------|---------|
| Raw ERROR lines | 393 |
| Unique traced operations | 100 |
| Untraced ERROR lines | 7 |
| Logging amplification | 3.9 lines/trace |

Dominantní konkrétní cause families:

| Unique operations | Raw lines | Amplification | Root app | Canonical cause |
|------------------:|----------:|--------------:|----------|-----------------|
| 40 | 200 | 5.0x | `bl-pcb-v1` | Card with product instance `null` not found |
| 18 | 18 | 1.0x | `bff-pcb-ch-card-servicing-v1` | `cardTokenizationCompletedAction -> 400` |
| 9 | 36 | 4.0x | `bff-pcb-ch-card-opening-v2` | `AccessDeniedException` |
| 6 | 12 | 2.0x | `bff-pcb-ch-card-servicing-admin-v1` | Limit change case was not saved / authorization URI missing |
| 4 | 28 | 7.0x | `bl-pcb-v1` | No card exists for cardholder |

Současný digest vybral `45 servicebusinessexception` a `18 cardsservicecallerror`. Těch `45` ale není jedna příčina: minimálně `40 + 4 + 1` operation families jsou sloučené jen společnou Java exception class. Dominantních 40 operací vytvořilo 200 ERROR řádků, takže raw volume výrazně nadhodnocuje business impact.

### Ověřené representative trace findings

#### Card repair: client does not exist

Trace prefixes `40accf81` a `211bc28e` ukazují stejný příběh ve dvou různých oknech:

1. `feapi-pca-v1` přijme požadavek na card repair.
2. `bl-pcb-v1` zjistí `Client does not exist`.
3. PCB repair vrátí 404.
4. Stejná jedna operace vytvoří několik exception/wrapper/downstream ERROR řádků.

V trace `40accf81` bylo devět ERROR řádků pro jednu operation occurrence. Současný digest uvádí devět errors, ale současně připisuje Behavior aplikaci `bl-pcb-click2pay-v1`, která v tomto trace vůbec není. To dokazuje chybnou vazbu mezi current-window payloadem, behavior patternem a representative trace.

Assessment: business rejection nebo stale/missing domain data, nikoli automaticky platform outage. Další krok je ověřit, proč repair přichází pro neexistujícího klienta a zda 404 odpovídá API kontraktu.

#### Card repair: optimistic locking

Trace prefix `1da68318`:

1. `feapi-pca-v1` spustí repair.
2. `bl-pcb-v1` selže na `HibernateOptimisticLockingFailureException`: řádek Card byl souběžně změněn nebo smazán.
3. PCB vrátí 500.
4. FEAPI zaloguje downstream 500 a mapuje výsledek dál.

Jedna potvrzená operation occurrence vytvořila 11 ERROR řádků. Současný alert ukazuje obecné `servererror...repair -> 500`, ale skrývá nejhlubší technickou příčinu a root aplikaci.

Assessment: skutečné technické concurrency selhání, high confidence. Action: dohledat konkurenční update stejné Card entity ve stejném okamžiku, ověřit optimistic-lock retry/idempotency a nevydávat outward 400 za primární cause.

#### Tokenization completed: CANCELLED -> 400

Trace prefixes `16148900` a `00c8cab8`:

1. `cardTokenizationCompletedAction` je volán s business výsledkem `CANCELLED`.
2. Case je rušen uživatelem a downstream event processing pokračuje.
3. BFF zapíše jediný ERROR `CardsServiceImpl#cardTokenizationCompletedAction -> 400`.
4. Následují WARN o nenalezených komponentách, ale ne důkaz platform failure.

Assessment: pravděpodobně očekávaný cancel outcome zalogovaný jako ERROR, nebo nesoulad API kontraktu; medium confidence. Než se z toho bude dělat incident, owner musí potvrdit, zda CANCELLED má vracet 2xx, 4xx jako business response, nebo je 400 skutečný defect.

#### Click2Pay card lookup: card not found

Trace prefix `0e4b4d6e`:

1. BFF žádá detail karty.
2. `bl-pcb-click2pay-v1` nenajde card detail v DB.
3. Konkrétní cause je `Resource not found. Card with id <ID> not found`.
4. Jedna operation occurrence vytvoří pět ERROR řádků a outward 404.

Assessment: missing domain data/business 404. Alert má ukázat jednu selhanou operaci a 5x logging amplification, ne pět nezávislých incidentů.

### Limity tohoto průzkumu

- Complete distribuční fetch se podařil pro 08:00-08:15 UTC a all-level context pro šest representative traces ze všech čtyř oken.
- Následně lokální ES credential začal vracet opakovaně `401` i na scoped `_count` a PIT. Další full-window distribuce proto nebyla vydávána za ověřenou.
- Lokální DB credential skončil na LDAP authentication failure, takže přesné P93/CAP hodnoty z `detection_events` nebyly doplněny.
- Čísla z ostatních tří digestů jsou proto reportována jako jejich current payload; causální závěry jsou opřené o konkrétní representative trace, ne o neověřenou window-wide distribuci.

## Root causes in current implementation

### 1. Reporting unit is error class, not operational cause

`ServiceBusinessException` sdružuje card-not-found, client-not-found, validation a další nezávislé příčiny. Known Errors už některé varianty odděluje podle fingerprintu, 15min alert je ale znovu sloučí na vyšší problem/error-class úrovni.

### 2. Raw lines are presented as impact

Jedna operace běžně vytvoří 5-11 ERROR řádků napříč root a downstream službami. Operátor potřebuje obě hodnoty, ale primary impact musí být unique operation occurrences.

### 3. Current evidence and historical behavior are mixed

Behavior v digestu může mít více eventů nebo aplikací než `Errors` v aktuálním okně. Jde o jinou agregaci nebo historický Known Peak pattern, ale renderer ji neoznačí. Current evidence a historical knowledge musí být samostatné sekce.

### 4. Root-cause rank prefers an informative downstream message

All-level enrichment je užitečný, ale `default_root_cause` vybírá první event se signal score. Technická exception bez známého positive keyword může prohrát s pozdějším downstream wrapperem. Root rank musí zohlednit level, wrapper role, span ancestry a upstream/downstream pozici.

### 5. Cluster merge preserves primary explanation

`_build_cluster_payload` sčítá secondary counts a scope, ale root cause/behavior primárního problému nemusí reprezentovat sloučený objem. Proto je výsledný text auditně nekonzistentní.

### 6. Daily report ranks lifetime objects

Backfill summary `Total problems: 294` a lifetime occurrences neříkají, které cause families byly aktivní v daném dni. Daily report musí být run/window-centric, zatímco Known Errors má být knowledge catalog.

## Proposed analytical contract

### Detection and diagnosis are separate stages

1. Namespace Pxx/CAP odpovídá pouze na „je celkový ERROR volume v namespace neobvyklý?“
2. Cause-family analysis odpovídá na „co přesně tento nárůst tvoří?“
3. Notification policy odpovídá na „je to actionable a komu to poslat?“

Namespace threshold se nikdy nesmí prezentovat jako threshold konkrétního fingerprintu bez explicitního family baseline.

### Operation occurrence

Primary impact unit:

```text
operation_occurrence = trace_id + root_span_or_request_boundary
```

Fallbacky:

- trace ID, pokud span/root request není dostupný,
- trace segment podle request boundary/time gap pro mega-trace,
- fingerprint event count s `low` confidence pro untraced logy.

### Cause signature

```text
cause_signature = root_app + canonical_cause + operation + outward_status
```

Stejná exception class s jiným canonical cause vytvoří jinou family. Stejná příčina zabalená do více wrapperů zůstane jedna family.

### Assessment taxonomy

| Assessment | Význam | Default notification policy |
|------------|--------|-----------------------------|
| `technical_failure` | timeout, DB/concurrency, 5xx root failure | immediate, severity podle impact/novelty |
| `business_rejection` | validace, missing domain data, 4xx | notify jen při family anomaly nebo vysokém dopadu |
| `expected_outcome_logged_as_error` | očekávaný flow zalogovaný ERROR | neincidentní digest / log-quality backlog |
| `unknown` | evidence nestačí | triage alert s explicitní low confidence |

Classifier může být nejprve deterministický. LLM může později formulovat summary nad strukturovanými evidence, ale nesmí měnit counts, cause signature ani assessment bez uloženého důvodu a confidence.

### Audit invariants

Před odesláním musí platit:

```text
sum(current family raw lines) + excluded/untraced lines = fetched ERROR lines
sum(current family unique occurrences) = unique segmented operations
displayed app/ns counts <= family raw lines
current evidence counts are never mixed with historical counts
representative trace belongs to displayed family and scope
```

## Proposed notification

### Compact digest row

```text
[TECHNICAL|BUSINESS|EXPECTED?] Cause summary
Why now: namespace 393 ERROR lines vs effective threshold [from snapshot]
Impact: 40 operations | 200 ERROR lines | 5.0x log amplification
Cause: bl-pcb-v1 - Card with product instance null not found
Outcome: [operation/status from evidence]
Assessment: business rejection / missing domain data (medium confidence)
Action: verify whether requests reference stale/missing card-product data
Evidence: trace 6a8d4e56... | current window only
```

### Example: optimistic locking

```text
[HIGH][TECHNICAL][NEW] Concurrent card update breaks repair

WHY ALERTED
Namespace total exceeded [effective Pxx/CAP from detection snapshot].

WHAT ACTUALLY FAILED
bl-pcb-v1: HibernateOptimisticLockingFailureException while updating Card.
Path: feapi-pca-v1 -> bl-pcb-v1 repair -> 500.

IMPACT
1 confirmed operation in representative trace; 11 ERROR lines (11x amplification).
Window-wide unique-operation count requires complete family aggregation.

ASSESSMENT
Technical concurrency failure, high confidence. Not a generic FEAPI server error.

NEXT ACTION
Inspect concurrent Card updates around the trace timestamp and verify retry/idempotency.
Evidence: trace 1da68318...
```

### Example: tokenization cancel

```text
[REVIEW][LIKELY EXPECTED] Tokenization CANCELLED is logged as HTTP 400

WHAT HAPPENED
cardTokenizationCompletedAction received result=CANCELLED and cancelled the case.
The BFF then logged CardsServiceImpl#cardTokenizationCompletedAction -> 400.

ASSESSMENT
Likely expected business outcome or API/logging contract mismatch (medium confidence).

NEXT ACTION
Owner confirms the contract. If CANCELLED is expected, change severity/log level and suppress incident alerting for this family.
Evidence: traces 16148900..., 00c8cab8...
```

### What to remove from notification

- `Applications affected` a `Namespaces affected` bez vazby na konkrétní family.
- Root cause opakovaný jako Behavior item 1.
- Historické behavior counts vydávané za current window.
- Jeden `Errors` count bez označení, zda jde o raw lines, fingerprint events nebo operations.
- Obecné labely `servicebusinessexception` jako hlavní titulek, pokud existuje konkrétní cause.

## Proposed daily wiki report

### Daily overview

```text
25 Aug 2026
Actionable technical causes: 1
Business/data anomalies: 2
Likely expected outcomes logged as ERROR: 1
Unknown requiring triage: N
```

### Cause-family table

| Cause family | Assessment | Active windows | First / last | Unique operations | Raw ERROR lines | Amplification | Dominant path/status | Confidence | Next action |
|--------------|------------|---------------:|--------------|------------------:|----------------:|--------------:|----------------------|------------|-------------|
| Client does not exist during card repair | business/data | 2 confirmed | 12:03 / 12:46 | at least 2 confirmed | 9 per representative trace | 9.0x | FEAPI -> PCB repair -> 404 | high cause, medium operational meaning | check stale/nonexistent client references |
| Card/product instance null not found | business/data | 1 | 10:00 / 10:15 | 40 | 200 | 5.0x | derive from family evidence | medium | validate product-instance data quality |
| Optimistic lock during card repair | technical | 1 | 11:52 / 11:52 | at least 1 confirmed | 11 in representative trace | 11.0x | FEAPI -> PCB -> 500 | high | inspect concurrent updates and retry |
| Tokenization CANCELLED -> 400 | expected?/contract | at least 2 representative windows | 10:08 / 11:46 | recompute after ES auth refresh | current selected lines available | near 1.0x in samples | BFF tokenization action -> 400 | medium | confirm API contract, then downgrade/suppress |

`at least` hodnoty jsou záměrně označené tam, kde po expiraci ES credential nebyl dokončen full-window recount.

### Per-family detail

Každá family má pouze tyto bloky:

1. Why it matters now: current operations vs own family baseline, namespace gate jako context.
2. Canonical cause: jedna věta, root app, operation/status.
3. Current evidence: top variants pouze z reportovaného období.
4. Historical knowledge: Known Error ID, Jira, owner, workaround a historical variants odděleně.
5. Next action: konkrétní, nebo explicitně `needs owner classification`.

### Known Errors page role

Known Errors má být knowledge catalog, ne druhý daily dashboard:

- titulek podle canonical cause, ne Java exception class,
- classification a confidence,
- owner/Jira/runbook/workaround,
- typical path a expected outcome,
- current 24h unique operations jako sekundární telemetry,
- lifetime raw lines pouze diagnosticky,
- Behavior nezopakuje canonical cause jako první bod; ukáže jen alternativní variants.

Known Peaks má popisovat seasonality/rate baseline. Recent Incidents má popisovat aktuální cause-family occurrences a akce.

## Implementation

### Phase 1: Correct current-window evidence

1. Přidat `OperationalCauseAnalyzer` nad raw normalized records před problem aggregation.
2. Segmentovat operation occurrences a klasifikovat event roles.
3. Vytvořit `CauseFamily` s unique operations, raw lines, amplification, current scope, evidence a assessment.
4. All-level context fetchnout pouze pro representative trace top families.
5. Připojit `detection_events` threshold evidence.
6. Renderovat digest z CauseFamily, ne z merged `ProblemAggregate`.
7. Zachovat starý renderer za feature flagem pro A/B porovnání bez dvojího odeslání.

### Phase 2: Persist daily cause facts

1. Přidat immutable per-run cause-family facts nebo rozšířit stávající fact model.
2. Uložit cause signature version, operation count, raw count, assessment, confidence a representative evidence.
3. Daily report agregovat pouze z `complete`, non-superseded runs.
4. Oddělit current-period counts od registry lifetime knowledge.

### Phase 3: Notification policy

1. Family-specific baseline z unique operation counts.
2. Severity kombinovat z assessment, novelty, operation impact, status a rate ratio.
3. Expected outcomes neposílat jako incident po potvrzení ownerem.
4. Cooldown klíčovat cause signature, ne obecnou error class.
5. Persistovat přesný důvod `sent`, `suppressed`, `daily_only` nebo `needs_classification`.

### Phase 4: Threshold lifecycle guard

1. Init před trainerem zkontroluje latest complete snapshot metadata.
2. Přepočet proběhne jen při chybějícím/stale/incompatible snapshotu nebo force flagu.
3. Cron zůstane weekly refresh.
4. Alert zobrazí snapshot provenance a population semantics.

## Files to modify

| Soubor | Změna |
|--------|-------|
| `scripts/analysis/operational_cause.py` | Nová operation/cause-family analýza |
| `scripts/analysis/trace_timeline.py` | Event role, span-aware root rank, mega-trace segmentation |
| `scripts/regular_phase.py` | Wire CauseFamily a threshold evidence, odstranit merged-payload ambiguity |
| `scripts/core/email_notifier.py` | Operator-centered compact/detailed renderer |
| `scripts/analysis/problem_report.py` | Daily cause-family report a current/history separation |
| `scripts/exports/table_exporter.py` | Wiki cause-family columns bez RC/Behavior duplicity |
| `scripts/core/run_persistence.py` | Persist immutable cause-family facts |
| `scripts/migrations/` | Cause-family fact schema, pokud nebude stačit evidence JSON |
| `k8s/templates/job-init.yaml` | Conditional threshold bootstrap/force reason |
| `scripts/core/calculate_peak_thresholds.py` | Explicit population semantics/version |
| `scripts/tests/` | Sanitizované real-trace fixtures a reconciliation tests |

## Testing

### Sanitized fixtures from 25 Aug

- `Client does not exist`: devět ERROR lines -> jedna operation, concrete PCB cause, outward 404.
- `HibernateOptimisticLockingFailureException`: root PCB technical cause porazí downstream FEAPI wrappers.
- `CANCELLED -> 400`: assessment `likely expected`, medium confidence, dokud není owner policy.
- `Card/product instance null not found`: 40 operations a 200 lines zůstanou jedna cause family.
- Dvě různé ServiceBusinessException messages vytvoří dvě families.
- Stejná cause ve dvou oknech se na wiki spojí, current counts se nesmíchají s lifetime registry.

### Required invariants

- Sum raw family lines reconciles to fetched ERROR lines.
- Representative trace scope odpovídá zobrazeným apps/namespaces.
- Behavior count nikdy nepřekročí family raw count bez explicitního `historical` labelu.
- Root cause není wrapper ani downstream symptom, když existuje concrete upstream cause.
- Unique operations a raw lines jsou vždy dvě pojmenované metriky.
- Threshold reason obsahuje evaluated namespace total, Pxx, CAP, effective threshold a snapshot ID.
- Incomplete ES fetch nevytvoří report.
- Expected-outcome suppression vyžaduje explicitní owner classification, ne pouze heuristiku.

### Validation workflow

1. Replay sanitizovaných fixtures lokálně.
2. Shadow-render old/new digest pro stejné complete runs bez odeslání.
3. Reconcile top families s Kibana/ES pro několik peak a non-peak oken.
4. Owner review nejčastějších business 4xx families.
5. Teprve potom přepnout notification renderer.

## Dependencies and blockers

- Refresh read-only ES credentials pro dokončení full-window recount ostatních tří oken.
- Funkční read-only DB role pro přesné threshold snapshot joins.
- Domain owner rozhodnutí pro `cardTokenizationCompletedAction(CANCELLED) -> 400`.
- Rozhodnutí, zda lokální zero-exclusion změna znamená záměrné `active-window percentile`; bez toho ji nelze korektně pojmenovat ani kalibrovat.

---

## Implementation status

Dokončeno:

- cause-family model a signature `root_app + canonical_cause + operation + outward_status`,
- oddělené operation occurrences, raw ERROR lines a amplification,
- span-aware root/request segmentation s přesnou count reconciliation,
- fail-closed `N/A` pro neúplnou nebo nejednoznačnou mega-trace ancestry,
- bounded trace-ID fallback přes `OPERATION_TRACE_FALLBACK_MAX_ERRORS` a `OPERATION_TRACE_FALLBACK_MAX_DURATION_MIN`,
- bounded all-level INFO/WARN context bez kontaminace ERROR counts,
- operator digest, individual fallback a daily report,
- structured escaped Confluence renderer,
- immutable cause-family facts v migraci 007 včetně operation-count audit metadata,
- cause-signature cooldown/delivery identity,
- threshold snapshot compatibility guard a init force-refresh wiring,
- installer, `.env.example` a Helm rollout values.

Validace:

- focused operation/cause/persistence/report slice: 42 tests plus 2 subtests,
- full suite bez známého user-owned registry blockeru: 93 passed, 5 skipped, 2 subtests passed,
- full suite včetně blockeru: 91 passed, 5 skipped, 3 failed, 2 subtests passed; všechny tři failure jsou `ProblemEntry.__init__() got an unexpected keyword argument 'fingerprints'` v user-owned `problem_registry.py`,
- `bash -n install.sh`, expanded installer YAML parse, Helm lint a template render prošly,
- migrations 000 až 007 prošly produkčním SQL splitterem.

Zbývající externí ověření:

- live PostgreSQL migration integration vyžaduje funkční `TEST_POSTGRES_DSN`/LDAP credentials,
- live ES recount a representative context probe vyžaduje obnovené read-only credentials; současný endpoint vrací 401,
- owner klasifikace `cardTokenizationCompletedAction(CANCELLED) -> 400`.

---

*Vytvořeno: 2026-08-25*
*Aktualizováno: 2026-08-26*
*Status: IMPLEMENTED, EXTERNAL VALIDATION BLOCKED*