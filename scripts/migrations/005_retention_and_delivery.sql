-- Daily rollups, retention audit, and notification delivery observability.

CREATE TABLE IF NOT EXISTS ailog_peak.daily_error_kind_rollups (
    rollup_date DATE NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    application VARCHAR(255) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    error_type VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100) NOT NULL,
    error_count BIGINT NOT NULL CHECK (error_count >= 0),
    complete_window_count INTEGER NOT NULL CHECK (complete_window_count >= 0),
    first_event_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_event_at TIMESTAMP WITH TIME ZONE NOT NULL,
    refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (
        rollup_date, namespace, application, fingerprint,
        error_type, category, subcategory
    ),
    CONSTRAINT ck_daily_error_kind_event_bounds CHECK (last_event_at >= first_event_at)
);

CREATE INDEX IF NOT EXISTS idx_daily_error_kind_namespace_date
ON ailog_peak.daily_error_kind_rollups (namespace, rollup_date DESC);

CREATE INDEX IF NOT EXISTS idx_daily_error_kind_fingerprint_date
ON ailog_peak.daily_error_kind_rollups (fingerprint, rollup_date DESC);

CREATE TABLE IF NOT EXISTS ailog_peak.daily_namespace_rollups (
    rollup_date DATE NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    error_count BIGINT NOT NULL CHECK (error_count >= 0),
    complete_window_count INTEGER NOT NULL CHECK (complete_window_count >= 0),
    source_kind VARCHAR(30) NOT NULL DEFAULT 'authoritative_facts',
    refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (rollup_date, namespace),
    CONSTRAINT ck_daily_namespace_source_kind CHECK (
        source_kind IN ('authoritative_facts', 'legacy_peak_raw_data', 'mixed')
    )
);

CREATE INDEX IF NOT EXISTS idx_daily_namespace_date
ON ailog_peak.daily_namespace_rollups (rollup_date DESC, namespace);

CREATE TABLE IF NOT EXISTS ailog_peak.maintenance_runs (
    maintenance_id UUID PRIMARY KEY,
    maintenance_type VARCHAR(50) NOT NULL,
    cutoff_at TIMESTAMP WITH TIME ZONE NOT NULL,
    status VARCHAR(20) NOT NULL,
    source_fact_rows BIGINT NOT NULL DEFAULT 0 CHECK (source_fact_rows >= 0),
    source_events BIGINT NOT NULL DEFAULT 0 CHECK (source_events >= 0),
    rolled_up_rows BIGINT NOT NULL DEFAULT 0 CHECK (rolled_up_rows >= 0),
    deleted_fact_rows BIGINT NOT NULL DEFAULT 0 CHECK (deleted_fact_rows >= 0),
    deleted_namespace_rows BIGINT NOT NULL DEFAULT 0 CHECK (deleted_namespace_rows >= 0),
    deleted_peak_raw_rows BIGINT NOT NULL DEFAULT 0 CHECK (deleted_peak_raw_rows >= 0),
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_maintenance_status CHECK (status IN ('running', 'complete', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_maintenance_runs_type_started
ON ailog_peak.maintenance_runs (maintenance_type, started_at DESC);

CREATE TABLE IF NOT EXISTS ailog_peak.notification_deliveries (
    delivery_id UUID PRIMARY KEY,
    run_id VARCHAR(160) REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE SET NULL,
    window_start TIMESTAMP WITH TIME ZONE,
    notification_type VARCHAR(100) NOT NULL,
    dedup_key VARCHAR(500) NOT NULL,
    destination VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    provider_message TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    attempted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_notification_delivery_status CHECK (
        status IN ('delivered', 'failed', 'suppressed', 'skipped')
    )
);

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_window
ON ailog_peak.notification_deliveries (window_start DESC, notification_type, status);

CREATE INDEX IF NOT EXISTS idx_notification_deliveries_dedup
ON ailog_peak.notification_deliveries (dedup_key, attempted_at DESC);

CREATE OR REPLACE VIEW ailog_peak.v_pipeline_health AS
SELECT
    run_id,
    run_type,
    window_start,
    window_end,
    status,
    expected_count,
    fetched_count,
    processed_count,
    persisted_event_count,
    fact_row_count,
    incident_count,
    query_hash,
    code_version,
    replay_of_run_id,
    superseded_by_run_id,
    started_at,
    completed_at,
    EXTRACT(EPOCH FROM (COALESCE(completed_at, NOW()) - started_at)) AS duration_seconds,
    CASE
        WHEN expected_count IS NULL THEN NULL
        ELSE expected_count - fetched_count
    END AS source_count_delta,
    fetched_count - persisted_event_count AS persistence_count_delta
FROM ailog_peak.analysis_runs;

CREATE OR REPLACE VIEW ailog_peak.v_notification_delivery_health AS
SELECT
    DATE_TRUNC('hour', attempted_at) AS hour_start,
    notification_type,
    destination,
    status,
    COUNT(*) AS delivery_count
FROM ailog_peak.notification_deliveries
GROUP BY DATE_TRUNC('hour', attempted_at), notification_type, destination, status;

CREATE OR REPLACE VIEW ailog_peak.v_metadata_quality_health AS
SELECT
    run_id,
    window_start,
    SUM(error_count)::BIGINT AS total_event_count,
    SUM(error_count) FILTER (WHERE metadata_quality = 'structured')::BIGINT
        AS structured_event_count,
    SUM(error_count) FILTER (WHERE metadata_quality = 'derived')::BIGINT
        AS derived_event_count,
    SUM(error_count) FILTER (WHERE metadata_quality = 'unknown')::BIGINT
        AS unknown_metadata_event_count,
    SUM(error_count) FILTER (WHERE application = 'unknown')::BIGINT
        AS unknown_application_event_count,
    SUM(error_count) FILTER (WHERE error_type = 'UnknownError')::BIGINT
        AS unknown_error_type_event_count,
    SUM(error_count) FILTER (WHERE subcategory = 'unclassified')::BIGINT
        AS unclassified_event_count,
    ROUND(
        100.0 * SUM(error_count) FILTER (WHERE metadata_quality = 'unknown')
        / NULLIF(SUM(error_count), 0),
        2
    ) AS unknown_metadata_pct
FROM ailog_peak.v_complete_error_kind_counts
GROUP BY run_id, window_start;