# query/relation tests (sqlite bridge)

SQLite bridge for the shared `feature/query/relation` testsuite topic. This
directory was moved from `feature/relation/` and merged with the old
`feature/query/relations/` bridge group, mirroring the testsuite source tree.

- `conftest.py` — star-imports `testsuite.feature.query.relation.conftest`.
- `core/` — sqlite-local relation tests (unchanged).
- `ordering/` — bridge to `testsuite.feature.query.relation.ordering`.
- `legacy/` — the merged old `query/relations` real-database `with_()` integration
  tests (`test_with_integration.py`) plus a self-contained L2 conftest.

See [feature tests](../README.md) and [tests/README.md](../../../../README.md).
