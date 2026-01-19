#!/bin/bash

echo "🔄 Resetting data..."

# Truncate tables
python3 << 'PYTHON'
import os, psycopg2
from dotenv import load_dotenv

load_dotenv()
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD')
}

try:
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    cur.execute("DELETE FROM ailog_peak.peak_investigation")
    cur.execute("DELETE FROM ailog_peak.peak_patterns")
    cur.execute("DELETE FROM ailog_peak.peak_statistics")
    cur.execute("DELETE FROM ailog_peak.peak_raw_data")
    conn.commit()
    
    print("✅ Cleared peak_investigation, peak_patterns, peak_statistics, peak_raw_data")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"❌ Error: {e}")
PYTHON

echo ""
echo "📊 Running correct ingest with REPLACE logic..."
python3 ingest_from_log_v2.py --input /tmp/peak_fixed_2025_12_08_09.txt
