ALTER TABLE ailog_peak.threshold_snapshot_runs
    ADD COLUMN IF NOT EXISTS monitored_namespaces TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];