# Plan 005: AI Log Analyzer PVC Handoff and Delivery FK

## Verdict

**Needs fixes before implementation.** The Multi-Attach diagnosis is consistent with the known RWO behavior, but the proposed quiesce hook does not prove that the target volume has detached. The notification FK explanation is plausible, not confirmed by the available runtime evidence.

**Target:** GitOps chart on `k8s-nprod-3394` and analyzer notification persistence
**Date:** 2026-10-26

## Findings

### P2: Quiesce does not confirm release of the target volume

- **Files:** `sas/k8s-infra-apps-nprod/infra-apps/ai-log-analyzer/templates/job-quiesce.yaml`, `templates/serviceaccount.yaml`
- **Issue:** The hook suspends regular/backfill CronJobs and waits for non-terminal Jobs plus init pods, then treats 20 seconds without those signals as quiescence. It neither checks every remaining pod that can mount the claim nor confirms that the `VolumeAttachment` for the PVC's PV is detached/deleted. The namespaced Role also cannot read cluster-scoped `VolumeAttachment` resources.
- **Risk:** Init can still hit Multi-Attach while CSI detach is in progress; the init Job has `backoffLimit: 0`, so this can fail the Argo sync. An in-pod PostgreSQL lock alone would not prevent the attach conflict because Kubernetes must mount the PVC before the container can acquire the lock.
- **Required remediation:** Choose an orchestration gate that prevents new PVC consumers from being created, discovers the bound PV, waits for all relevant pods to stop using it and for the specific attachment to be released, and fails closed on timeout. Grant only the necessary read access if the selected gate inspects cluster-scoped attachments. Never force-delete an attachment as routine recovery.

### P2: The FK failure's cause is not established

- **Files:** `ai-log-analyzer/scripts/core/delivery_persistence.py`, `scripts/migrations/010_peak_decision_episode_ledger.sql`, `scripts/regular_phase.py`
- **Issue:** Decision persistence commits separately before delivery persistence, and a delivery insert referencing a missing decision fails the run. The schema permits indirect deletion: decisions cascade from episode/window parents, and window decisions cascade from analysis runs; deliveries use `ON DELETE SET NULL` only when the parent is deleted after a delivery row already exists. The inspected rollup-retention code does not delete these parents, so the actual deletion path remains unknown.
- **Risk:** A delivery audit write can fail and make `regular_phase` exit non-zero; the CronJob's `backoffLimit: 1` can then create a retry that overlaps CSI detach. This is a possible chain, not a proven incident timeline.
- **Required remediation:** Correlate DB error timestamps and IDs with pod/job/node/attachment events, identify any DB-side or manual parent deletion, and test the delete-between-transactions race. If orphan deliveries are allowed, store the original decision ID as metadata, keep the FK nullable, and emit an explicit metric/alert without losing the delivery outcome.

## Implementation Gate

- [ ] Refresh read-only cluster access and capture PVC/PV access mode, all pods using the claim, exact `VolumeAttachment` state, relevant events, and original/retry pod times and nodes.
- [ ] Agree on the short-term handoff mechanism and its recovery behavior before editing the chart.
- [ ] Add focused tests for Job completion with a lingering pod, attachment still present, attachment released, timeout, and CronJob recovery.
- [ ] Add a database test reproducing the missing-parent delivery race and validate the chosen orphan-audit behavior.
- [ ] Render the Helm chart and inspect the rendered RBAC and hook ordering; do not deploy until these checks pass.

## Longer-Term Option

Moving mutable registry/alert state to PostgreSQL and reports to supported object/RWX storage can remove this RWO dependency, but requires a separate migration design, backup/restore plan, and data reconciliation. RWX alone does not coordinate concurrent writers.
