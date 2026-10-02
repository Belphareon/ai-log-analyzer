ALTER TABLE ailog_peak.threshold_snapshot_runs
    ADD COLUMN IF NOT EXISTS monitored_namespaces TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];

CREATE OR REPLACE VIEW ailog_peak.v_latest_threshold_snapshot AS
SELECT snapshot.*
FROM ailog_peak.threshold_snapshot_runs snapshot
WHERE snapshot.status = 'complete'
ORDER BY snapshot.completed_at DESC, snapshot.created_at DESC
LIMIT 1;