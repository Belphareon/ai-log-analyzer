-- Migration: Create peak_thresholds tables
-- Date: 2026-01-20
-- Purpose: Store dynamically calculated P93 and CAP thresholds per namespace per day_of_week
-- 
-- USAGE:
-- 1. Run this SQL to create tables
-- 2. Run calculate_peak_thresholds.py to populate from peak_raw_data
-- 3. peak_detection.py reads thresholds from these tables

-- ============================================================================
-- TABLE: peak_thresholds
-- Stores P93 (or other percentile) threshold for each (namespace, day_of_week)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ailog_peak.peak_thresholds (
    id SERIAL PRIMARY KEY,
    namespace VARCHAR(100) NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    
    -- Percentile threshold for this (namespace, dow)
    percentile_value NUMERIC(12, 2) NOT NULL DEFAULT 100,
    percentile_level NUMERIC(4, 2) NOT NULL DEFAULT 0.93,  -- Which percentile (e.g., 0.93 = P93)
    
    -- Statistics used for calculation
    sample_count INTEGER NOT NULL DEFAULT 0,
    median_value NUMERIC(12, 2),
    mean_value NUMERIC(12, 2),
    max_value NUMERIC(12, 2),
    
    -- Metadata
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    data_start_date DATE,
    data_end_date DATE,
    
    -- Unique constraint
    CONSTRAINT uq_peak_thresholds_ns_dow UNIQUE (namespace, day_of_week)
);

-- ============================================================================
-- TABLE: peak_threshold_caps
-- Stores CAP value per namespace (smoothed fallback)
-- CAP = (median_percentile + avg_percentile) / 2 across all DOWs
-- ============================================================================
CREATE TABLE IF NOT EXISTS ailog_peak.peak_threshold_caps (
    id SERIAL PRIMARY KEY,
    namespace VARCHAR(100) NOT NULL UNIQUE,
    
    -- CAP = (median_percentile + avg_percentile) / 2 across all DOWs
    cap_value NUMERIC(12, 2) NOT NULL DEFAULT 100,
    
    -- Percentile statistics across all DOWs for this namespace
    median_percentile NUMERIC(12, 2),
    avg_percentile NUMERIC(12, 2),
    min_percentile NUMERIC(12, 2),
    max_percentile NUMERIC(12, 2),
    
    -- Which percentile level was used
    percentile_level NUMERIC(4, 2) NOT NULL DEFAULT 0.93,
    
    -- Total samples across all DOWs
    total_samples INTEGER NOT NULL DEFAULT 0,
    
    -- Metadata
    calculated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_peak_thresholds_ns_dow 
ON ailog_peak.peak_thresholds (namespace, day_of_week);

CREATE INDEX IF NOT EXISTS idx_peak_thresholds_ns 
ON ailog_peak.peak_thresholds (namespace);

CREATE INDEX IF NOT EXISTS idx_peak_threshold_caps_ns 
ON ailog_peak.peak_threshold_caps (namespace);

-- ============================================================================
-- VIEW: v_peak_thresholds
-- Combined view for easy threshold lookup with effective threshold
-- ============================================================================
CREATE OR REPLACE VIEW ailog_peak.v_peak_thresholds AS
SELECT 
    t.namespace,
    t.day_of_week,
    t.percentile_value,
    t.percentile_level,
    c.cap_value,
    t.sample_count,
    t.calculated_at
FROM ailog_peak.peak_thresholds t
LEFT JOIN ailog_peak.peak_threshold_caps c ON t.namespace = c.namespace;

-- ============================================================================
-- VIEW: v_all_thresholds_matrix
-- Full matrix view for reporting (all namespaces x all DOWs)
-- ============================================================================
CREATE OR REPLACE VIEW ailog_peak.v_all_thresholds_matrix AS
WITH ns_list AS (
    SELECT DISTINCT namespace FROM ailog_peak.peak_thresholds
),
dow_list AS (
    SELECT generate_series(0, 6) AS day_of_week
),
full_grid AS (
    SELECT ns.namespace, d.day_of_week
    FROM ns_list ns
    CROSS JOIN dow_list d
)
SELECT 
    g.namespace,
    g.day_of_week,
    COALESCE(t.percentile_value, c.cap_value, 100) as threshold,
    t.percentile_value as p93_value,
    c.cap_value,
    COALESCE(t.sample_count, 0) as sample_count
FROM full_grid g
LEFT JOIN ailog_peak.peak_thresholds t 
    ON g.namespace = t.namespace AND g.day_of_week = t.day_of_week
LEFT JOIN ailog_peak.peak_threshold_caps c 
    ON g.namespace = c.namespace
ORDER BY g.namespace, g.day_of_week;

-- ============================================================================
-- PERMISSIONS
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_thresholds TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.peak_threshold_caps TO ailog_analyzer_user_d1;
GRANT SELECT ON ailog_peak.v_peak_thresholds TO ailog_analyzer_user_d1;
GRANT SELECT ON ailog_peak.v_all_thresholds_matrix TO ailog_analyzer_user_d1;
GRANT USAGE, SELECT ON SEQUENCE ailog_peak.peak_thresholds_id_seq TO ailog_analyzer_user_d1;
GRANT USAGE, SELECT ON SEQUENCE ailog_peak.peak_threshold_caps_id_seq TO ailog_analyzer_user_d1;

-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE ailog_peak.peak_thresholds IS 'Percentile thresholds per (namespace, day_of_week) - calculated from peak_raw_data by calculate_peak_thresholds.py';
COMMENT ON TABLE ailog_peak.peak_threshold_caps IS 'CAP values per namespace (smoothed fallback) - calculated from percentile values across all DOWs';
COMMENT ON VIEW ailog_peak.v_peak_thresholds IS 'Combined view of percentile and CAP thresholds';
COMMENT ON VIEW ailog_peak.v_all_thresholds_matrix IS 'Full matrix of all thresholds for reporting';

-- ============================================================================
-- HELPER FUNCTION: get_peak_threshold
-- Returns effective threshold for given namespace and day_of_week
-- ============================================================================
CREATE OR REPLACE FUNCTION ailog_peak.get_peak_threshold(
    p_namespace VARCHAR(100),
    p_day_of_week INTEGER,
    p_default_threshold NUMERIC DEFAULT 100
)
RETURNS NUMERIC AS $$
DECLARE
    v_percentile_value NUMERIC;
    v_cap_value NUMERIC;
BEGIN
    -- Get percentile threshold for this (namespace, dow)
    SELECT percentile_value INTO v_percentile_value
    FROM ailog_peak.peak_thresholds
    WHERE namespace = p_namespace AND day_of_week = p_day_of_week;
    
    -- Get CAP value for this namespace
    SELECT cap_value INTO v_cap_value
    FROM ailog_peak.peak_threshold_caps
    WHERE namespace = p_namespace;
    
    -- Return: if both exist, use percentile; if only cap, use cap; otherwise default
    IF v_percentile_value IS NOT NULL THEN
        RETURN v_percentile_value;
    ELSIF v_cap_value IS NOT NULL THEN
        RETURN v_cap_value;
    ELSE
        RETURN p_default_threshold;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION ailog_peak.get_peak_threshold IS 'Returns effective threshold for given namespace and day_of_week';
