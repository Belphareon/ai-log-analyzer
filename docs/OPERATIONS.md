# Provoz — AI Log Analyzer

Vše pro běžný provoz, manuální zásahy a diagnostiku. Systém běží **autonomně přes K8s CronJoby** — tato příručka je pro situace, kdy je třeba ručně zasáhnout.

---

## 1. CronJoby — přehled

| CronJob | Schedule | Co dělá | Typická doba |
|---------|----------|---------|--------------|
| `log-analyzer` | `5,20,35,50 * * * *` UTC | Live sber/detekce/alert, pak facts-only opravy pozdnich dat a mezer; r111 PostgreSQL rezim bez PVC | 1–10 min |
| `log-analyzer-reports` | `10 */2 * * *` UTC | DB-only trendy kazde 2 h; Known Peaks a Recent Daily Incidents jednou denne za poslednich 24 h | 1–15 min |
| `log-analyzer-backfill` | pozastaven (`suspend: true`) | Rucni backfill + Confluence publish v maintenance okne | 10–60 min |
| `log-analyzer-thresholds` | `0 3 * * 0` | Tydenni P95/MAD presnych UTC slotu z 12 tydnu uplnych faktu, bez globalniho CAP | 1–5 min |
| `log-analyzer-maintenance` | `30 2 * * *` | Denní rollup + retention faktů | 1–30 min |

### Závislosti

```
Init Job (PreSync)
  └─ migrace + v PostgreSQL rezimu bootstrap runtime checkpointu
  └─ snapshot guard → pri kompatibilnim modelu konec
  └─ pri nekompatibilnim snapshotu → threshold calc z complete facts
  └─ pouze init.bootstrap=true → facts-only backfill pred trenovanim

Poté autonomně:
  regular (kazdych 15 min) → live ES sber + UTC slot P95/MAD + alert → complete facts
                          → count-only kontrola pozdnich dat → zmenena okna facts-only
                          → nejstarsi chybejici okna facts-only → DB katalogova metadata
  reports (kazde 2 h)  → pouze DB snapshot → trendy / denni Confluence a Teams report
  backfill (rucne)     → pouze maintenance nebo explicitni bootstrap
  thresholds (Ne 03:00) → P95/MAD presnych UTC slotu z poslednich 12 tydnu
  maintenance (02:30)  → denní rollupy → smaže fakta starší než retention limit
```

### r111: Runtime bez PVC

`runtimeState.backend=postgres` odstrani PVC mount z regularu a pouzije pod-local `/data`. Migrace 013 uchovava oba registry a alert cooldown JSON v PostgreSQL; fingerprint index a ID countery se obnovi ze stejnych zaznamu. Kazde ulozeni registry a doruceneho alertu synchronne aktualizuje checkpoint. Session advisory lock pro query scope odmita druheho collectora i rucni soubezny Job. DB chyba, chybejici checkpoint nebo poskozeny obsah zastavi beh misto resetu na prazdny registry. Regular ma v tomto rezimu `activeDeadlineSeconds=900`, takze dalsi schedule neblokuje hodinovy zivy Job.

Pred prvnim prepnutim pozastavte regular, nechte stare filesystem joby skoncit a overte, ze zadny stary writer nebezi. Nprod init hook po migracich a pred snapshot guardem spusti `regular_phase.py --bootstrap-runtime-state` s `RUNTIME_STATE_BACKEND=postgres`. Bootstrap prevezme DB kopii registry z migrace 012 a cooldowny poslednich uspesnych doruceni ze stejneho query scope. Existujici checkpoint nikdy neprepise; chybejici nebo starsi mirror nez posledni complete sber je chyba vyzadujici explicitni import, nikoli duvod resetovat stav. Samostatny zdrojovy chart obsahuje jen CronJob sablony; pri jeho jinem pouziti zajistete tento bootstrap pred povolenim regularu.

Nprod ma pro rizeny prechod `init.quiesce=true`. Quiesce nejprve pozastavi regular a backfill a ceka na ukonceni starych writeru. Pouze Jobum, jejichz vsechny pody jsou `Pending` a aplikacni kontejnery nikdy nebezely, zkrati `activeDeadlineSeconds` na 1; ukonceni provede normalni Job controller. Bezicimu nebo drive spustenemu kontejneru deadline nemeni. Role proto potrebuje `patch` na Jobs v namespace. Po zklidneni PostgreSQL rezim preskoci PVC resize/attach operace. Pri chybe quiesce nebo initu zustava regular pozastaveny: SyncFail resume hook se v DB rezimu nevytvari, aby stary filesystem writer nerozesel stav s DB. Po oprave chyby zopakujte cely sync; regular povoli az aplikace noveho CronJob manifestu.

Puvodni PVC a pozastaveny legacy backfill zustavaji zachovane, ale nejsou soucasti noveho pravidelneho sberu ani reporteru. Pod-local CSV/MD/JSON exporty nejsou trvale zalohy. Po prepnuti nesmi legacy backfill ani stary filesystem image upravovat registry jako druhou autoritu; pripadny navrat na starsi image vyzaduje zastaveni collectoru a export aktualniho DB checkpointu, nikoli pouhe prepnuti tagu na stale stare PVC. DB zalohy/retence jsou nadale nutne. Cinder attachment ani jeho finalizery se kvuli teto zmene nemeni a jejich stav uz neblokuje bezny sber.

### Overene nasazeni r111

Stav k 2026-10-30 11:29 UTC, nikoli prubezne aktualizovany health dashboard:

- Aplikacni commit `41d1a12`, nprod GitOps commit `27be0fb`, image `dockerhub.kb.cz/pccm-sq016/ai-log-analyzer:r111`. Image po push/pull zachovala ID `4120f6822ac4a2a12663262a226128e6e570c184cf62c0ff4d2624d8b8833b1a` a revision label. r110 byl report-only zdrojovy mezikrok; nasazena kombinovana oprava je r111.
- Argo sync uspesne dokoncil vsechny kroky v 11:20:32 UTC. Nprod zachoval existujici Argo override `env.PERCENTILE_LEVEL=0.94`; release nemenil model ani netrenoval novy percentil.
- Cely izolovany release prosel 256 testy a 2 subtesty proti PostgreSQL 16, bez preskocenych testu. Pokryte jsou bootstrap, konkurencni writer, obnova registry/cooldownu po vymene podu, chybejici/stary checkpoint, Confluence limity a Helm kontrakty.
- Prvni regular Job `log-analyzer-29889320` obnovil 8 694 znamych fingerprintu, zpracoval vsech 1 771 ERROR radku aktualniho okna 11:00-11:15 UTC a uspesne dokoncil vsech osm naplanovanych oken v 11:29:03 UTC. Zbyvalo 42 historickych oken; jejich dalsi doplneni zavisi na nasledujicich schedulech a ES retenci. Historicke opravy neodesilaji stare peak alerty.
- Validacni reporter `log-analyzer-reports-r111-validation-20261030` uspesne publikoval vsechny tri Confluence cile. Pozadavky mely 348 333 / 89 662 / 252 950 bajtu; verze stranek 1914 / 1905 / 4011. `daily_complete=false` kvuli historickym mezeram zustalo pravdive a denni notifikacni gate se neobchazel.

### Stav

```bash
kubectl get cronjobs -n ai-log-analyzer
kubectl get jobs -n ai-log-analyzer --sort-by=.metadata.creationTimestamp | tail -10
kubectl logs job/<job-name> -n ai-log-analyzer
```

---

## 2. Manuální spuštění jobů

Když potřebujete spustit job mimo schedule:

**r109 a RWO:** `regular` a rucni backfill nesmeji soucasne pouzivat PVC. Pred spustenim backfillu pozastavte regular CronJob, nechte existujici joby dobehnout a overte ukonceni vsech PVC podu i odpojeni volume. Samotne `concurrencyPolicy: Forbid` jine CronJoby ani rucni Joby neserializuje. Po uspesnem backfillu, dokonceni podu a odpojeni volume regular znovu povolte. Backfill zustava pozastaveny. Automatickou publikaci zajistuje samostatny `log-analyzer-reports` bez PVC a bez ES pristupovych udaju; data znovu nesbira.

```bash
# Regular phase
kubectl create job manual-regular --from=cronjob/log-analyzer -n ai-log-analyzer
kubectl logs -f job/manual-regular -n ai-log-analyzer

# Backfill
kubectl create job manual-backfill --from=cronjob/log-analyzer-backfill -n ai-log-analyzer
kubectl logs -f job/manual-backfill -n ai-log-analyzer

# Threshold přepočet
kubectl create job manual-thresholds --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/manual-thresholds -n ai-log-analyzer

# Úklid po manuálním jobu
kubectl delete job manual-regular manual-backfill manual-thresholds -n ai-log-analyzer --ignore-not-found
```

### Re-bootstrap (init job)

Pro doplneni historickych faktu (zmena namespace, nove prostredi) nastavte jednorazove `init.bootstrap=true`, pozadovany pocet dni a workeru. Init pouzije `--bootstrap --facts-only` a lokalni `emptyDir`, nikoli sdilene PVC. Nepublikuje reporty ani neodesila upozorneni. Po uspechu vratte `init.bootstrap=false`. Instalator ma default `init.quiesce=false`, ale nasazeny nprod r111 pouziva `true` pro rizeny handoff; DB rezim pri selhani neobnovuje stareho filesystem writera. Runtime bootstrap checkpointu neni totizna operace jako historicky `init.bootstrap`.

Model 5.0 vyzaduje novy snapshot presnych UTC slotu; stary denni model 4.1 neni kompatibilni. Pri prvnim prechodu nebo rozsireni nprod z 6 na kanonickych 12 namespace init zkusi trenovani nad existujicimi uplnymi fakty. Pokud coverage snapshotu nestaci, skonci chybou; operator musi explicitne povolit bootstrap. Kratsi historie muze vytvorit init profily, nikoli mature. Bez kompatibilniho snapshotu regular fail-closed nebezi. `init.forceThresholdRefresh=true` vynuti pouze trenovani, nikoli historicky fetch.

```bash
# Uprav init values nebo image v infra-apps a spusť Argo sync.
# PreSync hook se obnovi pres BeforeHookCreation, bez Force/Replace.
kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
```

Init je ArgoCD PreSync hook s `BeforeHookCreation,HookSucceeded`. Globalni `Replace=true` je zakazany kvuli immutable bound PVC. Hook nepotrebuje sdilene PVC a bezny release nezvetsuje volume automaticky. Zadna zmena chartu sama neopravi drive zaseknuty Cinder VolumeAttachment; ten vyzaduje samostatne platformni overeni.

---

## 3. Parametry — values.yaml

Všechny parametry jsou v `values.yaml` daného prostředí (v infra-apps repu).

### Sber a publikace z faktu

| Parametr | Default | Popis |
|----------|---------|-------|
| `runtimeState.backend` | `filesystem`; nprod `postgres` | Volba autoritativniho stavu. PostgreSQL rezim vyzaduje migraci 013 a explicitni bootstrap pred prvnim regular behom; PVC nenamountuje. |
| `runtimeState.activeDeadlineSeconds` | `900` | Deadline regular Jobu v PostgreSQL rezimu. Legacy filesystem rezim zachovava 3600 s. |
| `RUNTIME_STATE_BACKEND` | `filesystem` | Aplikacni env generovane z `runtimeState.backend`; stejnojmenny vstup instalatoru vybira backend pro generovane values. |
| `env.REGULAR_COLLECTION_START` | prazdny | Start prvni aktivace; prazdny znamena posledni uzavrene okno. Explicitni ISO UTC cas musi byt zarovnany na 15 minut. Ulozeny checkpoint uz dalsi behy neposouvaji ani touto promennou. |
| `env.REGULAR_SETTLE_MINUTES` | `2` | Prodleva pred vyberem uzavreneho okna kvuli indexaci ES |
| `env.REGULAR_MAX_WINDOWS` | `8` | Maximalni velikost planu live + starych mezer; opravy pozdnich dat maji vlastni horizont a sdileny casovy rozpocet |
| `env.REGULAR_CATCHUP_BUDGET_SECONDS` | `480` | Po vycerpani se nespousti dalsi opravne okno; probihaici fetch se nepreemptuje |
| `env.REGULAR_LATE_RECHECK_HOURS` | `2` | Nedavna complete okna se overi pres ES `_count`; plny fetch jen pri zmene poctu |
| `env.DAILY_REPORT_HOUR_UTC` | `7` | Pevny konec klouzaveho 24h dne. Pri cron `10 */2` se den koncici 07:00 poprve publikuje v 08:10 UTC. |

Migrace 012 pridava scope checkpoint, DB kopii katalogovych metadat a publication ledger. Regular nejdrive zpracuje aktualni live okno, pak nedavne count opravy a nakonec nejstarsi mezery. Historicke opravy nepocitaji nove alerty, nemeni epizody ani registry. Summary obsahuje `pending_window_count`; `success` znamena uspesne provedene kroky, nikoli nutne prazdny backlog. Prubeh live workflow ma samostatny completion marker: retry po commitu faktu nesmi preskocit nedokoncene alertovani.

Prvni aktivace automaticky neopravuje starsi pre-r109 mezery. Pro pozadovany zaber nastavte start pred prvnim behom nebo pouzijte explicitni bootstrap. Mezery zustavaji planovatelne, ale doplneni zavisi na dostupnosti ES a kapacite jobu. Pozdni logy za horizontem se samy nereviduji; stejny pocet pri nahrade dokumentu `_count` neodhali. Skutecne nuly jsou complete okna, chybejici behy nikoli.

Reporter pouziva scoped autoritativni fakta a konzistentni DB snapshot; nepouziva ES fetch, souborovy registry ani DDL credentials. Jira/notes a historicky Known Peaks katalog cte z DB kopie vytvorene regular writerem. Denni tabulka detekcnich rozhodnuti neni opraveny volume soucet ani dukaz odeslanych alertu; historicky katalog ma vlastni oznaceny metrický rozsah. Trendy porovnavaji sousedni stejne intervaly; bez uplneho zakladu jsou `N/A`.

Neuplne stranky jsou viditelne oznacene a muzou se opravit po doplneni faktu. Denni Teams/email se odesle teprve pri vsech 96 oknech a shode cause-fact objemu s namespace fakty. Publication ledger eviduje uspech pro kazdy cil samostatne; uspesny cil se pri beznem retry neposila znovu a partial verze neblokuje finalni. Pad mezi externim prijetim zpravy a DB commitem stale muze zpusobit duplicitu: nejde o exactly-once doruceni ani potvrzeni precteni v Teams.

Confluence report je omezeny nahled: kazda tabulka zobrazi nejvyse 100 radku, bunky nejvyse 192 znaku a uvodni denni text nejvyse 128 Ki znaku. Stranka vyslovne oznaci vynechane radky a zkracene hodnoty; zdrojova DB fakta a kompletni CSV export v `REPORT_OUTPUT_DIR` se neorezavaji. CSV je lokalni artefakt reporter podu, nikoli automaticky publikovana priloha; pri zruseni podu muze zaniknout. Known Errors zachovava poradi podle objemu za 2 h a 24 h, denni priciny podle objemu ERROR. Historicky katalog peaku ma stejna omezeni jako ostatni tabulky. Uploader meri cely serializovany UTF-8 JSON a odmitne PUT nad 4 MiB, tedy s rezervou proti overenemu Confluence limitu 5 MiB. Odmitnuti neni evidovane jako uspesna publikace.

### Alerting

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.MAX_PEAK_ALERTS_PER_WINDOW` | `3` | Max peaků v jednom digest emailu |
| `env.ALERT_DIGEST_ENABLED` | `true` | Digest místo individuálních emailů |
| `env.ALERT_COOLDOWN_MIN` | `45` | Min. interval mezi alerty pro stejný peak |
| `env.ALERT_HEARTBEAT_MIN` | `120` | Opakovat alert pro trvající peak |
| `env.ALERT_MIN_DELTA_PCT` | `30` | Min. % změna pro znovu-odeslání |
| `env.ALERT_CONTINUATION_LOOKBACK_MIN` | `60` | Lookback pro pokračující peak |

### Detekce

| Parametr | Default | Popis |
|----------|---------|-------|
| `env.PERCENTILE_LEVEL` | `0.95` | Percentil pro každý UTC týdenní 15min slot samostatně |
| `env.MIN_SAMPLES_FOR_THRESHOLD` | `10` | Minimum pro mature, nelze snížit pod 10; méně vzorků je použitelný init |
| `env.DEFAULT_THRESHOLD` | `100` | Legacy proměnná, slotový model ji nepoužívá; missing se nevyhodnotí |
| `env.FINGERPRINT_SPIKE_MIN_COUNT` | `20` | Absolutní minimum pro historickou cause family |
| `env.FINGERPRINT_SPIKE_MAD_MULTIPLIER` | `6` | MAD násobek pro namespace/fingerprint family gate |

Pokud nelze inicializovat `PeakDetector` z authoritative threshold snapshotu, regular phase a backfill skončí s chybou. Selhání načtení authoritative namespace/fingerprint baseline běh nezastaví, ale fail-closed potlačí přiřazení namespace peaku ke cause family. Pro spike rozhodování není EWMA fallback.

### Init job

| Parametr | Default | Popis |
|----------|---------|-------|
| `init.bootstrap` | `false` | Explicitni facts-only historicky fetch pred trenovanim |
| `init.quiesce` | `false` | Volitelne maintenance quiesce/resume hooky |
| `init.forceThresholdRefresh` | `false` | Trenovani i pri kompatibilnim snapshotu |
| `init.backfillDays` | `21` | Dní zpětně pro backfill |
| `init.backfillWorkers` | `4` | Paralelní workery |
| `init.thresholdWeeks` | `12` | DB historie pro init i týdenní přepočet; požadovaný horizont alespoň 10 týdnů |
| `init.activeDeadlineSeconds` | `14400` | Max doba běhu (4h) |

Zdrojovy i pripraveny nprod chart maji DB-only maintenance a `FACT_RETENTION_DAYS=90`, tedy dostatecny planovany horizont pro 10 vzorku pri souvislem sberu. Jde o konfiguraci, ne dukaz skutecne retence firemni DB. Denni rollupy nenahradi 15min sloty. Pred nasazenim overte realnou DB coverage; kratky ES replay doklada jen init chovani, nikoli vyzralost modelu. Pozorovane nuly se pocitaji, chybejici behy nikoli.

### Alerting profily

**Méně emailů:**
```yaml
env:
  ALERT_COOLDOWN_MIN: "90"
  ALERT_HEARTBEAT_MIN: "180"
  ALERT_MIN_DELTA_PCT: "50"
```

**Citlivější:**
```yaml
env:
  ALERT_COOLDOWN_MIN: "30"
  ALERT_HEARTBEAT_MIN: "60"
  ALERT_MIN_DELTA_PCT: "20"
```

### Změna parametrů

1. Upravit `values.yaml` v infra-apps repu
2. Commit + push + PR
3. ArgoCD sync — CronJoby se aktualizují
4. Nový parametr platí od příštího běhu (do 15 min)

---

## 4. Přidání nové aplikace / namespace

1. **Přidat do `.env`:**
   ```
   MONITORED_NAMESPACES=...,nova-app-01-app
   ```

2. **Nový Docker image** (obsahuje `config/namespaces.yaml`):
   ```bash
   ./install.sh --skip-db
   ```

3. **Naplnit data pro nový namespace:**
   ```bash
  # Po merge změny spusť Argo sync; Job se při změně manifestu znovu vytvoří.
   kubectl logs -f job/log-analyzer-init -n ai-log-analyzer
   ```

> Bez profilu pro přesný UTC slot je rozhodnutí `missing`, `is_evaluated=False`, bez CAP/default fallbacku a bez recovery epizody. S 1-9 vzorky se použije vlastní slotový práh jako `init`, od 10 jako `mature` při výchozím minimu. UTC hodina není přes přechod CEST/CET stejná místní hodina.

---

## 5. Přepočet thresholdů

**Automatický:** CronJob každou neděli 03:00 UTC.

**Manuální:**
```bash
kubectl create job manual-thresholds --from=cronjob/log-analyzer-thresholds -n ai-log-analyzer
kubectl logs -f job/manual-thresholds -n ai-log-analyzer
kubectl delete job manual-thresholds -n ai-log-analyzer
```

---

## 6. Monitoring a diagnostika

### Failed joby

```bash
kubectl get jobs -n ai-log-analyzer --field-selector=status.successful=0
kubectl logs job/<failed-job> -n ai-log-analyzer
```

### Typické chyby

| Chyba | Příčina | Řešení |
|-------|---------|--------|
| `connection refused DB_HOST` | DB nedostupná z K8s | Ověřit DB_HOST, network policy |
| `ES connection timeout` | ES nedostupný | Ověřit ES_HOST, proxy |
| `401/403 (Confluence)` | Neplatný Bearer token nebo chybějící edit oprávnění | Ověřit token v `CONFLUENCE_PASSWORD`/`CONFLUENCE_TOKEN` a oprávnění cílové stránky |
| `413 Request Entity Too Large` | Serializovany report prekrocil Confluence request limit (overeno 5 MiB) | Overit image s omezenym nahledem a 4MiB pojistkou; stejny nadlimitni payload neopakovat jako reseni |
| `FailedAttachVolume`, `ContainerCreating` bez startu kontejneru | Cinder/CSI nedokazal pripojit RWO volume; kod analyzatoru dosud nebezel | Predat platforme PVC/PV, Cinder UUID, cilovy node a casy attach/detach; nemazat PVC ani attachment finalizery bez potvrzeni storage vlastnika |
| Daily Incident Analysis je prázdná | Chybné `CONFLUENCE_RECENT_INCIDENTS_PAGE_ID` nebo selhal publisher v `backfill.py` | Ověřit page ID v rendered backfill CronJobu a hledat `Recent Incidents` v logu posledního backfill jobu |
| Argo sync selže na immutable Job/PVC | Globalni `Replace=true` nebo nespravny lifecycle init Jobu | Odstranit globalni Replace; pro init pouzit PreSync `BeforeHookCreation,HookSucceeded`, migracni hooky nepreskakovat |
| `No thresholds found` | Prázdná DB | Spustit init job |
| `Pxx/CAP peak detector initialization failed` | DB snapshot nebo baseline není dostupný/kompatibilní | Ověřit DB přístup, complete facts a `PERCENTILE_LEVEL`; job nespustí legacy EWMA fallback |
| `SMTP connection refused` | Mail server | Ověřit SMTP_HOST z K8s |

### DB diagnostika

```sql
SELECT MAX(window_start) FROM ailog_peak.v_complete_namespace_error_counts;
SELECT namespace, COUNT(*) FROM ailog_peak.peak_thresholds GROUP BY namespace;
SELECT COUNT(*) FROM ailog_peak.peak_investigation WHERE created_at > NOW() - INTERVAL '24 hours';
```

---

## 7. Lokální testování (development)

> Vyžaduje přímý síťový přístup k DB a ES.

```bash
cp .env.example .env
# Vyplnit credentials

python3 scripts/regular_phase.py --window 15 --dry-run
python3 scripts/backfill.py --days 1 --dry-run
python3 scripts/core/calculate_peak_thresholds.py --dry-run --verbose
python3 scripts/core/peak_detection.py --show-thresholds
```
