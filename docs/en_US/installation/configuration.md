# Connection configuration

`BigQueryConnectionConfig` composes the core `ConnectionConfig` with the pool, SSL,
charset, timezone, version and logging mixins, and adds the BigQuery fields below.

| Field | Type | Meaning |
|---|---|---|
| `project` | `str \| None` | GCP project that runs the query jobs |
| `dataset` | `str \| None` | Dataset used for connection-level checks (see the warning below) |
| `location` | `str \| None` | Region for the jobs, e.g. `US`, `europe-north1` |
| `credentials_path` | `str \| None` | Path to a service-account key file |
| `credentials_json` | `dict \| None` | Service-account credentials as a dictionary |
| `api_endpoint` | `str \| None` | Override the client endpoint, e.g. `http://localhost:9050` for the emulator |
| `use_anonymous_credentials` | `bool` | Use `AnonymousCredentials`; for the emulator only |

The backends also accept these as constructor keyword arguments and build the config for
you when no `connection_config=` is passed.

## A real project

```python
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig

config = BigQueryConnectionConfig(
    project="my-gcp-project",
    dataset="app",
    location="US",
    credentials_path="/path/to/key.json",   # omit to use Application Default Credentials
)
backend = BigQueryBackend(connection_config=config)
backend.connect()
```

## Emulator settings

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="app",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

With `api_endpoint` set the backend takes a REST fast path and the emulator's limited
behaviour applies — for example it reports no affected-row count, so `update()` and
`delete()` recover one with a `SELECT COUNT(*)` qualified by the configured dataset.
See [Testing with the BigQuery emulator](../testing/README.md).

## What `dataset` does **not** do

> **Important:** `config.dataset` is **not** a default dataset for generated SQL. It is
> read only for connection-level work: `introspect_and_adapt()` uses it for an existence
> check and `ping()` uses it to list tables. It is never sent as the query job's
> `defaultDataset`. A model without `__schema_name__` therefore renders a bare table name
> with nothing to resolve against.

Declare `__schema_name__` on every model. The full explanation, including why there is no
session-level fallback, is in
[Schema namespaces and datasets](../modeling/schema_namespace.md#there-is-no-session-level-current-dataset).

## Environment variables used by the CLI

The command line tool reads flags or the environment: `--project`
(`BIGQUERY_PROJECT` / `GOOGLE_CLOUD_PROJECT`), `--dataset` (`BIGQUERY_DATASET`),
`--location` (`BIGQUERY_LOCATION`), `--credentials-path`
(`BIGQUERY_CREDENTIALS_PATH` / `GOOGLE_APPLICATION_CREDENTIALS`), `--credentials-json`
(`BIGQUERY_CREDENTIALS_JSON`) and `--api-endpoint` (`BIGQUERY_API_ENDPOINT`).
See [CLI usage](../cli/README.md).
