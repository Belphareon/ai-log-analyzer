# r109: stabilizace smysluplnych zmen oproti r92

## Rozhodnuti

Lokalne pripraveny release candidate, nikoli schvaleni produkcniho nasazeni. Referencni r92 je commit `647e0cf`; podkladem jsou obe revize v [005](005_review-ai-log-analyzer-pvc-fk.md) a [006](006_review-r92-to-r108-production-readiness.md). Existujici rozpracovane r108 zmeny zustaly zachovane. Nic nebylo commitnuto, pushnuto, publikovano ani nasazeno.

Cilem neni vratit kazdy soubor na r92 ani automaticky schvalit r108: zachovat prokazatelne uzitecne funkcnosti, opravit reprodukovane regrese a odstranit oddeleny runtime mimo ERROR peak monitoring.

## Potvrzene nalezy a reseni

| Nalez | Vysledek r109 | Dukaz |
|---|---|---|
| Cizi quiet namespace obnovil jedinou aktivni epizodu | Recovery vyzaduje pozorovane quiet scope vsech aktivnich namespace; chybejici data nejsou recovery | Episode correlation testy |
| Stridani namespace prispevku delalo falesny rust | Current dopad je soucet cele cause family v okne; kumulace a alokace zustavaji prispevky | Stabilni 60+40 ve trech oknech, idempotence |
| Stabilni CONTINUATION odesilala samotny digest | `no_material_change`, heartbeat/materialni zmeny zustavaji viditelne | Policy a skutecny dispatcher testy |
| Expected outcome dostaval primarni detail | Pouze high-confidence START/RECURRENCE jde do souhrnu; nejiste pripady a eskalace se neschovaji | Policy testy vcetne limitu detailu |
| Undiagnosed namespace peak zustal pouze v ledgeru | Explicitni souhrn s neprirazenou pricinou a nizkou confidence, i kdyz neni incident payload | Pruchodovy regular-phase test az k odeslani |
| MAD=0 srazil percentil 2 na 1 | Zachovana matematika percentilu v modelu 5.0 | Distribuce 90x1/8x2/2x100 pri p=.94 |
| Denni pooling smesoval tiche a exponovane hodiny | Presny UTC tydenni slot P95/MAD vcetne skutecnych nul, bez globalniho CAP/defaultu | Oddelene hodiny, UTC offset/den, chybejici tydny a realny PostgreSQL roundtrip |
| Kratka historie a chybejici profil nebyly rozlisene | Init pod 10 vzorku, mature od 10; missing se nevyhodnoti ani nevyvola recovery | Ledger, episode, spike/email evidence testy |
| Init 3 / tydenni 4 tydny neumoznily 10 slotovych vzorku | Sdilena historie 12 tydnu, DB request pod 10 odmitnut | Installer/Helm kontrakt a DB test deseti tydnu |
| Trace kontext byl tise neuplny | Samostatny limit na trace, coverage a spolecny 60s request budget; original ERROR evidence zustava pri partial/fail | Trace fetch, segmentation a report testy |
| Backfill registry chyba rozbila souhrn | Summary pripraven pred chybovou vetvi, zachovany pocty a puvodni chyba | Backfill regression testy |
| Delivery audit mohl predbehnout zaznam uspesneho odeslani | Cooldown ulozen pred auditem; neocekavana send chyba vraci error | Fault injection: SMTP success/audit failure a sender failure |
| FK ledger/delivery retezu byl overen jen mocky | Realny episode -> policy -> delivery retezec vcetne autoritativniho replay | PostgreSQL 16 integrace |
| Init opakoval nuceny historicky backfill | Migrace + guard; kompatibilni snapshot znamena konec, jinak trenovani z faktu; explicitni bootstrap je facts-only | Render obou Helm profilu, backfill testy |
| Nezavisle CronJoby sdilely RWO PVC | Regular je jediny planovany writer; init ma emptyDir, backfill je suspendovan | Source chart test a GitOps render |
| Nprod scope 6 namespace odporoval kontraktu 12 | GitOps scope sjednocen s kanonickym nprod kontraktem, strict zapnut | Helm/scope kontrola |
| Installer prepsal PVC request / ztratil scratch | Zachovan existujici request, zdrojova sablona ma scratch, doplnen chybejici Chart.yaml | Installer a source Helm testy |

## Co zustalo a co slo pryc

- Zustaly cause families, operation/outcome rozliseni, ERROR lines vs unique operations/amplification, presna authoritative fakta a reconciliace, namespace/snapshot guard a opravena epizodova kontinuita.
- Zustal r107 FK-safe audit, escapovane operator reporty a bounded backfill/SQLite cleanup z rozpracovaneho r108.
- Odstraneny ctyri runtime lifecycle moduly a ctyri jejich testovaci soubory: celkem 1 791 radku oproti puvodnimu HEAD. Odstraneny take jejich runtime volani, mail sender a konfigurace. Nejde o vypnuti testu zachovaneho chovani.
- Migrace `008_workflow_lifecycle_facts.sql` a historicke schema zustavaji beze zmen; prepis checksumu aplikovane migrace by rozbil upgrade. Historicke changelogy ani uzivatelovy revize se neprepisuji.
- Nepribyl dalsi INFO/WARN detector, obecny orchestrator, LLM rozhodovani ani nove kalibrovane volume/impact minimum bez dat. Primarni sber zustava ERROR-only.

## Schvaleny Slotovy Kontrakt

Uzivatel schvalil presny klic `(namespace, UTC weekday, hour, quarter)`, vlastni P95/MAD bez globalniho CAP, skutecne nuly jako vzorky, DB historii alespon 10 tydnu a jasne oznaceny init pod 10 vzorky. Implementace pouziva model 5.0, novou migraci 011 a 12tydenni horizont pro init i tydenni trener. Stare denni snapshoty se nepouzivaji. Nenahradni chybejici data neznamenaji quiet/recovery.

Kompletni aktualni [replay report](008_r109-prod-nprod-24h-replay.md) nahrazuje stare denni tabulky. Cached nprod ES ma pro vyhodnocovane sloty jen jeden vzorek, vse je init; 209 volume prekroceni neni 209 alertu ani precision/recall benchmark. UTC kontrakt znamena posun mistni hodiny pres CEST/CET. Zadnych pet prikladovych radku nebylo schvaleno jako false positive. Realne stari a souvislost firemni DB zustavaji neoverene po LDAP odmitnuti.

## Overeni

### Doplneny Schvaleny Collector/Reporter

Uzivatel schvalil nahradu manual-only report kompromisu: regular zustava jedinym planovanym PVC writerem a bezi kazdych 15 minut; samostatny DB-only reporter publikuje trendy kazde 2 hodiny, Known Peaks a Recent Daily Incidents jednou denne za poslednich 24 hodin. Backfill znovu nesbira data, ktera uz ma regular. Zdrojovy i spravny nprod chart maji reporter s emptyDir, bez PVC/ES credentials, a DB-only maintenance s retenci 90 dni.

Migrace 012 pridava trvaly scoped start sberu, completion marker live workflow, DB katalogovou metadata kopii a per-destination publication ledger. Collector preferuje live, pak nedavne count opravy, pak nejstarsi mezery v omezenem rozpoctu; historicke zpracovani je facts-only bez epizod/alertu/registry mutaci. `pending_window_count` ukazuje zbytek. Reporter pouziva konzistentni scoped snapshot, jasne rozlisuje chybejici data a pozorovane nuly a denni odeslani ceka na 96 oken a reconciliaci diagnostiky.

Katalogove CSV/Markdown zacinaji pricinou a diagnostikou, zachovavaji Jira/notes, escapovani a metrický rozsah. Podil contributoru nevytvari confidence; maximum stareho peaku neni vydavano za soucet a pouze pribuzny flow neni dukaz root cause. DB-only Known Peaks zachovava historicky katalog oddelene od dennich detekcnich rozhodnuti. Konkretni parametry a omezeni jsou v [provozni prirucce](../docs/OPERATIONS.md).

Nasledujici cisla popisuji predchozi checkpoint pred collector/reporter rozsirenim, nikoli automaticky vysledek nove plne sady:

**Finalni collector/reporter gate:** cela sada s PostgreSQL 16 ma 243 testu, 0 failures, 0 errors, 0 skipped (JUnit; 159.676 s). Zahrnuje partial-to-final prechod 95/96 na 96/96 oken, jednorazove denni odeslani, scope izolaci, per-destination retry, scheduled live retry a facts-only opravy. Oba charty byly vyrenderovany; reporter nema PVC ani ES/DDL credentials, backfill zustava suspendovany. Editor diagnostics jsou ciste. Zadne skutecne Confluence/SMTP/Teams odeslani ani deployment timto testem neprobehly.

- Kompletni pytest sada s realnym PostgreSQL po slotovych i alert evidence zmenach: 214 passed, 2 subtests passed, nic skipped. Obsahuje sedm DB integracnich testu vcetne migraci, presnych faktu, retention, FK/replay retezu a deseti tydnu slotovych faktu s init/missing auditem.
- GitOps Helm render: 9 resources v defaultu, 11 pri explicitnim bootstrap/quiesce; vzdy jeden planovany PVC writer, init bez PVC, bez `--force`, shell syntax platna, nprod scope kanonicky.
- Source Helm chart ma vlastni render regression test. Installer YAML parser, bash syntax a zachovani 40Gi/explicitniho override byly overeny.
- Editor diagnostics bez chyb. Whitespace kontrola pouziva `git -c core.whitespace=cr-at-eol diff --check`, protoze cast puvodnich souboru je verzovana s CRLF; konce radku se plosne nemenily.
- Docker image nebyla buildnuta ani publikovana; tag r109 v lokalnich souborech je cil budouciho vydani. Produkcni cluster nebyl v tomto ukolu menen ani znovu diagnostikovan.

Reprodukce testu z korene aplikace proti izolovane testovaci databazi:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:scripts TEST_POSTGRES_DSN="$TEST_POSTGRES_DSN" python3 -m pytest -q -p no:cacheprovider --disable-warnings scripts/tests
```

DB fixture resetuje schema pouze v databazi s test/migration nazvem. Nepouzivat produkcni DSN. Testy maji existujici deprecation warnings, nikoli warning-free gate.

## Provozni omezeni

1. Rucni backfill stale vyzaduje maintenance: suspend regular, dobehnuti podu a detach PVC, spusteni backfillu, dokonceni a detach, teprve potom resume regular. Bezny reporting uz na backfillu ani PVC nezavisi. Doplneni starsich mezer a pozdnich logu je omezeno ES retenci, zvolenym startem, dvouhodinovym recheck horizontem a casovym rozpoctem; nejde o nekonecnou garanci bez ztrat.
2. Prvni prechod na model 5.0 a scope 12 namespace muze vyzadovat jednorazove `init.bootstrap=true`, pokud existujici fakta nestaci. Po uspesnem naplneni vratit false. Kratka historie je init; pripravena 90denni maintenance neni dukazem skutecne retence nprod. Neprobihaji nucene historicke replaye pri kazdem releasu.
3. Ulozeni cooldownu pred DB auditem neni exactly-once SMTP ani DB outbox. Pad procesu mezi odeslanim a file write nebo selhani disku muze stale vytvorit duplicitu; opacne poradi tento problem pouze zhorsovalo.
4. Trace coverage je pouze v pozadovanem casovem rozsahu, ne uplnost cele operace. Budget zabranuje spousteni dalsich requestu po jeho vycerpani, neni to tvrdy preemptivni procesni timeout. Untraced logy nemaji novy domysleny join.
5. Zaseknuty historicky Cinder VolumeAttachment neni timto patchem opraven. Pred canary je nutne overit PVC, dostupnost scheduleru a stav drive pozastaveneho regular CronJobu. Existujici 40Gi request se nesnizuje; zmena chartu neni dukazem provedene expanze.
6. Produkcni scope, floors ani percentil nebyly zmeneny podle nprod odhadu. Nove prahy a recurrence relevance potrebuji kalibraci na oznacenych oknech. High-confidence expected neni automaticky prokazany business dopad.

## Akceptace pred produkci

- [x] Reprodukovat lokalni regrese a opravit je cilene.
- [x] Odstranit oddeleny lifecycle rozsah a ponechat kompatibilni migrace.
- [x] Overit celou sadu, realny DB retezec a oba Helm profily.
- [ ] Na stejnych oznacenych produkcnich oknech porovnat r92/r109: missing incidents, false alerts, duplicates, undiagnosed visibility a recovery/recurrence.
- [x] Uzivatel schvalil oddeleny DB-only reporter; lokalni implementace obnovuje automatickou publikaci bez druheho PVC writeru.
- [ ] Overit live DB coverage/retenci, migraci 012, realny Confluence update a SMTP/Teams doruceni po schvalenem nasazeni.
- [ ] Build a release image po schvaleni; overit rollout/PVC a novy snapshot, nasledne canary se skutecnou alertovou kadenci.

Bez poslednich bodu lze potvrdit opravene regrese a lokalni funkcnost, nikoli lepsi produkcni precision/recall nebo nulove provozni riziko oproti r92.