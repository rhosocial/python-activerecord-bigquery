# feature/backend — BigQuery backend test subjects

Directory layout follows the cross-backend test taxonomy
(`.claude/plan/2026-09-03/cross-backend-test-taxonomy.md` §5.9):
common subjects at the top level, vendor specifics under the subject tree.

## Top level

| File | Description |
|------|-------------|
| `test_expression_roundtrip_all.py` | Every expression class in core's package and in this backend's, round-tripped through dict/JSON/XML and classified by render outcome. Core's classes are in scope because BigQuery's SQL surface is the narrowest in the family, so which of them it refuses is worth pinning. |

## Subject matrix

| subject | status | notes |
|---------|--------|-------|
| adapters/ | ✅ | struct adapter round-trips |
| backend/ | ✅ | backend lifecycle/mock/config + async twin (`test_backend_async.py`) |
| ddl/ | ✅ | alter-table modifier + create-table diff |
| dialect/ | ✅ | formatting |
| dml/ | 🕳️ partial | `test_crud_backend.py` only |
| expression/ | ✅ | expressions |
| protocol/ | ✅ | conformance + capabilities |
| schema/ | ✅ | schema support |
| transactions/ | ✅ | transaction backend |

## Gaps (Tier-2)

- `dml/test_execute_many.py` — BigQuery backend has no `execute_many`
  (base class provides a sync one; untestable without an emulator/instance).
- `concurrency/` — no `get_concurrency_hint` on the BigQuery backend.
- `backend/test_error_handling.py(+_async)` — shared §6 matrix Fill item.
- async twins: `dml/test_crud_backend_async.py`,
  `transactions/test_transaction_backend_async.py` (AsyncBigQueryBackend is a
  real implementation; requires a service/emulator to run).

BigQuery has no live service instance in CI; those tests are not required to
pass. Offline/dialect tests collect and run with 0 errors.