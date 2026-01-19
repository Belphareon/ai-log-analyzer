#!/usr/bin/env python3
"""
Create Peak Investigation & Pattern Tables
================================================================================
Creates 2 new tables for Phase 5B peak detection analysis:
  - peak_investigation: Detailed peak records with AI analysis
  - peak_patterns: Aggregated patterns for self-learning

Usage:
    cd scripts
    python3 create_investigation_tables.py

Requirements:
    - DB credentials in .env
    - Schema ailog_peak must exist
    - User must have DDL permissions
"""

import psycopg2
import os
import sys

DB_HOST = os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ')
DB_PORT = int(os.getenv('DB_PORT', 5432))
DB_NAME = os.getenv('DB_NAME', 'ailog_analyzer')
DB_DDL_USER = os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1')
DB_DDL_PASSWORD = os.getenv('DB_DDL_PASSWORD')

print("\n" + "="*80)
print("🔧 Creating Peak Investigation & Pattern Tables")
print("="*80)
print(f"\nDatabase: {DB_HOST}:{DB_PORT}/{DB_NAME}")
print(f"User: {DB_DDL_USER}\n")

try:
    # Connect with DDL user
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_DDL_USER,
        password=DB_DDL_PASSWORD
    )
    cursor = conn.cursor()
    print("✅ Connected to PostgreSQL")
    
    # Set DDL role
    try:
        cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
        print("✅ DDL role activated\n")
    except:
        print("⚠️  Warning: Could not set DDL role (may not be critical)\n")
    
    # ============================================================================
    # TABLE 1: peak_investigation
    # ============================================================================
    print("📊 Creating table: ailog_peak.peak_investigation")
    print("-" * 80)
    
    create_peak_investigation = """
    CREATE TABLE IF NOT EXISTS ailog_peak.peak_investigation (
      -- Primary identifiers
      id SERIAL PRIMARY KEY,
      
      -- Time identifiers (when did the peak occur?)
      day_of_week INT NOT NULL,           -- 0-6 (Mon-Sun)
      hour_of_day INT NOT NULL,           -- 0-23
      quarter_hour INT NOT NULL,          -- 0-3 (00, 15, 30, 45 minutes)
      
      -- Metadata
      namespace VARCHAR(255) NOT NULL,    -- Which app/namespace? (e.g., pcb-dev-01-app)
      app_version VARCHAR(100),           -- App version at time of peak
      cluster_name VARCHAR(100),          -- Kubernetes cluster
      pod_name VARCHAR(255),              -- Specific pod that reported error
      
      -- Peak values
      original_value FLOAT NOT NULL,      -- Original error count (peak)
      reference_value FLOAT NOT NULL,     -- Calculated baseline
      replacement_value FLOAT,            -- What we stored in peak_statistics (if replaced)
      ratio FLOAT NOT NULL,               -- original_value / reference_value
      
      -- Detection context (for debugging/analysis)
      refs_windows_values FLOAT[],        -- 3 windows before (same day)
      refs_days_values FLOAT[],           -- 3 days before (same hour)
      detection_method VARCHAR(50),       -- 'ratio_15x' | 'ratio_50x' | 'manual'
      
      -- Classification
      peak_type VARCHAR(50),              -- 'recurring' | 'anomaly' | 'known'
      known_cause VARCHAR(255),           -- If it's a known peak, what causes it?
      
      -- AI Analysis
      ai_analysis TEXT,                   -- LLM analysis output
      ai_confidence FLOAT DEFAULT 0.5,    -- 0.0-1.0 confidence in analysis
      
      -- Resolution tracking
      investigation_status VARCHAR(50) DEFAULT 'pending',  -- 'pending' | 'in_progress' | 'resolved'
      resolution_notes TEXT,              -- What was done? How was it resolved?
      resolved_at TIMESTAMP,              -- When was it resolved?
      
      -- Timestamps
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW(),
      
      -- Unique constraint (one record per peak per time)
      UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
    );
    """
    
    try:
        cursor.execute(create_peak_investigation)
        conn.commit()
        print("   ✅ Table created\n")
    except psycopg2.Error as e:
        print(f"   ❌ Error: {e}\n")
        conn.rollback()
        cursor.close()
        conn.close()
        sys.exit(1)
    
    # Create indexes for peak_investigation
    print("📇 Creating indexes for peak_investigation")
    indexes_pi = [
        ("idx_pi_namespace", "CREATE INDEX IF NOT EXISTS idx_pi_namespace ON ailog_peak.peak_investigation(namespace)"),
        ("idx_pi_peak_type", "CREATE INDEX IF NOT EXISTS idx_pi_peak_type ON ailog_peak.peak_investigation(peak_type)"),
        ("idx_pi_created_at", "CREATE INDEX IF NOT EXISTS idx_pi_created_at ON ailog_peak.peak_investigation(created_at DESC)"),
        ("idx_pi_status", "CREATE INDEX IF NOT EXISTS idx_pi_status ON ailog_peak.peak_investigation(investigation_status)"),
    ]
    
    for idx_name, idx_sql in indexes_pi:
        try:
            cursor.execute(idx_sql)
            conn.commit()
            print(f"   ✅ {idx_name}")
        except psycopg2.Error as e:
            print(f"   ⚠️  {idx_name}: {e}")
    
    # ============================================================================
    # TABLE 2: peak_patterns
    # ============================================================================
    print("\n📊 Creating table: ailog_peak.peak_patterns")
    print("-" * 80)
    
    create_peak_patterns = """
    CREATE TABLE IF NOT EXISTS ailog_peak.peak_patterns (
      -- Primary identifiers
      id SERIAL PRIMARY KEY,
      pattern_hash VARCHAR(64) UNIQUE,    -- MD5(namespace + day_of_week + hour + quarter)
      
      -- Pattern metadata
      namespace VARCHAR(255) NOT NULL,    -- Which app/namespace?
      day_of_week INT,                    -- NULL = all days
      hour_of_day INT,                    -- NULL = all hours
      quarter_hour INT,                   -- NULL = all quarters
      
      -- Statistics
      occurrence_count INT DEFAULT 1,     -- How many times have we seen this peak?
      avg_original_value FLOAT,           -- Average height of peak
      avg_reference_value FLOAT,          -- Average baseline
      last_seen TIMESTAMP,                -- Last time we saw this peak
      first_seen TIMESTAMP,               -- First time we saw this peak
      
      -- AI & Knowledge
      probable_cause VARCHAR(500),        -- What causes this peak?
      cause_confidence FLOAT DEFAULT 0.0, -- 0.0-1.0 confidence in probable_cause
      recommended_action VARCHAR(500),    -- What should we do?
      
      -- Learning & Tracking
      is_known BOOLEAN DEFAULT FALSE,     -- Do we understand this peak?
      is_resolved BOOLEAN DEFAULT FALSE,  -- Have we fixed it?
      resolution_notes TEXT,              -- Details about resolution
      last_resolution_at TIMESTAMP,       -- When was it last resolved?
      
      -- Timestamps
      created_at TIMESTAMP DEFAULT NOW(),
      updated_at TIMESTAMP DEFAULT NOW(),
      
      UNIQUE (pattern_hash)
    );
    """
    
    try:
        cursor.execute(create_peak_patterns)
        conn.commit()
        print("   ✅ Table created\n")
    except psycopg2.Error as e:
        print(f"   ❌ Error: {e}\n")
        conn.rollback()
        cursor.close()
        conn.close()
        sys.exit(1)
    
    # Create indexes for peak_patterns
    print("📇 Creating indexes for peak_patterns")
    indexes_pp = [
        ("idx_pp_namespace", "CREATE INDEX IF NOT EXISTS idx_pp_namespace ON ailog_peak.peak_patterns(namespace)"),
        ("idx_pp_is_known", "CREATE INDEX IF NOT EXISTS idx_pp_is_known ON ailog_peak.peak_patterns(is_known)"),
        ("idx_pp_is_resolved", "CREATE INDEX IF NOT EXISTS idx_pp_is_resolved ON ailog_peak.peak_patterns(is_resolved)"),
        ("idx_pp_last_seen", "CREATE INDEX IF NOT EXISTS idx_pp_last_seen ON ailog_peak.peak_patterns(last_seen DESC)"),
    ]
    
    for idx_name, idx_sql in indexes_pp:
        try:
            cursor.execute(idx_sql)
            conn.commit()
            print(f"   ✅ {idx_name}")
        except psycopg2.Error as e:
            print(f"   ⚠️  {idx_name}: {e}")
    
    # ============================================================================
    # GRANT PERMISSIONS
    # ============================================================================
    print("\n🔐 Granting permissions to ailog_analyzer_user_d1")
    print("-" * 80)
    
    grants = [
        ("SELECT, INSERT, UPDATE, DELETE", "SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_investigation TO ailog_analyzer_user_d1"),
        ("SELECT, INSERT, UPDATE, DELETE", "SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_patterns TO ailog_analyzer_user_d1"),
        ("USAGE, SELECT", "USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1"),
    ]
    
    for perm_label, grant_sql in grants:
        try:
            cursor.execute(f"GRANT {grant_sql}")
            conn.commit()
            print(f"   ✅ GRANT {perm_label}")
        except psycopg2.Error as e:
            print(f"   ⚠️  GRANT {perm_label}: {e}")
    
    # ============================================================================
    # VERIFICATION
    # ============================================================================
    print("\n" + "="*80)
    print("✅ VERIFICATION")
    print("="*80)
    
    cursor.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'ailog_peak' 
        ORDER BY table_name
    """)
    tables = cursor.fetchall()
    
    print("\nTables in ailog_peak schema:")
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) FROM ailog_peak.{table[0]}")
        count = cursor.fetchone()[0]
        status = "✅" if table[0] != 'peak_investigation' or count == 0 else "✅"
        print(f"  {status} {table[0]}: {count} rows")
    
    cursor.close()
    conn.close()
    
    print("\n" + "="*80)
    print("✅ Setup Complete!")
    print("="*80)
    print("\nNext steps:")
    print("  1. Update ingest_from_log.py to log peaks to peak_investigation")
    print("  2. Reprocess INIT Phase 1 data (1.12-7.12)")
    print("  3. Process INIT Phase 2 data (8.12-14.12)")
    print("  4. Run REGULAR Phase (15.12+)")
    print()
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
