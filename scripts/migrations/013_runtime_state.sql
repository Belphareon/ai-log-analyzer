CREATE TABLE IF NOT EXISTS ailog_peak.runtime_state (
    query_hash CHAR(64) PRIMARY KEY,
    files JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);