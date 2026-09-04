# adapters/

Type-adapter tests for the BigQuery backend — the layer converting Python
values to BigQuery SQL parameters and back.

| File | Description |
|------|-------------|
| `test_struct_adapter.py` | `BigQueryStructAdapter` — Python `dict` ↔ BigQuery `STRUCT` parameter conversion. |

These tests are pure unit tests (no network, no emulator).
