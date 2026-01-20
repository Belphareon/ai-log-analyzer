================================================================================
🚀 AI LOG ANALYZER - MAIN PIPELINE
   Started: 2026-01-19T13:07:57.875103
================================================================================

📅 Processing period: 2026-01-06T12:00:00Z → 2026-01-09T23:59:59Z

================================================================================
🔄 STEP 1: SBĚR DAT Z ELASTICSEARCH (2026-01-06T12:00:00Z → 2026-01-09T23:59:59Z)
================================================================================
   Running: /usr/bin/python3 /home/jvsete/git/sas/ai-log-analyzer/scripts/collect_peak_detailed.py --from 2026-01-06T12:00:00Z --to 2026-01-09T23:59:59Z
   ✅ Collected 1618 DATA rows
   📄 Saved to: /tmp/tmp0to2vgeq.txt

================================================================================
🔄 STEP 2: INTELIGENTNÍ ANALÝZA (trace-based root cause)
================================================================================

📊 Analyzing period: 2026-01-06T12:00:00Z → 2026-01-09T23:59:59Z
   🔄 Fetching errors from Elasticsearch...
🔄 Fetcher - UNLIMITED via search_after
   Time range: 2026-01-06T12:00:00Z to 2026-01-09T23:59:59Z
   Batch size: 5,000

🔄 Batch   1... ✅ 5,000 | Total: 5,000
🔄 Batch   2... ✅ 5,000 | Total: 10,000
🔄 Batch   3... ✅ 5,000 | Total: 15,000
🔄 Batch   4... ✅ 5,000 | Total: 20,000
🔄 Batch   5... ✅ 5,000 | Total: 25,000
🔄 Batch   6... ✅ 5,000 | Total: 30,000
🔄 Batch   7... ✅ 5,000 | Total: 35,000
🔄 Batch   8... ✅ 5,000 | Total: 40,000
🔄 Batch   9... ✅ 5,000 | Total: 45,000
🔄 Batch  10... ✅ 5,000 | Total: 50,000
🔄 Batch  11... ✅ 5,000 | Total: 55,000
🔄 Batch  12... ✅ 5,000 | Total: 60,000
🔄 Batch  13... ✅ 5,000 | Total: 65,000
🔄 Batch  14... ✅ 5,000 | Total: 70,000
🔄 Batch  15... ✅ 5,000 | Total: 75,000
🔄 Batch  16... ✅ 5,000 | Total: 80,000
🔄 Batch  17... ✅ 5,000 | Total: 85,000
🔄 Batch  18... ✅ 5,000 | Total: 90,000
🔄 Batch  19... ✅ 5,000 | Total: 95,000
🔄 Batch  20... ✅ 5,000 | Total: 100,000
🔄 Batch  21... ✅ 5,000 | Total: 105,000
🔄 Batch  22... ✅ 5,000 | Total: 110,000
🔄 Batch  23... ✅ 5,000 | Total: 115,000
🔄 Batch  24... ✅ 5,000 | Total: 120,000
🔄 Batch  25... ✅ 5,000 | Total: 125,000
🔄 Batch  26... ✅ 5,000 | Total: 130,000
🔄 Batch  27... ✅ 5,000 | Total: 135,000
🔄 Batch  28... ✅ 5,000 | Total: 140,000
🔄 Batch  29... ✅ 5,000 | Total: 145,000
🔄 Batch  30... ✅ 5,000 | Total: 150,000
🔄 Batch  31... ✅ 5,000 | Total: 155,000
🔄 Batch  32... ✅ 5,000 | Total: 160,000
🔄 Batch  33... ✅ 5,000 | Total: 165,000
🔄 Batch  34... ✅ 5,000 | Total: 170,000
🔄 Batch  35... ✅ 5,000 | Total: 175,000
🔄 Batch  36... ✅ 5,000 | Total: 180,000
🔄 Batch  37... ✅ 5,000 | Total: 185,000
🔄 Batch  38... ✅ 5,000 | Total: 190,000
🔄 Batch  39... ✅ 5,000 | Total: 195,000
🔄 Batch  40... ✅ 5,000 | Total: 200,000
🔄 Batch  41... ✅ 5,000 | Total: 205,000
🔄 Batch  42... ✅ 5,000 | Total: 210,000
🔄 Batch  43... ✅ 5,000 | Total: 215,000
🔄 Batch  44... ✅ 5,000 | Total: 220,000
🔄 Batch  45... ✅ 4,555 | Total: 224,555

✅ Total fetched: 224,555 errors
   ✅ Fetched 224,555 errors
   🔍 Running trace-based root cause analysis...
   ✅ Found 26,577 unique traces
   ✅ Identified 10 root cause patterns
   📝 Tracking error patterns...
   ✅ 70136 new, 546 updated patterns
   🔗 Matching against known issues...
   ✅ 0 matched, 224555 unmatched
   ✅ Analyzed 224,555 errors
   🔍 Top root causes:
      1. bl-pcb-v1: Identification of client 123 could not be updated ... (24102 errors)
      2. bl-pcb-v1: Identification of client 14 could not be updated (... (16188 errors)
      3. bl-pcb-v1: Identification of client 100006856 could not be up... (15822 errors)
   📝 Patterns: 70136 new, 546 updated

================================================================================
🔄 STEP 4: INGESTION + PEAK DETECTION
================================================================================
   Running: /usr/bin/python3 /home/jvsete/git/sas/ai-log-analyzer/scripts/ingest_from_log_v2_regular_fixed.py --input /tmp/tmp0to2vgeq.txt
✅ Loaded config from /home/jvsete/git/sas/ai-log-analyzer/scripts/../values.yaml
   min_ratio_multiplier: 3.0
   max_ratio_multiplier: 5.0
   dynamic_min_multiplier: 2.5
================================================================================
📊 Peak Statistics Ingestion - DYNAMIC THRESHOLDS
================================================================================
Input: /tmp/tmp0to2vgeq.txt
Mode: 🟢 REGULAR PHASE (with peak detection)
Peak ratio multiplier: 3.0×
Dynamic min multiplier: 2.5×
================================================================================

🔍 Detecting file format...
   Format: DATA| (new format with timestamp)
📖 Parsing DATA| format from /tmp/tmp0to2vgeq.txt...
✅ Parsed 1618 DATA lines → 1618 unique keys (after aggregation)

💾 Connecting to database...
✅ Connected to P050TD01.DEV.KB.CZ:5432/ailog_analyzer
📤 Processing 1618 rows...
🔴 PEAK REPLACED: Tue 14:30 pcb-ch-sit-01-app    orig=   103.0 → repl=    11.7 (  8.8×) baseline=56.8 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 16:00 pcb-ch-dev-01-app    orig=   172.0 → repl=    20.7 (  8.3×) baseline=N/A ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 16:30 pcb-sit-01-app       orig=   232.0 → repl=    25.7 (  9.0×) baseline=157.0 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 19:15 pcb-dev-01-app       orig=   197.0 → repl=    35.0 (  5.6×) baseline=201.4 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 20:00 pcb-dev-01-app       orig=   944.0 → repl=    76.7 ( 12.3×) baseline=945.6 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 20:30 pcb-ch-dev-01-app    orig=   892.0 → repl=    20.7 ( 43.2×) baseline=576.2 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 21:15 pcb-sit-01-app       orig=   193.0 → repl=    51.0 (  3.8×) baseline=182.2 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 22:00 pcb-sit-01-app       orig=   940.0 → repl=    95.3 (  9.9×) baseline=935.0 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 22:15 pcb-ch-sit-01-app    orig=   160.0 → repl=    24.7 (  6.5×) baseline=86.2 ✅ [logged to peak_investigation]
🔴 PEAK REPLACED: Tue 22:30 pcb-ch-sit-01-app    orig=   803.0 → repl=    57.3 ( 14.0×) baseline=557.6 ✅ [logged to peak_investigation]

================================================================================
📊 SUMMARY:
   ✅ Total inserted to peak_raw_data: 1618
   🔴 Peaks detected & replaced: 93
   ❌ Failed: 0
   📄 Peak log: /tmp/peaks_replaced_v2.log
================================================================================

   ✅ Ingestion complete

================================================================================
🔄 STEP 5: CHECK KNOWN ISSUES & ERROR PATTERNS
================================================================================
   📊 Recent peaks (1h): 110
   📋 Active known issues: 0
   🔴 Peaks detected - need investigation

================================================================================
🔄 STEP 6: VYHODNOCENÍ & ZÁZNAM
================================================================================
   📊 DB Statistics:
      peak_raw_data: 44408 rows
      aggregation_data: 8064 rows
      peak_investigation: 110 rows
      error_patterns: 77506 rows

================================================================================
🔄 STEP 7: AI ANALÝZA (future)
================================================================================
   ⏭️  AI analysis not yet implemented
   📋 TODO: GitHub Copilot API integration

================================================================================
🔄 STEP 8: NOTIFIKACE
================================================================================
   ⏭️  Notifications disabled

================================================================================
🔄 STEP 9: MONITORING MAINTENANCE
================================================================================
   🗑️  Deleted 23033 old rows from peak_raw_data
   📅 Aggregation last updated: 2026-01-19 12:17:28.320866

================================================================================
✅ PIPELINE COMPLETED SUCCESSFULLY
   Finished: 2026-01-19T13:17:57.813499
================================================================================