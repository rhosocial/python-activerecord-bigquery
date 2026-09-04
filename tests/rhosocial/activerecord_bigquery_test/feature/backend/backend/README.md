# backend/

Backend-object behavior: construction, configuration, CRUD execution, and
emulator-based integration scenarios.

| File | Description |
|------|-------------|
| `test_backend.py` | `BigQueryBackend` construction and config propagation. |
| `test_backend_async.py` | `AsyncBigQueryBackend` construction and config propagation — async twin of `test_backend.py` (offline). |
| `test_backend_mock.py` | Backend instantiation smoke tests (offline). |
| `test_config.py` | `BigQueryConnectionConfig` (project/dataset/endpoint/anonymous credentials). |
| `test_integration_scenarios.py` | Scenario config loading from `tests/config/bigquery_scenarios.yaml` (emulator endpoint, anonymous credentials). |

Scenario environment: `BIGQUERY_SCENARIOS_CONFIG_PATH`,
`BIGQUERY_ACTIVE_SCENARIOS`, `BIGQUERY_EMULATOR_PORT`.
