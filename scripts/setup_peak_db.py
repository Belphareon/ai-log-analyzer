#!/usr/bin/env python3
"""
Safe Setup: Create ONLY new Peak Investigation & Patterns tables
================================================================================
⚠️  IMPORTANT: This script ONLY creates new tables. It NEVER modifies or deletes
existing data in peak_statistics (which contains 7,572 rows of INIT Phase 1 data).

What it creates:
  - ailog_peak.peak_investigation  (new table for peak analysis records)
  - ailog_peak.peak_patterns       (new table for pattern aggregation)

What it does NOT touch:
  - ailog_peak.peak_statistics     (UNCHANGED - data preserved!)

Usage:
    python3 setup_peak_db.py

Prerequisites:
    - .env file with DB credentials (DB_DDL_USER, DB_DDL_PASSWORD)
    - Schema ailog_peak already exists (created by init_peak_statistics_db.py)
    - peak_statistics table already exists and has data
"""

import psycopg2
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1'),
    'password': os.getenv('DB_DDL_PASSWORD')
}

def main():
    print("\n" + "="*80)
    print("🔐 SAFE Database Setup: Creating Peak Investigation Schema")
    print("="*80)
    print("\nDatabase Configuration:")
    print(f"  Host: {DB_CONFIG['host']}")
    print(f"  Database: {DB_CONFIG['database']}")
    print(f"  User: {DB_CONFIG['user']}")
    
    try:
        # Step 0: Verify existing data is safe (use data user for SELECT)
        print("\n" + "-"*80)
        print("🔍 Verification: Checking existing data...")
        print("-"*80)
        
        verify_config = {
            'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
            'port': int(os.getenv('DB_PORT', 5432)),
            'database': os.getenv('DB_NAME', 'ailog_analyzer'),
            'user': os.getenv('DB_USER', 'ailog_analyzer_user_d1'),
            'password': os.getenv('DB_PASSWORD')
        }
        
        verify_conn = psycopg2.connect(**verify_config)
        verify_cursor = verify_conn.cursor()
        
        verify_cursor.execute("SELECT COUNT(*) FROM ailog_peak.peak_statistics")
        ps_count = verify_cursor.fetchone()[0]
        print(f"✅ peak_statistics: {ps_count} rows (WILL NOT BE MODIFIED)")
        
        verify_cursor.close()
        verify_conn.close()
        
        # Now connect with DDL user for schema creation
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("✅ Connected to PostgreSQL (DDL user)")
        
        # Step 1: Set DDL role
        try:
            cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
            print("✅ DDL role activated")
        except psycopg2.Error as e:
            print(f"⚠️  Warning: DDL role not available: {e}")
        
        # Step 2: Create peak_investigation table
        print("\n" + "-"*80)
        print("📊 Creating table: ailog_peak.peak_investigation")
        print("-"*80)
        
        create_peak_investigation = """
        CREATE TABLE IF NOT EXISTS ailog_peak.peak_investigation (
          id SERIAL PRIMARY KEY,
          day_of_week INT NOT NULL,
          hour_of_day INT NOT NULL,
          quarter_hour INT NOT NULL,
          namespace VARCHAR(255) NOT NULL,
          app_version VARCHAR(100),
          cluster_name VARCHAR(100),
          pod_name VARCHAR(255),
          original_value FLOAT NOT NULL,
          reference_value FLOAT NOT NULL,
          replacement_value FLOAT,
          ratio FLOAT NOT NULL,
          refs_windows_values FLOAT[],
          refs_days_values FLOAT[],
          detection_method VARCHAR(50),
          peak_type VARCHAR(50),
          known_cause VARCHAR(255),
          ai_analysis TEXT,
          ai_confidence FLOAT DEFAULT 0.5,
          investigation_status VARCHAR(50) DEFAULT 'pending',
          resolution_notes TEXT,
          resolved_at TIMESTAMP,
          created_at TIMESTAMP DEFAULT NOW(),
          updated_at TIMESTAMP DEFAULT NOW(),
          UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
        );
        """
        
        cursor.execute(create_peak_investigation)
        print("✅ Table created successfully")
        
        # Create indexes for peak_investigation
        print("\nCreating indexes for peak_investigation...")
        indexes_pi = [
            "CREATE INDEX IF NOT EXISTS idx_pi_namespace ON ailog_peak.peak_investigation(namespace)",
            "CREATE INDEX IF NOT EXISTS idx_pi_peak_type ON ailog_peak.peak_investigation(peak_type)",
            "CREATE INDEX IF NOT EXISTS idx_pi_created_at ON ailog_peak.peak_investigation(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pi_status ON ailog_peak.peak_investigation(investigation_status)",
        ]
        
        for idx_sql in indexes_pi:
            try:
                cursor.execute(idx_sql)
                print(f"  ✅ {idx_sql.split('IF NOT EXISTS')[1].split('ON')[0].strip()}")
            except psycopg2.Error as e:
                print(f"  ⚠️  Index creation warning: {e}")
        
        # Step 3: Create peak_patterns table
        print("\n" + "-"*80)
        print("📊 Creating table: ailog_peak.peak_patterns")
        print("-"*80)
        
        create_peak_patterns = """
        CREATE TABLE IF NOT EXISTS ailog_peak.peak_patterns (
          id SERIAL PRIMARY KEY,
          pattern_hash VARCHAR(64) UNIQUE,
          namespace VARCHAR(255) NOT NULL,
          day_of_week INT,
          hour_of_day INT,
          quarter_hour INT,
          occurrence_count INT DEFAULT 1,
          avg_original_value FLOAT,
          avg_reference_value FLOAT,
          last_seen TIMESTAMP,
          first_seen TIMESTAMP,
          probable_cause VARCHAR(500),
          cause_confidence FLOAT DEFAULT 0.0,
          recommended_action VARCHAR(500),
          is_known BOOLEAN DEFAULT FALSE,
          is_resolved BOOLEAN DEFAULT FALSE,
          resolution_notes TEXT,
          last_resolution_at TIMESTAMP,
          created_at TIMESTAMP DEFAULT NOW(),
          updated_at TIMESTAMP DEFAULT NOW()
        );
        """
        
        cursor.execute(create_peak_patterns)
        print("✅ Table created successfully")
        
        # Create indexes for peak_patterns
        print("\nCreating indexes for peak_patterns...")
        indexes_pp = [
            "CREATE INDEX IF NOT EXISTS idx_pp_namespace ON ailog_peak.peak_patterns(namespace)",
            "CREATE INDEX IF NOT EXISTS idx_pp_is_known ON ailog_peak.peak_patterns(is_known)",
            "CREATE INDEX IF NOT EXISTS idx_pp_is_resolved ON ailog_peak.peak_patterns(is_resolved)",
            "CREATE INDEX IF NOT EXISTS idx_pp_last_seen ON ailog_peak.peak_patterns(last_seen DESC)",
        ]
        
        for idx_sql in indexes_pp:
            try:
                cursor.execute(idx_sql)
                print(f"  ✅ {idx_sql.split('IF NOT EXISTS')[1].split('ON')[0].strip()}")
            except psycopg2.Error as e:
                print(f"  ⚠️  Index creation warning: {e}")
        
        # Step 4: Grant permissions
        print("\n" + "-"*80)
        print("🔐 Granting permissions to ailog_analyzer_user_d1")
        print("-"*80)
        
        grants = [
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_investigation TO ailog_analyzer_user_d1",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_patterns TO ailog_analyzer_user_d1",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1",
        ]
        
        for grant_sql in grants:
            try:
                cursor.execute(grant_sql)
                table_name = grant_sql.split('ON')[1].split('TO')[0].strip()
                print(f"✅ {table_name}")
            except psycopg2.Error as e:
                print(f"⚠️  {grant_sql}: {e}")
        
        # Commit all changes
        conn.commit()
        
        # Step 5: Final verification
        print("\n" + "-"*80)
        print("✅ FINAL VERIFICATION")
        print("-"*80)
        
        cursor.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'ailog_peak'
            ORDER BY table_name
        """)
        tables = cursor.fetchall()
        
        print("\nTables in ailog_peak schema:")
        for table in tables:
            table_name = table[0]
            if table_name != 'peak_raw_data' and table_name != 'active_peaks' and table_name != 'peak_history':
                cursor.execute(f"SELECT COUNT(*) FROM ailog_peak.{table_name}")
                count = cursor.fetchone()[0]
                print(f"  ✅ {table_name}: {count} rows")
        
        print("\n" + "="*80)
        print("✅ SETUP COMPLETE - All new tables created safely!")
        print("="*80)
        print("\n📋 Next steps:")
        print("  1. Run: cd scripts && python3 ingest_from_log.py --input /tmp/peak_fixed_2025_12_08_09.txt")
        print("  2. Verify: python3 verify_db_integrity.py")
        print("  3. Process remaining Phase 2 data")
        
        cursor.close()
        conn.close()
        
    except psycopg2.Error as e:
        print(f"\n❌ Database Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
