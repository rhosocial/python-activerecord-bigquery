# rhosocial-activerecord-bigquery

BigQuery backend implementation for `rhosocial-activerecord`. Supports Google Cloud BigQuery via `google-cloud-bigquery`, with native async backend and local emulator testing via `goccy/bigquery-emulator`.

## Installation

```bash
pip install rhosocial-activerecord-bigquery
```

## Quick Start

### Real BigQuery

```python
from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

config = BigQueryConnectionConfig(
    project="my-gcp-project",
    dataset="my_dataset",
    credentials_path="/path/to/service-account.json",
)
backend = BigQueryBackend(connection_config=config)
```

### Local Emulator (No GCP Account Needed)

```bash
# Start emulator
bash tests/scripts/start_emulator.sh
# Or manually:
docker run -d -p 9050:9050 -p 9060:9060 \
  ghcr.io/goccy/bigquery-emulator:latest --project=test
```

```python
from google.auth.credentials import AnonymousCredentials
from google.api_core.client_options import ClientOptions
from google.cloud import bigquery

client = bigquery.Client(
    project="test",
    credentials=AnonymousCredentials(),
    client_options=ClientOptions(api_endpoint="http://localhost:9050"),
)
```

The backend supports emulator mode via `api_endpoint` and `use_anonymous_credentials`:

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="test_dataset",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

## Running Tests

```bash
# With emulator
bash tests/scripts/start_emulator.sh
pytest --scenarios=bigquery_emulator

# With environment variable config
export BIGQUERY_SCENARIOS_CONFIG_PATH=tests/config/bigquery_scenarios.yaml
export BIGQUERY_ACTIVE_SCENARIOS=bigquery_emulator
pytest
```

## Features

- **Dialect**: Backtick identifier quoting (`` `table` ``), named parameters (`@param_0`), standard SQL
- **Type Adapters**: STRUCT, ARRAY, JSON, BIGNUMERIC, TIMESTAMP, GEOGRAPHY
- **Transaction Management**: Session-level BEGIN/COMMIT/ROLLBACK and savepoints
- **Async Support**: Native `AsyncBigQueryBackend` using `google-cloud-bigquery` async APIs
- **CI Integration**: `.github/workflows/test.yml` and `.github/workflows/publish.yml`

## Project Structure

```
python-activerecord-bigquery/
├── src/rhosocial/activerecord/backend/impl/bigquery/
│   ├── backend.py         # Sync StorageBackend
│   ├── async_backend.py   # Async StorageBackend
│   ├── config.py          # Connection config
│   ├── dialect.py         # SQL dialect
│   ├── adapters.py        # Type adapters
│   ├── transaction.py     # Transaction manager
│   └── ...
├── tests/
│   ├── config/bigquery_scenarios.yaml
│   ├── providers/scenarios.py
│   └── scripts/start_emulator.sh
```

## License

Apache 2.0
