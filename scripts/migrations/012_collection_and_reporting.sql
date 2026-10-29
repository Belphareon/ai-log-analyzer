CREATE TABLE IF NOT EXISTS ailog_peak.collection_checkpoints (
    query_hash CHAR(64) PRIMARY KEY,
    coverage_start TIMESTAMPTZ NOT NULL,
    last_live_window TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ailog_peak.report_publications (
    query_hash CHAR(64) NOT NULL,
    report_kind TEXT NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    destination TEXT NOT NULL,
    delivered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (query_hash, report_kind, period_end, destination)
);

CREATE TABLE IF NOT EXISTS ailog_peak.report_knowledge (
    query_hash CHAR(64) NOT NULL,
    problem_key TEXT NOT NULL,
    fingerprints TEXT[] NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (query_hash, problem_key)
);