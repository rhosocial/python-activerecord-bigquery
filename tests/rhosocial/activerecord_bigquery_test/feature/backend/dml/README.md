# dml/

DML execution: CRUD statements against the BigQuery backend.

| File | Description |
|------|-------------|
| `test_crud_backend.py` | Full CRUD against the `goccy/bigquery-emulator` — **requires a running emulator** (`tests/scripts/start_emulator.sh`, endpoint `http://localhost:9050`). Currently placeholder stubs. |

Async parity: `AsyncBigQueryBackend` implements real async CRUD (`async_backend.py`) —
`test_crud_backend_async.py` is a Fill candidate (Tier-2).
