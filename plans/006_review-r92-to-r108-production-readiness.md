# Revize r92 az r108: cesta zpet k duveryhodnemu produkcnimu analyzatoru

Datum: 2026-10-26. Stav: analyza, bez implementace oprav a bez nasazeni.

## Zaver

**Doporuceni: ponechat produkcni r92 jako provozni referenci, zachovat prinosne diagnosticke zmeny a pripravit mensi stabilizacni release. Soucasnou r108 nepovazovat za produkcne pripravenou.**

Pozadavek neni mit vic detekovanych anomalii. Pozadavek je zachytit podstatny problem, omezit neakcni upozorneni a vysvetlit konkretni pricinu pomoci overitelnych logu. Soucasny vyvoj zlepsil evidenci a reporty, ale neprinesl dukaz lepsi produkcni relevance. Soucasne spojil upgrade s nakladnym bootstrapem a zachoval provozni zavislost na sdilenem RWO volume.

Nasel jsem **1 P1 a 9 P2**. Pet chovani bylo reprodukovano lokalne bez externich sluzeb. Existujicich **152 testu a 2 subtesty prosly**, ale reprodukce ukazaly scenare, ktere tyto testy nepokryvaji.

## Rozsah A Jistota

- Produkcni baseline ve zdrojacich: commit `647e0cf`, jehoz Dockerfile deklaruje r92. Skutecny digest bezici produkcni image jsem nezjistoval.
- Commitnuta aplikace: `10d791f`, r107, lokalni `main` je o jeden commit pred `origin/main`.
- Navic necommitnuta r108: zmeny backfill cleanup, SQLite scratch, testu, Dockerfile a changelogu. Tyto zmeny nebyly pri revizi upraveny.
- GitOps: autoritativni repozitar `~/git/sas/k8s-infra-apps-nprod`, branch `k8s-nprod-3394`, HEAD plus dirty chart pro image r108. Nejde o kopii pod uzivatelskym workspace `sas`.
- Porovnani commitnuteho kodu r92 az r107: 82 souboru, 13 319 pridanych a 1 372 smazanych radku. Velikost zmen sama o sobe neni vada, ale ukazuje, ze neslo pouze o upravu rendereru.
- Git nema release tag r92 ani samostatne zdrojove snapshoty pro kazdou mezilehlou image. Proto nezamenuji revizi zdrojoveho rozsahu za presny audit kazdeho publikovaneho image r93 az r105.
- Cluster, produkcni ES a produkcni DB nebyly kontaktovany. Nove nepotvrzuji pricinu konkretniho FK incidentu, aktualni stav attachmentu, image dostupnost ani produkcni precision/recall.
- Historicke empiricke vysledky nize jsou prevzate z existujicich projektovych analyz, nikoli nove provedene dotazy.

## Nalezy Podle Zavaznosti

### F1: P1 - Init quiesce neresi normalni soubeh regular a backfill nad RWO

**Dukaz:** vyrenderovany chart obsahuje tri konzumenty stejneho `PVC/log-analyzer-data`: `Job/log-analyzer-init`, `CronJob/log-analyzer` a `CronJob/log-analyzer-backfill`. Regular bezi kazdych 15 minut, backfill denne v 09:00 UTC. Oba CronJoby maji vlastni `concurrencyPolicy: Forbid`. Quiesce je pouze Argo `PreSync` hook pred initem.

`Forbid` serializuje instance jednoho CronJobu, nikoli regular proti backfillu nebo initu. RWO znamena zapis z jednoho nodu, ne nutne z jednoho podu. Jakmile dva soucasni konzumenti bezi na ruznych nodech, konflikt je stale mozny. V nprod byl takovy typ incidentu dolozen uz pred touto revizi.

**Dopad:** oprava SQLite a vetsi PVC nevylucuji dalsi `Multi-Attach`. Zamykani v Pythonu, file lock nebo PostgreSQL advisory lock nastavaji az po pripojeni volume a tento problem nevyresi.

**Zmena proti r92:** sdilene uloziste neni nove; delsi/narocnejsi init a nove pre-sync hooky jeho omezeni vic odhaluji. Nejde o dukaz, ze r92 mela spravne vyresenou storage architekturu.

- [ ] Kratkodobe zvolit jednoho vlastnika PVC a serializovat vsechny jeho workloady pred vznikem konkurecniho podu. Pouhe posunuti cron casu neni zaruka.
- [ ] Strednedobe zvazit DB jako autoritu pro mutable registry/alert state; exporty regenerovat a docasna data drzet lokalne. Je to samostatna migrace se zalohou a reconciliaci, ne podminka pro prvni mensi opravu.
- [ ] RWX ani pripnuti na stejny node samy o sobe neresi soubezne zapisovace; nepovazovat je za kompletni opravu.

### F2: P2 - Kazdy release znovu spousti nuceny historicky backfill

**Dukaz:** init je `PreSync` s `BeforeHookCreation`; v aktualnich values ma 10 dni a 4 workery. I pri kompatibilnim threshold snapshotu bezi backfill s `--force`; snapshot guard pouze prepina bootstrap detekci. Nasleduje prepocet thresholdu a verifikace. Backfill zaroven generuje/publikuje reporty a jeho CLI vraci chybu take pri delivery failure.

**Dopad:** bezna zmena reportu se meni v historicky reprocessing, zasah do registry a dlouhe predavani PVC. Selhani Confluence nebo notifikace muze pres `set -e` zastavit init pred threshold trainingem, i kdyz fakta uz byla ulozena. Zdroj: [backfill.py](../scripts/backfill.py#L1247).

**Korekce predchoziho review:** `Job/log-analyzer-resume` s hookem `SyncFail` existuje. Nelze tvrdit, ze chart nema zadnou obnovu CronJobu. Jeji realne provedeni pri timeoutu/abortu a nedostupne nove image zustava predmetem integracniho testu.

- [ ] Oddelit kratke idempotentni schema migrace, bootstrap/training na vyzadani a bezny release.
- [ ] Pri kompatibilnich a kompletnich datech neprovadet desetidenni `--force` backfill.
- [ ] Bootstrap dokonci fakta a snapshot bez zavislosti na dostupnosti wiki/SMTP; publikace ma vlastni retry a stav.
- [ ] Otestovat upgrade i prvni instalaci: PreSync quiesce dnes predpoklada uz existujici PVC, ktere je v chartu beznym Sync resource.

### F3: P2 - Tiche okno ciziho namespace vytvari falesnou eskalaci epizody

**Dukaz:** [peak_episode.py](../scripts/core/peak_episode.py#L326) pri jedine aktivni epizode pouzije i non-peak pozorovani z jineho namespace. To nastavi `RECOVERY`; navrat stejneho peaku pak prida `recovered_signal_returned` a vytvori `ESCALATION`.

**Lokalni reprodukce:** `a-unrelated` ma stale 0, `z-prod` ma ve trech sousednich oknech stale stejnych 50 ERROR radku a stejnou pricinu. Skutecny vysledek:

```text
peak-0  START
quiet-1 RECOVERY
peak-1  ESCALATION recovered_signal_returned
quiet-2 RECOVERY
peak-2  ESCALATION recovered_signal_returned
```

**Dopad:** nemenici se problem muze opakovane vypadat jako zhorseni. To je nova regrese v epizodove vrstve, nikoli vlastnost produkcni r92.

- [ ] Recovery vyhodnocovat nad relevantnim namespace/cause scope celeho okna, ne podle existence jedine epizody v celem streamu.
- [ ] Pridat regresni test s jednim aktivnim namespace a nekolika tichymi namespaces, vcetne zmeny jejich lexikografickeho poradi.
- [ ] Overit take zotaveni vice-namespace epizody a vic soucasnych pricin.

### F4: P2 - Novy median/MAD strop zvysuje citlivost na bezne male cetnosti

**Dukaz:** [calculate_peak_thresholds.py](../scripts/core/calculate_peak_thresholds.py#L175) pouziva minimum configured percentilu a `median + 6 * 1.4826 * MAD`, navic pouze z aktivnich oken.

**Lokalni reprodukce:** populace `90x 1, 8x 2, 2x 100`, percentile 0.94. Puvodni percentilovy vypocet da 2. Novy da 1, protoze MAD je 0. Hodnota 2 tedy nove prekroci namespace threshold, ackoli v r92 jej neprekrocila. Pro stejne populace ve vsech dnech zustane stejne nizky i CAP.

**Dulezita hranice dukazu:** jde o namespace verdict, nikoli dukaz, ze dve chyby automaticky odeslou email. Dalsi fingerprint gate muze alert zastavit. Prave tato kombinace muze ale produkovat mnoho nizkych namespace anomalii a soucasne zahazovat podstatne male cause families.

**Dopad:** outlier-robustnost vhodna pro kontaminovany nprod ocas neni automaticky dobra produkcni kalibrace. U nuloveho MAD navic zvyseni percentilu nemusi nic zmenit.

- [ ] Oddelit cold-start/sparse rezim od datove bohateho baseline a explicitne resit nulove MAD.
- [ ] Zvolit kombinaci absolutniho dopadu, relativni zmeny a relevance; ciselne hodnoty stanovit prod replayem, nikoli kopirovat z nprodu.
- [ ] Zachovat oddelenou cestu pro maly pocet vysoce zavaznych technickych chyb, aby absolutni floor neskryl skutecny incident.

### F5: P2 - Stabilni continuation se stale odesle jako 15min digest

**Dukaz:** policy vraci pro nemenici se continuation `digest_only`, ale [regular_phase.py](../scripts/regular_phase.py#L1645) posle digest pri neprazdnem `digest_payloads`, i kdyz `payloads` pro primary send je prazdne. Aktualni chart ma digest zapnuty.

**Lokalni reprodukce:** kandidat `CONTINUATION` bez materialni zmeny dostal `digest_only`; mock dispatcheru zaznamenal jedno odeslani digestu i s prazdnym seznamem primary alertu.

**Dopad:** cooldown/prevedeni do digestu nemusi snizit pocet mailu. Limit tri detailu navic omezuje podrobnost, nikoli pocet kandidatu nebo frekvenci digestu.

- [ ] Rozlisit incidentni upozorneni pri START/materialni zmene od casovaneho souhrnu stabilnich problemu.
- [ ] Pro samotne stabilni continuation neposilat kazdych 15 minut stejny primarni report; pouzit dohodnuty heartbeat nebo denni souhrn.
- [ ] Testovat pocet realnych volani senderu napric nekolika okny, nejen policy enum jednoho kandidata.

### F6: P2 - Assessment nefunguje jako relevance/routing gate

**Dukaz:** [notification_policy.py](../scripts/core/notification_policy.py#L127) nastavi pro START/RECURRENCE/EXPANSION/ESCALATION `primary_send`. Assessment je pouzity v razeni, nikoli jako podminka relevance. Lokalni kandidat `expected_outcome_logged_as_error` ve stavu START dostal `primary_send`.

**Dopad:** ocekavane CANCELLED/business flow zalogovane jako ERROR muze byt nadale prezentovano jako nove akcni upozorneni. To je v rozporu s hlavnim cilem, i kdyz implementace odpovida svym testum.

- [ ] Dohodnout routing pro technical failure, anomalni business rejection, potvrzeny expected outcome a neznamou pricinu.
- [ ] Expected outcome neposilat stejnou prioritou jako technickou poruchu; unknown nezamlcet, ale priznat nejistotu a odpovidajici nalehavost.
- [ ] Nesupprimovat bez potvrzeni ownerem vsechny 4xx, `not found`, test origin nebo `AccessDenied`; mohou znamenat realnou regresi.

### F7: P2 - Rozpracovana r108 ma rozbitou chybovou vetev registry

**Dukaz:** [backfill.py](../scripts/backfill.py#L1056) pri neuspesnem `update_registry_from_incidents` vraci mimo jine `success_count`, ale tato promenna se inicializuje az nize. Stejne plati pro dalsi agregovana pocitadla.

**Lokalni reprodukce:** mock selhani registry po uspesnem ulozeni faktu vyvolal `UnboundLocalError: cannot access local variable 'success_count' where it is not associated with a value`.

**Dopad:** changelog slibuje uplny chybovy souhrn, ale ve skutecnosti vznikne nova sekundarni vyjimka v ceste, ktera souvisi prave s problemy uloziste. Zmena je pouze v dirty r108, ne v commitnute r107.

- [ ] Pocitadla vypocitat pred prvnim chybovym navratem a pridat test neuspesneho registry save po DB commitu.
- [ ] Zachovat puvodni pricinu chyby a nenulovy exit bez sekundarni vyjimky.

### F8: P2 - Konfigurace a novy ledger jeste nejsou jednim end-to-end kontraktem

**Dukaz:** [phase_c_detect.py](../scripts/pipeline/phase_c_detect.py#L141) ma default namespace minimum 1, fingerprint floor 20 a pro novy fingerprint gate nejmene 50. Helm render potvrdil, ze nastavitelne minimum namespace ani fingerprint floor do tri workloadu nepredava. Chart navic stale monitoruje jen sest dev/fat namespaces; [namespaces.yaml](../config/namespaces.yaml) obsahuje dvanact. Entry-point wrappery zapinaji strict kontrolu jen explicitnim env flagem, ktery chart nema.

Soucasne se ulozi i `peak_undiagnosed`, ale odesilani stale vstupuje pres starsi vyber problemu s `has_spike/has_burst`: [regular_phase.py](../scripts/regular_phase.py#L385). Novy ledger, YAML alert state a problem-centric vyber tedy netvori jeden jednotny rozhodovaci tok.

**Dopad:** v auditnich tabulkach muze existovat namespace signal, ktery neni notifikacnim kandidatem. Pro maly prod problem muze byt fingerprint floor prilis vysoky, zatimco namespace gate je prilis citlivy. Pocet mailu pak nevysvetluje kvalitu detectoru.

- [ ] Zavest explicitni prod/nprod scope a policy profily; neprepnout prod na hardcoded nprod namespace seznam.
- [ ] Stejna env smlouva pro regular, backfill a init, vcetne runtime logu efektivnich hodnot a hash scope.
- [ ] Auditovat funnel: complete windows, namespace signals, cause candidates, relevance decisions, delivery. Nezamitnout namespace signal jen proto, ze diagnoza neni dost dobra.

### F9: P2 - Send, delivery audit a cooldown nejsou odolne proti castecne chybe

**Dukaz:** [regular_phase.py](../scripts/regular_phase.py#L2955) nejdrive odesle zpravy, potom ulozi delivery audit a teprve pak aktualizuje YAML stav o doruceni. Selhani auditu vraci error pred zaznamem cooldownu. CronJob ma `backoffLimit: 1`.

**Dopad:** uspesne doruceny mail muze pri retry vzniknout znovu. Oprava r107 spravne odstranuje FK reference na decision, ktera nebyla persistovana pro chybejici context. Neresi tim ale obecne selhani po send ani nedokazuje, ze vsechny FK chyby zmizely.

**Korekce incidentni hypotezy:** schema umoznuje cascade mazani decision pres parenty; samotna existence FK ale neni dukaz, ze to konkretni incident zpusobilo. Tato revize neprokazala vazbu FK failure na konkretni volume attachment.

- [ ] Oddelit stav analyzy od delivery a pripravit trvaly outbox/delivery workflow s dedup identitou a explicitnimi retry stavy.
- [ ] Otestovat uspech SMTP a nasledny pad DB auditu; neopakovat celou analyzu jako jedinou formu delivery retry.
- [ ] Neslibovat exactly-once doruceni SMTP bez podpory poskytovatele; resit nejednoznacne pokusy a reconciliaci.

### F10: P2 - All-level trace context muze byt nekompletni bez oznaceni

**Dukaz:** [fetch_unlimited.py](../scripts/core/fetch_unlimited.py#L523) vezme jednim `_search` nejvyse 3 000 udalosti celkem pro seznam representative traces, serazenych od nejstarsich. Nepaginuje a nekontroluje `hits.total`, `timed_out` ani shard failures. Enrichment pak nalezeny representative timeline nahradi timto vysledkem.

**Dopad:** velky trace muze spotrebovat limit ostatnich a konec operace/outward status muze chybet. Vysledek je vzorek kontextu, ne prokazatelne cela operace. Jde prevazne o zdedeny dluh uz z r92, ale pro pozadovany lepsi kontext je dulezity.

- [ ] Vracet coverage/completeness metadata a odlisit missing/failed/truncated od complete.
- [ ] Pouzit omezene per-trace dotazy nebo paginaci s rozpoctem udalosti/casu; neprejit na neomezene cteni vsech severity ve vsech namespaces.
- [ ] Zachovat puvodni ERROR dukazy pri nekompletnim enrichmentu a nepriznavat cele family vysokou jistotu z jednoho representative trace.

## Co Ma Smysl Zachovat

| Oblast | Zhodnoceni | Proc |
|---|---|---|
| Presne ERROR pocty, run facts a complete fetch contract | Zachovat | Odhaluji chybejici/castecna data; bez nich nelze merit detector. Cast teto infrastruktury byla uz v r92. |
| Cause families misto obecne exception class | Zachovat a dotahnout | Pricina, root aplikace, operace a outcome jsou lepsi jednotka reportu nez `ServiceBusinessException`. |
| ERROR lines vs operation occurrences vs amplification | Zachovat | Jedna operace muze produkovat mnoho wrapperu a nemusi znamenat mnoho incidentu. |
| Operation count method/confidence a N/A | Zachovat | Trace ID neni automaticky jedna business operace; fallback omezeni je spravne priznat. |
| Namespace decision ledger a contributors | Zachovat jako audit | Umoznuje vysvetlit, proc vznikl signal. Sam ledger ale nezlepsuje precision. |
| Peak episodes | Zachovat po oprave F3 | Stejny problem napric okny je lepsi nez nove upozorneni kazdych 15 minut. |
| r106 bounded backfill batches a uvolneni payloadu | Zachovat | Omezuji soucasne drzenou detailni evidenci; adresuji realny init bottleneck. |
| r107 oprava syntetickych FK reference | Zachovat | Resi konkretni chybu auditniho propojeni bez predstirani persistovaneho contextu. |
| r107 escapovany Recent Incidents vystup | Zachovat | Zlepsuje bezpecne zobrazeni textu a odstranuje jednobunkove tabulky. |
| r108 job-local SQLite a cleanup ve finally | Zachovat po oprave F7 | Docasne spill soubory nepatri do persistentni registry. Neni to ale oprava RWO soubehu. |
| Bootstrap snapshot compatibility guard | Zachovat, zmensit scope | Brani pouziti nekompatibilniho modelu; nema vynucovat uplny reprocessing pri kazdem releasu. |
| Workflow lifecycle diagnostika | Oddelit od teto produkcni stabilizace | Hleda stalls/retries i bez ERROR; je to dalsi use case, ne nutna podminka lepsiho peak reportu. |

Rozsireni PVC na 40 Gi resi kapacitu, nikoli attach konflikt. Zvyseni RAM/workers je tuning az nad zmerenym limitem; nesmi nahrazovat ohranicene zpracovani. Scratch 3 500 Mi sdileji ctyri init workery, takze test jednoho workeru neprokazuje dostatecnost celeho rozpoctu.

## Co Uz Existovalo V r92

P93/CAP, streaming se SQLite trace detailem, trace ownership a sekundarni fetch vsech levelu pro representative trace vznikly uz pred r92. Neni nutne kvuli nim prijmout vsechnu slozitost pozdejsich releasu.

Zdedene OR pravidlo znamena prekroceni nizsiho z Pxx a CAP. Zvyseni percentilu proto nemusi detector zklidnit, pokud zustane nizsi CAP. Jeho zmenu neprovadet naslepo na AND/max; nejprve zmerit skutecne pozitivni i negativni okna.

## Vyvojova Linie

| Zdrojovy bod | Obsah | Verdikt |
|---|---|---|
| `647e0cf`, r92 | Produkcne overena reference a Bearer Confluence auth | Pouzit jako baseline, ne jako dukaz idealni detekce. |
| `209869f` a `80154f4` | Velky balik operator reporting, cause facts, threshold model, decisions/episodes a review oprav | Rozebrat podle funkci, neprenaset jako nedelitelny balik. |
| `8f71dfe` | Zachovani checksumu jiz aplikovanych migraci | Spravny smer; aplikovane migrace dal nemenit. |
| `dc0a9d0` a `a0e290e` | Idempotentni episode replay a poradi recurrence predecessor persistence | Potrebne opravy nove vrstvy, nikoli novy produkcni prinos samy o sobe. |
| `05dedc6`, r106 | Backfill persistence/memory, omezeni denniho cause grainu, registry merge | Zachovat; daily fakta nesmi predstirat presnou 15min cause alokaci. |
| `10d791f`, r107 | FK context fix a upravy vystupu | Zachovat s dalsim overenim F9. |
| Dirty r108 a GitOps | SQLite scratch/cleanup, vetsi PVC, quiesce/resize flow | Uzitecna kapacitni oprava, ale ne kompletni produkcni stabilizace. |

## Dosavadni Empiricka Evidence

[Analyza 002](002_operator-centered-alert-and-wiki-reporting.md#L80) zaznamenala produkcni okno s complete fetchem 393 ERROR radku, 100 unikatnimi traced operations a 7 untraced radky. Jedna konkretni optimistic-lock operace vytvorila 11 ERROR radku. To podporuje zmenu reporting jednotky, nikoli automaticke potlacovani vsech maloobjemovych udalosti.

[Analyza 003](003_restore-peak-alert-trust-and-usability.md#L112) zaznamenala 94 complete nprod regular runu a 13 135 ERROR radku, ale scope zahrnoval pouze dev/fat. Male mnozstvi mailu v teto analyze nedokazovalo kvalitu detectoru: cast peaku byla mimo monitorovany scope a cast potlacila test-origin policy.

Tyto starsi vysledky nejsou srovnavaci benchmark r92 versus r108 na stejnych produkcnich datech. Zadny takovy novy benchmark tato revize nevydava za hotovy.

## Cilovy Funkcni Kontrakt

1. **Sber:** complete ERROR data pro presne `[from, to)` a explicitni environment scope. Chybejici data nejsou nula.
2. **Signal:** rozhodnuti, zda je chovani nestandardni. Raw volume, family anomaly a zavazny jednotlivy technicky event jsou ruzne signaly.
3. **Diagnoza:** konkretni cause families s variantami, root aplikaci, operaci, outcome a confidence. Unknown je platny vysledek, ne duvod pro vymyslenou pricinu.
4. **Kontext:** pro representative trace dotahnout dalsi severity, s limitem a jasnou coverage; ERROR pocty tim nenavysovat.
5. **Policy:** zda je to akcni, pro koho a pri jake materialni zmene znovu upozornit.
6. **Delivery:** samostatne trvale evidovany pokus a vysledek; publikacni chyba neznamena ztratu analytickych faktu.

Priklad vystupu pro jednu skupinu:

```text
Card repair: optimistic locking in bl-pcb-v1
Impact: 1 observed operation, 11 ERROR lines, amplification 11x
Outcome: 500; technical_failure; high diagnosis confidence
Evidence: representative trace + relevant timeline; context coverage explicit
Change: new cause / stable continuation / material escalation
Action: inspect concurrent Card updates and retry/idempotency behavior
```

Historic knowledge ma vlastni oznacenou sekci. Z reprezentativniho trace nelze bez dalsi evidence prohlasit pricinu vsech logu family. Pocet operaci nesmi byt vydavan za pocet zasazenych uzivatelu nebo podil selhanych requestu bez traffic denominatoru.

## Doporuceny Postup

### 1. Stabilizace Bez Zmeny Produkcni Citlivosti

- [ ] Zafixovat source commit, image digest, chart revision, konfiguraci a schema/snapshot verzi pro dalsi release.
- [ ] Opravit F1, zmensit init podle F2 a opravit r108 chybovy navrat F7.
- [ ] Zachovat scratch cleanup a zmerit worst-case soucasnou spotrebu workeru, RAM a ephemeral storage.
- [ ] Overit rollback nad kopii DB/registry. Nevydavat prosty downgrade na r92 za bezpecny po novych migracich bez kompatibilitniho testu.

### 2. Detekce A Policy V Shadow Rezimu

- [ ] Opravit recovery scope F3 a frekvenci digestu F5.
- [ ] Vytvorit explicitni relevance pravidla F6; nemenit heuristickou klasifikaci na tichou automatickou suppress policy bez schvaleni ownerem.
- [ ] Otestovat sparse/MAD=0, cold start, nove fingerprinty a maloobjemove vysoko-zavazne chyby.
- [ ] Porovnat r92 a kandidatni policy nad stejnymi daty, oddelenou registry a bez odesilani. Nedelit RWO mezi dva konkurencni shadow workloady.

### 3. Report A Trace Evidence

- [ ] Zachovat strukturovane cause families a rozlisene count domains.
- [ ] Opravit nekompletni enrichment F10, zobrazovat evidence coverage a degradation reason.
- [ ] Relevance/top-N representative vybirat podle dopadu a novosti, nikoli jen mnozstvi wrapper logu.
- [ ] Doplnit odkazy do log exploreru podle trace ID, namespace a presneho casu; overit sanitizaci citlivych logovych hodnot pred publikaci.

### 4. Produkcni Acceptance A Canary

- [ ] Pripravit alespon 7-14 dni produkcnich oken se seznamem potvrzenych incidentu a neakcnich udalosti; nprod dataset vest zvlast.
- [ ] Pro threshold training pouzit jen minulost pred hodnocenym oknem, ne vlastni budoucnost benchmarku.
- [ ] Merit actionable precision, zachyt potvrzenych incidentu, duplicitni upozorneni za epizodu, cas do zachyceni, unknown/trace coverage a resource budget.
- [ ] Zvlast merit detekci a doruceni; mensi pocet mailu sam o sobe neni uspech.
- [ ] Pred canary odsimulovat cold install, bezny upgrade, init failure/timeout, resume, regular/backfill soubeh, disk-full, DB failure a SMTP-success/audit-failure.
- [ ] Dohodnout cilove metriky pred ladenim. Minimalni navrh: neztratit zadny potvrzeny zavazny incident, nesignalizovat eskalaci bez materialni zmeny a neposilat opakovane 15min maily pro stabilni pricinu.

## Provedena Validace

| Overeni | Vysledek | Co Dokazuje |
|---|---|---|
| Decision ledger, episodes, policy, thresholds, replay, delivery persistence | 51 passed | Zakladni implementacni kontrakty techto modulu. |
| Operator report, cause analysis, digest, publisher HTML, streaming, run persistence, snapshot/scope a lifecycle testy | 101 passed, 2 subtests passed | Regresni pokryti a presne pocty ve fixture/mocked scenarich. |
| Nizkoobjemova populace s MAD=0 | Threshold 2 v r92 versus 1 nyni | Konkretni zmenu citlivosti namespace verdictu, ne skutecne produkcni precision. |
| Peak + tichy cizi namespace | Opakovane falesne ESCALATION | F3 je runtime chyba, ne jen hypoteza. |
| Stabilni continuation + mock sender | `digest_only`, jedno odeslani | F5 muze udrzovat frekvenci mailu. |
| Expected outcome START | `primary_send` | F6 neni implementovana relevance gate. |
| Registry save failure po mock DB commitu | `UnboundLocalError` | F7 v dirty r108. |
| Helm template + YAML parse | 11 resources, 3 PVC konzumenti | Chart syntakticky renderuje; nedokazuje runtime readiness ani bezpecny detach. |

Rozsirena sada vypsala 8 146 existujicich deprecation warnings okolo `datetime.utcnow()`; testy neselhaly. Testovalo se v lokalnim WSL interpreteru, ne uvnitr produkcni image. Nebyl proveden realny PostgreSQL FK/race integracni test ani Kubernetes fault injection.

Izolovane reprodukce a render jsou v [review_r92_behavior.py](../../tmp_verify/review_r92_behavior.py). DB, ES a odesilani v runtime probes nejsou pouzity; backfill persistence a sendery jsou mockovane. Soubor nemeni analyzator.

## Otevrene Otazky

1. Ktere male prod udalosti jsou skutecne akcni a ktere ocekavany business flow? To musi potvrdit owner, ne odhadnout percentualni threshold.
2. Je primarni cil Teams/email incidentni upozorneni, nebo souhrn kazdeho statisticky zajimaveho okna? Pro omezeni spamu doporucuji prvni moznost a oddeleny denni digest.
3. Ktere presne prod incidenty ma novy detector zachytit oproti r92 navic? Bez teto reference nelze objektivne schvalit prinos modelu.
4. Je pro nejblizsi release prijatelny jeden orchestrujici vlastnik PVC, nebo je uz rozhodnuto o migraci registry do DB? Obe cesty maji jiny rozsah, rollback a provozni kompromisy.

**Nic z toho nevyzaduje zahodit prinosne reportovani. Vyzaduje to mensi release, jednotny rozhodovaci tok a merene overeni nad produkcnimi daty.**