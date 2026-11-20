# Testing with the BigQuery emulator

CI and local integration tests do not need GCP credentials. They run against
`goccy/bigquery-emulator` in a container.

## Start the emulator

```bash
bash tests/scripts/start_emulator.sh
```

Or start it directly:

```bash
docker run -d -p 9050:9050 -p 9060:9060 \
  ghcr.io/goccy/bigquery-emulator:latest --project=test
```

## Point the backend at it

```python
from google.api_core.client_options import ClientOptions
from google.auth.credentials import AnonymousCredentials
from google.cloud import bigquery

client = bigquery.Client(
    project="test",
    credentials=AnonymousCredentials(),
    client_options=ClientOptions(api_endpoint="http://localhost:9050"),
)
```

At the library level the same thing is expressed with two config fields:

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="app",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

See [Connection configuration](../installation/configuration.md#emulator-settings).

## What differs on the emulator

* **No billing.** The emulator is a shim; it does not charge for the scans that the three
  data introspection families perform.
* **Partial GoogleSQL.** It implements a subset of the language. A `seconds_between` live
  case that cannot evaluate `TIMESTAMP_DIFF` skips with the server's own reason rather than
  reporting a formatter failure.
* **Narrower `COLUMNS` projection.** The emulator answers 10 of the 24 documented columns.
  `list_columns()` asks the full list first and falls back once; a real server is never
  asked for less. See
  [The `COLUMNS` projection and the emulator](../introspection/README.md#the-columns-projection-and-the-emulator).
* **No affected-row count.** `update()` and `delete()` pre-count matching rows to recover
  one. See [Transactions and DML](../capabilities/transactions.md#affected-row-counts).
* **It degrades over time.** The workflow restarts it between shards as tables accumulate.
* **Verification scope.** Only the emulator has been exercised in this repository; the
  full-list `COLUMNS` path and the `routines` live path have not been run against a real
  service here. See
  [What Has Been Verified](../introspection/README.md#what-has-been-verified).

A statement that parses and returns rows on the emulator is one BigQuery should accept; it
is not proof that a real project answered it.
