#!/usr/bin/env python3
"""
Setup Peak DB V2 - Create new tables for improved peak detection
"""

import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'P050TD01.DEV.KB.CZ'),
    'port': int(os.getenv('DB_PORT', 5432)),
    'database': os.getenv('DB_NAME', 'ailog_analyzer'),
    'user': os.getenv('DB_DDL_USER', 'ailog_analyzer_ddl_user_d1'),
    'password': os.getenv('DB_DDL_PASSWORD')
}

def setup_db():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # SET DDL ROLE - CRITICAL!
        cursor.execute("SET ROLE role_ailog_analyzer_ddl;")
        
        print("=" * 80)
        print("📊 Setting up Peak DB V2 - New Tables")
        print("=" * 80)
        
        # TABLE 1: peak_raw_data
        print("\n1️⃣  Creating table: ailog_peak.peak_raw_data")
        create_peak_raw_data = """
        CREATE TABLE IF NOT EXISTS ailog_peak.peak_raw_data (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP NOT NULL,
            day_of_week INT NOT NULL,
            hour_of_day INT NOT NULL,
            quarter_hour INT NOT NULL,
            namespace VARCHAR(255) NOT NULL,
            error_count FLOAT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            
            UNIQUE (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
        );
        """
        cursor.execute(create_peak_raw_data)
        print("   ✅ Table created")
        
        indexes_raw = [
            "CREATE INDEX IF NOT EXISTS idx_raw_namespace ON ailog_peak.peak_raw_data(namespace)",
            "CREATE INDEX IF NOT EXISTS idx_raw_timestamp ON ailog_peak.peak_raw_data(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_raw_day_hour ON ailog_peak.peak_raw_data(day_of_week, hour_of_day, quarter_hour)",
        ]
        
        for idx in indexes_raw:
            try:
                cursor.execute(idx)
            except:
                pass
        print("   ✅ Indexes created")
        
        # TABLE 2: aggregation_data
        print("\n2️⃣  Creating table: ailog_peak.aggregation_data")
        create_aggregation_data = """
        CREATE TABLE IF NOT EXISTS ailog_peak.aggregation_data (
            id SERIAL PRIMARY KEY,
            day_of_week INT NOT NULL,
            hour_of_day INT NOT NULL,
            quarter_hour INT NOT NULL,
            namespace VARCHAR(255) NOT NULL,
            
            mean FLOAT,
            stddev FLOAT,
            samples INT DEFAULT 1,
            
            last_updated TIMESTAMP DEFAULT NOW(),
            
            UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
        );
        """
        cursor.execute(create_aggregation_data)
        print("   ✅ Table created")
        
        indexes_agg = [
            "CREATE INDEX IF NOT EXISTS idx_agg_namespace ON ailog_peak.aggregation_data(namespace)",
        ]
        
        for idx in indexes_agg:
            try:
                cursor.execute(idx)
            except:
                pass
        print("   ✅ Indexes created")
        
        # TABLE 3: known_issues
        print("\n3️⃣  Creating table: ailog_peak.known_issues")
        create_known_issues = """
        CREATE TABLE IF NOT EXISTS ailog_peak.known_issues (
            id SERIAL PRIMARY KEY,
            issue_name VARCHAR(255) NOT NULL UNIQUE,
            description TEXT,
            
            error_type_pattern VARCHAR(255),
            affected_namespace VARCHAR(255),
            affected_app_name VARCHAR(255),
            
            typical_ratio_min FLOAT DEFAULT 10,
            typical_ratio_max FLOAT DEFAULT 1000,
            typical_duration_min INT,
            typical_duration_max INT,
            
            first_detected TIMESTAMP,
            last_occurrence TIMESTAMP,
            occurrence_count INT DEFAULT 0,
            status VARCHAR(50) DEFAULT 'active',
            
            resolution_steps TEXT,
            is_auto_resolvable BOOLEAN DEFAULT FALSE,
            
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
        cursor.execute(create_known_issues)
        print("   ✅ Table created")
        
        indexes_ki = [
            "CREATE INDEX IF NOT EXISTS idx_ki_namespace ON ailog_peak.known_issues(affected_namespace)",
            "CREATE INDEX IF NOT EXISTS idx_ki_error_type ON ailog_peak.known_issues(error_type_pattern)",
        ]
        
        for idx in indexes_ki:
            try:
                cursor.execute(idx)
            except:
                pass
        print("   ✅ Indexes created")
        
        # TABLE 4: known_peaks
        print("\n4️⃣  Creating table: ailog_peak.known_peaks")
        create_known_peaks = """
        CREATE TABLE IF NOT EXISTS ailog_peak.known_peaks (
            id SERIAL PRIMARY KEY,
            peak_name VARCHAR(255) NOT NULL UNIQUE,
            description TEXT,
            
            namespace VARCHAR(255),
            app_name VARCHAR(255),
            day_of_week INT,
            hour_of_day INT,
            quarter_hour INT,
            
            expected_ratio_min FLOAT,
            expected_ratio_max FLOAT,
            expected_duration_min INT,
            expected_duration_max INT,
            
            peak_type VARCHAR(50),
            is_expected BOOLEAN DEFAULT TRUE,
            
            first_detected TIMESTAMP,
            last_occurrence TIMESTAMP,
            occurrence_count INT DEFAULT 0,
            status VARCHAR(50) DEFAULT 'active',
            
            created_at TIMESTAMP DEFAULT NOW()
        );
        """
        cursor.execute(create_known_peaks)
        print("   ✅ Table created")
        
        indexes_kp = [
            "CREATE INDEX IF NOT EXISTS idx_kp_namespace ON ailog_peak.known_peaks(namespace)",
            "CREATE INDEX IF NOT EXISTS idx_kp_hour ON ailog_peak.known_peaks(day_of_week, hour_of_day)",
        ]
        
        for idx in indexes_kp:
            try:
                cursor.execute(idx)
            except:
                pass
        print("   ✅ Indexes created")
        
        # TABLE 5: peak_investigation
        print("\n5️⃣  Creating table: ailog_peak.peak_investigation")
        create_peak_investigation = """
        CREATE TABLE IF NOT EXISTS ailog_peak.peak_investigation (
            peak_id SERIAL PRIMARY KEY,
            
            timestamp TIMESTAMP NOT NULL,
            day_of_week INT,
            hour_of_day INT,
            quarter_hour INT,
            
            trace_id VARCHAR(255),
            app_name VARCHAR(255),
            app_version VARCHAR(100),
            namespace VARCHAR(255),
            
            original_value FLOAT NOT NULL,
            reference_value FLOAT NOT NULL,
            replacement_value FLOAT,
            ratio FLOAT,
            
            baseline_mean FLOAT,
            same_day_refs_mean FLOAT,
            
            error_type VARCHAR(255),
            error_message TEXT,
            affected_services TEXT,
            
            ai_analysis TEXT,
            ai_confidence FLOAT DEFAULT 0.0,
            suspected_root_cause VARCHAR(255),
            
            known_issue_id INT,
            known_peak_id INT,
            
            investigation_status VARCHAR(50) DEFAULT 'pending',
            resolution_notes TEXT,
            resolved_at TIMESTAMP,
            
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW(),
            
            UNIQUE (timestamp, namespace, app_name),
            FOREIGN KEY (known_issue_id) REFERENCES ailog_peak.known_issues(id) ON DELETE SET NULL,
            FOREIGN KEY (known_peak_id) REFERENCES ailog_peak.known_peaks(id) ON DELETE SET NULL
        );
        """
        cursor.execute(create_peak_investigation)
        print("   ✅ Table created")
        
        indexes_pi = [
            "CREATE INDEX IF NOT EXISTS idx_pi_namespace ON ailog_peak.peak_investigation(namespace)",
            "CREATE INDEX IF NOT EXISTS idx_pi_timestamp ON ailog_peak.peak_investigation(timestamp DESC)",
            "CREATE INDEX IF NOT EXISTS idx_pi_status ON ailog_peak.peak_investigation(investigation_status)",
        ]
        
        for idx in indexes_pi:
            try:
                cursor.execute(idx)
            except:
                pass
        print("   ✅ Indexes created")
        
        conn.commit()
        print("\n" + "=" * 80)
        print("✅ All tables created successfully!")
        print("=" * 80)
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    import sys
    success = setup_db()
    sys.exit(0 if success else 1)
