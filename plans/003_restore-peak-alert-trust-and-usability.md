# Plan 003: Restore 15-minute peak detection, episodes, and alert usability

Tento plan shrnuje puvodni peak alerting, skutecne chovani live verze `r97` za prvnich priblizne 24 hodin a cilovy stav. Detekce zustava v pevnych 15min oknech. Oprava musi pokryt vsechny pozadovane namespaces, spojit stejny problem pres sousedni okna do peak episode a obnovit auditovatelny vztah mezi namespace signalem, konkretni operational cause a alertem.

## Executive decision

Live evidence potvrdilo, ze peak detection a alerting jsou funkcne neuplne:

- `r97` zpracovalo 94 complete regular runu a 13 135 ERROR radku, ale runtime `MONITORED_NAMESPACES` override obsahoval pouze sest `dev/fat` namespaces.
- Repozitarovy `config/namespaces.yaml` jiz obsahuje vsech 12 `dev/fat/sit/uat` namespaces, ale runtime env override ma pred YAML konfiguraci prednost. `sit/uat` proto nebyly ve fetch query, threshold trainingu ani live snapshotu a vetsina uzivatelem identifikovanych peaku nemohla byt detekovana.
- Pro monitorovane `dev/fat` scope detector nasel sest unikatnich namespace peak owneru ve ctyrech 15min oknech.
- Jeden alert byl dorucen a pet alert payloadu bylo zamerne potlaceno jako `test_peak_suppressed:MochaXTestApp`.
- Uzivatelem sledovany 30min objem `pcb-dev=2431` a `pcb-ch-dev=836` presne odpovida 15min datum `2200+231` a `344+492`. Detekce probehla, ale alerting vsechny payloady skryl.
- Sousedni 15min peaky se neudrzuji jako jedna episode. Registry pouziva coarse `category + flow + peak_type`, delivery stav cause signature a suppressed okna stav vubec neaktualizuji.
- V tomto obdobi nebyl dolozen cooldown suppression, heartbeat suppression, top-N omission ani delivery failure.
- Threshold snapshot byl cerstvy, complete a vytvoreny pri nasazeni 30. 9. 2026. Neni podklad pro tvrzeni, ze jedinou pricinu maleho poctu alertu tvori stale threshold.
- Doruceny alert je diagnosticky slaby, protoze zobrazuje tri ruzne scope jako by slo o jednu metriku: 431 namespace ERROR radku, 86 radku owner fingerprintu v trigger namespace a 160 radku sirsiho alert/problem agregatu.
- `ServiceBusinessException`, `unknown-operation` a chybejici outward status nejsou dostatecny problem identity ani operational diagnosis.

> **Doporuceni k revizi:** schvalit rozsireni coverage, 15min episode state, fail-open namespace peak signal s fail-closed diagnosis a hybridni alert. `MochaXTestApp` ma byt viditelna klasifikace, ne duvod k uplnemu umlceni volume peaku. P94/CAP se bude kalibrovat az replayem nad rozsirenym scope.

## Upresneny funkcni pozadavek

- Detekcni okno zustava presne 15 minut. Zadny 30min detector ani 30min threshold se nezavadi.
- Uzivatelem dodane 30min hodnoty jsou pouze indicie a acceptance oracle pro dvojice 15min oken.
- Kazde 15min okno musi vytvorit auditni namespace decision, i kdyz nelze spolehlive urcit dominantni cause family.
- `NamespacePeakDecision` odpovida pouze na otazku, zda je konkretni namespace v konkretnim 15min okne peak. `PeakEpisode` koreluje stejnou operational cause pres vice decisions. `NotificationDecision` urcuje, zda se posila start/update/digest. Tyto tri identity se nesmi sloucit do jednoho `peak_key`.
- Stejna cause v navazujicim 15min okne musi pokracovat pod stejnym `episode_id` a nest predchozi diagnosis, scope a trend.
- Nova namespace nebo aplikace se stejnou cause je `EXPANSION` stejne episode.
- Vyssi impact nebo zhorseny outcome stejne cause je `ESCALATION`.
- Jina cause ve stejnem namespace/case je nova episode, nikoli continuation podle obecne category/flow.
- Operator musi byt informovan o kazdem `START`, `EXPANSION` a `ESCALATION`. `CONTINUATION` se zobrazi v digestu a znovu alertuje pri materialni zmene nebo heartbeat. Zadny detekovany peak se nesmi tise ztratit.

### Release-blocking oracle pro zadanych 24 hodin

- Kandidati 1, 2, 4, 6, 7 a 8 musi v deterministic replayi vytvorit alespon jeden `is_peak=true` namespace decision. Pokud nektery nevznikne, release se zastavi a threshold verdict musi byt vysvetlen a schvalen nad ulozenymi Pxx/CAP vstupy.
- Kandidat 3 musi byt samostatne vyhodnocen po 15min oknech. Pokud cause signature navazuje na kandidata 2, jde o `CONTINUATION`; jinak o novy `START`. Nesmí zmizet jen proto, ze je povazovan za dojezd.
- Kandidat 4 musi podle cause evidence vytvorit bud `EXPANSION` jedne episode, nebo vice soubeznych episodes. Shodny cas ani spolecny 30min soucet samy o sobe nejsou korelacni dukaz.
- Kandidat 5 musi vzdy vytvorit auditni decision s vysvetlitelnym `is_peak=true/false` verdictem; zadani jej nepovazuje automaticky za peak.
- Kandidat 8 musi zachovat dve namespace timelines (`pcb-dev` a `pcb-ch-dev`) a byt viditelny i pri `MochaXTestApp` klasifikaci.
- Replay report musi pro vsech osm kandidatu ukazat raw UTC window key, `Europe/Prague` display window, namespace decision, cause/diagnosis confidence, episode state, policy outcome a delivery outcome. Tim se odstrani nejednoznacnost uzivatelskeho orientacniho casu `cca 08:00` proti presnym 15min datum.

## Scope a source provenance

### Namespace source-of-truth drift

| Vrstva | Stav | Cil |
|---|---|---|
| `config/namespaces.yaml` | Obsahuje 12 `pca/pcb/pcb-ch x dev/fat/sit/uat` namespaces | Kanonicky aplikacni seznam |
| `_load_monitored_namespaces()` | Preferuje `MONITORED_NAMESPACES`, YAML je pouze fallback | Zachovat precedence, ale validovat shodu override s kanonickym seznamem |
| Lokalni `k8s/values.yaml` | Obsahuje placeholder `<comma_separated_application_namespaces>` | Renderovat explicitnich 12 hodnot nebo generovat override z jednoho hodnotoveho zdroje |
| Live `r97` workload | Override obsahoval pouze sest `dev/fat` namespaces | Failnout start/training pri chybejicim `sit/uat` nebo partial snapshotu |
| GitOps deployment values | Autoritativni pro skutecne nasazeny env override | Reviewovat a menit spolu s aplikacnim contractem |

Nejde tedy o chybejici seznam v aplikacnim repozitari, ale o configuration drift a precedence chybu mezi YAML fallbackem, chartem a live workloadem.

### Live stav overeny pres Kubernetes Manager

| Polozka | Overeny stav |
|---|---|
| Cluster | `pccm-sq016-nprod-1.34-3394` |
| Namespace | `ai-log-analyzer` |
| Live image | `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r97` |
| Regular schedule | `*/15 * * * *` |
| Backfill schedule | `0 9 * * *` |
| Threshold schedule | `0 3 * * 0` |
| Posledni sledovane regular runy | Complete, priblizne 4-5 minut |
| Live pristup | `km`; `speedctl` nebyl pouzit |

### Reprodukovatelnost release

- Aplikacni Git `main` je na commitu `647e0cf385e719bb65b218fdafc93b098a039e0b` z 24. 8. 2026 a release historie v Gitu konci pred `r97`.
- Kod odpovidajici `r97` je z velke casti v dirty/untracked worktree, nikoli v jednom cistem zdrojovem commitu.
- Autoritativni GitOps branch stale pinuje image `r97`.
- Tri manifest soubory obsahuji lokalni necommitnute zmeny z predchozi analyzy: `values.yaml`, `templates/cronjob.yaml` a `templates/job-init.yaml`.
- Lokalni opravy report/trace flag contractu, fail-closed trace evidence a Helm wiring nejsou soucasti bezici image `r97`.

To je samostatny release risk. Pred dalsim buildem musi byt zdroj `r97` zachycen v reviewovatelnem commitu nebo tagu; jinak nelze spolehlive dokazat, co se mezi releasy zmenilo.

## Jak to bylo

Tato cast popisuje legacy alert dodany uzivatelem a legacy renderer, ktery v kodu stale existuje.

### Silne stranky legacy formatu

- Uvodni window summary a tabulka umoznily rychly scan vice problemu.
- Titulek a detail ukazovaly konkretnejsi root cause, napriklad `PrimeIssuerServicesSoap#LoadBridgeXmlRequest`, nikoli pouze obecnou exception class.
- Detail obsahoval dominant behavior patterns s pocty.
- Alert obsahoval representative trace pro rychly prechod k dukazu.
- Aplikace, namespace, trend a raw errors byly vedle sebe a operator nemusel skladat informaci z nekolika karet.

### Slabe stranky legacy formatu

- Primary impact byl casto raw ERROR count, ne pocet unikatnich operation occurrences.
- Jeden business request mohl vytvorit nekolik wrapper/downstream ERROR radku a pusobit jako nekolik incidentu.
- Behavior nebo Known Peak kontext mohl obsahovat historicke/agregovane patterns, aniz bylo zretelne oddeleno current window a historie.
- Reporting unit byl casto fingerprint nebo error class, ne konkretni operational cause.
- Stary format proto nelze pouze zapnout zpet. Jeho citelnost je vhodny vzor, jeho count a causality contract nikoli.

## Jak je to v `r97`

### Aktualni processing flow

1. Elasticsearch vrati vsechny ERROR eventy v half-open 15min okne.
2. Pipeline agreguje fingerprinty a spocita namespace totals.
3. P94/CAP rozhodne, zda je namespace volume neobvykle.
4. Fingerprint family gate vybere jednoho anomalniho ownera namespace peaku.
5. Incidenty se agreguji do problemu a problemy s trace overlapem se mohou sloucit do alert clusteru.
6. Run-level cause families se pripoji pouze tehdy, kdyz jejich trace IDs a raw lines presne pokryji cely alert payload.
7. Pri nesouladu zustane fallback family z alert payloadu bez explicitniho degradation markeru.
8. Policy potlaci test peak, aplikuje state/cooldown/heartbeat/delta/scope pravidla a limit `MAX_PEAK_ALERTS_PER_WINDOW`.
9. Povolenych nekolik payloadu se odesle jako jeden Operator Peak Report digest.
10. Delivery nebo suppression outcomes se ukladaji do `notification_deliveries`.

### Live vysledek prvniho dne

Auditni interval: 30. 9. 2026 09:00 UTC az 1. 10. 2026 08:30 UTC, tj. 11:00 az 10:30 Europe/Prague.

| Metrika | Hodnota |
|---|---:|
| Complete regular runy | 94 |
| Fetched ERROR lines | 13 135 |
| Okna s unikatnim P94/CAP peak ownerem | 4 |
| Unikatni `peak_identifier` | 6 |
| Doručene alert payloady | 1 |
| Potlacene alert payloady | 5 |
| Potlaceni `MochaXTestApp` | 5 |
| Jine suppression duvody | 0 |
| Delivery failures | 0 |

Poznamka: tabulka `detection_events` obsahuje 10 `spike_p93_cap` radku, ale pouze sest unikatnich `peak_identifier`. Fan-out pres fact namespaces vytvari duplicitni radky pro stejnou evidence.

Tato cisla nejsou 24h coverage vsech prostredi. Jsou pouze vysledkem aktualniho `MONITORED_NAMESPACES`:

```text
pca-dev-01-app, pcb-dev-01-app, pcb-ch-dev-01-app,
pca-fat-01-app, pcb-fat-01-app, pcb-ch-fat-01-app
```

Navrhovany nprod monitoring contract je kartesky soucin aplikacnich skupin `pca`, `pcb`, `pcb-ch` a prostredi `dev`, `fat`, `uat`, `sit`, celkem 12 explicitnich namespaces. Zmena seznamu musi invalidovat kompatibilitu stareho threshold snapshotu a vytvorit novy snapshot z historickych dat pro vsech 12 namespaces.

### Live peak windows

| Window Europe/Prague | Raw window | Namespace signal | Unique owners | Policy result |
|---|---:|---|---:|---|
| 30. 9. 15:30-15:45 | 822 | `pcb-fat-01-app`: 431 vs effective 73.08 | 1 | delivered |
| 1. 10. 09:30-09:45 | 2 545 | `pcb-dev-01-app`: 2 200; `pcb-ch-dev-01-app`: 344 | 2 | 2x test suppressed |
| 1. 10. 09:45-10:00 | 724 | `pcb-dev-01-app`: 231; `pcb-ch-dev-01-app`: 492 | 2 | 2x test suppressed |
| 1. 10. 10:00-10:15 | 286 | `pcb-ch-dev-01-app`: 216 | 1 | test suppressed |

Nasledujici okno 10:15-10:30 melo 469 ERROR radku a zadny peak. Detector byl nacten a run byl complete.

### ES overeni uzivatelskych peak kandidatu

Read-only ES agregace pouzila stejnou podminku `level=ERROR`, pevna 15min okna a vsech 12 `dev/fat/uat/sit` namespaces. Potvrdila, ze 30min indicie jsou tvorene konkretnimi 15min spiky:

| Kandidat | Overena 15min evidence Europe/Prague | Co musi target udelat |
|---|---|---|
| 30. 9. cca 13:00 `pcb-ch-sit` 4782/30m | 13:00 obsahuje 4760 ERROR; druhy dil je pouze dojezd | `START`, konkretni cause a impact alert |
| 30. 9. cca 14:30 `pcb-sit` 3204/30m | 14:30=2457, 14:45=747 | `START` a navazujici `CONTINUATION` stejne cause |
| 30. 9. cca 15:00 `pcb-sit` 737/30m | 15:00=226, 15:15=511 | continuation predchozi episode pouze pokud sedi cause signature; jinak novy `START` |
| 30. 9. cca 15:30 vice namespaces cca 2500/30m | 15:30: `pcb-ch-sit`=306, `pcb-dev`=391, `pcb-fat`=431, `pcb-sit`=788, `pcb-uat`=431; jen techto pet tvori 2347 | `EXPANSION`, pokud cause navazuje; jinak vice samostatnych episodes ve stejnem digestu |
| 30. 9. cca 18:00 `pcb-uat` 366/30m | 18:00=281, 18:15=85 | threshold rozhodne peak/non-peak; decision musi byt ulozen a vysvetlitelny |
| 1. 10. cca 07:00 `pcb-ch-sit` 592/30m | 07:00 obsahuje 580 ERROR | `START` nebo recurrence zname cause, nikoli tiche vynechani |
| 1. 10. cca 08:00 `pcb-ch-sit` 4768/30m | 08:00 obsahuje 4756 ERROR | `START`/recurrence a high-impact alert |
| 1. 10. `pcb-dev` 2431 a `pcb-ch-dev` 836/30m | 09:30/09:45: `pcb-dev`=2200+231, `pcb-ch-dev`=344+492 | detekovano, ale nesmi byt kompletne umlceno test-origin policy |

Samotna podobnost casu nebo namespace nestaci k prohlaseni continuation. Rozhoduje prekryv concrete cause signatures, fingerprint variants a operation/trace evidence. Pokud diagnosis neni dostupna, episode muze docasne pokracovat jako `unresolved` pouze pri kratkem gapu a vysokem contributor overlapu; alert musi nizkou confidence priznat.

### Threshold snapshot

| Polozka | Hodnota |
|---|---|
| Snapshot ID | `35ede1b9-690f-4ce2-9cf6-208fbd5e8806` |
| Stav | `complete` |
| Vytvoren | 30. 9. 2026 09:36 UTC |
| Percentile | P94 |
| Population | `namespace/15m/day_of_week/active_windows` |
| Training interval | 9. 9. az 30. 9. 2026 |
| Samples | 3 861 |
| Calculation version | `4.0` |

Aktualni evidence proto nepodporuje okamzite preladeni threshold modelu. Citlivost je nutne posoudit replayem, ne poctem dorucenych e-mailu.

## Rozbor doruceneho alertu

Alert z 30. 9. 2026 15:30-15:45 obsahuje nasledujici odlisne metriky:

| Vrstva | Hodnota | Co skutecne znamena |
|---|---:|---|
| Window fetch | 822 | Vsechny ERROR radky ve vsech monitorovanych namespaces v okne |
| Namespace detector signal | 431 | Vsechny ERROR radky v `pcb-fat-01-app` |
| P94 | 87.0 | Percentile threshold pro trigger namespace a den |
| CAP | 73.08 | CAP pro trigger namespace a den |
| Effective threshold | 73.08 | Nizsi z P94 a CAP pouzity OR pravidlem |
| Namespace/fingerprint candidates | 58 | Pocet fingerprintu, ktere tvorily namespace total 431 |
| Owner fingerprint contribution | 86 | Prispevek anomalniho owner fingerprintu v trigger namespace |
| Owner family threshold | 20 | Median/MAD family gate |
| Owner anomaly score | 4.3x | 86 / 20 |
| Alert/problem aggregate | 160 | Sirsi pocet radku, ktery vstoupil do payloadu a delivery identity |
| Reported operations | 160 | Trace-ID fallback pocet, nikoli span/root-request operation count |
| Amplification | 1.0x | 160 raw / 160 trace-ID fallback occurrences |

### Proc se zobrazi 431, 160 a 86 soucasne

- `431` patri namespace volume gate.
- `86` patri owner fingerprintu v namespace, ktery gate prekrocil.
- `160` patri alert/problem agregatu napric jeho scope.
- `_build_peak_alert_payload` zobrazuje jen namespaces nad `max(100, 1 % total)` a pokud zadny neprojde, ponecha jen top namespace. Proto muze scope zobrazit pouze `pcb-fat-01-app (86)`, i kdyz payload ma 160 radku.
- `_build_cluster_payload` navic muze pricist dalsi souvisejici problem counts pri trace-overlap clusteringu.
- Renderer tyto count domains nepojmenovava, takze vypadaji jako rozpor nebo chyba scitani.

### Proc je cause diagnosticky slaba

- Generic `ServiceBusinessException` je wrapper/classification bucket, nikoli stabilni root cause.
- `operation=unknown-operation` a chybejici outward status nedavaji operatorovi selhanou cestu ani outcome.
- All-or-nothing `_attach_authoritative_cause_families` pri jakemkoli count/trace mismatch tise ponecha fallback family.
- Fallback family odvozuje canonical cause z obecneho alert/problem payloadu a `unique_operations` muze byt jen pocet trace IDs.
- Report nezobrazuje konkretni current-window variants ani vysvetleni, ktere radky patri trigger ownerovi a ktere jsou jen correlated context.

## Overene vady a otevrene hypotezy

### Overene vady

| ID | Vada | Dukaz | Dopad |
|---|---|---|---|
| V1 | Release `r97` nema cisty zdrojovy commit | Live image vs Git `main` a dirty worktree | Nelze spolehlive reviewovat ani reprodukovat image |
| V2 | Jeden pojem `error_count` nese vice count domains | 431 namespace, 86 owner contribution, 160 payload | Alert je auditne nejasny |
| V3 | Namespace display filtr skryva cast payload scope bez labelu | `max(100, 1 %)` plus top-one fallback | `namespace_counts` se nesecte na raw lines a vypada chybne |
| V4 | Generic exception class zustava fallback problem identity | Doruceny `servicebusinessexception` | Operator nevi, co skutecne selhalo |
| V5 | Authoritative cause attach je all-or-nothing a fallback neni oznacen | Presna equality trace IDs a raw lines | Kvalita reportu degraduje potichu |
| V6 | `detection_events` fan-outuje evidence pres fact namespaces | 10 DB radku vs 6 peak IDs; column/evidence namespace mismatch | Audit nadhodnocuje peaky a muze uvadet spatny namespace |
| V7 | Alert cap se aplikuje pred policy suppression | `cluster_index >= max_alerts` pred `_should_send_peak_alert` | Test/suppressed candidate muze obsadit slot actionable alertu |
| V8 | E-mail neukazuje detected/suppressed decision funnel | Pet test peak payloadu je videt pouze v DB/logu | Jeden mail pusobi jako nefunkcni detector |
| V9 | Operation/status extraction casto konci fail-closed jako unknown/N/A | Live regular reporty a doruceny alert | Slaby operational diagnosis |
| V10 | Local trace/report Helm opravy nejsou v live `r97` | GitOps dirty state a live image | Daily/backfill oprava neni dosud dorucena |
| V11 | Runtime namespace override se rozchazi s kanonickou konfiguraci | `config/namespaces.yaml` obsahuje 12 namespaces, ale live `MONITORED_NAMESPACES` a threshold snapshot pouze `dev/fat` | Sest z osmi uzivatelskych kandidatu detector vubec nevidel |
| V12 | Family gate muze zrusit namespace peak | Bez qualified contributor se nevytvori fingerprint peak result | Velky volume signal zmizi, pokud diagnosis neni dostatecne jista |
| V13 | Contributor selection zahazuje platnou evidence | `prepare_namespace_peak_results()` vybere jeden owner na namespace a `_fingerprint_peak_results[owner]` ponecha pouze nejsilnejsi namespace candidate stejneho ownera | Alert nevysvetli vice soucasnych pricin a muze ztratit dalsi namespace peak |
| V14 | Neexistuje persistentni peak episode state nad existujicimi cause facts | `cause_family_facts` persistuji `operational_cause_v1`, ale registry pouziva coarse peak key a `_record_delivered_peak_alerts()` aktualizuje state pouze po delivery | Suppressed, digest-only a failed okna neprenesou continuity; expansion se rozpada nebo chybne spojuje |
| V15 | Test origin je hard suppression | Pet potvrzenych peak payloadu bylo umlceno | Operator nevi o tisicich ERROR radku ani o jejich pricine |
| V16 | Namespace kompatibilita snapshotu neni vynucena ve vsech entry pointech | `threshold_snapshot_guard.decide_refresh()` kontroluje set pri initu, ale regular DB loader a replay bundle neoveruji uplnost proti runtime scope | Job muze pouzit snapshot, jehoz metadata neprokazuji coverage vsech pozadovanych namespaces |

### Co overeno nebylo

- Neni prokazano, ze P94 je prilis vysoky nebo prilis nizky.
- Neni prokazano, ze CAP vypocet zpusobil ztratu actionable peaku.
- Neni prokazano, ze cooldown nebo heartbeat potlacil alert v analyzovanem obdobi.
- Neni prokazano, ze trace extraction v regular alertu selhala; doruceny alert mel 160 trace IDs.
- `1.0x` samo o sobe neni chyba. Muze byt realne, pokud kazda trace obsahuje jeden ERROR radek; zde je ale operation metoda pouze `trace_id`, ne root span.
- Neni prokazano, ze `MochaXTestApp` peaky jsou bezcenne. Proto test origin nesmi byt hard suppression; target ho zobrazi jako klasifikaci a routing signal.
- Neni zatim prokazano, ktere z casove navazujicich `sit` spiku maji stejnou cause. To musi rozhodnout replay cause signatures, nikoli pouhy soucet za 30 minut.

## Cilovy stav

### Oddelene vrstvy rozhodnuti

1. **Namespace signal:** Je celkovy ERROR volume namespace neobvykly?
2. **Anomalous contributor:** Ktery fingerprint/family konkretne vzrostl proti vlastni historii?
3. **Operational cause:** Co je canonical cause, root app, operation a outward status?
4. **Business impact:** Kolik operation occurrences selhalo a kolik ERROR radku vytvorily?
5. **Episode correlation:** Je to start, continuation, expansion, escalation, recovery nebo recurrence predchoziho problemu?
6. **Notification policy:** Jak se rozhodnuti zobrazi a kam se odesle?

Kazda vrstva musi mit vlastni datovy typ a vlastni pojmenovane metriky. `error_count` bez qualifieru nebude soucasti noveho payload contractu.

### Peak episode contract

```text
window_decision_id = hash(stream_key + signal_namespace + window_start_utc + detector_version + threshold_snapshot_id)
cause_signature = existing operational_cause_v1(root_app + canonical_cause + operation + outward_status)
episode_id = immutable UUID vytvorene pri START/RECURRENCE; scope ani count nejsou soucast identity
correlation_version = explicitni verze algoritmu ulozena u kazde episode-window vazby
```

Jeden namespace decision muze prispet do vice cause episodes, pokud ma vice anomalnich contributors. `peak_episode_windows` proto uklada vazbu `window_decision_id + episode_id + cause_signature`, alokovane raw lines a reconciliation confidence. Neprirazene radky zustanou explicitne `unexplained`; nesmi se zapocitat do dvou episodes.

Korelace se pro kazdou current-window cause vyhodnoti deterministicky v tomto poradi:

1. Presny `operational_cause_v1` match na otevrenou episode je primary evidence.
2. Pokud je status nebo operation na jedne strane `unknown`, lze pouzit provisional match jen pri shodnem root app + canonical cause a silnem contributor/fingerprint overlapu. Duvod a confidence se ulozi; samotna casova blizkost nestaci.
3. Bez spolehlive cause lze unresolved episode prodlouzit pouze do bezprostredne navazujiciho 15min okna se silnym contributor overlapem. Jakmile evidence prestane sedet, vznikne novy `START`; zadny coarse `category + flow + peak_type` auto-merge.
4. Stejna cause a stejny scope je `CONTINUATION`. Novy namespace/app je `EXPANSION`. Materialne horsi impact/outcome je `ESCALATION`. Pokud nastane expansion i escalation, primary state je `EXPANSION` a oba duvody zustanou v `material_change_reasons`.
5. Non-peak okno otevrenou episode neposouva jako detekovany peak; tvori `RECOVERY` observation. Po schvalenem poctu po sobe jdoucich non-peak oken se episode uzavre jako `RESOLVED`; pozdejsi stejna cause je `RECURRENCE` s novym `episode_id`.

Korelace pracuje vyhradne s UTC half-open okny `[start, end)`. `Europe/Prague` je display timezone, nikoli soucast identity. Processing-time poradi ani pozdni replay nesmi menit vysledek: upsert stejneho `window_decision_id` musi byt idempotentni a transition timeline se pri replayi prepocita deterministicky podle event time.

| Episode state | Podminka | Alert behavior |
|---|---|---|
| `START` | Nova cause nebo zadna kompatibilni otevrena episode | Vzdy viditelny alert |
| `CONTINUATION` | Stejna cause v nasledujicim 15min okne | Soucast digestu; samostatny update pri materialni zmene/heartbeat |
| `EXPANSION` | Stejna cause zasahla novou namespace/aplikaci | Vzdy alert update se scope delta |
| `ESCALATION` | Vyrazne roste impact/ratio nebo se zhorsi outward outcome | Vzdy alert update |
| `RECOVERY` | Signal klesa, ale episode jeste neni uzavrena | Digest/status update |
| `RESOLVED` | Definovany pocet po sobe jdoucich non-peak oken | Jedno uzavreni s duration a cumulative impact |
| `RECURRENCE` | Známá historicka cause po uzavreni predchozi episode | Novy episode ID, link na knowledge/previous episode |

Episode state se aktualizuje pro kazdy detected decision bez ohledu na to, zda notification delivery uspela nebo zda policy zvolila digest-only zobrazeni. `Known Problem` a `continuing episode` jsou dve ruzne informace a nesmi se zamenovat.

### Cilovy count contract

| Field | Vyklad |
|---|---|
| `window_raw_error_lines` | Vsechny fetched ERROR lines v okne |
| `signal_namespace_raw_lines` | Namespace total vyhodnoceny proti P94/CAP |
| `owner_namespace_raw_lines` | Prispevek owner fingerprintu v trigger namespace |
| `owner_scope_raw_lines` | Stejny owner fingerprint napric presne definovanym current scope |
| `cause_family_raw_lines` | Radky prirazene konkretni cause family |
| `correlated_context_raw_lines` | Dalsi wrapper/downstream radky na stejne operation, explicitne oddelene |
| `unique_operation_occurrences` | `trace_id + root_span_or_request_boundary`; fallback je oznacen metodou/confidence |
| `amplification` | `cause_family_raw_lines / unique_operation_occurrences` |
| `unexplained_raw_lines` | Zbytek, ktery nelze korektne priradit |

### Povinne invarianty

```text
signal_namespace_raw_lines = sum(all fingerprint contributions in signal namespace)
owner_namespace_raw_lines <= signal_namespace_raw_lines
sum(cause_family_raw_lines) + unexplained_raw_lines = owner/correlated scope declared by payload
displayed namespace/app counts are either complete or explicitly labelled Top N + omitted count
current-window counts are never mixed with historical Known Peak counts
representative trace belongs to the displayed cause family
suppressed + skipped + delivered + failed accounts for every notification candidate
```

### Cilovy digest

Prvni obrazovka bude opet scan-friendly jako legacy alert, ale s korektnimi metrikami:

```text
PEAK WINDOW 30. 9. 2026 15:30-15:45
822 raw ERROR lines | 1 namespace peak | 1 actionable | 0 suppressed

Signal: pcb-fat-01-app 431 vs effective 73.08 (P94=87, CAP=73.08, 5.9x)
Owner: <concrete family> 86/431 namespace lines | 160 owner-scope lines

Impact  Assessment  Cause                         Root app  Ops  Raw  Amp  Outcome
HIGH    BUSINESS    <canonical concrete cause>    <app>     N    M    Xx   <operation/status>
```

Per-family detail bude obsahovat pouze:

1. Why alerted: namespace signal, owner contribution, family threshold a snapshot provenance.
2. What failed: canonical cause, root app, operation a outward status.
3. Impact: operations, family raw lines, amplification a evidence coverage.
4. Current patterns: pouze current-window variants s pocty.
5. Representative trace: trace patrici family.
6. Assessment/confidence a konkretni next action.

Kazdy detail musi oddelit runtime stav `NEW EPISODE`/`CONTINUATION`/`EXPANSION` od knowledge match `KNOWN PROBLEM`/`NEW CAUSE`. Pri nedostatecne diagnosis se alert nezahodi: zobrazi `UNDIAGNOSED`, top contributors, confidence, unexplained count a konkretni dalsi krok.

Na konci digestu bude decision summary, napriklad `6 peak decisions / 4 episodes: 2 START, 1 EXPANSION, 3 CONTINUATION; 3 primary updates, 3 digest-only; 0 failed`. Test-origin episodes budou oznacene podilem a originatorem, nikoli skryte jako `test-suppressed`.

## Solutions

### Vybrane reseni

Zachovat 15min namespace P94/CAP jako volume gate, rozsirit jej na uplny monitoring scope a zavest explicitni `NamespacePeakDecision`, `PeakEpisode` a `AlertCandidate` contract. Family analysis peak vysvetluje, ale nesmi ho zrusit. Renderer bude hybrid: legacy tabulka a konkretni patterns, soucasne threshold evidence, episode timeline, operation counts, amplification a current/history separation.

### Zamítnute zkratky

1. **Pouze zapnout legacy renderer**
   - Vyhoda: okamzite citelnejsi e-mail.
   - Nevyhoda: vrati raw-count impact a nejasne current/historical behavior.

2. **Snizit P94 nebo CAP bez replaye**
   - Vyhoda: vice peak kandidatu.
   - Nevyhoda: neresi pet prokazane potlacenych test peak payloadu ani kvalitu jedineho doruceneho alertu; muze pouze zvysit sum.

3. **Posilat kazde continuation okno jako samostatny e-mail**
   - Vyhoda: nic se neschova.
   - Nevyhoda: stejna episode vytvori opakovany sum. Target posila kazdy `START/EXPANSION/ESCALATION`, ale stabilni continuation konsoliduje do digestu a heartbeat.

4. **Jen upravit HTML/CSS**
   - Vyhoda: mala zmena.
   - Nevyhoda: 431/160/86 a generic cause jsou payload/data-contract vady, ne kosmetika.

## Implementation

### Phase 0: Reproducible baseline a oddeleni existujicich zmen

1. Zachytit skutecny zdroj `r97` v cistem commitu/tagu a ulozit image digest plus source revision.
2. Oddelit drive implementovane, ale nenasazene daily/backfill trace opravy do samostatneho reviewable commitu/PR:
   - report flag dedi trace analysis,
   - invalidni report=true/trace=false failne,
   - chybejici timelines pri dostupnych trace IDs failnou,
   - operation count bez coverage se renderuje jako `N/A`,
   - Helm wiring pro regular/backfill/init,
   - required Confluence Recent Incidents page ID.
3. Teprve nad cistym baseline implementovat tento plan.
4. Pridat source commit a dirty-state guard do build metadata; release build z dirty worktree musi failnout.

### Phase 1: Complete namespace coverage and threshold bootstrap

1. Zachovat `config/namespaces.yaml` jako kanonicky aplikacni contract 12 namespaces `pca/pcb/pcb-ch x dev/fat/uat/sit`.
2. Zavest jeden sdileny loader/validator pro fetch, threshold training, init guard, regular job a replay. Runtime `MONITORED_NAMESPACES` muze kanonicky seznam dodat, ale pri chybejici, navic nebo preklepene namespace musi workload failnout s diffem; nesmi tise prepsat scope na sest hodnot.
3. Odstranit rozdil mezi `_load_monitored_namespaces()` s YAML fallbackem a `calculate_peak_thresholds.load_monitored_namespaces()` zavislym jen na env. Vsechny entry pointy musi logovat stejny normalized namespace contract hash.
4. Renderovat explicitnich 12 hodnot v lokalnim chartu i autoritativnim GitOps values a pridat CI test, ktery oba deployment contracty porovna s `config/namespaces.yaml`.
5. Zachovat existujici namespace comparison v `threshold_snapshot_guard.decide_refresh()`, ale stejnou kontrolu pridat i do regular DB loaderu a replay bundle metadata. Snapshot bez presneho setu 12 namespaces je incompatible, nikoli partial fallback.
6. Vytvorit fresh P94/CAP snapshot z historickych 15min dat vcetne `sit/uat`; regular job se nesmi spustit, dokud complete snapshot nema stejny contract hash.
7. Pred aktivaci alertu replayovat uvedenych osm kandidatu a reprezentativni normalni okna pro kazdou namespace.

### Phase 2: First-class peak decision ledger

1. Povyšit existujici `phase_c.namespace_peak_audit` na strukturovany `NamespacePeakDecision`; threshold rozhodnuti se nesmi pocitat podruhe v alert builderu.
2. Pro kazdy complete 15min run persistovat prave jeden decision pro kazdou z 12 namespaces, vcetne nuly/non-peak, s `verdict_reason` (`below_min_volume`, `below_threshold`, `peak_diagnosed`, `peak_undiagnosed`). To umozni vysvetlit i kandidata 5 a recovery okna.
3. Pouzit idempotentni unique key `(stream_key, window_start_utc, signal_namespace, detector_version, threshold_snapshot_id)` a stabilni `window_decision_id`. `run_id` je provenance posledniho/uspesneho materialization attemptu, nikoli soucast logical identity; retry s novym run ID musi upsertnout stejny decision. `peak_identifier` zustane citelny external correlation key pouze pro peak verdict.
4. Oddelit namespace decision od contributor rows. Ulozit vsechny `family_decisions` s contribution, threshold, anomaly score, method a `is_anomalous`; `detection_events` ponechat jako legacy evidence, ne zdroj pravdy.
5. Namespace decision zustava `is_peak=true`, i kdyz diagnosis vrati `family_baseline_unavailable` nebo `no_anomalous_family`. Family gate nesmi byt veto volume signalu a alert se oznaci `UNDIAGNOSED`.
6. Zrusit loss pri `_fingerprint_peak_results[owner]`: alert candidate se vytvari z decision + vsech anomalnich contributors, ne z jedineho owner resultu globalne klicovaneho fingerprintem.
7. Decision ulozit pred problem aggregation, episode correlation a notification policy. Do run summary ulozit funnel counts: evaluated namespaces, peaks/non-peaks, diagnosed/undiagnosed peaks, contributors, episodes, alert candidates, policy outcomes, delivery outcomes a failures.

### Phase 3: Persistent 15-minute peak episodes

1. Reuse `cause_family_facts` a `CAUSE_SIGNATURE_VERSION=operational_cause_v1`; nevytvaret druhy odlisny hash v episode modulu. Signature version presunout k owning cause modelu a ulozit ji u episode i window vazby.
2. Pridat `peak_episodes`, immutable `peak_episode_windows` a append-only `peak_episode_transitions`. Vazba nese decision, cause signature, contributor IDs, alokovane raw lines, correlation method/version a confidence.
3. Implementovat korelacni poradi z `Peak episode contract`; `category + flow + peak_type` ani samotny lookback nejsou episode identity.
4. Udrzovat state `START`, `CONTINUATION`, `EXPANSION`, `ESCALATION`, `RECOVERY`, `RESOLVED` a `RECURRENCE` a prenaset previous/current/cumulative impact, scope, diagnosis, representative evidence a confidence.
5. Episode transition a vazby ulozit v jedne DB transakci po decision/cause facts a pred notification policy. Unique constraints plus per-stream DB lock musi zabranit dvojimu START pri retry nebo soubehu.
6. Oddelit `stream_key` pro live, shadow a historical replay, aby validacni replay nemenil live continuity. Opakovany replay stejnych event-time oken musi dat stejne transitions a cumulative counts.
7. Aktualizovat episode pro test-origin, digest-only, route-suppressed a failed-delivery candidates. `_record_delivered_peak_alerts()` zustane delivery/cooldown stavem a nesmi byt zdrojem episode continuity.
8. Oddelit historical Known Problem match od runtime episode continuity. `KNOWN PROBLEM` je enrichment stejne episode, nikoli dukaz continuation.
9. Non-peak decisions pouzit pro `RECOVERY`/`RESOLVED` podle schvaleneho gapu; kratky pokles nesmi automaticky vytvorit novy problem.

### Phase 4: Owner-bound cause correlation

1. Stavet alert candidate z `NamespacePeakDecision` a vsech anomalnich contributors, ne z celeho `ProblemAggregate` bez puvodniho detector scope.
2. Zachovat tri oddelene scope: signal namespace, contributor fingerprint a correlated operation context.
3. Cause families prirazovat po event/trace membership s explicitnim reconciliation vysledkem.
4. Nahradit all-or-nothing authoritative attach stavem `complete`, `partial` nebo `degraded`.
5. Pri `partial` zobrazit prirazene families a `unexplained_raw_lines`; nikdy tise nespadnout na generic wrapper jako by byl autoritativni.
6. Generic `ServiceBusinessException` pouzit pouze jako fallback bucket. Pokud existuje concrete canonical cause, musi byt title/identity konkretni cause.
7. Pokud jeden contributor obsahuje vice konkretnich causes, zobrazit oddelene cause-family rows.

### Phase 5: Operation and outcome evidence

1. Zachovat fail-closed `N/A`, pokud root/request boundary nelze obhajit.
2. Zlepsit span/root-request korelaci pro regular current-window traces.
3. U operation count vzdy zobrazit metodu `root_span`, `trace_id`, `mixed` nebo `unavailable` a confidence.
4. Outward status odvozovat pouze z eventu ve stejne operation occurrence; chybejici status nesmi byt doplnen historickym Known Error kontextem.
5. Representative trace musi projit family/scope membership validaci.

### Phase 6: Hybrid operator renderer

1. Obnovit compact summary tabulku z legacy formatu.
2. Zachovat presnou threshold evidence ze soucasneho rendereru.
3. Pridat explicitni sloupce operations, raw lines, amplification, root app, operation/status, assessment a trend.
4. Pridat current-window patterns s pocty; historical knowledge zobrazit v samostatnem bloku.
5. Zobrazit `Top N of M` a omitted raw count vs skryte filtrovani scope.
6. Zobrazit episode state, duration, previous/current/cumulative counts a presnou scope delta.
7. Zobrazit segmentation/reconciliation quality a degradation reason.
8. V subjectu zachovat episode state, konkretni cause/window a nejvyssi assessment, ne generic `Operator Peak Report`.

### Phase 7: Notification policy ordering and observability

1. Kazdy `START`, `EXPANSION` a `ESCALATION` musi byt viditelny v primary alert channel; zadna source aplikace ho nesmi hard-suppressnout.
2. `MochaXTestApp` a jiny test origin zobrazi label, podil na peaku a muze ovlivnit severity/routing, ale neexistenci alertu.
3. Stabilni `CONTINUATION` konsolidovat do digestu; znovu odeslat pri materialni count/cause/outcome zmene nebo heartbeat.
4. `MAX_PEAK_ALERTS_PER_WINDOW` zmenit na detail limit, ne omission limit: digest musi obsahovat vsechny episodes, i kdyz detail ma jen top N.
5. Radit episodes podle state, assessment, namespace ratio, operation impact, novelty a confidence.
6. Cooldown klicovat episode ID; expansion/escalation musi cooldown obejit.
7. Pred jakymkoli detail limitem vytvorit a persistovat `NotificationDecision` pro kazdou episode update. Terminal policy outcome je prave jeden z `primary_send`, `digest_only`, `route_suppressed` nebo `no_material_change`; test-origin neni terminal suppression reason.
8. Provider delivery je samostatny outcome (`delivered`, `failed`, `not_attempted`) vazany na notification decision. Failed delivery nesmi zmenit episode state ani se vydavat za policy suppression.
9. Nahradit delivery-only continuity v `_record_delivered_peak_alerts()` episode state z DB. JSON alert state ponechat pouze pro channel cooldown/heartbeat a po migraci jej nechat rebuildovat z delivery ledgeru.
10. Pridat window summary `evaluated namespaces / detected peaks / open episodes / started / continued / expanded / primary sends / digest-only / delivered / failed`.

### Phase 8: Threshold sensitivity az po replayi

1. Replayovat nejmene 7, 14 a 28 dni complete facts pro vsech 12 namespaces se stejnou 15min granularitou.
2. Porovnat namespace decisions, episodes, diagnosis coverage, alert classifications a delivery outcomes.
3. Oddelene vyhodnotit jednotliva prostredi a test-origin podil; prostredi se nesmi v threshold population michat.
4. Teprve nad reviewovanou precision/recall sadou rozhodnout o `PERCENTILE_LEVEL`, CAP metode, minimum samples a family threshold.
5. Kazda zmena threshold modelu musi vytvorit novou `calculation_version` a fresh snapshot; nesmi se schovat jako renderer fix.

## Files to Modify

| Soubor | Planovana zmena |
|---|---|
| `scripts/core/namespace_contract.py` (new) | Jediny loader, normalization, contract hash a strict env/YAML diff |
| `scripts/core/fetch_unlimited.py` | Pouzit sdileny namespace contract pro ES fetch |
| `scripts/core/calculate_peak_thresholds.py` | Odstranit env-only loader a trenovat pres stejny namespace contract |
| `scripts/core/threshold_snapshot_guard.py` | Reuse namespace comparison a contract hash v init/runtime/replay preflightu |
| `scripts/core/peak_detection.py` | Explicitni threshold result/provenance a runtime snapshot scope validation |
| `scripts/pipeline/phase_c_detect.py` | Povyšit `namespace_peak_audit` na decisions; zachovat vsechny contributors a odstranit owner-keyed loss |
| `scripts/core/peak_decision.py` (new) | Typy, validace a idempotentni persistence namespace decisions/contributors |
| `scripts/core/peak_episode.py` (new) | Versionovana korelace, lifecycle transitions, cumulative state a replay stream isolation |
| `scripts/core/run_persistence.py` | Persistovat decision/cause/episode facts ve spravnem poradi; `detection_events` zustava legacy evidence |
| `scripts/migrations/010_peak_decision_episode_ledger.sql` (new) | `namespace_peak_decisions`, contributors, episodes, windows, transitions, notification decisions a constraints |
| `scripts/regular_phase.py` | Decision/episode orchestrace, contributor-bound candidates, partial cause attach a policy funnel pred detail capem |
| `scripts/analysis/operational_cause.py` | Vlastnit `operational_cause_v1` version a event/trace membership mezi contributorem a cause family |
| `scripts/core/problem_registry.py` | Odebrat runtime continuity odpovednost; ponechat historical known-problem enrichment |
| `scripts/core/delivery_persistence.py` | Vazba provider outcomes na notification decision; presne jeden terminal delivery outcome per destination |
| `scripts/analysis/trace_timeline.py` | Operation boundary a outward outcome evidence |
| `scripts/core/email_notifier.py` | Hybrid scan-friendly operator digest a suppression summary |
| `scripts/replay_48h.py` | Parametricky 24h+ replay, candidate manifest, decisions/episodes/policy funnel a count reconciliation |
| `scripts/tests/test_namespace_contract.py` (new) | 12-namespace env/YAML/chart shoda a strict mismatch failure |
| `scripts/tests/test_peak_decision_ledger.py` (new) | Vsech 12 verdictu, deduplikace, all-contributor preservation a idempotence |
| `scripts/tests/test_peak_episode_correlation.py` (new) | Cause-driven transitions, unresolved fallback, recovery, recurrence, retry a replay determinismus |
| `scripts/tests/test_peak_digest_r88.py` | Payload, renderer, cap ordering a policy regression testy |
| `scripts/tests/test_peak_threshold_training.py` | Snapshot provenance a replay sensitivity testy |
| `scripts/tests/test_regular_phase_replay.py` | End-to-end window to decision ledger to digest |
| `scripts/tests/test_postgres_integration.py` | Unique decision persistence a namespace correctness |
| `scripts/tests/test_operator_problem_report.py` | Partial/degraded cause evidence a operation count semantics |
| `scripts/tests/fixtures/peak_episode_2026-09-30_2026-10-01.json` (new, sanitized) | Osm candidate groups, presna UTC okna, 15min namespace totals a ocekavane invarianty bez produkcnich messages |
| `k8s/values.yaml` | Pokud lokalni chart zustava podporovany, nahradit placeholder presnym 12-namespace contractem a drzet jej v CI shode |
| External `infra-apps/ai-log-analyzer/values.yaml` | Autoritativni 12-namespace runtime override, episode/policy konfigurace a explicitni test-origin mode |
| External `infra-apps/ai-log-analyzer/templates/cronjob.yaml` | Stejny namespace contract a episode flags pro regular/backfill/threshold workloads |
| External `infra-apps/ai-log-analyzer/templates/job-init.yaml` | Fresh snapshot guard, contract hash, source/version metadata a trace opravy |

## Testing

### Traceability matice zadanych kandidatu

| ID | 30min indicie od operatora | Povinne 15min rozhodnuti | Episode a alert oracle |
|---|---|---|---|
| 1 | 30. 9. cca 13:00 `pcb-ch-sit`, 4 782 | Alespon jeden `is_peak=true`; overena dominantni ctvrt-hodina 4 760 | `START` nebo `RECURRENCE`, primary update, concrete cause nebo explicitni `UNDIAGNOSED` |
| 2 | 30. 9. cca 14:30 `pcb-sit`, 3 204 | 2 457 a 747 vyhodnotit oddelene | Prvni peak `START`; druhy je `CONTINUATION` jen pri shodne cause, jinak novy `START` |
| 3 | 30. 9. cca 15:00 `pcb-sit`, 737 | 226 a 511 vyhodnotit oddelene a oba verdicts ulozit | Shodna cause muze pokracovat z ID 2; jina cause je novy `START`; non-peak je `RECOVERY` observation, nikdy tiche vynechani |
| 4 | 30. 9. cca 15:30, vice namespaces, cca 2 500 | Persistovat decision pro kazdou namespace; overenych pet totals tvori 2 347 | Shodna cause v novem scope je `EXPANSION`; rozdilne causes jsou soubezne episodes; vsechny jsou v summary |
| 5 | 30. 9. cca 18:00 `pcb-uat`, 366 | 281 a 85 maji auditni peak/non-peak verdict | Zadani jej nevnucuje jako peak; threshold evidence musi vysvetlit vysledek a pripadnou recovery |
| 6 | 1. 10. cca 07:00 `pcb-ch-sit`, 592 | Alespon jeden `is_peak=true`; overena dominantni ctvrt-hodina 580 | `START` nebo `RECURRENCE`, primary update a known/new knowledge label |
| 7 | 1. 10. cca 08:00 `pcb-ch-sit`, 4 768 | Alespon jeden `is_peak=true`; overena dominantni ctvrt-hodina 4 756 | Primary update; nesmi byt pohlcen pouze casovym lookbackem predchozi episode |
| 8 | 1. 10. `pcb-dev` 2 431 a `pcb-ch-dev` 836 | Zachovat `2200+231` a `344+492` jako dve namespace timelines po 15min | Cause-driven continuation/expansion; `MochaXTestApp` label je viditelny a neni hard suppression |

Release oracle neni presne sest nebo osm e-mailu. Musi ale obsahovat peak decisions pro povinne skupiny 1, 2, 4, 6, 7 a 8 a auditni verdict pro vsech osm skupin. Pokud se vice skupin spoji do jedne cause episode, timeline musi stale ukazat kazde puvodni 15min decision a kazdy `EXPANSION`/`ESCALATION` update.

### Sanitizovana regression fixture z live okna

Fixture musi zachovat tyto auditni hodnoty bez produkcnich message payloadu:

| Field | Expected |
|---|---:|
| Window raw | 822 |
| Signal namespace raw | 431 |
| P94 | 87.0 |
| CAP/effective | 73.08 |
| Contributing fingerprints | 58 |
| Owner namespace contribution | 86 |
| Owner threshold | 20 |
| Owner anomaly score | 4.3 |
| Alert aggregate scope | 160 |

Expected assertion: renderer zobrazi vsechny tri count domains s labely a zadny z nich nevydava za jiny. Namespace/app scope bud reconciliuje, nebo explicitne zobrazi omitted/unexplained count.

### Povinne unit/integration testy

- [ ] Jedno `peak_identifier` vytvori jeden namespace decision row i kdyz owner fingerprint existuje ve vice namespaces.
- [ ] `detection_events.namespace` nebo novy ledger field odpovida `evidence.details.namespace`.
- [ ] `sit/uat` namespaces jsou ve fetchi, baseline i stejnem complete threshold snapshotu jako `dev/fat`.
- [ ] Runtime namespace override s chybejici nebo navic namespace failne pred fetchem a vypise set diff; regular DB/replay snapshot se stejnym mismatch take failne.
- [ ] Kazdy complete event-time window ulozi 12 namespace decisions vcetne non-peak verdicts; retry s jinym `run_id` ve stejnem streamu nevytvori dalsi radky, stejny window v shadow/replay streamu je izolovany.
- [ ] Namespace peak bez anomalni family ownera zustane peakem a alertuje jako undiagnosed se snizenou confidence.
- [ ] Vsechny anomalni contributors jsou zachovany; dominantni contributor nerusi ostatni.
- [ ] Stejny anomalni fingerprint ve dvou namespaces vytvori dva namespace decisions a muze vytvorit `EXPANSION`; zadny candidate se neprepise v owner-keyed dictu.
- [ ] Dve sousedni okna se stejnou cause sdili episode ID a druhe je `CONTINUATION`.
- [ ] Stejna cause v nove namespace vytvori `EXPANSION`, jina cause vytvori novy `START`.
- [ ] Pouha shoda casu, category/flow nebo 60min lookback bez cause/contributor evidence episodes neslouci.
- [ ] Provisional unresolved match plati nejvyse pro bezprostredne navazujici okno a nese low confidence/reason.
- [ ] Expansion a escalation ve stejnem okne maji deterministicky primary state a oba material-change reasons.
- [ ] Dve non-peak okna uzavrou episode podle schvaleneho defaultu; pozdejsi stejna cause vytvori `RECURRENCE` s novym ID.
- [ ] Live, shadow a replay streamy se navzajem neovlivni; out-of-order retry/replay vrati stejnou timeline a cumulative counts.
- [ ] Suppressed-route nebo failed-delivery okno aktualizuje episode continuity.
- [ ] Tri test-origin candidates a ctvrty non-test candidate jsou vsechny viditelne i pri detail limitu 3.
- [ ] Pet `MochaXTestApp` candidates ma label a policy evidence; zadny neni uplne skryt.
- [ ] Cooldown, heartbeat, delta a scope-change reasons maji samostatne testy.
- [ ] Cause attach mismatch vytvori `partial/degraded`, nikoli tichy generic fallback.
- [ ] Dve concrete causes pod `ServiceBusinessException` vytvori dve cause-family rows.
- [ ] Trace-ID fallback je oznacen jako fallback a nevydava se za root-span count.
- [ ] App/namespace Top N zobrazi total entities a omitted raw count.
- [ ] Representative trace patri zvolene family a signal/owner scope.
- [ ] Digest obsahuje detected, delivered, suppressed, omitted a failed counts.
- [ ] User evidence fixture zachova `pcb-dev 2200+231=2431` a `pcb-ch-dev 344+492=836` jako dve 15min episode timelines, nikoli 30min detection bucket.
- [ ] Candidate fixture splni traceability matici: sest povinnych peak groups, osm auditnich verdictu a cause-driven states bez 30min detection logiky.
- [ ] Current-window a historical Known Peak counts se nikdy nescitaji.
- [ ] Release build failne na dirty source tree a publikuje commit plus image digest.

### Replay a shadow validation

1. Spustit deterministic replay nad immutable complete runs bez odesilani.
2. Pro stejna okna vyrenderovat legacy, `r97` a target payload vedle sebe.
3. Reconcile namespace totals s `namespace_error_counts` a owner contribution s fingerprint facts.
4. Reconcile cause-family raw lines s current-window source count.
5. Manualne reviewovat vsech osm uzivatelskych kandidatu po 15min oknech a reprezentativni non-peak windows.
6. Zmerit, kolik decisions tvori start, continuation, expansion, escalation, recovery, diagnosed a undiagnosed peak.
7. Udelat owner review dominantnich test a business rejection families.

### Focused prikazy po implementaci

```bash
python3 -m pytest -q scripts/tests/test_namespace_contract.py
python3 -m pytest -q scripts/tests/test_peak_decision_ledger.py
python3 -m pytest -q scripts/tests/test_peak_episode_correlation.py
python3 -m pytest -q scripts/tests/test_peak_digest_r88.py
python3 -m pytest -q scripts/tests/test_regular_phase_replay.py
python3 -m pytest -q scripts/tests/test_peak_threshold_training.py
python3 -m pytest -q scripts/tests/test_operator_problem_report.py
python3 -m pytest -q scripts/tests/test_postgres_integration.py
helm lint infra-apps/ai-log-analyzer
helm template ai-log-analyzer infra-apps/ai-log-analyzer
```

## Acceptance Criteria

### Detector a audit

- [ ] Operator umi za libovolnych 24 hodin a vsech 12 namespaces odpovedet: kolik 15min namespace peak signalu vzniklo, do kolika episodes patri, co je zpusobilo a jak byl kazdy alert dorucen.
- [ ] DB count unikatnich peak decisions odpovida poctu unikatnich `peak_identifier` bez fan-out duplicit.
- [ ] Signal namespace je konzistentni ve strukturovanych fields, logu i alertu.
- [ ] Snapshot ID, age, population grain, Pxx, CAP a effective threshold jsou dostupne pro kazdy namespace decision.
- [ ] Traceability matice projde: skupiny 1, 2, 4, 6, 7 a 8 obsahuji peak decision a vsech osm skupin ma dohledatelny 15min verdict.
- [ ] Uvedene `sit/uat` spiky se v replayi objevi jako namespace decisions; 18:00 `pcb-uat` ma vysvetlitelny peak/non-peak verdict.
- [ ] Casove navazujici okna se spoji pouze pri cause evidence; 30min soucet se nepouziva jako detekcni pravidlo.
- [ ] Kazdy detected decision je mapovany na episode/cause allocation nebo explicitni undiagnosed/unexplained stav; nic se neztrati mezi detector, policy a delivery ledgerem.

### Alert content

- [ ] Zadny alert nepouzije generic wrapper jako hlavni cause, pokud current evidence obsahuje concrete cause.
- [ ] Window total, namespace total, owner contribution, family raw a operations jsou oddelene a pojmenovane.
- [ ] Scope counts se reconciliuji nebo explicitne ukazuji omitted/unexplained count.
- [ ] Operation/status je evidence-based; pri nedostatku dukazu je `N/A` s duvodem.
- [ ] Prvni obrazovka obsahuje scan-friendly tabulku a detail obsahuje current patterns plus representative trace.

### Notification policy

- [ ] Detail limit nikdy nezpusobi vynechani episode ze summary nebo delivery ledgeru.
- [ ] Test origin je defaultne viditelny alert label, nikoli hard suppression.
- [ ] `START`, `EXPANSION` a `ESCALATION` vzdy vytvori primary-channel alert; stabilni continuation respektuje material-change/heartbeat policy.
- [ ] Kazdy candidate ma prave jeden terminal policy outcome.
- [ ] Delivery failure se nezameni za policy suppression.
- [ ] Alert samostatne zobrazi runtime episode state a knowledge match `KNOWN PROBLEM`/`NEW CAUSE`; jedno se nepouziva jako nahrada druheho.

### Release a rollout

- [ ] Image je sestaven z cisteho reviewovaneho commitu a publikuje source revision.
- [ ] Target renderer projde shadow replayem bez odesilani.
- [ ] Canary bezi nejmene jeden kompletni provozni cyklus s porovnanim old/new decisions.
- [ ] Rollback prepina pouze renderer/policy contract, nikoli maze persisted evidence.

## Rollout a rollback

1. **Shadow:** persistovat novy decision ledger a target payload, ale odesilat stale `r97` renderer.
2. **Compare:** vytvorit denni diff old/new counts, causes a policy outcomes.
3. **Canary:** zapnout target digest pro jednu explicitni destination nebo review distribuci.
4. **Production:** prepnout primary renderer po schvaleni replay a canary vysledku.
5. **Threshold tuning:** samostatny release az po sensitivity review.

Feature flags musi umoznit nezavisle vratit renderer a notification policy, zatimco novy auditni ledger zustane aktivni. Rollback nesmi vratit duplicitni `detection_events` jako jediny zdroj pravdy.

## Dependencies a review decisions

- [ ] Potvrdit routing/severity policy pro `MochaXTestApp`; volume peak zustava viditelny bez ohledu na routing.
- [x] Target monitoring contract je 12 namespaces `pca/pcb/pcb-ch x dev/fat/uat/sit`; runtime override se s nim musi presne shodovat.
- [ ] Potvrdit default `EPISODE_RESOLVE_NON_PEAK_WINDOWS=2` a heartbeat 120 minut; provisional unresolved match je maximalne jedno bezprostredne navazujici 15min okno.
- [ ] Schvalit count contract a terminologii `signal`, `owner`, `family`, `correlated context` a `operations`.
- [x] Zavest samostatnou `namespace_peak_decisions` tabulku; `detection_events` zustane legacy evidence kvuli odlisne granularite a migracnimu riziku.
- [ ] Potvrdit retention pro per-window decision ledger a replay data.
- [ ] Dokoncit samostatne review lokalnich daily/backfill trace a Helm zmen pred jejich releasem.

## Warnings

> **Nezaměnovat malo e-mailu za malo detekci ani za kompletni coverage.** Sest owneru vzniklo pouze v `dev/fat`; `sit/uat` detector vubec necetl a pet monitorovanych payloadu umlcela policy.

> **Nesnizovat threshold pred opravou observability.** Jinak nebude mozne rozlisit zlepsenou citlivost od narustu test/noise candidates.

> **Nezavadet 30min detector.** Vsechny decisions zustavaji 15min; 30min uzivatelska evidence pouze overuje, ze dvojice navazujicich oken musi tvorit smysluplnou episode timeline.

> **Nevracet legacy counts bez operation modelu.** Citelnost legacy alertu je zadouci; jeho implicitni raw-line impact nikoli.

> **Nestavet dalsi image z dirty worktree.** Bez source revision nelze tento plan ani budouci review uzavrit auditovatelnym diffem.

---

*Vytvoreno: 2026-10-01*
*Aktualizovano: 2026-10-01 po 15min ES replayi `dev/fat/uat/sit`*
*Status: DRAFT - FOR REVIEW, NO IMPLEMENTATION AUTHORIZED*

<!-- Tento plan neobsahuje casove odhady. -->