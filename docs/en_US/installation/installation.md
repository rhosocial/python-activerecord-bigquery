# Installation guide

## Packages

Install the backend together with the core library so that the expression layer and the
dialect come from the same development line:

```bash
pip install rhosocial-activerecord rhosocial-activerecord-bigquery
```

Both distributions install under the `rhosocial.activerecord` namespace, so importing the
backend is an import from that namespace:

```python
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import AsyncBigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig
```

The client library (`google-cloud-bigquery`) is pulled in as a dependency. Use Python
3.10–3.14 on a standard GIL build; see [Supported versions](../introduction/supported_versions.md).

## Credentials for a real project

The client uses Application Default Credentials unless a key file or a JSON credential
object is supplied to the connection config. The account needs permission to run jobs in
the project and to read/write the dataset you name. No special service is installed
locally — BigQuery is a managed service.

## Working without GCP credentials

For development and CI, point the client at an emulator instead. It runs as a container,
and the connection config carries two extra fields (`api_endpoint` and
`use_anonymous_credentials`) to select it. See
[Connection configuration](configuration.md#emulator-settings) and
[Testing with the BigQuery emulator](../testing/README.md).

## Worked examples

The repository's `examples/` directory holds small runnable programs for named
connections, named procedures and named queries; start with
[`examples/named_connections/example.py`](../../../examples/named_connections/example.py).
