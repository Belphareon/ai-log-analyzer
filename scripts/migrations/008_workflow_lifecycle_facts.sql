CREATE TABLE IF NOT EXISTS ailog_peak.workflow_lifecycle_runs (
    run_id VARCHAR(160) PRIMARY KEY,
    window_start TIMESTAMP WITH TIME ZONE NOT NULL,
    window_end TIMESTAMP WITH TIME ZONE NOT NULL,
    source_cluster VARCHAR(512) NOT NULL,
    source_index VARCHAR(2048) NOT NULL,
    scope TEXT NOT NULL,
    status VARCHAR(16) NOT NULL,
    expected_count BIGINT,
    fetched_count BIGINT NOT NULL,
    processed_count BIGINT NOT NULL,
    query_count INTEGER NOT NULL,
    truncated BOOLEAN NOT NULL DEFAULT FALSE,
    reason TEXT,
    code_version VARCHAR(255),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_workflow_lifecycle_run_status
        CHECK (status IN ('running', 'complete', 'partial', 'failed')),
    CONSTRAINT ck_workflow_lifecycle_run_counts
        CHECK (expected_count IS NULL OR (fetched_count >= 0 AND processed_count >= 0))
);

CREATE TABLE IF NOT EXISTS ailog_peak.workflow_lifecycle_incidents (
    run_id VARCHAR(160) NOT NULL REFERENCES ailog_peak.workflow_lifecycle_runs(run_id),
    topic VARCHAR(1024) NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    queue_event_id VARCHAR(255) NOT NULL,
    source_cluster VARCHAR(512) NOT NULL,
    source_indices JSONB NOT NULL DEFAULT '[]'::jsonb,
    first_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    last_seen TIMESTAMP WITH TIME ZONE NOT NULL,
    attempt_count INTEGER NOT NULL,
    processing_to_registered_count INTEGER NOT NULL,
    without_delaying_count INTEGER NOT NULL,
    stale_delay_count INTEGER NOT NULL,
    predecessor_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    predecessor_completed_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    pod_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence VARCHAR(16) NOT NULL,
    loop_detected BOOLEAN NOT NULL,
    alert_eligible BOOLEAN NOT NULL DEFAULT FALSE,
    incomplete BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, topic, namespace, queue_event_id),
    CONSTRAINT ck_workflow_lifecycle_incident_confidence
        CHECK (confidence IN ('low', 'medium', 'high', 'partial')),
    CONSTRAINT ck_workflow_lifecycle_incident_alert
        CHECK (NOT alert_eligible OR (confidence = 'high' AND NOT incomplete))
);

CREATE TABLE IF NOT EXISTS ailog_peak.workflow_lifecycle_evidence (
    run_id VARCHAR(160) NOT NULL,
    topic VARCHAR(1024) NOT NULL,
    namespace VARCHAR(255) NOT NULL,
    queue_event_id VARCHAR(255) NOT NULL,
    es_index VARCHAR(1024) NOT NULL,
    es_id VARCHAR(1024) NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    event_kind VARCHAR(64) NOT NULL,
    pod_name VARCHAR(255),
    trace_id VARCHAR(512),
    message TEXT NOT NULL,
    PRIMARY KEY (run_id, topic, namespace, queue_event_id, es_index, es_id),
    FOREIGN KEY (run_id, topic, namespace, queue_event_id)
        REFERENCES ailog_peak.workflow_lifecycle_incidents(run_id, topic, namespace, queue_event_id)
);