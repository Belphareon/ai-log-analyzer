-- ============================================================================
-- AI Log Analyzer - Enhanced Analysis Tables
-- Migration: 002_create_enhanced_analysis_tables.sql
-- Version: 5.0
-- Date: 2026-01-20
-- ============================================================================

-- ============================================================================
-- TABLE 1: known_issues (Známé problémy s verzováním)
-- ============================================================================
-- Účel: Evidence známých problémů pro filtrování nových errorů
-- Klíčové: obsahuje app_version pro tracking fix

CREATE TABLE IF NOT EXISTS ailog_peak.known_issues (
    id SERIAL PRIMARY KEY,
    
    -- Identifikace
    issue_id VARCHAR(32) NOT NULL UNIQUE,      -- MD5 hash pro deduplikaci
    issue_name VARCHAR(255) NOT NULL,          -- Lidsky čitelný název
    
    -- Pattern matching
    error_type_pattern VARCHAR(255),           -- Regex nebo substring pro error type
    message_pattern VARCHAR(500),              -- Regex nebo substring pro message
    affected_namespace VARCHAR(100),           -- NULL = všechny namespaces
    affected_app_name VARCHAR(200),            -- NULL = všechny apps
    
    -- Verzování (NOVÉ!)
    introduced_in_version VARCHAR(50),         -- Verze kde se problém objevil
    fixed_in_version VARCHAR(50),              -- Verze kde byl opraven (NULL = neopraveno)
    affected_versions VARCHAR(255)[],          -- Seznam postižených verzí
    
    -- Severity & Impact
    severity VARCHAR(20) DEFAULT 'medium',     -- critical, high, medium, low
    impact_description TEXT,                   -- Popis dopadu na business
    
    -- Root cause
    root_cause_description TEXT,               -- Co způsobuje problém
    root_cause_service VARCHAR(200),           -- Která služba je příčina
    is_external_dependency BOOLEAN DEFAULT FALSE, -- Externí závislost (DB, API, ...)
    
    -- Resolution
    status VARCHAR(50) DEFAULT 'open',         -- open, investigating, resolved, wontfix, duplicate
    resolution_description TEXT,               -- Jak byl problém vyřešen
    workaround TEXT,                           -- Dočasné řešení
    jira_ticket VARCHAR(50),                   -- JIRA-123
    
    -- Statistics
    first_seen_at TIMESTAMP WITH TIME ZONE,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    occurrence_count INTEGER DEFAULT 0,
    total_errors_caused INTEGER DEFAULT 0,
    
    -- Metadata
    created_by VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    resolved_at TIMESTAMP WITH TIME ZONE
);

-- Indexy pro known_issues
CREATE INDEX IF NOT EXISTS idx_ki_status ON ailog_peak.known_issues(status);
CREATE INDEX IF NOT EXISTS idx_ki_namespace ON ailog_peak.known_issues(affected_namespace);
CREATE INDEX IF NOT EXISTS idx_ki_app ON ailog_peak.known_issues(affected_app_name);
CREATE INDEX IF NOT EXISTS idx_ki_severity ON ailog_peak.known_issues(severity);
CREATE INDEX IF NOT EXISTS idx_ki_last_seen ON ailog_peak.known_issues(last_seen_at DESC);

-- ============================================================================
-- TABLE 2: error_signatures (Smart Error Grouping)
-- ============================================================================
-- Účel: Seskupování podobných errorů pomocí signature hash
-- Klíčové: normalizovaná message pro fuzzy matching

CREATE TABLE IF NOT EXISTS ailog_peak.error_signatures (
    id SERIAL PRIMARY KEY,
    
    -- Identifikace
    signature_hash VARCHAR(64) NOT NULL UNIQUE,  -- Hash normalizované message
    
    -- Normalizované hodnoty
    normalized_message TEXT NOT NULL,            -- Message bez UUIDs, IDs, timestamps
    error_type VARCHAR(100),                     -- Exception type
    
    -- Representative sample
    sample_raw_message TEXT,                     -- Původní message (příklad)
    sample_namespace VARCHAR(100),
    sample_app_name VARCHAR(200),
    sample_trace_id VARCHAR(100),
    
    -- Grouping stats
    occurrence_count INTEGER DEFAULT 1,
    affected_namespaces VARCHAR(100)[] DEFAULT '{}',
    affected_apps VARCHAR(200)[] DEFAULT '{}',
    
    -- Time tracking
    first_seen_at TIMESTAMP WITH TIME ZONE,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    
    -- Linkage to known_issues
    known_issue_id INTEGER REFERENCES ailog_peak.known_issues(id),
    is_known_issue BOOLEAN DEFAULT FALSE,
    
    -- Analysis
    is_new BOOLEAN DEFAULT TRUE,                 -- Nikdy předtím neviděno
    needs_investigation BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_es_hash ON ailog_peak.error_signatures(signature_hash);
CREATE INDEX IF NOT EXISTS idx_es_is_new ON ailog_peak.error_signatures(is_new);
CREATE INDEX IF NOT EXISTS idx_es_known_issue ON ailog_peak.error_signatures(known_issue_id);
CREATE INDEX IF NOT EXISTS idx_es_last_seen ON ailog_peak.error_signatures(last_seen_at DESC);

-- ============================================================================
-- TABLE 3: service_health (Health Score per Service)
-- ============================================================================
-- Účel: Agregovaný health score pro každou službu

CREATE TABLE IF NOT EXISTS ailog_peak.service_health (
    id SERIAL PRIMARY KEY,
    
    -- Identifikace
    app_name VARCHAR(200) NOT NULL,
    namespace VARCHAR(100) NOT NULL,
    
    -- Time window
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
    window_duration_minutes INTEGER DEFAULT 15,
    
    -- Error metrics
    total_requests INTEGER DEFAULT 0,            -- Celkový počet requestů (pokud známo)
    total_errors INTEGER DEFAULT 0,              -- Počet errorů
    error_rate NUMERIC(5,2) DEFAULT 0,           -- Error rate (%)
    
    -- Health score (0-100)
    health_score NUMERIC(5,2) DEFAULT 100,       -- 100 = healthy, 0 = dead
    
    -- Breakdown
    errors_by_type JSONB DEFAULT '{}',           -- {"timeout": 10, "connection": 5, ...}
    errors_by_severity JSONB DEFAULT '{}',       -- {"critical": 2, "high": 10, ...}
    
    -- Trend
    trend VARCHAR(20) DEFAULT 'stable',          -- improving, stable, degrading
    health_score_1h_ago NUMERIC(5,2),
    health_score_24h_ago NUMERIC(5,2),
    
    -- Dependencies health
    downstream_services JSONB DEFAULT '[]',      -- [{"name": "db", "health": 95}, ...]
    upstream_services JSONB DEFAULT '[]',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE (app_name, namespace, window_start)
);

CREATE INDEX IF NOT EXISTS idx_sh_app ON ailog_peak.service_health(app_name);
CREATE INDEX IF NOT EXISTS idx_sh_namespace ON ailog_peak.service_health(namespace);
CREATE INDEX IF NOT EXISTS idx_sh_window ON ailog_peak.service_health(window_start DESC);
CREATE INDEX IF NOT EXISTS idx_sh_health ON ailog_peak.service_health(health_score);

-- ============================================================================
-- TABLE 4: cascade_failures (Cascade Failure Detection)
-- ============================================================================
-- Účel: Detekce kaskádových selhání napříč službami

CREATE TABLE IF NOT EXISTS ailog_peak.cascade_failures (
    id SERIAL PRIMARY KEY,
    
    -- Identifikace
    cascade_id VARCHAR(64) NOT NULL UNIQUE,     -- Hash pro deduplikaci
    
    -- Time window
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    window_start TIMESTAMP WITH TIME ZONE,
    window_end TIMESTAMP WITH TIME ZONE,
    
    -- Root cause (deepest failure)
    root_cause_app VARCHAR(200),
    root_cause_namespace VARCHAR(100),
    root_cause_error_type VARCHAR(100),
    root_cause_message TEXT,
    root_cause_trace_id VARCHAR(100),
    
    -- Affected services (cascade chain)
    affected_services JSONB NOT NULL DEFAULT '[]',
    -- Format: [
    --   {"app": "service-a", "namespace": "dev", "error_count": 100, "depth": 1},
    --   {"app": "service-b", "namespace": "dev", "error_count": 50, "depth": 2},
    -- ]
    
    -- Impact
    total_affected_services INTEGER DEFAULT 0,
    total_errors_in_cascade INTEGER DEFAULT 0,
    cascade_depth INTEGER DEFAULT 1,             -- Jak hluboko kaskáda sahá
    
    -- Classification
    cascade_type VARCHAR(50),                    -- database, network, external_api, internal
    severity VARCHAR(20) DEFAULT 'high',
    
    -- Resolution
    status VARCHAR(50) DEFAULT 'active',         -- active, resolved, investigating
    resolution_notes TEXT,
    resolved_at TIMESTAMP WITH TIME ZONE,
    
    -- Link to known_issue
    known_issue_id INTEGER REFERENCES ailog_peak.known_issues(id),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cf_detected ON ailog_peak.cascade_failures(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_cf_root_app ON ailog_peak.cascade_failures(root_cause_app);
CREATE INDEX IF NOT EXISTS idx_cf_status ON ailog_peak.cascade_failures(status);
CREATE INDEX IF NOT EXISTS idx_cf_severity ON ailog_peak.cascade_failures(severity);

-- ============================================================================
-- TABLE 5: service_dependencies (Service Dependency Map)
-- ============================================================================
-- Účel: Automaticky buildovaná mapa závislostí z error messages

CREATE TABLE IF NOT EXISTS ailog_peak.service_dependencies (
    id SERIAL PRIMARY KEY,
    
    -- Source → Target
    source_app VARCHAR(200) NOT NULL,
    source_namespace VARCHAR(100),
    target_app VARCHAR(200) NOT NULL,           -- Může být i externí URL
    target_namespace VARCHAR(100),
    
    -- Type
    dependency_type VARCHAR(50) DEFAULT 'internal',  -- internal, external_api, database, queue
    
    -- Statistics (rolling 7 days)
    total_calls INTEGER DEFAULT 0,
    failed_calls INTEGER DEFAULT 0,
    failure_rate NUMERIC(5,2) DEFAULT 0,
    
    -- Error breakdown
    errors_by_code JSONB DEFAULT '{}',          -- {"500": 10, "503": 5, "timeout": 3}
    
    -- Time tracking
    first_seen_at TIMESTAMP WITH TIME ZONE,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    last_failure_at TIMESTAMP WITH TIME ZONE,
    
    -- Health
    is_healthy BOOLEAN DEFAULT TRUE,
    health_score NUMERIC(5,2) DEFAULT 100,
    
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE (source_app, target_app, COALESCE(source_namespace, ''), COALESCE(target_namespace, ''))
);

CREATE INDEX IF NOT EXISTS idx_sd_source ON ailog_peak.service_dependencies(source_app);
CREATE INDEX IF NOT EXISTS idx_sd_target ON ailog_peak.service_dependencies(target_app);
CREATE INDEX IF NOT EXISTS idx_sd_health ON ailog_peak.service_dependencies(is_healthy);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- View: Aktuální health všech služeb
CREATE OR REPLACE VIEW ailog_peak.v_current_service_health AS
SELECT DISTINCT ON (app_name, namespace)
    app_name,
    namespace,
    health_score,
    total_errors,
    error_rate,
    trend,
    window_start as measured_at
FROM ailog_peak.service_health
ORDER BY app_name, namespace, window_start DESC;

-- View: Aktivní kaskádová selhání
CREATE OR REPLACE VIEW ailog_peak.v_active_cascades AS
SELECT 
    c.*,
    ki.issue_name as known_issue_name,
    ki.jira_ticket
FROM ailog_peak.cascade_failures c
LEFT JOIN ailog_peak.known_issues ki ON c.known_issue_id = ki.id
WHERE c.status = 'active'
ORDER BY c.detected_at DESC;

-- View: Nové error typy (nikdy neviděné)
CREATE OR REPLACE VIEW ailog_peak.v_new_errors AS
SELECT 
    es.*,
    CASE 
        WHEN es.occurrence_count > 100 THEN 'critical'
        WHEN es.occurrence_count > 50 THEN 'high'
        WHEN es.occurrence_count > 10 THEN 'medium'
        ELSE 'low'
    END as suggested_severity
FROM ailog_peak.error_signatures es
WHERE es.is_new = TRUE
  AND es.is_known_issue = FALSE
ORDER BY es.occurrence_count DESC;

-- View: Service dependency health
CREATE OR REPLACE VIEW ailog_peak.v_unhealthy_dependencies AS
SELECT 
    source_app,
    source_namespace,
    target_app,
    target_namespace,
    dependency_type,
    failure_rate,
    total_calls,
    failed_calls,
    last_failure_at
FROM ailog_peak.service_dependencies
WHERE is_healthy = FALSE
   OR failure_rate > 5.0
ORDER BY failure_rate DESC;

-- ============================================================================
-- FUNCTIONS
-- ============================================================================

-- Funkce pro normalizaci error message (pro signature hash)
CREATE OR REPLACE FUNCTION ailog_peak.normalize_error_message(msg TEXT)
RETURNS TEXT AS $$
BEGIN
    -- Remove UUIDs
    msg := regexp_replace(msg, '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '<UUID>', 'gi');
    -- Remove long numbers (IDs)
    msg := regexp_replace(msg, '\b\d{10,}\b', '<ID>', 'g');
    -- Remove IP addresses
    msg := regexp_replace(msg, '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', '<IP>', 'g');
    -- Remove timestamps
    msg := regexp_replace(msg, '\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', '<TS>', 'g');
    -- Remove hex strings
    msg := regexp_replace(msg, '0x[0-9a-fA-F]+', '<HEX>', 'g');
    -- Limit length
    RETURN left(msg, 500);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Funkce pro výpočet health score
CREATE OR REPLACE FUNCTION ailog_peak.calculate_health_score(
    error_count INTEGER,
    baseline_errors NUMERIC,
    critical_errors INTEGER DEFAULT 0,
    high_errors INTEGER DEFAULT 0
)
RETURNS NUMERIC AS $$
DECLARE
    score NUMERIC := 100;
    error_penalty NUMERIC;
    severity_penalty NUMERIC;
BEGIN
    -- Penalty za errory nad baseline
    IF baseline_errors > 0 THEN
        error_penalty := LEAST(50, (error_count - baseline_errors) / baseline_errors * 30);
    ELSE
        error_penalty := LEAST(50, error_count * 0.5);
    END IF;
    
    -- Penalty za severity
    severity_penalty := (critical_errors * 10) + (high_errors * 5);
    
    score := GREATEST(0, 100 - error_penalty - severity_penalty);
    
    RETURN ROUND(score, 2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- ============================================================================
-- GRANTS
-- ============================================================================

GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.known_issues TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.error_signatures TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.service_health TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.cascade_failures TO ailog_analyzer_user_d1;
GRANT SELECT, INSERT, UPDATE, DELETE ON ailog_peak.service_dependencies TO ailog_analyzer_user_d1;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ailog_peak TO ailog_analyzer_user_d1;

GRANT SELECT ON ailog_peak.v_current_service_health TO ailog_analyzer_user_d1;
GRANT SELECT ON ailog_peak.v_active_cascades TO ailog_analyzer_user_d1;
GRANT SELECT ON ailog_peak.v_new_errors TO ailog_analyzer_user_d1;
GRANT SELECT ON ailog_peak.v_unhealthy_dependencies TO ailog_analyzer_user_d1;

-- ============================================================================
-- DONE
-- ============================================================================
-- Run: psql -f 002_create_enhanced_analysis_tables.sql
