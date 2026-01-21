-- ============================================================================
-- AI Log Analyzer - Upgrade from V3 to V4
-- Migration: upgrade_v3_to_v4.sql
-- Purpose: Add V4 features to existing peak_investigation table
-- ============================================================================
-- Spuštění:
--   psql -h $DB_HOST -U $DB_DDL_USER -d $DB_NAME -f upgrade_v3_to_v4.sql
--
-- Poznámka: Toto ZACHOVÁVÁ existující data a jen přidá nové sloupce!
-- ============================================================================

SET ROLE role_ailog_analyzer_ddl;

\echo '=============================================='
\echo '🔄 Upgrading AI Log Analyzer V3 → V4'
\echo '=============================================='
\echo ''

-- ============================================================================
-- STEP 1: Add V4 Flags to peak_investigation
-- ============================================================================
\echo '🔧 Adding V4 flag columns to peak_investigation...'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS is_new BOOLEAN DEFAULT FALSE;
\echo '✅ Added: is_new'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS is_spike BOOLEAN DEFAULT FALSE;
\echo '✅ Added: is_spike'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS is_burst BOOLEAN DEFAULT FALSE;
\echo '✅ Added: is_burst'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS is_cross_namespace BOOLEAN DEFAULT FALSE;
\echo '✅ Added: is_cross_namespace'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS is_regression BOOLEAN DEFAULT FALSE;
\echo '✅ Added: is_regression'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS is_cascade BOOLEAN DEFAULT FALSE;
\echo '✅ Added: is_cascade'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS detection_method VARCHAR(50);
\echo '✅ Added: detection_method'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS score NUMERIC(5,2);
\echo '✅ Added: score'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS severity VARCHAR(20);
\echo '✅ Added: severity'

ALTER TABLE ailog_peak.peak_investigation ADD COLUMN IF NOT EXISTS threshold_used NUMERIC(12,2);
\echo '✅ Added: threshold_used'

\echo ''

-- ============================================================================
-- STEP 2: Create new tables for V4
-- ============================================================================
\echo '📊 Creating V4 analysis tables...'

CREATE TABLE IF NOT EXISTS ailog_peak.peak_thresholds (
    id SERIAL PRIMARY KEY,
    namespace VARCHAR(100) NOT NULL,
    day_of_week INTEGER,
    hour_of_day INTEGER,
    
    spike_threshold NUMERIC(8,2),
    spike_mad_threshold NUMERIC(8,2),
    baseline_value NUMERIC(12,2),
    baseline_stddev NUMERIC(12,2),
    
    samples_count INTEGER,
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE (namespace, day_of_week, hour_of_day)
);

\echo '✅ Created table: peak_thresholds'

CREATE TABLE IF NOT EXISTS ailog_peak.incident_metrics (
    id SERIAL PRIMARY KEY,
    incident_id INTEGER REFERENCES ailog_peak.peak_investigation(id) ON DELETE CASCADE,
    
    metric_name VARCHAR(100),
    metric_value NUMERIC(12,2),
    baseline_value NUMERIC(12,2),
    ratio NUMERIC(8,2),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

\echo '✅ Created table: incident_metrics'

\echo ''

-- ============================================================================
-- STEP 3: Create indices for V4 queries
-- ============================================================================
\echo '⚡ Creating V4 indices...'

CREATE INDEX IF NOT EXISTS idx_pi_is_spike ON ailog_peak.peak_investigation(is_spike);
CREATE INDEX IF NOT EXISTS idx_pi_is_burst ON ailog_peak.peak_investigation(is_burst);
CREATE INDEX IF NOT EXISTS idx_pi_is_new ON ailog_peak.peak_investigation(is_new);
CREATE INDEX IF NOT EXISTS idx_pi_is_cross_ns ON ailog_peak.peak_investigation(is_cross_namespace);
CREATE INDEX IF NOT EXISTS idx_pi_is_regression ON ailog_peak.peak_investigation(is_regression);
CREATE INDEX IF NOT EXISTS idx_pi_is_cascade ON ailog_peak.peak_investigation(is_cascade);
CREATE INDEX IF NOT EXISTS idx_pi_detection_method ON ailog_peak.peak_investigation(detection_method);
CREATE INDEX IF NOT EXISTS idx_pi_severity ON ailog_peak.peak_investigation(severity);
CREATE INDEX IF NOT EXISTS idx_pi_score ON ailog_peak.peak_investigation(score);
CREATE INDEX IF NOT EXISTS idx_pt_namespace ON ailog_peak.peak_thresholds(namespace);
CREATE INDEX IF NOT EXISTS idx_im_incident ON ailog_peak.incident_metrics(incident_id);

\echo '✅ Indices created'

\echo ''

-- ============================================================================
-- STEP 4: Verification
-- ============================================================================
\echo '✅ VERIFICATION'
\echo '=============================================='
\echo ''

\echo 'Tables in ailog_peak schema:'
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'ailog_peak' ORDER BY table_name;

\echo ''
\echo 'Peak Investigation columns (V4 additions):'
SELECT column_name, data_type 
FROM information_schema.columns
WHERE table_schema = 'ailog_peak' AND table_name = 'peak_investigation'
  AND column_name IN ('is_new', 'is_spike', 'is_burst', 'is_cross_namespace', 
                     'is_regression', 'is_cascade', 'severity', 'score', 
                     'detection_method', 'threshold_used')
ORDER BY ordinal_position;

\echo ''
\echo '=============================================='
\echo '✅ V3 → V4 Upgrade completed successfully!'
\echo '=============================================='
