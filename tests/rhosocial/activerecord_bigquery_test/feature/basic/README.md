# `basic` scope wiring — BigQuery

This directory mirrors the shared `testsuite/feature/basic` scope with thin
bridge files (`from rhosocial.activerecord.testsuite.feature.basic.<dir>... import *`).
There is **one copy of every test** — the test bodies live only in the testsuite.

## Not-yet-introduced directories

The testsuite `basic` scope also defines the directories below. Their test
modules are retained in the testsuite (the single source of truth); this
backend deliberately does **not** provide bridge files for them yet. This is a
record of "not enabled here", not a uniform claim that BigQuery lacks the
feature — note where the gap is the `goccy` emulator rather than the service.

| Directory | Observed when temporarily bridged | Why not introduced |
|-----------|-----------------------------------|--------------------|
| `connection/` | hangs locally — connection lifecycle waits for the `goccy` emulator (default port 9050) | The contract needs a live emulator/project; without one the probe cannot complete. Deferred until connection-lifecycle tests can run against a provisioned emulator. |
| `ddl/` | 0 failed, 1 skipped — only a capability-gated materialized-view case | The scope yields almost no signal on this backend; the one case is already capability-gated. Not worth wiring as a standalone scope. |
| `transaction/` | fails under the `goccy` emulator | The emulator does not implement `ROLLBACK TRANSACTION`, so cross-task ownership / savepoint assertions cannot hold (real BigQuery documents BEGIN/COMMIT/ROLLBACK — see the root `conftest.py` skip for `test_transaction_crud`). Needs emulator reconciliation. |
| `validation/` | collection-time error | The shared validation modules are incompatible with this backend's fixture graph as wired; needs reconciliation before the contract can be collected. |
| `worker/` | collection-time error | Same collection-time incompatibility as `validation/`; multi-worker lifecycle is not yet reconciled with the BigQuery scenario setup. |

Introducing any of these is future work: add the bridge files, make the shared
contract compatible with the emulator/real service and this backend's fixtures,
and confirm green against a provisioned emulator.
