┌─────────────────────────────────────────────────────────┐
│                    ELASTICSEARCH                         │
│                   (všechny errory)                       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
         ┌─────────────────────────────┐
         │  collect_peak_detailed.py   │
         │  (agregace 15-min windows)  │
         └──────────────┬──────────────┘
                        │
                        ▼
         ┌─────────────────────────────┐
         │   ingest_from_log_v2.py     │
         │   (peak detection)          │
         └──────────────┬──────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
   ┌────────┐    ┌──────────┐   ┌──────────────┐
   │ PEAK?  │    │ NO PEAK  │   │ HIGH STEADY  │
   └────┬───┘    └─────┬────┘   └──────┬───────┘
        │              │                │
        ▼              ▼                ▼
┌──────────────┐  ┌────────────┐  ┌─────────────────┐
│peak_raw_data │  │peak_raw_   │  │error_patterns   │
│(replaced val)│  │data (real) │  │(všechny errory) │
└──────┬───────┘  └─────┬──────┘  └────────┬────────┘
       │                │                   │
       ▼                ▼                   ▼
┌──────────────────────────────────────────────────┐
│           update_aggregation.py                   │
│         (refresh baseline každých 15min)          │
└───────────────────────┬──────────────────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│peak_         │  │known_peaks  │  │known_issues  │
│investigation │  │(expected)   │  │(bugs)        │
└──────┬───────┘  └──────┬──────┘  └──────┬───────┘
       │                 │                 │
       └────────┬────────┴────────┬────────┘
                │                 │
                ▼                 ▼
       ┌─────────────────────────────────┐
       │    match_known_issues.py        │
       │    match_known_peaks.py         │
       │  (pattern matching + context)   │
       └────────────────┬────────────────┘
                        │
                        ▼
       ┌─────────────────────────────────┐
       │     ai_analyze_peaks.py         │
       │  (AI inference - OpenAI/Claude) │
       │   + analyze_steady_errors.py    │
       └────────────────┬────────────────┘
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
┌──────────────┐  ┌─────────────┐  ┌──────────────┐
│ Teams alert  │  │ Auto-ticket │  │ Auto-fix PR  │
│ (critical)   │  │ (trends)    │  │ (GHC)        │
└──────────────┘  └─────────────┘  └──────────────┘




📋 COMPLETE WORKFLOW CHAIN
INIT Fáze ✅ (HOTOVO)
Peak_raw_data: 10,861 řádků (21 dnů reálných dat)
Aggregation_data: 8,064 řádků (kompletní týdenní grid)
REGULAR Fáze (denní)
1) Data collection (collect_peak_detailed.py)

Sbírá data z ES každých 15 min
Output: DATA|timestamp|day|hour|quarter|namespace|mean|stddev|samples
2) Peak detection + DB write (ingest_from_log_v2.py BEZ --init flag)

Porovnání:
Aggregation baseline (z aggregation_data)
3 předchozí okna stejný den (z peak_raw_data)
Decision: ratio ≥ 15× AND value ≥ 100 → PEAK!
3a) NO PEAK:

→ INSERT do peak_raw_data
3b) PEAK detected:

→ INSERT do peak_investigation (full context)
→ INSERT do peak_raw_data s nahrazenou hodnotou (reference místo peaku)
4) Update aggregation (update_aggregation.py - CHYBÍ, musím vytvořit)

Po každém insertu do peak_raw_data
Přepočítá mean/stddev/samples v aggregation_data
Rolling update (zachová 7denní okno)
5) Known issues matching (match_known_issues.py - CHYBÍ)

Po detekci peaku
Porovná error pattern s known_issues tabulkou
Pokud match → aktualizuje peak_investigation.known_issue_id
6) AI Analysis (ai_analyze_peaks.py - CHYBÍ, fáze 5)

Načte nové peaky z peak_investigation (WHERE ai_analysis IS NULL)
Zavolá AI (OpenAI/Claude) s kontextem
Uloží analýzu do peak_investigation.ai_analysis
7) Teams notification (send_teams_notification.py - ČÁSTEČNĚ EXISTUJE)

Po AI analýze
Formátuje message s AI insights
Pošle do Teams kanálu
8) Auto-fix PR (create_fix_pr.py - fáze 5, GHC)

Pokud AI confidence > 0.8 AND je to známý pattern
GitHub Copilot vytvoří PR s fixem


Known Issues vs Known Peaks
Máš naprostou pravdu - jsou 2 kategorie:

A) known_peaks - Očekávané anomálie
Scheduled jobs (denní backup v 2:00 → spike errorů)
Maintenance windows
Známé deploymenty
Nejsou problémy, ale očekávané vzorce
Akce: Suppress notifikaci, zalogovat jako "expected"
B) known_issues - Známé bugs/problémy
Opakující se errory (OutOfMemory na service X)
Známé regression bugs
Timeout na endpoint Y
JSOU problémy, ale už identifikované
Akce: Match pattern, doplnit context, link na ticket/PR
**C) Všechny ostatní errory (mimo peaky)
Potřebujeme tabulku error_patterns pro tracking všech errorů
AI analýza i pro non-peak errory (např. steady 50 errors/15min = možný memory leak)
Tracking trendu (pomalu roste → problém, ale ne peak)

Known Peaks - JIŽ VIDĚNÉ/VYŘEŠENÉ
Správnější popis:

known_peaks = Katalog vyřešených problémů
Peak který už byl, byl investigován, má známé řešení
Pattern matching: Nový peak → match na known_peak → instant context
Obsah:
Error pattern (stacktrace, message)
Root cause (co to způsobilo)
Solution (jak vyřešit)
Prevention (jak předejít)
Link na ticket/PR
Benefit: Při matchi není třeba investigace, rovnou pošleme řešení
Příklad:
Known Peak #42:
  Pattern: "OutOfMemoryError in pcb-sit-01-app"
  Root Cause: Memory leak v UserService.getUsers()
  Solution: Restart pod + hotfix v2.3.2
  Prevention: Upgrade na v2.4.0 (fix je tam)
  Ticket: JIRA-1234
Nový peak → match → "Toto je známý problém JIRA-1234, řešení: restart + upgrade"

🔧 3) Evidence VŠECH errorů - rychlejší analýza
Nová tabulka: error_patterns
CREATE TABLE error_patterns (
  id SERIAL PRIMARY KEY,
  namespace VARCHAR(255),
  error_type VARCHAR(255),
  error_message TEXT,
  pattern_hash VARCHAR(64),  -- hash pro rychlé matching
  
  -- Statistics
  first_seen TIMESTAMP,
  last_seen TIMESTAMP,
  occurrence_count INT,
  avg_errors_per_15min FLOAT,
  
  -- Classification
  severity VARCHAR(50),  -- low, medium, high, critical
  is_peak BOOLEAN,
  is_steady BOOLEAN,  -- steady high errors (ne peak, ale problém)
  
  -- Analysis
  ai_analysis TEXT,
  root_cause VARCHAR(255),
  solution TEXT,
  
  -- Links
  related_ticket VARCHAR(100),
  related_pr VARCHAR(100)
);

Tracking script: track_all_errors.py

Sbírá všechny errory z ES (ne jen agregované okna)
Vytváří pattern hash (stacktrace + message)
Ukládá do error_patterns
AI analýza i pro non-peak errory


K8s Deployment (poznámka k bodu 5):
CronJob každých 15 min:
schedule: "*/15 * * * *"
containers:
  - collect_peak_detailed.py (ES → .txt)
  - ingest_from_log_v2.py (txt → DB, peak detection)
  - update_aggregation.py (refresh baseline)
  - match_known_issues.py (pattern matching)
  - ai_analyze_peaks.py (AI inference)
  - send_teams_notification.py (alert)
  
  
Chybějící scripty k implementaci:

update_aggregation.py - rolling update aggregation_data
match_known_issues.py - pattern matching
create_fix_pr.py - auto-fix (fáze 5, GHC)
track_all_errors.py -new
- doladit peak detection


SPRÁVNÝ Algoritmus (z dokumentace):
To, co jsem říkal, byla TOTÁLNÍ PITOMOST!
# REFERENCE 1: BASELINE (1 týden - aggregation_data)
baseline_mean = aggregation[day, hour, quarter, namespace].mean

# REFERENCE 2: SAME DAY (poslední 4 okna dnes z peak_raw_data)
same_day_windows = [poslední 4 okna z raw_data dnes]
same_day_mean = average(same_day_windows)

# FINAL REFERENCE
final_ref = average([baseline_mean, same_day_mean])

# PEAK DECISION
is_peak = (ratio >= 15?) AND..?


🔑 Klíčové rozdíly:
✅ Layer 2 SPRÁVNĚ: Stejné okno (10:30) ze STEJNÉHO dne TÝDNE v minulých týdnech → To je baseline_mean v aggregation_data!

✅ Nahrazování:

Detekujeme peak → zaznamenáme ORIGINÁLNÍ hodnotu (5000) do peak_investigation
Do peak_raw_data uložíme REFERENČNÍ hodnotu (replacement)
Další okna pak budou používat čistou referenci
✅ Ratio >= 15 AND value >= 100 - To je DYNAMICKÉ na baseline, ne hardcoded!

REFERENCE 2: SAME DAY (poslední 4 okna dnes z peak_raw_data) - dame 3, ale sbirat budeme 4, pro jistotu, ono stejne to ctvrte je to, ktere se aktualne sbira.... s tim se to neda porovnat
PEAK DECISION
is_peak = (ratio >= 15) ... pouze, zadna absolutni hodnota jako (value >= 100), spis by se tam namisto 100 dal pouzit treba celkovy prumer za poslednich 24h pro dane NS a jeste je otazka jestli ratio ma byt taky hardcodovane, jestli by nemelo byt dynamicke, 15 se mi zda moc a dost absolutni