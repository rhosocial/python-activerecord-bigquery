# rhosocial-activerecord-bigquery

BigQuery backend implementation for rhosocial-activerecord.

## Installation

```bash
pip install rhosocial-activerecord-bigquery
```

## Usage

```python
from rhosocial.activerecord.backend.impl.bigquery import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

config = BigQueryConnectionConfig(
    project="my-project",
    dataset="my_dataset",
    credentials_path="/path/to/service-account.json",
)

backend = BigQueryBackend(config=config)
```
