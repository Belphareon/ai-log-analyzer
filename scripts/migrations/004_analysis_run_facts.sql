-- Transactional run ledger and analytics fact model.

CREATE TABLE IF NOT EXISTS ailog_peak.schema_migrations (
    migration_name TEXT PRIMARY KEY,
    checksum CHAR(64) NOT NULL,
    applied_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    execution_ms INTEGER NOT NULL CHECK (execution_ms >= 0)
);

CREATE TABLE IF NOT EXISTS ailog_peak.analysis_runs (
    run_id VARCHAR(160) PRIMARY KEY,
    run_type VARCHAR(20) NOT NULL,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
    query_hash CHAR(64) NOT NULL,
    source_index TEXT NOT NULL,
    code_version VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    expected_count BIGINT,
    fetched_count BIGINT NOT NULL DEFAULT 0,
    processed_count BIGINT NOT NULL DEFAULT 0,
    persisted_event_count BIGINT NOT NULL DEFAULT 0,
    fact_row_count BIGINT NOT NULL DEFAULT 0,
    incident_count INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(100),
    error_message TEXT,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    replay_of_run_id VARCHAR(160) REFERENCES ailog_peak.analysis_runs(run_id),
    superseded_by_run_id VARCHAR(160) REFERENCES ailog_peak.analysis_runs(run_id),
    CONSTRAINT ck_analysis_runs_window CHECK (window_end > window_start),
    CONSTRAINT ck_analysis_runs_status CHECK (
        status IN ('running', 'complete', 'failed', 'partial', 'superseded')
    ),
    CONSTRAINT ck_analysis_runs_counts CHECK (
        fetched_count >= 0 AND processed_count >= 0
        AND persisted_event_count >= 0 AND fact_row_count >= 0
        AND incident_count >= 0
        AND (expected_count IS NULL OR expected_count >= 0)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_runs_identity
ON ailog_peak.analysis_runs (run_type, window_start, window_end, query_hash)
WHERE status = 'running';

CREATE INDEX IF NOT EXISTS idx_analysis_runs_status_window
ON ailog_peak.analysis_runs (status, window_start DESC);

CREATE TABLE IF NOT EXISTS ailog_peak.error_kind_counts (
    run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE CASCADE,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    application VARCHAR(255) NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    error_type VARCHAR(255) NOT NULL,
    category VARCHAR(100) NOT NULL,
    subcategory VARCHAR(100) NOT NULL,
    error_count BIGINT NOT NULL CHECK (error_count > 0),
    first_event_at TIMESTAMP WITH TIME ZONE NOT NULL,
    last_event_at TIMESTAMP WITH TIME ZONE NOT NULL,
    sample_message TEXT,
    metadata_quality VARCHAR(20) NOT NULL DEFAULT 'unknown',
    PRIMARY KEY (run_id, window_start, namespace, application, fingerprint),
    CONSTRAINT ck_error_kind_event_bounds CHECK (last_event_at >= first_event_at),
    CONSTRAINT ck_error_kind_metadata_quality CHECK (
        metadata_quality IN ('structured', 'derived', 'unknown')
    )
);

CREATE INDEX IF NOT EXISTS idx_error_kind_counts_window_namespace
ON ailog_peak.error_kind_counts (window_start DESC, namespace);

CREATE INDEX IF NOT EXISTS idx_error_kind_counts_fingerprint_window
ON ailog_peak.error_kind_counts (fingerprint, window_start DESC);

CREATE TABLE IF NOT EXISTS ailog_peak.namespace_error_counts (
    run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE CASCADE,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    error_count BIGINT NOT NULL CHECK (error_count >= 0),
    PRIMARY KEY (run_id, window_start, namespace)
);

CREATE INDEX IF NOT EXISTS idx_namespace_error_counts_window
ON ailog_peak.namespace_error_counts (window_start DESC, namespace);

CREATE TABLE IF NOT EXISTS ailog_peak.threshold_snapshot_runs (
        snapshot_id UUID PRIMARY KEY,
        percentile_level NUMERIC(5,4) NOT NULL,
        population_grain VARCHAR(50) NOT NULL,
        training_start TIMESTAMP WITH TIME ZONE NOT NULL,
        training_end TIMESTAMP WITH TIME ZONE NOT NULL,
        sample_count BIGINT NOT NULL CHECK (sample_count >= 0),
        percentile_method VARCHAR(100) NOT NULL,
        calculation_version VARCHAR(100) NOT NULL,
        status VARCHAR(20) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        completed_at TIMESTAMP WITH TIME ZONE,
        CONSTRAINT ck_threshold_snapshot_window CHECK (training_end > training_start),
        CONSTRAINT ck_threshold_snapshot_status CHECK (status IN ('running', 'complete', 'failed'))
);

CREATE TABLE IF NOT EXISTS ailog_peak.threshold_snapshot_values (
        snapshot_id UUID NOT NULL REFERENCES ailog_peak.threshold_snapshot_runs(snapshot_id) ON DELETE CASCADE,
        namespace VARCHAR(255) NOT NULL,
        day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
        percentile_value NUMERIC(12,2) NOT NULL,
        cap_value NUMERIC(12,2) NOT NULL,
        sample_count INTEGER NOT NULL CHECK (sample_count >= 0),
        median_value NUMERIC(12,2),
        mean_value NUMERIC(12,2),
        max_value NUMERIC(12,2),
        PRIMARY KEY (snapshot_id, namespace, day_of_week)
);

CREATE OR REPLACE VIEW ailog_peak.v_latest_threshold_snapshot AS
SELECT snapshot.*
FROM ailog_peak.threshold_snapshot_runs snapshot
WHERE snapshot.status = 'complete'
ORDER BY snapshot.completed_at DESC, snapshot.created_at DESC
LIMIT 1;

CREATE OR REPLACE VIEW ailog_peak.v_latest_threshold_values AS
SELECT value_row.*, snapshot.percentile_level, snapshot.training_start,
             snapshot.training_end, snapshot.percentile_method,
             snapshot.calculation_version
FROM ailog_peak.threshold_snapshot_values value_row
JOIN ailog_peak.v_latest_threshold_snapshot snapshot
    ON snapshot.snapshot_id = value_row.snapshot_id;

CREATE TABLE IF NOT EXISTS ailog_peak.detection_events (
        run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE CASCADE,
        window_start TIMESTAMP WITH TIME ZONE NOT NULL,
        namespace VARCHAR(255) NOT NULL,
        fingerprint VARCHAR(64) NOT NULL,
        detector_type VARCHAR(100) NOT NULL,
        detector_version VARCHAR(100) NOT NULL,
        evaluated_value NUMERIC,
        threshold_value NUMERIC,
        threshold_snapshot_id UUID REFERENCES ailog_peak.threshold_snapshot_runs(snapshot_id),
        flags JSONB NOT NULL,
        explanation TEXT NOT NULL,
        evidence JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
        PRIMARY KEY (run_id, window_start, namespace, fingerprint, detector_type)
);

CREATE INDEX IF NOT EXISTS idx_detection_events_window
ON ailog_peak.detection_events (window_start DESC, detector_type);

ALTER TABLE ailog_peak.peak_investigation
    ADD COLUMN IF NOT EXISTS run_id VARCHAR(160),
    ADD COLUMN IF NOT EXISTS window_start TIMESTAMP WITH TIME ZONE,
    ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64);

DO $$
DECLARE
    legacy_constraint RECORD;
BEGIN
    FOR legacy_constraint IN
        SELECT constraint_row.conname
        FROM pg_constraint constraint_row
        WHERE constraint_row.conrelid = 'ailog_peak.peak_investigation'::regclass
          AND constraint_row.contype = 'u'
          AND ARRAY(
              SELECT attribute_row.attname::TEXT
              FROM unnest(constraint_row.conkey) AS key_row(attnum)
              JOIN pg_attribute attribute_row
                ON attribute_row.attrelid = constraint_row.conrelid
               AND attribute_row.attnum = key_row.attnum
              ORDER BY attribute_row.attname
          ) = ARRAY['namespace', 'timestamp']::TEXT[]
    LOOP
        EXECUTE format(
            'ALTER TABLE ailog_peak.peak_investigation DROP CONSTRAINT %I',
            legacy_constraint.conname
        );
    END LOOP;
END $$;

DO $$
DECLARE
    legacy_index RECORD;
BEGIN
    FOR legacy_index IN
        SELECT index_namespace.nspname AS schema_name, index_class.relname AS index_name
        FROM pg_index index_row
        JOIN pg_class table_class ON table_class.oid = index_row.indrelid
        JOIN pg_namespace table_namespace ON table_namespace.oid = table_class.relnamespace
        JOIN pg_class index_class ON index_class.oid = index_row.indexrelid
        JOIN pg_namespace index_namespace ON index_namespace.oid = index_class.relnamespace
        WHERE table_namespace.nspname = 'ailog_peak'
          AND table_class.relname = 'peak_investigation'
          AND index_row.indisunique
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint constraint_row
              WHERE constraint_row.conindid = index_row.indexrelid
          )
          AND ARRAY(
              SELECT attribute_row.attname::TEXT
              FROM unnest(index_row.indkey) AS key_row(attnum)
              JOIN pg_attribute attribute_row
                ON attribute_row.attrelid = index_row.indrelid
               AND attribute_row.attnum = key_row.attnum
              WHERE key_row.attnum > 0
              ORDER BY attribute_row.attname
          ) = ARRAY['namespace', 'timestamp']::TEXT[]
    LOOP
        EXECUTE format(
            'DROP INDEX %I.%I', legacy_index.schema_name, legacy_index.index_name
        );
    END LOOP;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'ailog_peak.peak_investigation'::regclass
          AND conname = 'fk_peak_investigation_run'
    ) THEN
        ALTER TABLE ailog_peak.peak_investigation
            ADD CONSTRAINT fk_peak_investigation_run
            FOREIGN KEY (run_id) REFERENCES ailog_peak.analysis_runs(run_id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_peak_investigation_run_fingerprint
ON ailog_peak.peak_investigation (run_id, window_start, namespace, fingerprint);

CREATE OR REPLACE VIEW ailog_peak.v_authoritative_run_windows AS
SELECT ranked.run_id, ranked.window_start
FROM (
        SELECT
                namespace_window.run_id,
                namespace_window.window_start,
                ROW_NUMBER() OVER (
                        PARTITION BY namespace_window.window_start
                        ORDER BY run_row.completed_at DESC NULLS LAST,
                                         run_row.started_at DESC,
                                         run_row.run_id DESC
                ) AS authority_rank
        FROM (
                SELECT DISTINCT run_id, window_start
                FROM ailog_peak.namespace_error_counts
        ) namespace_window
        JOIN ailog_peak.analysis_runs run_row ON run_row.run_id = namespace_window.run_id
        WHERE run_row.status = 'complete'
            AND run_row.superseded_by_run_id IS NULL
) ranked
WHERE ranked.authority_rank = 1;

CREATE OR REPLACE VIEW ailog_peak.v_complete_error_kind_counts AS
SELECT fact_row.*
FROM ailog_peak.error_kind_counts fact_row
JOIN ailog_peak.v_authoritative_run_windows authority
    ON authority.run_id = fact_row.run_id
 AND authority.window_start = fact_row.window_start;

CREATE OR REPLACE VIEW ailog_peak.v_complete_namespace_error_counts AS
SELECT fact_row.*
FROM ailog_peak.namespace_error_counts fact_row
JOIN ailog_peak.v_authoritative_run_windows authority
    ON authority.run_id = fact_row.run_id
 AND authority.window_start = fact_row.window_start;