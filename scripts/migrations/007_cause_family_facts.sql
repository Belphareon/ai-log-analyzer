-- Immutable operator cause-family facts attached to a complete analysis run.

CREATE TABLE IF NOT EXISTS ailog_peak.cause_family_facts (
    run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE CASCADE,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    cause_signature VARCHAR(64) NOT NULL,
    signature_version VARCHAR(50) NOT NULL,
    canonical_cause TEXT NOT NULL,
    root_application VARCHAR(255) NOT NULL,
    operation VARCHAR(255) NOT NULL,
    outward_status INTEGER,
    assessment VARCHAR(50) NOT NULL,
    confidence VARCHAR(20) NOT NULL,
    raw_error_lines BIGINT NOT NULL CHECK (raw_error_lines > 0),
    traced_error_lines BIGINT NOT NULL CHECK (traced_error_lines >= 0),
    unsegmented_error_lines BIGINT NOT NULL CHECK (unsegmented_error_lines >= 0),
    unique_operations BIGINT CHECK (unique_operations >= 0),
    amplification NUMERIC(14, 3),
    app_counts JSONB NOT NULL DEFAULT '{}'::JSONB,
    namespace_counts JSONB NOT NULL DEFAULT '{}'::JSONB,
    representative_trace_id TEXT,
    trace_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    operation_count_method VARCHAR(30) NOT NULL,
    operation_count_confidence VARCHAR(20) NOT NULL,
    operation_count_reason TEXT NOT NULL DEFAULT '',
    next_action TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, cause_signature),
    CONSTRAINT ck_cause_family_status CHECK (
        outward_status IS NULL OR outward_status BETWEEN 100 AND 599
    ),
    CONSTRAINT ck_cause_family_assessment CHECK (
        assessment IN (
            'technical_failure',
            'business_rejection',
            'expected_outcome_logged_as_error',
            'unknown'
        )
    ),
    CONSTRAINT ck_cause_family_confidence CHECK (
        confidence IN ('low', 'medium', 'high')
    ),
    CONSTRAINT ck_cause_family_operation_count_method CHECK (
        operation_count_method IN ('root_span', 'trace_id', 'mixed', 'unavailable')
    ),
    CONSTRAINT ck_cause_family_operation_count_confidence CHECK (
        operation_count_confidence IN ('low', 'medium', 'high')
    ),
    CONSTRAINT ck_cause_family_operation_count_availability CHECK (
        (unique_operations IS NULL AND operation_count_method = 'unavailable')
        OR
        (unique_operations IS NOT NULL AND operation_count_method <> 'unavailable')
    ),
    CONSTRAINT ck_cause_family_operation_trace_count CHECK (
        unique_operations IS NULL
        OR unique_operations >= JSONB_ARRAY_LENGTH(trace_ids)
    ),
    CONSTRAINT ck_cause_family_coverage CHECK (
        traced_error_lines + unsegmented_error_lines = raw_error_lines
    )
);

CREATE INDEX IF NOT EXISTS idx_cause_family_facts_window_assessment
ON ailog_peak.cause_family_facts (window_start DESC, assessment);

CREATE INDEX IF NOT EXISTS idx_cause_family_facts_signature_window
ON ailog_peak.cause_family_facts (cause_signature, window_start DESC);

CREATE OR REPLACE VIEW ailog_peak.v_complete_cause_family_facts AS
SELECT
    fact_row.*,
    run_row.run_type,
    run_row.window_end,
    run_row.completed_at
FROM ailog_peak.cause_family_facts fact_row
JOIN ailog_peak.analysis_runs run_row ON run_row.run_id = fact_row.run_id
WHERE run_row.status = 'complete'
  AND run_row.superseded_by_run_id IS NULL;