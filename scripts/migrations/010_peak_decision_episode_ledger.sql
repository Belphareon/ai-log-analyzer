-- First-class namespace verdicts, cause allocations, episode continuity, and policy outcomes.

CREATE TABLE IF NOT EXISTS ailog_peak.namespace_peak_decisions (
    window_decision_id CHAR(64) PRIMARY KEY,
    run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE CASCADE,
    stream_key VARCHAR(160) NOT NULL,
    signal_namespace VARCHAR(255) NOT NULL,
    window_start_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    detector_version VARCHAR(100) NOT NULL,
    threshold_snapshot_id UUID REFERENCES ailog_peak.threshold_snapshot_runs(snapshot_id),
    namespace_raw_lines BIGINT NOT NULL CHECK (namespace_raw_lines >= 0),
    p93_threshold NUMERIC,
    cap_threshold NUMERIC,
    effective_threshold NUMERIC,
    triggered_by VARCHAR(30),
    is_peak BOOLEAN NOT NULL,
    verdict_reason VARCHAR(80) NOT NULL,
    diagnosis_status VARCHAR(30) NOT NULL,
    contract_hash CHAR(64) NOT NULL DEFAULT '',
    peak_identifier VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_namespace_peak_decision_window CHECK (
        window_end_utc = window_start_utc + INTERVAL '15 minutes'
    ),
    CONSTRAINT ck_namespace_peak_decision_reason CHECK (
        verdict_reason IN (
            'below_min_volume', 'below_threshold', 'peak_diagnosed', 'peak_undiagnosed'
        )
    ),
    CONSTRAINT ck_namespace_peak_decision_diagnosis CHECK (
        diagnosis_status IN ('diagnosed', 'undiagnosed')
    ),
    CONSTRAINT ck_namespace_peak_identifier CHECK (
        (is_peak AND peak_identifier IS NOT NULL) OR (NOT is_peak)
    ),
    UNIQUE (
        stream_key, window_start_utc, signal_namespace,
        detector_version, threshold_snapshot_id
    )
);

CREATE INDEX IF NOT EXISTS idx_namespace_peak_decisions_window
ON ailog_peak.namespace_peak_decisions (stream_key, window_start_utc DESC, signal_namespace);

CREATE TABLE IF NOT EXISTS ailog_peak.namespace_peak_contributors (
    window_decision_id CHAR(64) NOT NULL
        REFERENCES ailog_peak.namespace_peak_decisions(window_decision_id) ON DELETE CASCADE,
    run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.analysis_runs(run_id) ON DELETE CASCADE,
    fingerprint VARCHAR(64) NOT NULL,
    error_type VARCHAR(255) NOT NULL DEFAULT '',
    normalized_message TEXT NOT NULL DEFAULT '',
    contribution BIGINT NOT NULL CHECK (contribution >= 0),
    baseline NUMERIC,
    threshold NUMERIC,
    anomaly_score NUMERIC,
    method VARCHAR(100) NOT NULL,
    is_anomalous BOOLEAN NOT NULL,
    apps JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (window_decision_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS ailog_peak.peak_episodes (
    episode_id UUID PRIMARY KEY,
    stream_key VARCHAR(160) NOT NULL,
    cause_signature VARCHAR(64),
    signature_version VARCHAR(50) NOT NULL,
    state VARCHAR(30) NOT NULL,
    first_window_start_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    last_window_start_utc TIMESTAMP WITH TIME ZONE NOT NULL,
    resolved_at_utc TIMESTAMP WITH TIME ZONE,
    current_raw_error_lines BIGINT NOT NULL DEFAULT 0 CHECK (current_raw_error_lines >= 0),
    cumulative_raw_error_lines BIGINT NOT NULL DEFAULT 0 CHECK (cumulative_raw_error_lines >= 0),
    current_operation_occurrences BIGINT,
    cumulative_operation_occurrences BIGINT,
    diagnosis_confidence VARCHAR(20) NOT NULL DEFAULT 'low',
    active_namespaces JSONB NOT NULL DEFAULT '[]'::JSONB,
    material_change_reasons JSONB NOT NULL DEFAULT '[]'::JSONB,
    non_peak_windows INTEGER NOT NULL DEFAULT 0 CHECK (non_peak_windows >= 0),
    previous_episode_id UUID REFERENCES ailog_peak.peak_episodes(episode_id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_peak_episode_state CHECK (
        state IN ('START', 'CONTINUATION', 'EXPANSION', 'ESCALATION', 'RECOVERY', 'RESOLVED', 'RECURRENCE')
    ),
    CONSTRAINT ck_peak_episode_confidence CHECK (diagnosis_confidence IN ('low', 'medium', 'high'))
);

CREATE INDEX IF NOT EXISTS idx_peak_episodes_open
ON ailog_peak.peak_episodes (stream_key, state, last_window_start_utc DESC);

CREATE TABLE IF NOT EXISTS ailog_peak.peak_episode_windows (
    episode_id UUID NOT NULL REFERENCES ailog_peak.peak_episodes(episode_id) ON DELETE CASCADE,
    window_decision_id CHAR(64) NOT NULL
        REFERENCES ailog_peak.namespace_peak_decisions(window_decision_id) ON DELETE CASCADE,
    cause_signature VARCHAR(64),
    signature_version VARCHAR(50) NOT NULL,
    transition_state VARCHAR(30) NOT NULL,
    correlation_method VARCHAR(80) NOT NULL,
    correlation_version VARCHAR(30) NOT NULL,
    correlation_confidence VARCHAR(20) NOT NULL,
    allocated_raw_error_lines BIGINT NOT NULL DEFAULT 0 CHECK (allocated_raw_error_lines >= 0),
    unexplained_raw_lines BIGINT NOT NULL DEFAULT 0 CHECK (unexplained_raw_lines >= 0),
    contributor_fingerprints JSONB NOT NULL DEFAULT '[]'::JSONB,
    material_change_reasons JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (episode_id, window_decision_id, cause_signature),
    CONSTRAINT ck_peak_episode_window_state CHECK (
        transition_state IN ('START', 'CONTINUATION', 'EXPANSION', 'ESCALATION', 'RECOVERY', 'RESOLVED', 'RECURRENCE')
    ),
    CONSTRAINT ck_peak_episode_window_confidence CHECK (
        correlation_confidence IN ('low', 'medium', 'high')
    )
);

CREATE TABLE IF NOT EXISTS ailog_peak.peak_episode_transitions (
    transition_id BIGSERIAL PRIMARY KEY,
    episode_id UUID NOT NULL REFERENCES ailog_peak.peak_episodes(episode_id) ON DELETE CASCADE,
    window_decision_id CHAR(64) NOT NULL
        REFERENCES ailog_peak.namespace_peak_decisions(window_decision_id) ON DELETE CASCADE,
    previous_state VARCHAR(30),
    next_state VARCHAR(30) NOT NULL,
    transition_reason VARCHAR(120) NOT NULL,
    previous_raw_error_lines BIGINT,
    current_raw_error_lines BIGINT NOT NULL CHECK (current_raw_error_lines >= 0),
    cumulative_raw_error_lines BIGINT NOT NULL CHECK (cumulative_raw_error_lines >= 0),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    UNIQUE (episode_id, window_decision_id, next_state)
);

CREATE TABLE IF NOT EXISTS ailog_peak.notification_decisions (
    notification_decision_id CHAR(64) PRIMARY KEY,
    episode_id UUID NOT NULL REFERENCES ailog_peak.peak_episodes(episode_id) ON DELETE CASCADE,
    window_decision_id CHAR(64) NOT NULL
        REFERENCES ailog_peak.namespace_peak_decisions(window_decision_id) ON DELETE CASCADE,
    stream_key VARCHAR(160) NOT NULL,
    destination VARCHAR(100) NOT NULL,
    policy_outcome VARCHAR(30) NOT NULL,
    episode_state VARCHAR(30) NOT NULL,
    candidate_reason VARCHAR(120) NOT NULL,
    detail_rank INTEGER,
    detail_limit INTEGER,
    test_origin_label VARCHAR(255),
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    decided_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_notification_decision_outcome CHECK (
        policy_outcome IN ('primary_send', 'digest_only', 'route_suppressed', 'no_material_change')
    ),
    UNIQUE (episode_id, window_decision_id, destination)
);

ALTER TABLE ailog_peak.notification_deliveries
    ADD COLUMN IF NOT EXISTS notification_decision_id CHAR(64)
        REFERENCES ailog_peak.notification_decisions(notification_decision_id)
        ON DELETE SET NULL;

ALTER TABLE ailog_peak.notification_deliveries
    DROP CONSTRAINT IF EXISTS ck_notification_delivery_status;

ALTER TABLE ailog_peak.notification_deliveries
    ADD CONSTRAINT ck_notification_delivery_status CHECK (
        status IN ('delivered', 'failed', 'suppressed', 'skipped', 'not_attempted')
    );

CREATE INDEX IF NOT EXISTS idx_notification_decisions_window
ON ailog_peak.notification_decisions (stream_key, decided_at DESC, policy_outcome);

ALTER TABLE ailog_peak.peak_episodes
    ADD COLUMN IF NOT EXISTS non_peak_windows INTEGER NOT NULL DEFAULT 0;