CREATE TABLE IF NOT EXISTS ailog_peak.threshold_slot_values (
    snapshot_id UUID NOT NULL REFERENCES ailog_peak.threshold_snapshot_runs(snapshot_id) ON DELETE CASCADE,
    namespace VARCHAR(255) NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    hour_of_day INTEGER NOT NULL CHECK (hour_of_day BETWEEN 0 AND 23),
    quarter_hour INTEGER NOT NULL CHECK (quarter_hour BETWEEN 0 AND 3),
    percentile_value DOUBLE PRECISION NOT NULL CHECK (percentile_value >= 0),
    sample_count INTEGER NOT NULL CHECK (sample_count > 0),
    profile_status VARCHAR(10) NOT NULL CHECK (profile_status IN ('init', 'mature')),
    median_value DOUBLE PRECISION NOT NULL,
    mean_value DOUBLE PRECISION NOT NULL,
    max_value DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (snapshot_id, namespace, day_of_week, hour_of_day, quarter_hour)
);

CREATE OR REPLACE VIEW ailog_peak.v_latest_threshold_slots AS
SELECT value_row.*, snapshot.percentile_level, snapshot.training_start,
       snapshot.training_end, snapshot.percentile_method, snapshot.calculation_version,
       snapshot.population_grain
FROM ailog_peak.threshold_slot_values value_row
JOIN ailog_peak.v_latest_threshold_snapshot snapshot
  ON snapshot.snapshot_id = value_row.snapshot_id;

ALTER TABLE ailog_peak.namespace_peak_decisions
  ADD COLUMN IF NOT EXISTS profile_status VARCHAR(10) NOT NULL DEFAULT 'legacy'
    CHECK (profile_status IN ('legacy', 'init', 'mature', 'missing', 'not_used')),
  ADD COLUMN IF NOT EXISTS threshold_samples INTEGER NOT NULL DEFAULT 0 CHECK (threshold_samples >= 0),
  ADD COLUMN IF NOT EXISTS is_evaluated BOOLEAN NOT NULL DEFAULT TRUE;

ALTER TABLE ailog_peak.namespace_peak_decisions
  DROP CONSTRAINT IF EXISTS ck_namespace_peak_decision_reason;

ALTER TABLE ailog_peak.namespace_peak_decisions
  ADD CONSTRAINT ck_namespace_peak_decision_reason CHECK (
    verdict_reason IN (
      'below_min_volume', 'below_threshold', 'peak_diagnosed', 'peak_undiagnosed',
      'threshold_profile_missing'
    )
  );