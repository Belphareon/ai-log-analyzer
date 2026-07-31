# Plan 001: Code Review - Analysis, Data, and Reporting Process

Full review of the active Elasticsearch ingestion, analysis, persistence, registry, reporting, notification, deployment, and trend-data paths.

**Target:** Current end-to-end AI Log Analyzer process, including unreleased r87/r88 changes
**Repository:** `/home/jvsete/git/ai-log-analyzer`
**Date:** 2026-07-31
**Verdict:** Repository fixes complete; production validation pending
**Release decision:** Source may be committed and pushed after local gates. Do not deploy migrations or an image until production schema, infra-apps, and Elasticsearch reconciliation gates pass.

## Remediation Status

All repository P1/P2 findings were implemented and locally validated on 2026-07-31. The original finding checklists below are retained as the review record; production database introspection, live infra-apps verification, and representative Elasticsearch reconciliation remain external gates.

## Summary

The streaming implementation removes the immediate high-volume materialization risk and the r88 digest changes improve notification scope, but the process still cannot prove complete or correct processing. The most serious defects are silent persistence failure, non-idempotent state transitions, overlapping source windows, mismatched peak quantities, and structured metadata being discarded before analysis.

The existing PostgreSQL tables are not a trustworthy source for Grafana error-kind trends. Grafana should be built only after a run-completeness ledger and deterministic 15-minute fact table are introduced and reconciled against Elasticsearch.

## Confirmed Strengths

- Streaming pagination consumes all fetched pages without deliberately truncating the production path.
- SQLite detail spill bounds retained raw trace detail and stale spill files are cleaned up.
- Peak digest correlation removes duplicate behavior views and carries full application/namespace scope.
- Elasticsearch PIT is used when available, giving a stable snapshot in the normal path.
- Registry YAML writes are atomic at the individual-file level.
- Confluence recent-incidents publication updates a fixed page rather than creating duplicate pages.

## Critical Issues (P1) - Must Fix

- [ ] **[Database / Integrity] Replace the invalid incident identity and make persistence a hard success criterion.**
  - Evidence: `scripts/migrations/000_create_base_tables.sql:62-114` defines `UNIQUE(timestamp, namespace)`, while `scripts/regular_phase.py:1358-1422` and `scripts/backfill.py:232-314` insert one row per incident/fingerprint without conflict handling.
  - Risk: Two incidents in one namespace/window roll back the entire batch. Both callers reduce the failure to `0 saved`, while registry/report processing can continue and the job can still report success.
  - Fix: Introduce a stable incident identity such as `(window_start, namespace, fingerprint, detection_method)`, use deterministic upserts in one transaction, validate inserted/upserted row counts, and fail the run before registry mutation when persistence is incomplete.

- [ ] **[Database / Backfill] Replace `COUNT(*) > 0` day completion with an explicit run ledger.**
  - Evidence: `scripts/backfill.py:198-229` treats any existing backfill row as a completed day; `scripts/backfill.py:816-852` can classify processing as successful even when persistence returned zero.
  - Risk: A partially written day can be skipped permanently, while YAML and reports contain data absent from PostgreSQL.
  - Fix: Record expected, fetched, processed, and persisted counts in `pipeline_runs`; mark a day complete only in the same transaction that commits all facts.

- [ ] **[Ingestion] Make adjacent source windows half-open.**
  - Evidence: `scripts/regular_phase.py:1571-1577` creates adjacent windows, while `scripts/core/fetch_unlimited.py:205-208` queries with both `gte` and `lte`.
  - Risk: An event exactly on a 15-minute boundary belongs to two runs, inflating counts, registry occurrences, thresholds, and notifications.
  - Fix: Standardize all windows as `[window_start, window_end)` and query Elasticsearch with `gte` plus `lt`.

- [ ] **[Detection] Train and evaluate P93/CAP on the same quantity and grain.**
  - Evidence: `scripts/regular_phase.py:1425-1493` stores total ERROR count per namespace/window and `scripts/core/calculate_peak_thresholds.py:55-151` trains namespace/day-of-week thresholds. `scripts/pipeline/phase_c_detect.py:500-583` compares those thresholds with a single fingerprint's namespace count, and multi-window execution averages only active, non-zero fingerprint buckets.
  - Reproduction: A namespace total of 100 split into ten fingerprints of 10 exceeds a threshold of 50, but the current detector produces zero peak candidates.
  - Risk: Distributed namespace peaks are missed; individual fingerprint behavior is compared with an unrelated population; backfill and regular runs use different effective semantics.
  - Fix: Choose two explicit detectors if both are needed: namespace-total thresholds evaluated on namespace totals, and fingerprint thresholds trained/evaluated per fingerprint. Keep 15-minute UTC grain identical in training and detection.

- [ ] **[Parsing / Classification] Preserve structured Elasticsearch metadata through the fetch boundary.**
  - Evidence: `scripts/core/fetch_unlimited.py:225-239` requests exception/error fields, but `scripts/core/fetch_unlimited.py:300-328` drops them before Phase A. It reads `application.name` as a flat key and does not request/pass `application.version`, span IDs, HTTP status, or stack trace. `scripts/pipeline/phase_a_parse.py:262-337` is prepared to consume those fields but never receives them.
  - Reproduction: A nested source containing application `orders-v1`, version `2.4.1`, and `SocketTimeoutException` becomes `application=unknown`, `error_type=UnknownError`, and `app_version=None` after the fetch transformation.
  - Risk: Fingerprints are less stable and specific, classification degrades, application ownership is lost for common ES mappings, and regression detection cannot run.
  - Observed signal: In the local latest export, 135 of 346 rows are category `unknown` and 66 are `unclassified`; this is impact evidence, not proof that every unknown row has the same cause.
  - Fix: Add one tested source-to-record adapter supporting nested and dotted mappings, preserve all fields required by Phase A, and emit metadata-quality counters.

- [ ] **[Baseline / Trends] Stop deriving historical rates from anomaly rows and positive reference values.**
  - Evidence: `scripts/core/baseline_loader.py:52-116` loads only `reference_value > 0` from `peak_investigation`, grouped by `error_type`; it does not construct dense 15-minute observations. The query has a lower time bound but no analysis-time upper bound. `scripts/pipeline/phase_b_measure.py:267-297` then mixes these values into fingerprint measurements.
  - Risk: Quiet windows disappear, threshold/reference values are treated as observed rates, unrelated fingerprints sharing an error type contaminate each other, and historical backfills can read future rows. Trend ratios and severity bonuses are not analytically trustworthy.
  - Fix: Load observed counts from a complete fact table, generate zero bins over elapsed time, key by the same dimensions as the detector, and enforce `fact.window_start < analysis_window_start` for as-of correctness.

- [ ] **[Registry / Concurrency] Make registry mutation atomic across read-modify-write.**
  - Evidence: `scripts/core/problem_registry.py:724-849` loads state before mutation and locks only while writing the current in-memory snapshot. It does not reload and merge while holding the lock. Regular and backfill are separate CronJobs, so each `concurrencyPolicy: Forbid` does not prevent them from overlapping.
  - Risk: The later writer can overwrite newer problem, peak, fingerprint, or alert state with an older snapshot despite successful file locking.
  - Fix: Prefer PostgreSQL as the authoritative mutable state. As an interim measure, acquire one process lock before load, hold it through mutation/save, and add a concurrent-writer integration test.

- [ ] **[Ingestion / Completeness] Do not silently downgrade from PIT to mutable direct-index pagination.**
  - Evidence: `scripts/core/fetch_unlimited.py:190-201` logs PIT-open failure and continues with direct index search; pagination still relies on `search_after` and `_shard_doc`.
  - Risk: Refreshes and shard changes during pagination can skip or duplicate events while the run reports success.
  - Fix: Fail the run when a stable snapshot cannot be opened, or restart from a deterministic cursor using a documented stable sort and completeness reconciliation. Record PIT/fallback mode in the run ledger.

- [ ] **[Deployment] Repair generated Helm values before using the installer.**
  - Evidence: `install.sh:318-379` emits incorrectly indented YAML around DB roles, Confluence page configuration, email, and Teams values; Helm validation is not a mandatory release gate.
  - Risk: New installations can fail validation or deploy materially wrong settings and secrets references.
  - Fix: Generate values with a structured YAML mechanism or corrected template, then require `helm lint` and rendered-manifest validation in CI and installation.

## Important Issues (P2) - Should Fix

- [ ] **[Scope] Enforce or remove `MONITORED_NAMESPACES`.** `config/namespaces.yaml` and installation configuration declare a monitored scope, but `scripts/core/fetch_unlimited.py` queries all ERROR records without a namespace predicate. This changes both cost and analytical population.

- [ ] **[Alerting] Persist cooldown state only for payloads actually delivered.** In `scripts/regular_phase.py:2000-2073`, a failed digest can fall back to individual email; if only some sends succeed, `sent_alerts > 0` causes every prepared payload to receive cooldown state, suppressing alerts that were never delivered.

- [ ] **[Registry] Make peak updates replay-idempotent.** Problem occurrence updates deduplicate minute buckets, but `scripts/core/problem_registry.py:1090-1160` increments peak occurrences on repeated ingestion of the same window. A retry or forced backfill can inflate peak history.

- [ ] **[Publication] Remove duplicate and misleading Confluence execution.** `scripts/backfill.py:1032-1049` publishes recent incidents, then `k8s/templates/cronjob.yaml:185-197` invokes the same publisher again and prints unconditional publication success even after commands handled failure with `|| echo`.

- [ ] **[Reporting] Gate exports and publication on complete authoritative data.** `scripts/regular_phase.py:1900-1947` exports registry snapshots after non-fatal persistence failures; backfill publication errors also do not change final success. Reports can look current while PostgreSQL is incomplete.

- [ ] **[Schema] Introspect the live database before any migration or Grafana query.** `scripts/migrations/upgrade_v3_to_v4.sql:60-78` and `scripts/migrations/001_create_peak_thresholds.sql:13-36` describe incompatible `peak_thresholds` shapes. Repository source alone cannot establish the deployed schema.

- [ ] **[Detection] Wire real application versions or remove the regression claim.** `scripts/pipeline/pipeline.py:603` passes `current_version=None`; combined with fetch metadata loss, `is_regression` is unreachable in production although it carries a 35-point score bonus and appears in reports.

- [ ] **[Trend Semantics] Define zero, unknown, missing-run, and no-data states separately.** A zero count in a complete window is valid evidence; a missing or failed run is not zero. Current data structures cannot distinguish them reliably.

- [ ] **[Retention] Add retention and rollup policy.** No active pruning/partition policy was found for high-frequency raw/fact tables. A Grafana-ready model needs bounded 15-minute retention and longer daily aggregates.

- [ ] **[Observability] Add structured run metrics and hard invariants.** Plain log output does not expose query identity, expected/fetched/processed/persisted counts, metadata-quality ratios, replay status, publication status, or alert delivery per payload.

- [ ] **[Testing] Add integration coverage for correctness boundaries.** Existing r87/r88 tests cover streaming and digest behavior but do not exercise PostgreSQL constraints, transactional ordering, adjacent windows, PIT failure, source mapping, concurrent registry writers, as-of baseline behavior, or partial notifier success.

- [ ] **[Operations] Verify the live infra-apps manifest and database rather than inferring deployment from this repository.** The Helm files here are templates copied into a separate deployment repository; this review did not assert the currently deployed image, values, schema, or CronJob commands.

## Nice-to-Have (P3) - Enhancements

- [ ] Consolidate the multiple report/export/publisher entry points into one orchestrated publication stage with explicit per-destination outcomes.
- [ ] Remove or quarantine legacy analysis and migration scripts after live-schema reconciliation so operators cannot invoke incompatible paths accidentally.
- [ ] Document which trace and message details are sampled/capped while making clear that aggregate event counts remain exact.
- [ ] Replace manual production-validation instructions in `docs/TESTING.md` with executable commands and expected invariants.

## Required Repair Order

1. **Freeze release:** Preserve the current worktree and do not publish r88.
2. **Establish truth:** Introspect the live PostgreSQL schema, active infra-apps manifests, CronJob schedules, image tag, and representative Elasticsearch `_source` mappings.
3. **Fix ingestion identity:** Use half-open windows, require PIT, preserve structured fields, and record source completeness.
4. **Fix persistence:** Add run ledger and deterministic fact identities; make DB commit the gate before registry, reports, and notifications.
5. **Fix analytical contracts:** Separate namespace-total and fingerprint detectors; rebuild baseline/trend logic from dense observed facts with as-of cutoffs.
6. **Fix state/delivery:** Make registry/replay behavior idempotent and track notification outcome per payload.
7. **Reconcile history:** Reprocess a bounded period from Elasticsearch and compare source, fact, incident, registry, and report counts.
8. **Add Grafana:** Only point dashboards and alerts at complete-run views after reconciliation passes.
9. **Release:** Run focused and full validation, build/tag the image, then commit and push source only according to the original release instruction.

## Grafana Data Proposal

### 1. `pipeline_runs` - Completeness Ledger

One row per attempted source window and query contract.

| Column | Purpose |
|---|---|
| `run_id` | Immutable run identifier |
| `run_type` | `regular`, `backfill`, or `threshold` |
| `window_start`, `window_end` | UTC half-open interval |
| `query_hash`, `source_index` | Reproducible source contract |
| `code_version` | Analyzer/image version |
| `status` | `running`, `complete`, `partial`, `failed`, `superseded` |
| `expected_hits`, `fetched_hits`, `processed_hits` | Source completeness invariant |
| `fact_rows`, `incident_rows` | Persistence invariant |
| `started_at`, `completed_at` | Runtime and staleness |
| `replay_of`, `error_code`, `error_detail` | Replay lineage and failure diagnosis |

Use a uniqueness contract equivalent to `(run_type, window_start, window_end, query_hash)`. A replay writes under a new `run_id`; it becomes authoritative only after its facts commit and status changes to `complete` in one transaction.

### 2. `error_kind_counts` - Primary Fact Table

Grain: one complete 15-minute UTC window per namespace, application, and fingerprint/error kind.

| Column | Purpose |
|---|---|
| `run_id` | Provenance and completeness join |
| `window_start` | Canonical 15-minute bucket |
| `namespace`, `application` | Operational dimensions |
| `fingerprint`, `error_type` | Stable error-kind dimensions |
| `category`, `subcategory` | Deterministic classification snapshot |
| `error_count` | Observed count for this exact grain |
| `first_event_at`, `last_event_at` | Event-time bounds |
| `sample_message` | Optional sanitized diagnostic sample, not a Grafana label |
| `metadata_quality` | Structured/derived/unknown classification source |

Primary identity should be deterministic, for example `(run_id, window_start, namespace, application, fingerprint)`, with an authoritative view selecting facts only from completed, non-superseded runs. Do not use raw message, trace ID, stack trace, or unbounded exception text as dashboard labels.

### 3. Derived and Audit Tables

- `namespace_error_counts`: view or materialized view summing `error_kind_counts` at namespace/window grain. This is the only input for namespace P93/CAP.
- `detection_events`: immutable detector output with detector type, evaluated value, threshold snapshot, score, flags, and explanation. Do not mix anomalies with raw counts.
- `threshold_snapshots`: threshold value, population grain, training interval, sample count, percentile method, and calculation version.
- `notification_deliveries`: one row per detection/destination/attempt with delivered status and provider response.
- Daily rollup: retain long-term totals by date/namespace/application/error type after fine-grain retention expires.

### 4. Trend Definitions

- Generate dense 15-minute time bins and include zero-count bins only when `pipeline_runs.status = 'complete'`.
- Treat missing/partial/failed runs as gaps, never as zero.
- Compute namespace trends from namespace totals and fingerprint trends from fingerprint facts; never cross those populations.
- Use only facts with `window_start < analysis_window_start` for baseline training.
- Define short trend as last 8 complete bins versus previous 8; daily trend as last 96 versus previous 96; weekly trend as last 672 versus previous 672 or an explicitly documented seasonal comparison.
- Version every detector and threshold calculation so historical dashboard explanations remain reproducible.

### 5. Initial Dashboard Panels

1. **Pipeline health:** last complete window, lag, expected/fetched/processed/persisted counts, failed and partial runs.
2. **ERROR volume:** 15-minute total by namespace and application with data-gap annotations.
3. **Top error kinds:** error type/fingerprint ranked by count and change over prior period.
4. **Peak overlay:** observed namespace total versus the exact P93/CAP snapshot used by detection.
5. **New and returning errors:** first-seen and regression events after version metadata is trustworthy.
6. **Metadata quality:** percentage of unknown application, unknown error type, unclassified category, and missing trace context.
7. **Delivery health:** sent, failed, suppressed, and cooldown notifications by destination.
8. **Replay/reconciliation:** superseded runs, source-to-fact count differences, and unresolved gaps.

## Validation Gates

- [ ] An event at exactly `08:15:00Z` is counted once across the `08:00` and `08:15` jobs.
- [ ] Nested and dotted Elasticsearch fixtures produce identical normalized records, including application, version, exception type, HTTP status, trace/span IDs, and namespace.
- [ ] A namespace count of 100 split across ten fingerprints still triggers the namespace-total detector when its threshold is 50.
- [ ] Two fingerprints in the same namespace/window persist successfully and an exact replay leaves one deterministic fact per identity.
- [ ] Injected DB failure leaves the run failed/partial and does not mutate registry, publish reports, or advance alert state.
- [ ] Concurrent regular/backfill execution cannot lose registry or fact updates.
- [ ] PIT-open failure cannot result in a successful complete run.
- [ ] Baseline tests include zero windows, reject future data, and keep namespace/fingerprint populations separate.
- [ ] Partial email fallback marks cooldown only for payloads confirmed delivered.
- [ ] `helm lint` and rendered-manifest schema validation pass for generated values.
- [ ] For a replayed sample period, Elasticsearch hit count equals processed count and the sum of complete fact counts; documented exclusions are explicit and measurable.
- [ ] Full Python test discovery, focused r87/r88 tests, compile checks, and migration integration tests pass sequentially in WSL.

## Files Reviewed

- `scripts/core/fetch_unlimited.py`
- `scripts/core/streaming_aggregator.py`
- `scripts/core/baseline_loader.py`
- `scripts/core/calculate_peak_thresholds.py`
- `scripts/core/peak_detection.py`
- `scripts/core/problem_registry.py`
- `scripts/core/email_notifier.py`
- `scripts/pipeline/phase_a_parse.py`
- `scripts/pipeline/phase_b_measure.py`
- `scripts/pipeline/phase_c_detect.py`
- `scripts/pipeline/phase_d_score.py`
- `scripts/pipeline/phase_e_classify.py`
- `scripts/pipeline/pipeline.py`
- `scripts/regular_phase.py`
- `scripts/backfill.py`
- `scripts/recent_incidents_publisher.py`
- `scripts/backfill_report_publisher.py`
- `scripts/confluence_csv_uploader.py`
- `scripts/exports/table_exporter.py`
- `scripts/migrations/000_create_base_tables.sql`
- `scripts/migrations/001_create_peak_thresholds.sql`
- `scripts/migrations/upgrade_v3_to_v4.sql`
- `k8s/templates/cronjob.yaml`
- `install.sh`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/HOW_IT_WORKS.md`
- `docs/OPERATIONS.md`
- `docs/TESTING.md`
- `scripts/tests/test_streaming_r87.py`
- `scripts/tests/test_peak_digest_r88.py`

## Review Notes

- Security-oriented source inspection found no new credential literal or direct SQL string interpolation in the reviewed active inserts; the blocking risks are integrity and correctness rather than a newly identified exploit.
- The review did not query the production database, Elasticsearch mapping, Kubernetes cluster, ArgoCD application, SMTP provider, or Confluence page. Those checks are explicit prerequisites, not inferred facts.
- The local worktree already contained source and documentation changes before this plan was created. This review did not revert or modify them.

---

*Reviewer: code-review full-review workflow*
*Status: LOCAL_FIXES_COMPLETE_EXTERNAL_GATES_PENDING*