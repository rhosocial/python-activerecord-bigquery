# Quick start

This is the smallest program that shows the one rule specific to this backend: **declare
the dataset on the model**.

```python
from typing import ClassVar, Optional

from rhosocial.activerecord import ActiveRecord
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig
from rhosocial.activerecord.backend.expression import FieldProxy

config = BigQueryConnectionConfig(
    project="my-gcp-project",
    dataset="app",
    location="US",
)
backend = BigQueryBackend(connection_config=config)
backend.connect()


class Order(ActiveRecord):
    __table_name__ = "orders"
    __schema_name__ = "app"          # -> `app`.`orders`
    c: ClassVar[FieldProxy] = FieldProxy()

    id: Optional[int] = None
    note: Optional[str] = None


# Rendered SQL: SELECT `orders`.`id` FROM `app`.`orders`
sql = Order.query().select(Order.c.id).to_sql()[0]
print(sql)
```

Note the two-part column reference: the dataset qualifies the range in `FROM` and stops
there. This is the rule that most changes code written against an OLTP backend; see
[Schema namespaces and datasets](../modeling/schema_namespace.md).

## Running against the emulator

Replace the config with the emulator variant and no GCP account is needed:

```python
config = BigQueryConnectionConfig(
    project="test",
    dataset="app",
    api_endpoint="http://localhost:9050",
    use_anonymous_credentials=True,
)
```

Start the emulator first (see [Testing with the BigQuery emulator](../testing/README.md)).

## Async

The async backend has the same shape and uses the client's native async support:

```python
from rhosocial.activerecord.backend.impl.bigquery.backend.async_backend import AsyncBigQueryBackend

async_backend = AsyncBigQueryBackend(connection_config=config)
await async_backend.connect()
```

## Next steps

* [BigQuery field types](../modeling/field_types.md) — STRUCT, ARRAY, JSON, GEOGRAPHY,
  BIGNUMERIC
* [Querying BigQuery native types](../querying/bigquery_types.md)
* [Transactions and DML](../capabilities/transactions.md) — session transactions and the
  absence of `RETURNING`
* [CLI usage](../cli/README.md) — introspect a dataset from the command line

Runnable examples are at the repository root under `examples/`, including
[`examples/named_connections/example.py`](../../../examples/named_connections/example.py).
