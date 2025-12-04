1. 
a) projit soucasny system/postup od A-Z, vyzkouset, pak revize zbytecnych filu, ktere se nehodi odstranit
b) z toho pak udelat jednoduchou prirucku how to use.md kde bude v krocich popsano, jak se agent obsluhuje, jake scripty pouziva a jak an sebe navazuji

2. DETECTION & ML IMPROVEMENTS (PRIORITY)
a) overit detekci vsech problemu, ze se zadny dulezity nevynecha -> pridat indexy pca, pcb-ch
   - Review fetch_unlimited.py for hardcoded PCB indexes
   - Add support for PCA index (pca-*)
   - Add support for PCB-CH index (pcb-ch-*)
   - Test multi-index queries
   - Update analyze_period.py with new indexes
   
b) overit seznam vsech znamych/dlouhodobych erroru k likvidaci - jira ticket (vymyslet efektivni zpusob kde ukladat)
   - Export current 49 root causes from last run to known_issues_baseline.json
   - Design storage format (JSON + metadata):
     { issue_id, pattern, count, first_seen, last_updated, severity, affected_apps[], affected_namespaces[] }
   - Create known_issues.json file in data/ directory
   - Implement filtering in analyze_period.py to:
     1. Compare new issues against baseline
     2. Highlight ONLY new issues in reports
     3. Track baseline updates (when issue count increases significantly)
   - Setup for future Jira integration (reserve issue_id field)
   
c) potvrdit machine-learning (hlavne aby dokazal diky DB snadneji poznavat uz zname errory) a vyhodnoceni trvalo mensi cas
   - Verify pattern matching logic in intelligent_analysis.py works correctly
   - Check "new unique patterns" calculation (< 5 errors = new pattern?)
   - Optimize query time (currently 4s for 743 errors, acceptable)
   - Prepare for DB integration (Point 4c)

3.
a) vylepsit zpusob vyhodnoceni - zaklad mame, lepe vyzusit kombinaci - apps affected, peak detection/rate app,ns... 
 aby to bylo vic nez klasicky alerting (ktery je velmi uzitecny, nicmene nezachyti vse a nema intelginetnejsi reakci):
Alert 792 - Major
Resource:
prod@cluster-k8s_prod_0792-in@ITO-114@err
Description:
ITO-114#PCB#bl-pcb#bl-pcb-v1#n/a#n/a#n/a#n/a#114#Problem occurred in case processing step. Processing of step SET_CARD_LIMITS of case 15229758 processing failed due to error Called service OnlineServicesSoap.CardUsageConfigurationMaintenanceRequest error occurred. 1 - Invalid Card Serno . Step will be retried at 2025-11-18T12:58:01.531798391+01:00[Europe/Prague]. ::: CDC prod alerts
Trace ID:
23441d643fdbf302c64f7adf610b5219
Vyskytl se propustny problem behem zpracovani karetniho pozadavku. Zpracovani pokracuje dalsim krokem: Problem occurred in case processing step. Processing of step SET_CARD_LIMITS of case 15229758 processing failed due to error Called service OnlineServicesSoap.CardUsageConfigurationMaintenanceRequest error occurred. 1 - Invalid Card Serno . Step will be retried at 2025-11-18T12:58:01.531798391+01:00[Europe/Prague]. --- traceId: 23441d643fdbf302c64f7adf610b5219 --- v case: 2025-11-18T12:57:01.542+01:00

b) pridat i dohledani ostatni severity logu pro komplexni detekci podle trace ID - tzn primarne fungovat jen pres errory, ale pokud je tam neco opakovaneho, tak podle traceID dohledat i ostatni logy nezavisle na severite pro big picture

c) co to chce dodelat - vyuzit affected apps, najit root cause, ktery tady v detailu je, ale ukazat pres co to jde
                      - podle peak detection vyhodnotit zavaznost (pokud je najednou nekolikrat vice erroru, neni to nahoda, musi se vedet proc)
                      - dat lepsi describtion nez zatim mame
                      - porovnavat s known issue pro rychlejsi vyhodnoceni
                      - navrh reseni problemu



4.
a) predelat agenta do automatickeho modu - aby fungoval autonomne v clusteru a hlasil vysledky sve prace
b) pravidelny evaluation dotazu, sledovat zlepsivani/ubytek dotazu na zaklade denni zpetne vazby, po tydnu zkusit 2-3x tydne
c) napojeni na novou DB s dual ucty:

PostgreSQL database ailog_analyzer was created on instance P050TD01.
Database accounts:
ailog_analyzer_ddl_user_d1/WWvkHhyjje8YSgvU
ailog_analyzer_ddl_user_d2/rO1c4d2ocn3bAHXe
ailog_analyzer_user_d1/y01d40Mmdys/lbDE
ailog_analyzer_user_d2/qE+2bfLaXc3FmoRL
JDBC connection string : jdbc:postgresql://P050TD01.DEV.KB.CZ:5432/ailog_analyzer


5.
napojeni na alertovaci Teams kanal, kam se pak bude propagovat info a nasledne predelat na produkci a testovat tam

6.
monitorovani celeho agenta a postupu uceni, navrhovani optimalizaci pro lepsi uceni, priprava how-to pro jine squady
