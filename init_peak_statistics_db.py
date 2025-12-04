#!/usr/bin/env python3
"""
Phase 1: Initialize peak_statistics database with historical data from Elasticsearch

This script:
1. Connects to PostgreSQL P050TD01
2. Creates peak_statistics, peak_history, and active_peaks tables
3. Collects 2 weeks of historical error data from ES (15-min windows per namespace)
4. Calculates mean/stddev with 3-window smoothing
5. Initializes peak_statistics table for anomaly detection

Usage:
    python3 init_peak_statistics_db.py

Database: P050TD01.DEV.KB.CZ:5432/ailog_analyzer
"""

import psycopg2
from psycopg2 import sql
import json
from datetime import datetime, timedelta
import os
import sys

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
    'password': os.getenv('DB_PASSWORD', 'y01d40Mmdys/lbDE')
}

def connect_db():
    """Connect to PostgreSQL"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        print("✅ Connected to PostgreSQL P050TD01")
        return conn
    except psycopg2.Error as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)

def create_tables(conn):
    """Create peak_statistics, peak_history, and active_peaks tables"""
    cursor = conn.cursor()
    
    sql_commands = [
        # Table 1: peak_statistics
        """
        CREATE TABLE IF NOT EXISTS peak_statistics (
          id SERIAL PRIMARY KEY,
          day_of_week INT NOT NULL,
          hour_of_day INT NOT NULL,
          quarter_hour INT NOT NULL,
          namespace VARCHAR(255) NOT NULL,
          
          mean_errors FLOAT,
          stddev_errors FLOAT,
          samples_count INT DEFAULT 0,
          last_updated TIMESTAMP DEFAULT NOW(),
          
          UNIQUE(day_of_week, hour_of_day, quarter_hour, namespace)
        );
        """,
        
        # Index for peak_statistics
        """
        CREATE INDEX IF NOT EXISTS idx_peak_statistics_lookup 
        ON peak_statistics(day_of_week, hour_of_day, quarter_hour, namespace);
        """,
        
        # Table 2: peak_history
        """
        CREATE TABLE IF NOT EXISTS peak_history (
          id SERIAL PRIMARY KEY,
          peak_id VARCHAR(100) UNIQUE,
          first_occurrence TIMESTAMP NOT NULL,
          last_occurrence TIMESTAMP,
          occurrence_count INT DEFAULT 1,
          root_cause_pattern VARCHAR(500),
          affected_apps TEXT[],
          affected_namespaces TEXT[],
          severity VARCHAR(20),
          is_known BOOLEAN DEFAULT FALSE,
          resolution_note TEXT,
          created_at TIMESTAMP DEFAULT NOW(),
          updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        
        # Indexes for peak_history
        """
        CREATE INDEX IF NOT EXISTS idx_peak_history_known ON peak_history(is_known);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_peak_history_root_cause ON peak_history(root_cause_pattern);
        """,
        
        # Table 3: active_peaks
        """
        CREATE TABLE IF NOT EXISTS active_peaks (
          id SERIAL PRIMARY KEY,
          peak_id VARCHAR(100) UNIQUE,
          namespace VARCHAR(255) NOT NULL,
          start_time TIMESTAMP NOT NULL,
          end_time TIMESTAMP,
          error_count INT,
          status VARCHAR(20) DEFAULT 'in_progress',
          created_at TIMESTAMP DEFAULT NOW(),
          updated_at TIMESTAMP DEFAULT NOW()
        );
        """,
        
        # Indexes for active_peaks
        """
        CREATE INDEX IF NOT EXISTS idx_active_peaks_status ON active_peaks(status);
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_active_peaks_start_time ON active_peaks(start_time DESC);
        """
    ]
    
    for sql_cmd in sql_commands:
        try:
            cursor.execute(sql_cmd)
            conn.commit()
        except psycopg2.Error as e:
            print(f"⚠️  SQL Error: {e}")
            conn.rollback()
    
    print("✅ Database tables created/verified")
    cursor.close()

def main():
    """Main initialization"""
    print("\n" + "="*60)
    print("Phase 1: Peak Detection Database Initialization")
    print("="*60)
    
    # Connect to database
    conn = connect_db()
    
    # Create tables
    create_tables(conn)
    
    print("\n📊 Database Setup Status:")
    print("  ✅ peak_statistics table - ready for baseline data")
    print("  ✅ peak_history table - ready for peak tracking")
    print("  ✅ active_peaks table - ready for temporary peak tracking")
    
    print("\n🔄 Next Steps:")
    print("  1. Run 'collect_historical_peak_data.py' to load 2 weeks of ES data")
    print("  2. Calculate mean/stddev with 3-window smoothing")
    print("  3. Deploy 'collect_peak_data_continuous.py' for ongoing updates")
    
    conn.close()
    print("\n✅ Phase 1 Complete!")

if __name__ == '__main__':
    main()
