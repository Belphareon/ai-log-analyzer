# Review commit `209869f`

## Verdict

**Request changes.** The implementation has three blocking defects in episode correctness and deployment generation.

## Findings

### P1: Episode load, correlation, and persistence are not protected by one lock

[`regular_phase.py`](../scripts/regular_phase.py#L2537) loads prior episodes through a separate connection before correlation. [`run_persistence.py`](../scripts/core/run_persistence.py#L679) acquires `pg_advisory_xact_lock`, but [`run_persistence.py`](../scripts/core/run_persistence.py#L722) immediately commits the transaction and releases that lock before writing decisions and episodes. Overlapping regular runs can therefore read the same stale episode state and independently classify the same next window, producing duplicate or incorrect START, CONTINUATION, EXPANSION, and cumulative state.

Required fix: serialize the complete load -> correlate -> persist operation for each `stream_key` on one lock lifetime. Add a concurrent integration test in which two workers process adjacent or identical windows and verify one deterministic ledger timeline.

### P1: Multi-namespace cause families inflate episode impact

[`peak_episode.py`](../scripts/core/peak_episode.py#L668) attaches a family to every namespace present in `namespace_counts`, but [`peak_episode.py`](../scripts/core/peak_episode.py#L143) puts the family's global `raw_error_lines` and `unique_operations` into every namespace observation. [`peak_episode.py`](../scripts/core/peak_episode.py#L468) then adds those global values again for each namespace. A family with 100 total lines across two namespaces can therefore record 200 cumulative lines in one 15-minute window and trigger false escalation or misleading alert impact.

Required fix: allocate namespace observations from `family.namespace_counts[namespace]` and ensure episode window totals and operation counts are added exactly once. Add a two-namespace, one-family reconciliation test.

### P1: `install.sh` generates invalid YAML

The values heredoc mixes two-space and four-space sibling indentation under `env`, `init`, and `teams`; examples are visible at [`install.sh`](../install.sh#L353), [`install.sh`](../install.sh#L385), and [`install.sh`](../install.sh#L397). Keys such as `DB_DDL_ROLE` are parsed as an unexpected nested block below scalar `DB_PORT`, so generated `values.yaml` is invalid and installation cannot reach Helm successfully.

Required fix: restore consistent two-space indentation for all sibling keys and add a test that executes the values generation path and parses the output as YAML.

## Validation

- Full suite previously completed successfully under system Python; the repository virtualenv does not contain pytest.
- Focused replay tests: `17 passed in 0.61s`, exit `0`.
- Existing tests do not cover the three failure modes above.

## Remediation

- Regular and backfill decision load, episode correlation, and persistence now share one PostgreSQL advisory-lock transaction.
- Cause-family episode observations use per-namespace line counts and assign family operation counts once per window.
- `install.sh` now emits consistently indented YAML; a regression test parses the generated values heredoc.

Post-fix validation: `151 passed, 5 skipped`, plus `bash -n install.sh`.