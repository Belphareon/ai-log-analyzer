#!/usr/bin/env python3
"""Quick check of peak detection statistics"""
import psycopg2
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load env
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR.parent / '.env')

conn = psycopg2.connect(
    host=os.getenv('DB_HOST'),
    port=int(os.getenv('DB_PORT', 5432)),
    database=os.getenv('DB_NAME'),
    user=os.getenv('DB_USER'),
    password=os.getenv('DB_PASSWORD')
)

cur = conn.cursor()

print("=" * 80)
print("PEAK DETECTION STATISTICS - LAST 24H")
print("=" * 80)

# Statistiky za 24h - baseline-based
cur.execute('''
SELECT 
    COUNT(*) as cnt,
    is_spike,
    is_burst,
    CASE 
        WHEN reference_value = 0 THEN 'ref=0'
        WHEN reference_value IS NULL THEN 'ref=NULL'
        WHEN reference_value > 0 AND reference_value < 10 THEN 'ref=1-9'
        WHEN reference_value >= 10 AND reference_value < 100 THEN 'ref=10-99'
        ELSE 'ref>=100'
    END as ref_bucket
FROM ailog_peak.peak_investigation
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY is_spike, is_burst, ref_bucket
ORDER BY cnt DESC
LIMIT 30;
''')

rows = cur.fetchall()
print("\nCount | Spike | Burst | Baseline")
print("------|-------|-------|----------")
for row in rows:
    spike_str = "TRUE" if row[1] else "FALSE"
    burst_str = "TRUE" if row[2] else "FALSE"
    print(f"{row[0]:5} | {spike_str:5} | {burst_str:5} | {row[3]}")

# Detekce typů
print("\n" + "=" * 80)
print("DETECTION TYPE BREAKDOWN")
print("=" * 80)

cur.execute('''
SELECT 
    COUNT(*) as cnt,
    detection_method,
    is_spike,
    is_burst,
    CASE WHEN score >= 30 THEN 'score>=30' ELSE 'score<30' END as score_level
FROM ailog_peak.peak_investigation
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY detection_method, is_spike, is_burst, score_level
ORDER BY cnt DESC
LIMIT 20;
''')

rows = cur.fetchall()
print(f"\nCount | Method         | Spike | Burst | Score")
print("------|----------------|-------|-------|-------")
for row in rows:
    spike_str = "TRUE" if row[2] else"FALSE"
    burst_str = "TRUE" if row[3] else "FALSE"
    print(f"{row[0]:5} | {row[1]:14} | {spike_str:5} | {burst_str:5} | {row[4]}")

# Problem examples - with baseline = 0
print("\n" + "=" * 80)
print("EXAMPLES: BURSTS WITH BASELINE=0 (FALSE POSITIVES?)")
print("=" * 80)

cur.execute('''
SELECT 
    namespace,
    error_type,
    original_value,
    reference_value,
    score,
    timestamp
FROM ailog_peak.peak_investigation
WHERE timestamp > NOW() - INTERVAL '24 hours'
  AND is_burst = TRUE
  AND reference_value = 0
ORDER BY timestamp DESC
LIMIT 10;
''')

rows = cur.fetchall()
print("\nNamespace          | Error Type         | Orig | Ref | Score | Time")
print("-------------------|--------------------|----- |-----|-------|------")
for row in rows:
    ns = str(row[0])[:18]
    et = str(row[1])[:18]
    print(f"{ns:18} | {et:18} | {row[2]:4} | {row[3]:3} | {row[4]:5.1f} | {row[5].strftime('%H:%M')}")

cur.close()
conn.close()
