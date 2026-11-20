<!-- README.md -->
# rhosocial-activerecord-bigquery

[![Python](https://img.shields.io/pypi/pyversions/rhosocial-activerecord-bigquery.svg)](https://pypi.org/project/rhosocial-activerecord-bigquery/)
[![Tests](https://github.com/rhosocial/python-activerecord-bigquery/actions/workflows/test.yml/badge.svg)](https://github.com/rhosocial/python-activerecord-bigquery/actions)
[![Apache 2.0 License](https://img.shields.io/github/license/rhosocial-activerecord-bigquery.svg)](https://github.com/rhosocial/python-activerecord-bigquery/blob/main/LICENSE)
[![BigQuery](https://img.shields.io/badge/BigQuery-serverless-blue?logo=googlecloud)](docs/en_US/README.md)

<div align="center">
    <img src="https://raw.githubusercontent.com/rhosocial/python-activerecord/main/docs/images/logo.svg" alt="rhosocial ActiveRecord Logo" width="200"/>
    <h3>BigQuery Backend for rhosocial-activerecord</h3>
    <p><b>Standard SQL · STRUCT / ARRAY / JSON · Serverless</b></p>
</div>

A [Google Cloud BigQuery](https://cloud.google.com/bigquery) backend for
[rhosocial-activerecord](https://github.com/rhosocial/python-activerecord).

> **This package is not on PyPI yet.** Install from source until the first
> release is published.

**Keywords:** bigquery, activerecord, orm, pydantic, python, serverless, data-warehouse, async

## Why This Project?

BigQuery is a serverless, columnar warehouse billed per query — not an
operational SQL server. This backend lets you keep the same ActiveRecord models,
field proxies, and type-safe query builder you already use, while speaking
BigQuery's dialect natively:

- **BigQuery types are first-class** — `STRUCT`, `ARRAY`, `JSON`, `GEOGRAPHY`, and
  `Decimal` have dedicated adapters.
- **Dataset-aware naming** — `__schema_name__` maps to a dataset; identifiers are
  backtick-quoted and tables referenced as `project.dataset.table`.
- **Native async** — `AsyncBigQueryBackend` is built on the Google Cloud async
  client, not a thread-pool wrapper around sync code.

No instance to provision and no engine version to track — configure a project and
dataset and start querying.

## Quick Start

### Installation

```bash
pip install rhosocial-activerecord-bigquery
```

Requires Python 3.10+ and the core `rhosocial-activerecord` library. Until the
first release, install both from source.

### Configure and query

BigQuery identifies data by **project**, **dataset**, and **table**. By default the
client uses Application Default Credentials; pass `credentials_path` for a
service-account key, or point `api_endpoint` at the local emulator for development.

```python
from typing import Annotated, ClassVar, Optional

from rhosocial.activerecord.base import FieldProxy, UseSqlType
from rhosocial.activerecord.backend.expression.types import IntegerType, VarCharType
from rhosocial.activerecord.backend.impl.bigquery.backend import BigQueryBackend
from rhosocial.activerecord.backend.impl.bigquery.config import BigQueryConnectionConfig
from rhosocial.activerecord.model import ActiveRecord


class User(ActiveRecord):
    @classmethod
    def table_name(cls) -> str:
        return "users"

    c: ClassVar[FieldProxy] = FieldProxy()  # enables User.c.<field> expressions
    id: Optional[Annotated[int, UseSqlType(IntegerType())]] = None
    name: Annotated[str, UseSqlType(VarCharType(length=100))]
    email: Annotated[str, UseSqlType(VarCharType(length=255))]


User.configure(
    BigQueryConnectionConfig(
        project="my-gcp-project",
        dataset="my_dataset",
        location="US",
        credentials_path="/path/to/service-account.json",
    ),
    BigQueryBackend,
)
User.create_table()

alice = User(name="Alice", email="alice@example.com")
alice.save()
rows = User.query().where(User.c.email == "alice@example.com").all()

# Inspect the generated SQL without touching GCP:
sql, params = User.query().where(User.c.email == "alice@example.com").to_sql()
print(sql, params)
# SELECT * FROM `my_dataset`.`users` WHERE `users`.`email` = ?   ('alice@example.com',)
```

> **Async parity:** use `AsyncActiveRecord` with `AsyncBigQueryBackend` — same method
> names, same patterns, just add `await`.

### No GCP account? Use the emulator

Start the [goccy/bigquery-emulator](https://github.com/goccy/bigquery-emulator)
with `bash tests/scripts/start_emulator.sh`, then point the backend at it:

```python
config = BigQueryConnectionConfig(
    project="test", dataset="test_dataset",
    api_endpoint="http://localhost:9050", use_anonymous_credentials=True,
)
```

## Project Architecture

Your models, field proxies, and query builders stay backend-agnostic; this package
supplies the BigQuery pieces that render and execute them:

```
Your Code → ActiveRecord → BigQuery dialect (Standard SQL, backticks, ? params)
          → google-cloud-bigquery (query jobs) → BigQuery
```

The backend lives in `src/rhosocial/activerecord/backend/impl/bigquery/`:
`BigQueryBackend` / `AsyncBigQueryBackend`, `BigQueryConnectionConfig`, the dialect,
the `STRUCT` / `ARRAY` / `JSON` / `Decimal` / `TIMESTAMP` type adapters, and an
`INFORMATION_SCHEMA` introspector. `__schema_name__` maps to a dataset and columns
are never dataset-qualified.

For the full picture, see the [backend documentation](docs/en_US/README.md) and the
[Schema Namespaces](docs/en_US/bigquery_specific_features/schema_namespace.md) guide.

## Backend Support & Progress

BigQuery is **serverless** — there is no server version to track, no host to
provision, and no engine release matrix to maintain. This backend targets BigQuery
Standard SQL through the `google-cloud-bigquery` client and ships as a **separate
package** installed alongside the core `rhosocial-activerecord` library.

> **⚠️ Development Stage:** This project is under active development. APIs may
> change and some features are not yet production-ready. BigQuery has no
> `RETURNING`, no backend-level connection pooling, and a few DDL limits; see the
> documentation for the current contract.

## Contributing, License, Links

### Contributing

We welcome contributions! Please see
[CONTRIBUTING.md](https://github.com/rhosocial/python-activerecord/blob/main/CONTRIBUTING.md)
for guidelines.

### License

[Apache License 2.0](LICENSE) — Copyright © 2026 [vistart](https://github.com/vistart)

### Documentation

* **[Backend Documentation](docs/en_US/README.md)** — the full documentation table of contents
* **[Schema Namespaces](docs/en_US/bigquery_specific_features/schema_namespace.md)** — `__schema_name__`, dataset-qualified names, identifier quoting
* **[Database Introspection](docs/en_US/bigquery_specific_features/introspection.md)** — what the backend reads from `INFORMATION_SCHEMA`
* **[中文文档 (Chinese)](docs/zh_CN/README.md)**
* **[Core Library Documentation](https://github.com/rhosocial/python-activerecord/tree/main/docs)**

---

<div align="center">
    <p><b>Built with ❤️ by the rhosocial team</b></p>
    <p><a href="https://github.com/rhosocial/python-activerecord-bigquery">GitHub</a> · <a href="docs/en_US/README.md">Documentation</a></p>
</div>
