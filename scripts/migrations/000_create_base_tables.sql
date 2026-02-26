-- ============================================================================
-- AI Log Analyzer - Base Tables
-- Migration: 000_create_base_tables.sql
-- Version: 4.0
-- ============================================================================
-- Spuštění:
--   psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f 000_create_base_tables.sql
-- ============================================================================

-- Create schema
CREATE SCHEMA IF NOT EXISTS ailog_peak;

-- ============================================================================
-- TABLE: peak_raw_data
-- Účel: Raw error counts per 15-min window
-- ============================================================================
CREATE TABLE IF NOT EXISTS ailog_peak.peak_raw_data (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    day_of_week INTEGER NOT NULL,       -- 0=Mon, 6=Sun
    hour_of_day INTEGER NOT NULL,       -- 0-23
    quarter_hour INTEGER NOT NULL,      -- 0-3 (0, 15, 30, 45 min)
    namespace VARCHAR(100) NOT NULL,
    error_count NUMERIC(12,2),          -- Aktuální hodnota
    original_value NUMERIC(12,2),       -- Původní hodnota před replacement
    is_peak BOOLEAN DEFAULT FALSE,
    replacement_value NUMERIC(12,2),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE (timestamp, day_of_week, hour_of_day, quarter_hour, namespace)
);

CREATE INDEX IF NOT EXISTS idx_prd_timestamp ON ailog_peak.peak_raw_data(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_prd_namespace ON ailog_peak.peak_raw_data(namespace);
CREATE INDEX IF NOT EXISTS idx_prd_is_peak ON ailog_peak.peak_raw_data(is_peak);
CREATE INDEX IF NOT EXISTS idx_prd_dow ON ailog_peak.peak_raw_data(day_of_week);

-- ============================================================================
-- TABLE: aggregation_data
-- Účel: Rolling baseline statistiky
-- ============================================================================
CREATE TABLE IF NOT EXISTS ailog_peak.aggregation_data (
    id SERIAL PRIMARY KEY,
    day_of_week INTEGER NOT NULL,
    hour_of_day INTEGER NOT NULL,
    quarter_hour INTEGER NOT NULL,
    namespace VARCHAR(100) NOT NULL,
    mean NUMERIC(12,2),
    stddev NUMERIC(12,2),
    samples INTEGER,
    last_updated TIMESTAMP WITH TIME ZONE,
    
    UNIQUE (day_of_week, hour_of_day, quarter_hour, namespace)
);

CREATE INDEX IF NOT EXISTS idx_ad_namespace ON ailog_peak.aggregation_data(namespace);

-- ============================================================================
-- TABLE: peak_investigation
-- Účel: Detekované peaks/incidents
-- ============================================================================
CREATE TABLE IF NOT EXISTS ailog_peak.peak_investigation (
    id SERIAL PRIMARY KEY,
    
    -- Time
    timestamp TIMESTAMP WITH TIME ZONE,
    day_of_week INTEGER NOT NULL,
    hour_of_day INTEGER NOT NULL,
    quarter_hour INTEGER NOT NULL,
    
    -- Location
    namespace VARCHAR(255) NOT NULL,
    
    -- Values
    original_value NUMERIC(12,2) NOT NULL,
    reference_value NUMERIC(12,2),
    baseline_mean NUMERIC(12,2),
    ratio NUMERIC(8,2),
    threshold_used NUMERIC(12,2),
    detection_method VARCHAR(50),
    
    -- Severity & Score
    severity VARCHAR(20),
    score NUMERIC(5,2),
    
    -- Enrichment
    trace_id VARCHAR(100),
    app_name VARCHAR(200),
    app_version VARCHAR(50),
    error_type VARCHAR(100),
    error_message TEXT,
    affected_services TEXT[],
    
    -- V4 Flags
    is_new BOOLEAN DEFAULT FALSE,
    is_spike BOOLEAN DEFAULT FALSE,
    is_burst BOOLEAN DEFAULT FALSE,
    is_cross_namespace BOOLEAN DEFAULT FALSE,
    is_regression BOOLEAN DEFAULT FALSE,
    is_cascade BOOLEAN DEFAULT FALSE,
    
    -- Status
    status VARCHAR(50) DEFAULT 'open',
    resolution TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    assigned_to VARCHAR(100),
    
    -- Known issue
    known_issue_id INTEGER,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE (timestamp, namespace)
);

CREATE INDEX IF NOT EXISTS idx_pi_timestamp ON ailog_peak.peak_investigation(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_pi_namespace ON ailog_peak.peak_investigation(namespace);
CREATE INDEX IF NOT EXISTS idx_pi_status ON ailog_peak.peak_investigation(status);
CREATE INDEX IF NOT EXISTS idx_pi_severity ON ailog_peak.peak_investigation(severity);
CREATE INDEX IF NOT EXISTS idx_pi_created ON ailog_peak.peak_investigation(created_at DESC);

-- ============================================================================
-- TABLE: error_patterns
-- Účel: Hash-based error patterns
-- ============================================================================
CREATE TABLE IF NOT EXISTS ailog_peak.error_patterns (
    id SERIAL PRIMARY KEY,
    namespace VARCHAR(100),
    error_type VARCHAR(100),
    error_message TEXT,
    pattern_hash VARCHAR(64) UNIQUE,
    first_seen TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE,
    occurrence_count INTEGER DEFAULT 1,
    avg_errors_per_15min NUMERIC(10,2),
    severity VARCHAR(20),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ep_hash ON ailog_peak.error_patterns(pattern_hash);
CREATE INDEX IF NOT EXISTS idx_ep_namespace ON ailog_peak.error_patterns(namespace);
CREATE INDEX IF NOT EXISTS idx_ep_last_seen ON ailog_peak.error_patterns(last_seen DESC);

-- ============================================================================
-- GRANTS (adjust for your users)
-- ============================================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1;

-- ============================================================================
-- VERIFICATION
-- ============================================================================
DO $$
BEGIN
    RAISE NOTICE '✅ Base tables created successfully';
    RAISE NOTICE '';
    RAISE NOTICE 'Tables in ailog_peak schema:';
END $$;

SELECT table_name, 
       (SELECT COUNT(*) FROM information_schema.columns c WHERE c.table_name = t.table_name) as columns
FROM information_schema.tables t
WHERE table_schema = 'ailog_peak'
ORDER BY table_name;
